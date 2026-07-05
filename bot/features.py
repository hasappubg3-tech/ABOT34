from .shared import *
import random as _random
import time as _time

def _col(name):
    return get_mongo_db()[name]

def _d(doc):
    if doc is None:
        return None
    doc = dict(doc)
    doc.pop("_id", None)
    return doc

def _next_id(col_name: str) -> int:
    result = get_mongo_db()["_counters"].find_one_and_update(
        {"_id": col_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return result["seq"]

# ── العبارات التحفيزية ────────────────────────────────────────────
def get_phrases():
    return [_d(r) for r in _col("motivational_phrases").find().sort("id", 1)]

def add_phrase(text: str):
    new_id = _next_id("motivational_phrases")
    _col("motivational_phrases").insert_one({"id": new_id, "phrase": text})

def del_phrase(pid: int):
    _col("motivational_phrases").delete_one({"id": pid})

def get_phrases_chance() -> int:
    return int(get_setting("phrases_chance", "30"))

def get_random_phrase() -> str | None:
    chance = get_phrases_chance()
    if chance <= 0 or _random.randint(1, 100) > chance:
        return None
    docs = list(_col("motivational_phrases").aggregate([{"$sample": {"size": 1}}]))
    return docs[0]["phrase"] if docs else None

# ── تبديل إعدادات الأزرار ────────────────────────────────────────
def toggle_btn_no_caption(bid):
    b = get_btn(bid)
    if not b:
        return False
    new_val = 0 if (b.get("no_caption", 0) or 0) else 1
    _col("buttons").update_one({"id": bid}, {"$set": {"no_caption": new_val}})
    return bool(new_val)

def toggle_btn_no_btn_caption(bid):
    b = get_btn(bid)
    if not b:
        return False
    new_val = 0 if (b.get("no_btn_caption", 0) or 0) else 1
    _col("buttons").update_one({"id": bid}, {"$set": {"no_btn_caption": new_val}})
    return bool(new_val)

def toggle_btn_unified_rating(bid):
    b = get_btn(bid)
    if not b:
        return False
    new_val = 0 if (b.get("unified_rating", 0) or 0) else 1
    _col("buttons").update_one({"id": bid}, {"$set": {"unified_rating": new_val}})
    return bool(new_val)

# ── كويز ─────────────────────────────────────────────────────────
def add_quiz_question(bid, question, explanation=""):
    count = _col("quiz_questions").count_documents({"button_id": bid})
    new_id = _next_id("quiz_questions")
    _col("quiz_questions").insert_one({
        "id": new_id, "button_id": bid, "question": question,
        "correct_option": 0, "explanation": explanation, "ord": count + 1
    })
    return new_id

def get_quiz_questions(bid):
    docs = _col("quiz_questions").find({"button_id": bid}).sort([("ord", 1), ("id", 1)])
    return [_d(r) for r in docs]

def get_quiz_question(qid):
    return _d(_col("quiz_questions").find_one({"id": qid}))

def del_quiz_question(qid):
    _col("quiz_options").delete_many({"question_id": qid})
    _col("quiz_questions").delete_one({"id": qid})

def add_quiz_option(qid, text):
    count = _col("quiz_options").count_documents({"question_id": qid})
    new_id = _next_id("quiz_options")
    _col("quiz_options").insert_one({
        "id": new_id, "question_id": qid, "text": text, "ord": count + 1
    })
    return new_id

def get_quiz_options(qid):
    docs = _col("quiz_options").find({"question_id": qid}).sort([("ord", 1), ("id", 1)])
    return [_d(r) for r in docs]

def del_quiz_option(oid):
    _col("quiz_options").delete_one({"id": oid})

def set_correct_option(qid, option_idx):
    _col("quiz_questions").update_one({"id": qid}, {"$set": {"correct_option": option_idx}})

def toggle_random_quiz(bid):
    b = get_btn(bid)
    if not b:
        return False
    new_val = 0 if (b.get("random_quiz", 0) or 0) else 1
    _col("buttons").update_one({"id": bid}, {"$set": {"random_quiz": new_val}})
    return bool(new_val)

def log_question_sent(uid, qid):
    _col("quiz_sent_log").update_one(
        {"user_id": uid, "question_id": qid},
        {"$set": {"user_id": uid, "question_id": qid, "sent_at": int(_time.time())}},
        upsert=True
    )

def get_next_random_question(bid, uid):
    one_hour_ago = int(_time.time()) - 3600
    questions = get_quiz_questions(bid)
    if not questions:
        return None
    sent_ids = {
        d["question_id"] for d in _col("quiz_sent_log").find(
            {"user_id": uid, "sent_at": {"$gt": one_hour_ago}}
        )
    }
    available = [q for q in questions if q["id"] not in sent_ids]
    if not available:
        available = questions
    return _random.choice(available)

# ── أزرار الكليشة ─────────────────────────────────────────────────
def get_caption_buttons():
    docs = _col("caption_buttons").find().sort([("ord", 1), ("id", 1)])
    return [_d(r) for r in docs]

def add_caption_button(label, url):
    last = _col("caption_buttons").find_one(sort=[("ord", -1)])
    n = (last["ord"] if last else 0) + 1
    new_id = _next_id("caption_buttons")
    _col("caption_buttons").insert_one({"id": new_id, "label": label, "url": url, "ord": n})

def del_caption_button(cbid):
    _col("caption_buttons").delete_one({"id": cbid})

def build_caption_btn_markup(buttons):
    if not buttons:
        return None
    rows = [[InlineKeyboardButton(b["label"], url=b["url"])] for b in buttons]
    return InlineKeyboardMarkup(rows)

# ── نظام التنبيهات ────────────────────────────────────────────────
def _today_str():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")

def _ensure_user_stats(uid):
    now = int(_time.time())
    today = _today_str()
    existing = _col("user_stats").find_one({"user_id": uid})
    if existing is None:
        _col("user_stats").insert_one({
            "user_id": uid, "opens": 0, "sessions": 0,
            "last_notif_opens": 0, "last_notif_sessions": 0,
            "pending_notif_bid": 0, "subscribed_via_notif": 0,
            "subscribed_at": 0, "first_seen": now, "last_active": now,
            "ratings_hidden": 0, "username": None, "first_name": None
        })
        _col("daily_stats").update_one(
            {"date": today},
            {"$inc": {"new_users": 1}, "$setOnInsert": {"date": today, "msg_count": 0}},
            upsert=True
        )
    elif not existing.get("first_seen"):
        _col("user_stats").update_one({"user_id": uid}, {"$set": {"first_seen": now}})

def track_message(uid):
    _ensure_user_stats(uid)
    today = _today_str()
    now = int(_time.time())
    _col("user_stats").update_one({"user_id": uid}, {"$set": {"last_active": now}})
    _col("daily_stats").update_one(
        {"date": today},
        {"$inc": {"msg_count": 1}, "$setOnInsert": {"date": today, "new_users": 0}},
        upsert=True
    )

def get_user_stats(uid):
    _ensure_user_stats(uid)
    return _d(_col("user_stats").find_one({"user_id": uid})) or {}

def inc_user_opens(uid):
    _ensure_user_stats(uid)
    result = _col("user_stats").find_one_and_update(
        {"user_id": uid}, {"$inc": {"opens": 1}}, return_document=True
    )
    return result["opens"] if result else 0

def inc_user_sessions(uid):
    _ensure_user_stats(uid)
    result = _col("user_stats").find_one_and_update(
        {"user_id": uid}, {"$inc": {"sessions": 1}}, return_document=True
    )
    return result["sessions"] if result else 0

def mark_notif_sent(uid):
    s = get_user_stats(uid)
    _col("user_stats").update_one({"user_id": uid}, {"$set": {
        "last_notif_opens": s.get("opens", 0),
        "last_notif_sessions": s.get("sessions", 0),
    }})

def set_pending_notif(uid, bid, chat_id=None, msg_id=None):
    _ensure_user_stats(uid)
    update = {"pending_notif_bid": bid}
    if chat_id is not None:
        update["pending_notif_chat_id"] = int(chat_id)
        update["pending_notif_msg_id"]  = int(msg_id) if msg_id else 0
    _col("user_stats").update_one({"user_id": uid}, {"$set": update})

def clear_pending_notif(uid):
    _ensure_user_stats(uid)
    _col("user_stats").update_one({"user_id": uid}, {"$set": {
        "pending_notif_bid": 0,
        "pending_notif_chat_id": 0,
        "pending_notif_msg_id": 0,
    }})

def record_channel_subscription(uid):
    _ensure_user_stats(uid)
    doc = _col("user_stats").find_one({"user_id": uid})
    if doc and not doc.get("subscribed_via_notif"):
        _col("user_stats").update_one({"user_id": uid}, {"$set": {
            "subscribed_via_notif": 1, "subscribed_at": int(_time.time())
        }})

def get_pending_notif(uid):
    s = get_user_stats(uid)
    return s.get("pending_notif_bid", 0) or 0

def get_pending_notif_gate(uid):
    """يُعيد (bid, chat_id, msg_id) لرسالة البوابة الحالية المعلّقة."""
    s = get_user_stats(uid)
    bid     = s.get("pending_notif_bid",     0) or 0
    chat_id = s.get("pending_notif_chat_id", 0) or 0
    msg_id  = s.get("pending_notif_msg_id",  0) or 0
    return bid, chat_id, msg_id

def get_user_ratings_hidden(uid):
    s = get_user_stats(uid)
    return bool(s.get("ratings_hidden", 0) or 0)

def toggle_user_ratings_hidden(uid):
    _ensure_user_stats(uid)
    current = get_user_ratings_hidden(uid)
    new_val = 0 if current else 1
    _col("user_stats").update_one({"user_id": uid}, {"$set": {"ratings_hidden": new_val}})
    return bool(new_val)

async def is_subscribed(bot, uid: int):
    chan = get_setting("notif_channel", "").strip()
    if not chan:
        return None
    try:
        if chan.startswith("http"):
            parts = chan.rstrip("/").split("/")
            channel_id = f"@{parts[-1]}"
        elif chan.startswith("-"):
            channel_id = int(chan)
        else:
            channel_id = f"@{chan.lstrip('@')}"
        member = await bot.get_chat_member(channel_id, uid)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return None

def should_notify(uid) -> bool:
    chan = get_setting("notif_channel", "").strip()
    if not chan:
        return False
    msg = get_setting("notif_message", "")
    if not msg:
        return False
    if get_setting("notif_enabled", "1") != "1":
        return False
    if consume_force_next_notif(uid):
        return True
    s = get_user_stats(uid)
    opens = s.get("opens", 0)
    last_op = s.get("last_notif_opens", 0)
    try:
        every_opens = int(get_setting("notif_every_opens", "5"))
    except Exception:
        every_opens = 5
    if every_opens > 0 and opens > 0 and (opens - last_op) >= every_opens:
        return True
    return False

# ── عداد الرفض المتسلسل (يُحفظ بشكل دائم لكل مستخدم) ──────────────
def get_notif_no_count(uid) -> int:
    s = get_user_stats(uid)
    return s.get("notif_no_count", 0) or 0

def set_notif_no_count(uid, val: int):
    _ensure_user_stats(uid)
    _col("user_stats").update_one({"user_id": uid}, {"$set": {"notif_no_count": val}})

def inc_notif_no_count(uid) -> int:
    _ensure_user_stats(uid)
    result = _col("user_stats").find_one_and_update(
        {"user_id": uid}, {"$inc": {"notif_no_count": 1}}, return_document=True
    )
    return result.get("notif_no_count", 0) if result else 0

def reset_notif_no_count(uid):
    set_notif_no_count(uid, 0)

# ── إجبار ظهور رسالة الاشتراك في أول محاولة قادمة (يتجاوز عداد الفتحات) ──
def set_force_next_notif(uid, val: bool = True):
    _ensure_user_stats(uid)
    _col("user_stats").update_one({"user_id": uid}, {"$set": {"notif_force_next": 1 if val else 0}})

def consume_force_next_notif(uid) -> bool:
    s = get_user_stats(uid)
    if s.get("notif_force_next"):
        set_force_next_notif(uid, False)
        return True
    return False

# ── حظر استلام الملفات لفترة زمنية (مثلاً ساعة كاملة) ───────────────
def block_user_files(uid, seconds: int = 3600) -> int:
    _ensure_user_stats(uid)
    until = int(_time.time()) + seconds
    _col("user_stats").update_one({"user_id": uid}, {"$set": {"file_block_until": until}})
    return until

def clear_file_block(uid):
    _ensure_user_stats(uid)
    _col("user_stats").update_one({"user_id": uid}, {"$set": {"file_block_until": 0}})

def get_file_block_remaining(uid) -> int:
    s = get_user_stats(uid)
    until = s.get("file_block_until", 0) or 0
    remaining = until - int(_time.time())
    return remaining if remaining > 0 else 0

async def send_notif_gate(target, uid, bid):
    msg         = get_setting("notif_message", "🔔 يرجى الاشتراك في قناتنا!")
    chan        = get_setting("notif_channel", "").strip()
    ok_text     = get_setting("notif_ok_text",    "✅ نعم، اشتركت")
    cancel_text = get_setting("notif_cancel_text", "❌ لا، لاحقاً")
    rows = []
    if chan:
        url = chan if chan.startswith("http") else f"https://t.me/{chan.lstrip('@')}"
        rows.append([InlineKeyboardButton("📢 انضم للقناة الآن", url=url)])
    rows.append([
        InlineKeyboardButton(ok_text,     callback_data=f"notif_ok_{bid}"),
        InlineKeyboardButton(cancel_text, callback_data=f"notif_skip_{bid}"),
    ])
    markup = InlineKeyboardMarkup(rows)
    try:
        try:
            sent = await target.reply_text(msg, parse_mode="Markdown", reply_markup=markup)
        except Exception:
            sent = await target.reply_text(msg, reply_markup=markup)
        mark_notif_sent(uid)
        set_pending_notif(uid, bid, chat_id=sent.chat_id, msg_id=sent.message_id)
    except Exception:
        pass

# ── البومودورو ────────────────────────────────────────────────────
POMODORO_MODES = [
    (25,  5,  "⏱ 25 دراسة / 5 استراحة (كلاسيكي)"),
    (50, 10,  "⏱ 50 دراسة / 10 استراحة (موسّع)"),
    (45, 15,  "⏱ 45 دراسة / 15 استراحة (طويل)"),
    (15,  5,  "⏱ 15 دراسة / 5 استراحة (سريع)"),
]

def get_pomodoro_settings(uid: int) -> dict:
    doc = _col("pomodoro_settings").find_one({"user_id": uid})
    if doc:
        return _d(doc)
    return {"user_id": uid, "enabled": 1, "study_min": 25, "break_min": 5}

def save_pomodoro_settings(uid: int, enabled=None, study_min=None, break_min=None):
    cur = get_pomodoro_settings(uid)
    if enabled   is not None: cur["enabled"]   = enabled
    if study_min is not None: cur["study_min"] = study_min
    if break_min is not None: cur["break_min"] = break_min
    _col("pomodoro_settings").update_one(
        {"user_id": uid},
        {"$set": {"user_id": uid, "enabled": cur["enabled"],
                  "study_min": cur["study_min"], "break_min": cur["break_min"]}},
        upsert=True
    )

def parse_pomodoro_minutes(text: str, max_minutes: int = 240):
    if not text:
        return None
    import re
    match = re.search(r"\d+", text.strip())
    if not match:
        return None
    try:
        val = int(match.group(0))
    except Exception:
        return None
    if val < 1 or val > max_minutes:
        return None
    return val

def pomodoro_settings_text(uid: int) -> str:
    s = get_pomodoro_settings(uid)
    status = "✅ مفعّل" if s["enabled"] else "❌ موقف"
    return (
        f"🍅 *مؤقت الدراسة (بومودورو)*\n\n"
        f"⏱ الوضع: {s['study_min']} دراسة + {s['break_min']} استراحة\n"
        f"الحالة: {status}"
    )

def parse_stars_amount(text: str, max_stars: int = 10000):
    if not text:
        return None
    import re
    match = re.search(r"\d+", text.strip())
    if not match:
        return None
    try:
        amount = int(match.group(0))
    except Exception:
        return None
    if amount < 1 or amount > max_stars:
        return None
    return amount

def donation_text() -> str:
    return (
        "💝 *دعم البوت بالنجوم*\n\n"
        "إذا استفدت من المحتوى وتحب تدعم استمرار البوت، تقدر تتبرع بأي عدد من نجوم تلغرام.\n\n"
        "اختر مبلغاً جاهزاً أو اكتب عدد النجوم الذي تريده."
    )

def default_donation_thanks_message() -> str:
    return "💝 شكراً جزيلاً على دعمك بـ {stars} نجمة!\n\nدعمك يساعدنا نستمر ونطور المحتوى."

def get_donation_thanks_message(stars: int = 0) -> str:
    msg = get_setting("donation_thanks_message", default_donation_thanks_message())
    if not msg:
        msg = default_donation_thanks_message()
    stars_text = str(stars) if stars else "نجوم"
    return msg.replace("{stars}", stars_text)

def kb_donation_stars(uid=None):
    rows = [
        [
            InlineKeyboardButton("10 ⭐", callback_data="don_amount_10"),
            InlineKeyboardButton("25 ⭐", callback_data="don_amount_25"),
            InlineKeyboardButton("50 ⭐", callback_data="don_amount_50"),
        ],
        [
            InlineKeyboardButton("100 ⭐", callback_data="don_amount_100"),
            InlineKeyboardButton("250 ⭐", callback_data="don_amount_250"),
        ],
        [InlineKeyboardButton("✏️ أكتب عدد النجوم", callback_data="don_custom")],
    ]
    if uid is not None and is_admin(uid):
        rows.append([InlineKeyboardButton("✏️ تعديل رسالة الشكر", callback_data="don_thanks_set")])
    rows.append([InlineKeyboardButton("❌ إغلاق", callback_data="don_close")])
    return InlineKeyboardMarkup(rows)

def toggle_ratings_text(uid: int) -> str:
    hidden = get_user_ratings_hidden(uid)
    status = "⭕ مخفية حالياً" if hidden else "✅ ظاهرة حالياً"
    desc = (
        "عند إخفاء التقييمات لن تظهر لك رسائل التقييم بعد استلام الملفات."
        if not hidden else
        "عند تفعيل التقييمات ستظهر لك رسائل التقييم بعد استلام الملفات."
    )
    return (
        f"⭐ *إعدادات التقييمات*\n\n"
        f"الحالة: {status}\n\n"
        f"{desc}"
    )

def kb_toggle_ratings(uid: int):
    hidden = get_user_ratings_hidden(uid)
    toggle_label = "✅ تفعيل التقييمات" if hidden else "🚫 إخفاء التقييمات"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data="rating_toggle")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="rating_close")],
    ])

async def send_stars_invoice(bot, chat_id: int, stars: int):
    await bot.send_invoice(
        chat_id=chat_id,
        title="دعم البوت بالنجوم",
        description=f"تبرع اختياري لدعم استمرار البوت بقيمة {stars} نجمة.",
        payload=f"stars_donation:{stars}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"{stars} نجمة", amount=stars)],
    )

def top_users_text() -> str:
    admin_ids = [a["id"] for a in all_admins()]
    query = {"user_id": {"$nin": admin_ids}} if admin_ids else {}
    pipeline = [
        {"$match": query},
        {"$addFields": {"activity": {"$add": [{"$ifNull": ["$opens", 0]}, {"$ifNull": ["$sessions", 0]}]}}},
        {"$sort": {"activity": -1}},
        {"$limit": 30},
    ]
    rows = list(get_mongo_db()["user_stats"].aggregate(pipeline))
    if not rows:
        return "🏆 *أبرز المستخدمين*\n\nلا توجد بيانات بعد."

    def _safe(text):
        if not text:
            return ""
        for ch in ["_", "*", "`", "["]:
            text = text.replace(ch, f"\\{ch}")
        return text

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = ["🏆 *أبرز المستخدمين نشاطاً*\n"]
    for i, row in enumerate(rows, start=1):
        medal = medals.get(i, f"{i}\\.")
        first_name = row.get("first_name")
        display = _safe(first_name) if first_name else f"مستخدم {i}"
        lines.append(f"{medal} {display}")
    return "\n".join(lines)

def _setup_pomodoro_feature():
    mdb = get_mongo_db()
    b421 = mdb["buttons"].find_one({"id": 421})
    if not b421:
        return
    mdb["buttons"].update_one({"id": 421}, {"$set": {"special_action": "container"}})

    def _ensure_special(action, label):
        if not mdb["buttons"].find_one({"parent_id": 421, "special_action": action}):
            from bot.data_access import _next_id as _nid, _siblings_ids
            ids = _siblings_ids(421)
            new_id = _nid("buttons")
            mdb["buttons"].insert_one({
                "id": new_id, "parent_id": 421, "type": "special",
                "label": label, "ord": len(ids) + 1, "new_row": 1,
                "special_action": action, "click_count": 0,
                "unified_rating": 0, "no_caption": 0, "no_btn_caption": 0,
                "hidden": 0, "compound_text": None, "random_quiz": 0, "random_exam": 0,
            })

    _ensure_special("pomodoro",       "🍅 مؤقت الدراسة")
    _ensure_special("donate_stars",   "💝 ادعمنا بالنجوم")
    _ensure_special("toggle_ratings", "⭐ التقييمات")
    _ensure_special("file_request",   "📩 طلب إضافة ملف")
    _ensure_special("file_upload",    "📤 رفع ملف")
    _ensure_special("top_users",      "🏆 أبرز المستخدمين")
    mdb["buttons"].delete_many({"special_action": "yt_search"})
