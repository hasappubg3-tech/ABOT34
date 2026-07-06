import logging
import os
import sqlite3
import json
import httpx
import zipfile
import datetime
import time as _time
from collections import deque as _deque
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, LabeledPrice
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, PollAnswerHandler, PreCheckoutQueryHandler, filters
from pymongo import MongoClient, ASCENDING
from pymongo.collection import Collection

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
STORAGE_CHANNEL_ID = os.environ.get("STORAGE_CHANNEL_ID", "-1003800078762").strip()
DB = "data.db"
MEDIA_DIR = "media"
os.makedirs(MEDIA_DIR, exist_ok=True)

GEMINI_MODEL = "gemini-2.5-flash"

MONGODB_URI = os.environ.get("MONGODB_URI", "")

_mongo_client = None
_mongo_db = None

def get_mongo_db():
    global _mongo_client, _mongo_db
    if _mongo_db is None:
        _mongo_client = MongoClient(MONGODB_URI)
        _mongo_db = _mongo_client.get_default_database() if "/" in MONGODB_URI.rsplit("@", 1)[-1] and MONGODB_URI.rsplit("/", 1)[-1].split("?")[0] else _mongo_client["botdb"]
    return _mongo_db

def _load_gemini_keys():
    keys = []
    for k in [
        os.environ.get("GEMINI_API_KEY", ""),
        *[os.environ.get(f"GEMINI_API_KEY_{i}", "") for i in range(1, 11)],
    ]:
        if k and k not in keys:
            keys.append(k)
    return keys

GEMINI_KEYS = _load_gemini_keys()

BTN_BACK     = "رجوع"
BTN_HOME     = "القائمة الرئيسية"
BTN_ADD      = "➕ إضافة"
BTN_MANAGE   = "⚙️ إدارة"
BTN_ADMINS   = "👥 مشرفون"
BTN_CANCEL   = "❌ إلغاء"
BTN_SETTINGS = "⚙️ الاعدادات"

BTN_SWAP = "🔀 تغيير"
BTN_EXAM_STATS = "📊 إحصائيات الامتحانات"

ADMIN_BTNS   = {BTN_ADMINS}
BTN_PLUS = "➕"
SPECIAL_BTNS = {BTN_BACK, BTN_HOME, BTN_ADD, BTN_MANAGE, BTN_ADMINS, BTN_CANCEL, BTN_SWAP, BTN_PLUS,
                BTN_SETTINGS, "📂 قائمة", "📄 محتوى", BTN_EXAM_STATS}

_SUP_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_SUP_MAP    = {c: str(i) for i, c in enumerate(_SUP_DIGITS)}

def _plus_label(bid: int) -> str:
    return BTN_PLUS + ''.join(_SUP_DIGITS[int(d)] for d in str(bid))

def _parse_plus(text: str):
    if not text.startswith(BTN_PLUS):
        return None
    rest = text[len(BTN_PLUS):]
    if not rest:
        return None
    digits = ''.join(_SUP_MAP.get(c, '') for c in rest)
    if not digits:
        return None
    try:
        return int(digits)
    except Exception:
        return None

_BID_ZERO = "\u200B"
_BID_ONE  = "\u200C"
_BID_END  = "\u2060"
_BID_INVISIBLES = (_BID_ZERO, _BID_ONE, _BID_END)

def _encode_bid(bid) -> str:
    try:
        n = int(bid)
    except (TypeError, ValueError):
        return ""
    if n < 0:
        return ""
    bits = format(n, "b")
    return "".join(_BID_ONE if c == "1" else _BID_ZERO for c in bits) + _BID_END

def _decode_bid(text: str):
    if not text:
        return text, None
    bid = None
    if _BID_END in text:
        end_idx = text.rfind(_BID_END)
        bits = []
        i = end_idx - 1
        while i >= 0 and text[i] in (_BID_ZERO, _BID_ONE):
            bits.append("1" if text[i] == _BID_ONE else "0")
            i -= 1
        bits.reverse()
        if bits:
            try:
                bid = int("".join(bits), 2)
            except Exception:
                bid = None
    cleaned = "".join(c for c in text if c not in _BID_INVISIBLES)
    return cleaned, bid

def _strip_bid_markers(text: str) -> str:
    cleaned, _ = _decode_bid(text or "")
    return cleaned

def btn_id_header(bid: int) -> str:
    """سطر رقم الزر يظهر أعلى كل رسالة إدارة للمشرف."""
    return f"🔢 *#{bid}*\n"

# ── حد الإزعاج (Rate Limiter) ─────────────────────────────────────
_rate_data: dict = {}
_RATE_MSG_MAX = 5    # أقصى عدد رسائل
_RATE_CB_MAX  = 12   # أقصى عدد ضغطات أزرار
_RATE_WINDOW  = 5.0  # خلال كم ثانية

def check_rate_limit(uid: int, kind: str = 'msg') -> bool:
    """
    يتحقق من حد الإزعاج.
    True = مسموح  |  False = تجاوز الحد
    kind: 'msg' للرسائل، 'cb' للأزرار.
    """
    now = _time.monotonic()
    key = (uid, kind)
    dq = _rate_data.setdefault(key, _deque())
    while dq and now - dq[0] > _RATE_WINDOW:
        dq.popleft()
    limit = _RATE_CB_MAX if kind == 'cb' else _RATE_MSG_MAX
    if len(dq) >= limit:
        return False
    dq.append(now)
    return True

# ── AI Queue (Semaphore) ──────────────────────────────────────────
_ai_semaphore = None

def init_ai_semaphore(concurrency: int = None):
    global _ai_semaphore
    import asyncio
    if concurrency is None:
        try:
            concurrency = int(get_mongo_db()["settings"].find_one({"key": "ai_queue_concurrency"}) or {}).get("value", "3")
        except Exception:
            concurrency = 3
        try:
            concurrency = int(concurrency)
        except Exception:
            concurrency = 3
    if concurrency < 1:
        concurrency = 1
    _ai_semaphore = asyncio.Semaphore(concurrency)
    logging.info(f"AI Queue: تم تهيئة الطابور بـ {concurrency} طلب متزامن كحد أقصى.")

def get_ai_semaphore():
    global _ai_semaphore
    if _ai_semaphore is None:
        import asyncio
        _ai_semaphore = asyncio.Semaphore(3)
    return _ai_semaphore

def get_ai_queue_concurrency() -> int:
    try:
        doc = get_mongo_db()["settings"].find_one({"key": "ai_queue_concurrency"})
        return int(doc["value"]) if doc else 3
    except Exception:
        return 3

__all__ = [name for name in globals() if not name.startswith("__")]
