"""
غرف الدراسة الجماعية (Study Sessions)
======================================
special_action = "sessions"
callbacks prefix: ses_
states: wait_ses_study_time | wait_ses_break_time | wait_ses_room_name_create
        wait_ses_password | wait_ses_join_pw | wait_ses_rename | wait_ses_chat
"""
import datetime
import logging
from .shared import *

logger = logging.getLogger(__name__)

ATTENDANCE_WINDOW = 120
READY_THRESHOLD   = 0.25          # 25 % من المشاركين يكفي لبدء الجلسة تلقائياً
_ACTIVE = ["waiting", "studying", "break", "attendance", "ready_check"]

# ══════════════════════════════════════════════════════════════════
# قاعدة البيانات – Collections
# ══════════════════════════════════════════════════════════════════

def _col_r():  return get_mongo_db()["study_rooms"]
def _col_p():  return get_mongo_db()["study_participants"]
def _col_c():  return get_mongo_db()["study_comments"]

def _strip(doc):
    if doc is None: return None
    d = dict(doc); d.pop("_id", None); return d

def _next_room_id():
    res = get_mongo_db()["_counters"].find_one_and_update(
        {"_id": "study_rooms"}, {"$inc": {"seq": 1}},
        upsert=True, return_document=True)
    return res["seq"]

# ══════════════════════════════════════════════════════════════════
# قراءة
# ══════════════════════════════════════════════════════════════════

def ses_get_room(rid: int):
    return _strip(_col_r().find_one({"id": rid, "status": {"$ne": "ended"}}))

def _get_room_any(rid: int):
    return _strip(_col_r().find_one({"id": rid}))

def ses_get_active_rooms():
    return [_strip(r) for r in _col_r().find({"status": {"$in": _ACTIVE}}, sort=[("created_at", 1)])]

def ses_get_participants(rid: int):
    return [_strip(p) for p in _col_p().find({"room_id": rid}).sort("joined_at", 1)]

def _get_participant(rid: int, uid: int):
    return _strip(_col_p().find_one({"room_id": rid, "user_id": uid}))

def ses_is_in_room(rid: int, uid: int) -> bool:
    return bool(_col_p().count_documents({"room_id": rid, "user_id": uid}))

def ses_is_in_any_room(uid: int) -> bool:
    active_rids = [r["id"] for r in ses_get_active_rooms()]
    if not active_rids: return False
    return bool(_col_p().count_documents({"user_id": uid, "room_id": {"$in": active_rids}}))

def ses_is_muted(rid: int, uid: int) -> bool:
    p = _get_participant(rid, uid)
    return bool(p and p.get("is_muted"))

# ══════════════════════════════════════════════════════════════════
# كتابة – غرفة
# ══════════════════════════════════════════════════════════════════

def ses_create_room(creator_id, creator_name, study_time, break_time,
                    password=None, custom_name=None) -> int:
    rid  = _next_room_id()
    name = (custom_name or creator_name)[:30]
    _col_r().insert_one({
        "id": rid, "name": name,
        "creator_id": creator_id, "creator_name": creator_name,
        "study_time": study_time, "break_time": break_time,
        "password": password, "status": "waiting",
        "comments_open": True,
        "created_at": datetime.datetime.utcnow(),
        "started_at": None, "current_session": 0,
        "current_phase_start": None, "last_phase_end": None,
        "attendance_open": False, "attendance_session": 0,
    })
    ses_join_room(rid, creator_id, creator_name)
    return rid

def ses_join_room(rid: int, uid: int, user_name: str):
    """
    يُرجع True عند النجاح,
             False إذا كان في الغرفة بالفعل,
             None  إذا كان في غرفة أخرى نشطة.
    """
    if _col_p().count_documents({"room_id": rid, "user_id": uid}):
        return False
    # منع الانضمام لأكثر من غرفة واحدة
    active_rids = [r["id"] for r in ses_get_active_rooms()]
    other = [r for r in active_rids if r != rid]
    if other and _col_p().count_documents({"user_id": uid, "room_id": {"$in": other}}):
        return None
    room = ses_get_room(rid)
    now  = datetime.datetime.utcnow()
    phase_join = now if room and room["status"] == "studying" else None
    _col_p().insert_one({
        "room_id": rid, "user_id": uid, "user_name": user_name,
        "joined_at": now, "phase_join_time": phase_join,
        "total_study_seconds": 0, "sessions_attended": 0,
        "last_confirmed_session": 0, "is_muted": False,
    })
    return True

def ses_leave_room(rid: int, uid: int):
    _col_p().delete_one({"room_id": rid, "user_id": uid})

def ses_kick_member(rid: int, uid: int):
    ses_leave_room(rid, uid)

def ses_toggle_mute(rid: int, uid: int) -> bool:
    p = _get_participant(rid, uid)
    if not p: return False
    new_val = not p.get("is_muted", False)
    _col_p().update_one({"room_id": rid, "user_id": uid}, {"$set": {"is_muted": new_val}})
    return new_val

def ses_rename_room(rid: int, new_name: str):
    _col_r().update_one({"id": rid}, {"$set": {"name": new_name[:30]}})

def ses_toggle_comments(rid: int) -> bool:
    room = _get_room_any(rid)
    new_val = not room.get("comments_open", True)
    _col_r().update_one({"id": rid}, {"$set": {"comments_open": new_val}})
    return new_val

def ses_update_room_times(rid: int, study_time: int, break_time: int):
    _col_r().update_one({"id": rid}, {"$set": {"study_time": study_time, "break_time": break_time}})

# ══════════════════════════════════════════════════════════════════
# إدارة الجلسة
# ══════════════════════════════════════════════════════════════════

def ses_start_room(rid: int):
    now = datetime.datetime.utcnow()
    _col_r().update_one({"id": rid}, {"$set": {
        "status": "studying", "started_at": now,
        "current_session": 1, "current_phase_start": now,
    }})
    _col_p().update_many({"room_id": rid}, {"$set": {"phase_join_time": now}})

def ses_open_attendance(rid: int, session_num: int, phase_end: datetime.datetime):
    _col_r().update_one({"id": rid}, {"$set": {
        "status": "attendance", "attendance_open": True,
        "attendance_session": session_num, "last_phase_end": phase_end,
    }})

def ses_start_break(rid: int):
    now = datetime.datetime.utcnow()
    _col_r().update_one({"id": rid}, {"$set": {
        "status": "break", "current_phase_start": now, "attendance_open": False,
    }})
    _col_p().update_many({"room_id": rid}, {"$set": {"phase_join_time": None}})

def ses_next_study_phase(rid: int) -> int:
    now  = datetime.datetime.utcnow()
    room = _get_room_any(rid)
    sn   = (room.get("current_session") or 0) + 1
    _col_r().update_one({"id": rid}, {"$set": {
        "status": "studying", "current_session": sn,
        "current_phase_start": now, "attendance_open": False,
    }})
    _col_p().update_many({"room_id": rid}, {"$set": {"phase_join_time": now}})
    return sn

def ses_confirm_attendance(rid: int, uid: int, session_num: int):
    p = _get_participant(rid, uid)
    if not p: return False
    if (p.get("last_confirmed_session") or 0) >= session_num: return False
    room = _get_room_any(rid)
    if not room: return False
    phase_start = room.get("current_phase_start") or datetime.datetime.utcnow()
    phase_end   = room.get("last_phase_end")       or datetime.datetime.utcnow()
    join_time   = p.get("phase_join_time")         or phase_start
    secs = max(0, (phase_end - max(join_time, phase_start)).total_seconds())
    _col_p().update_one({"room_id": rid, "user_id": uid}, {
        "$inc": {"total_study_seconds": int(secs), "sessions_attended": 1},
        "$set": {"last_confirmed_session": session_num},
    })
    return int(secs)

def ses_end_room(rid: int):
    _col_r().update_one({"id": rid}, {"$set": {
        "status": "ended", "ended_at": datetime.datetime.utcnow(),
    }})

def ses_open_ready_check(rid: int):
    """يفتح نافذة جاهزية بعد الاستراحة — ينتظر ضغط المشاركين أو قرار المالك."""
    _col_r().update_one({"id": rid}, {"$set": {
        "status": "ready_check", "ready_users": [],
    }})

def ses_mark_ready(rid: int, uid: int) -> tuple:
    """يُسجّل المستخدم كجاهز. يُعيد (عدد_الجاهزين, مجموع_المشاركين)."""
    _col_r().update_one({"id": rid}, {"$addToSet": {"ready_users": uid}})
    room  = _get_room_any(rid)
    ready = len(room.get("ready_users", []))
    total = _col_p().count_documents({"room_id": rid})
    return ready, total

# ══════════════════════════════════════════════════════════════════
# التعليقات
# ══════════════════════════════════════════════════════════════════

def ses_add_comment(rid: int, uid: int, user_name: str, text: str):
    _col_c().insert_one({
        "room_id": rid, "user_id": uid, "user_name": user_name,
        "text": text[:200], "created_at": datetime.datetime.utcnow(),
    })

def ses_get_comments(rid: int, limit: int = 10):
    docs = list(_col_c().find({"room_id": rid}).sort("created_at", -1).limit(limit))
    docs.reverse()
    return [_strip(d) for d in docs]

# ══════════════════════════════════════════════════════════════════
# إحصائيات
# ══════════════════════════════════════════════════════════════════

def ses_get_my_stats(uid: int) -> dict:
    res = list(_col_p().aggregate([
        {"$match": {"user_id": uid}},
        {"$group": {"_id": None,
            "total_secs":     {"$sum": "$total_study_seconds"},
            "total_sessions": {"$sum": "$sessions_attended"},
            "rooms":          {"$sum": 1},
        }}
    ]))
    return res[0] if res else {"total_secs": 0, "total_sessions": 0, "rooms": 0}

def ses_get_user_rooms(uid: int) -> list:
    records = list(_col_p().find({"user_id": uid}).sort("total_study_seconds", -1))
    rooms = []
    for rec in records:
        r = _get_room_any(rec["room_id"])
        if r:
            rooms.append(r)
    return rooms

def ses_get_room_top(rid: int, limit: int = 10):
    """يُعيد أفضل المشاركين مُجمَّعين عبر كل غرف المالك نفسه (لا تُفقد الإحصائيات عند إعادة الإنشاء)."""
    room = _get_room_any(rid)
    if not room:
        return []
    creator_id = room["creator_id"]
    owner_room_ids = [r["id"] for r in _col_r().find({"creator_id": creator_id}, {"id": 1})]
    result = list(_col_p().aggregate([
        {"$match": {"room_id": {"$in": owner_room_ids}}},
        {"$group": {
            "_id":                "$user_id",
            "user_id":            {"$first": "$user_id"},
            "user_name":          {"$last":  "$user_name"},
            "total_study_seconds":{"$sum":   "$total_study_seconds"},
            "sessions_attended":  {"$sum":   "$sessions_attended"},
        }},
        {"$match": {"total_study_seconds": {"$gt": 0}}},
        {"$sort":  {"total_study_seconds": -1}},
        {"$limit": limit},
    ]))
    return [dict(r) for r in result]

def ses_get_global_top(limit: int = 10):
    return list(_col_p().aggregate([
        {"$group": {"_id": "$user_id", "user_name": {"$first": "$user_name"},
            "total_secs":     {"$sum": "$total_study_seconds"},
            "total_sessions": {"$sum": "$sessions_attended"},
        }},
        {"$match": {"total_secs": {"$gt": 0}}},
        {"$sort": {"total_secs": -1}}, {"$limit": limit},
    ]))

# ══════════════════════════════════════════════════════════════════
# تنسيق النصوص
# ══════════════════════════════════════════════════════════════════

def _fmt_time(secs: int) -> str:
    secs = int(secs)
    if secs <= 0: return "0د"
    m = secs // 60
    if m < 60: return f"{m}د"
    h, m2 = divmod(m, 60)
    return f"{h}س {m2}د" if m2 else f"{h}س"

_ST = {"waiting": "⏳ تنتظر", "studying": "📚 دراسة",
       "break": "☕ استراحة", "attendance": "✋ حضور",
       "ready_check": "🔔 تحقق جاهزية", "ended": "🏁 انتهت"}

def ses_menu_text() -> str:
    cnt = len(ses_get_active_rooms())
    return (
        "🎓 *جلسات الدراسة الجماعية*\n\n"
        f"📡 الغرف المفتوحة: *{cnt}*\n\n"
        "انضم لغرفة أو أنشئ غرفتك الخاصة!"
    )

def _room_info_text(room, pts) -> str:
    lock = "🔒" if room.get("password") else "🔓"
    st   = _ST.get(room["status"], room["status"])
    sn   = room.get("current_session", 0)
    com  = "🔒 التعليقات مغلقة" if not room.get("comments_open", True) else ""
    lines = [
        f"🏠 *{room['name']}*",
        f"{lock} {'مقفلة' if room.get('password') else 'مفتوحة'} | {st}",
        "",
        f"📚 الدراسة: *{room['study_time']}د*  |  ☕ الاستراحة: *{room['break_time']}د*",
        f"👥 المشاركون: *{len(pts)}*",
    ]
    if sn:   lines.append(f"🔢 الجلسة: *{sn}*")
    if com:  lines.append(com)
    return "\n".join(lines)

def ses_my_stats_text(uid: int) -> str:
    s = ses_get_my_stats(uid)
    return (
        "📊 *إحصائياتي*\n\n"
        f"⏱ إجمالي وقت الدراسة: *{_fmt_time(s.get('total_secs', 0))}*\n"
        f"✅ الجلسات المسجَّلة: *{s.get('total_sessions', 0)}*\n"
        f"🏠 الغرف: *{s.get('rooms', 0)}*\n\n"
        "_اضغط على أي غرفة لعرض تفاصيل مشاركتك فيها:_"
    )

def _my_room_stat_text(rid: int, uid: int) -> str:
    p    = _strip(_col_p().find_one({"room_id": rid, "user_id": uid}))
    room = _get_room_any(rid)
    if not p or not room: return "❌ لا توجد بيانات."
    return (
        f"🏠 *{room['name']}*\n\n"
        f"⏱ وقت الدراسة: *{_fmt_time(p.get('total_study_seconds', 0))}*\n"
        f"✅ الجلسات المسجَّلة: *{p.get('sessions_attended', 0)}*"
    )

def _global_user_stat_text(uid2: int) -> str:
    records = list(_col_p().find({"user_id": uid2}))
    if not records: return "❌ لا توجد إحصائيات."
    uname   = records[0].get("user_name", "مجهول")
    total_s = sum(r.get("total_study_seconds", 0) for r in records)
    total_n = sum(r.get("sessions_attended", 0) for r in records)
    return (
        f"👤 *{uname}*\n\n"
        f"⏱ إجمالي وقت الدراسة: *{_fmt_time(total_s)}*\n"
        f"✅ إجمالي الجلسات: *{total_n}*\n"
        f"🏠 عدد الغرف: *{len(records)}*"
    )

def _room_member_stat_text(rid: int, uid2: int) -> str:
    p    = _strip(_col_p().find_one({"room_id": rid, "user_id": uid2}))
    room = _get_room_any(rid)
    if not p or not room: return "❌ لا توجد بيانات."
    muted = "🔇 مكتوم" if p.get("is_muted") else ""
    return (
        f"👤 *{p.get('user_name', 'مجهول')}*\n"
        f"🏠 {room['name']}\n\n"
        f"⏱ وقت الدراسة: *{_fmt_time(p.get('total_study_seconds', 0))}*\n"
        f"✅ الجلسات المسجَّلة: *{p.get('sessions_attended', 0)}*\n"
        + (f"\n{muted}" if muted else "")
    )

def _ses_comments_text(rid: int) -> str:
    room     = _get_room_any(rid)
    open_    = room.get("comments_open", True) if room else True
    comments = ses_get_comments(rid)
    name     = room["name"] if room else "الغرفة"
    st_icon  = "🔓" if open_ else "🔒"
    header   = f"💬 *تعليقات {name}* {st_icon}\n\n"
    if not comments:
        body = "_لا توجد تعليقات بعد._"
    else:
        lines = []
        for c in comments:
            lines.append(f"[{c['user_name']}]: {c['text']}")
        body = "\n".join(lines)
    return header + body

# ══════════════════════════════════════════════════════════════════
# لوحات المفاتيح
# ══════════════════════════════════════════════════════════════════

def kb_ses_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 عرض الغرف المتاحة",   callback_data="ses_rooms")],
        [InlineKeyboardButton("➕ إنشاء غرفة جديدة",    callback_data="ses_create")],
        [
            InlineKeyboardButton("📊 إحصائياتي",        callback_data="ses_my_stats"),
            InlineKeyboardButton("🌍 الإحصائيات العامة", callback_data="ses_global_stats"),
        ],
    ])

def kb_ses_rooms(rooms) -> InlineKeyboardMarkup:
    st_e = {"waiting": "⏳", "studying": "📚", "break": "☕", "attendance": "✋"}
    rows = []
    for r in rooms:
        lock = "🔒" if r.get("password") else "🔓"
        st   = st_e.get(r["status"], "")
        cnt  = _col_p().count_documents({"room_id": r["id"]})
        rows.append([InlineKeyboardButton(
            f"{lock}{st} {r['name']} | {r['study_time']}/{r['break_time']}د | {cnt}👥",
            callback_data=f"ses_room_{r['id']}"
        )])
    rows.append([
        InlineKeyboardButton("🔄 تحديث", callback_data="ses_rooms"),
        InlineKeyboardButton("🔙 رجوع",  callback_data="ses_menu"),
    ])
    return InlineKeyboardMarkup(rows)

def kb_ses_study_time() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("25 دقيقة", callback_data="ses_ct_25"),
         InlineKeyboardButton("45 دقيقة", callback_data="ses_ct_45")],
        [InlineKeyboardButton("60 دقيقة", callback_data="ses_ct_60"),
         InlineKeyboardButton("90 دقيقة", callback_data="ses_ct_90")],
        [InlineKeyboardButton("✏️ وقت مخصص", callback_data="ses_ct_c")],
        [InlineKeyboardButton("🔙 إلغاء",    callback_data="ses_menu")],
    ])

def kb_ses_break_time() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("5 دقائق",  callback_data="ses_cb_5"),
         InlineKeyboardButton("10 دقائق", callback_data="ses_cb_10")],
        [InlineKeyboardButton("15 دقيقة", callback_data="ses_cb_15"),
         InlineKeyboardButton("20 دقيقة", callback_data="ses_cb_20")],
        [InlineKeyboardButton("✏️ وقت مخصص", callback_data="ses_cb_c")],
        [InlineKeyboardButton("🔙 إلغاء",    callback_data="ses_menu")],
    ])

def kb_ses_privacy() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 عامة (بدون رمز)", callback_data="ses_priv_n"),
         InlineKeyboardButton("🔒 خاصة (برمز سري)", callback_data="ses_priv_y")],
        [InlineKeyboardButton("🔙 إلغاء", callback_data="ses_menu")],
    ])

def kb_ses_room(room, uid: int, is_in: bool) -> InlineKeyboardMarkup:
    rid   = room["id"]
    is_cr = room["creator_id"] == uid
    st    = room["status"]
    rows  = []
    if is_cr:
        if st == "waiting":
            rows.append([InlineKeyboardButton("🚀 بدء الجلسة",    callback_data=f"ses_start_{rid}")])
        elif st == "ready_check":
            rows.append([InlineKeyboardButton("🚀 بدء الجلسة الآن", callback_data=f"ses_force_start_{rid}")])
        rows.append([InlineKeyboardButton("⏹ إنهاء الغرفة", callback_data=f"ses_end_{rid}")])
    elif not is_in:
        rows.append([InlineKeyboardButton("✅ انضمام للغرفة", callback_data=f"ses_join_{rid}")])
    else:
        rows.append([InlineKeyboardButton("🚪 مغادرة الغرفة", callback_data=f"ses_leave_{rid}")])
    if is_in:
        rows.append([InlineKeyboardButton("💬 التعليقات", callback_data=f"ses_chat_{rid}")])
    if is_cr:
        rows.append([InlineKeyboardButton("⚙️ إعدادات الغرفة", callback_data=f"ses_settings_{rid}")])
    rows.append([InlineKeyboardButton("🔙 الغرف المتاحة", callback_data="ses_rooms")])
    return InlineKeyboardMarkup(rows)

def kb_ses_ready_check(rid: int, is_creator: bool, ready: int, total: int) -> InlineKeyboardMarkup:
    needed  = max(1, int(total * READY_THRESHOLD))
    pct_txt = f"✅ جاهز {ready}/{total} (نحتاج {needed})"
    rows = [[InlineKeyboardButton(pct_txt,         callback_data=f"ses_ready_{rid}")]]
    if is_creator:
        rows.append([InlineKeyboardButton("🚀 بدء الجلسة الآن", callback_data=f"ses_force_start_{rid}")])
    rows.append([InlineKeyboardButton("🏠 الغرفة", callback_data=f"ses_room_{rid}")])
    return InlineKeyboardMarkup(rows)

def kb_ses_attendance(rid: int, sn: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✋ أنا موجود!", callback_data=f"ses_present_{rid}_{sn}")],
        [InlineKeyboardButton("🏠 الغرفة",    callback_data=f"ses_room_{rid}")],
    ])

def kb_ses_back_to_room(rid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 الغرفة", callback_data=f"ses_room_{rid}")
    ]])

def kb_ses_my_stats(uid: int) -> InlineKeyboardMarkup:
    rooms = ses_get_user_rooms(uid)
    rows  = []
    for r in rooms:
        rows.append([InlineKeyboardButton(f"🏠 {r['name']}", callback_data=f"ses_my_room_{r['id']}")])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="ses_menu")])
    return InlineKeyboardMarkup(rows)

def kb_ses_room_stats(rid: int) -> InlineKeyboardMarkup:
    top    = ses_get_room_top(rid)
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
    rows   = []
    for i, p in enumerate(top):
        medal = medals[i] if i < len(medals) else "🏅"
        secs  = p.get("total_study_seconds", 0)
        rows.append([InlineKeyboardButton(
            f"{medal} {p['user_name']} — {_fmt_time(secs)}",
            callback_data=f"ses_pstat_{rid}_{p['user_id']}"
        )])
    back = f"ses_room_{rid}" if ses_get_room(rid) else "ses_menu"
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=back)])
    return InlineKeyboardMarkup(rows)

def kb_ses_global_stats() -> InlineKeyboardMarkup:
    top    = ses_get_global_top()
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
    rows   = []
    for i, p in enumerate(top):
        medal = medals[i] if i < len(medals) else "🏅"
        rows.append([InlineKeyboardButton(
            f"{medal} {p['user_name']} — {_fmt_time(p.get('total_secs', 0))}",
            callback_data=f"ses_gstat_{p['_id']}"
        )])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="ses_menu")])
    return InlineKeyboardMarkup(rows)

def kb_ses_comments(rid: int, uid: int, is_creator: bool, is_muted: bool,
                    comments_open: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("🔄 تحديث", callback_data=f"ses_chat_r_{rid}")]]
    if comments_open and not is_muted:
        rows.append([InlineKeyboardButton("✏️ كتابة تعليق", callback_data=f"ses_chat_w_{rid}")])
    if is_creator:
        tog = "🔒 غلق التعليقات" if comments_open else "🔓 فتح التعليقات"
        rows.append([InlineKeyboardButton(tog, callback_data=f"ses_stog_{rid}")])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"ses_room_{rid}")])
    return InlineKeyboardMarkup(rows)

def kb_ses_members(rid: int, pts: list) -> InlineKeyboardMarkup:
    rows = []
    for p in pts:
        muted = " 🔇" if p.get("is_muted") else ""
        rows.append([InlineKeyboardButton(
            f"{p['user_name']}{muted}",
            callback_data=f"ses_mbr_{rid}_{p['user_id']}"
        )])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"ses_room_{rid}")])
    return InlineKeyboardMarkup(rows)

def kb_ses_member_actions(rid: int, target_uid: int, is_muted: bool,
                          is_creator_view: bool) -> InlineKeyboardMarkup:
    rows = []
    if is_creator_view:
        mute_txt = "🔊 إلغاء الكتم" if is_muted else "🔇 كتم عن التعليقات"
        rows.append([InlineKeyboardButton("🚫 طرد من الغرفة", callback_data=f"ses_kick_{rid}_{target_uid}")])
        rows.append([InlineKeyboardButton(mute_txt,            callback_data=f"ses_mute_{rid}_{target_uid}")])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"ses_members_{rid}")])
    return InlineKeyboardMarkup(rows)

def kb_ses_settings(rid: int, comments_open: bool) -> InlineKeyboardMarkup:
    tog = "🔒 غلق التعليقات" if comments_open else "🔓 فتح التعليقات"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 المشاركون",          callback_data=f"ses_members_{rid}"),
         InlineKeyboardButton("📊 الإحصائيات",         callback_data=f"ses_room_stats_{rid}")],
        [InlineKeyboardButton("⏱ تعديل وقت الدراسة",  callback_data=f"ses_edit_times_{rid}")],
        [InlineKeyboardButton("✏️ تغيير اسم الغرفة",  callback_data=f"ses_rename_{rid}")],
        [InlineKeyboardButton(tog,                     callback_data=f"ses_stog_{rid}")],
        [InlineKeyboardButton("🔙 رجوع",              callback_data=f"ses_room_{rid}")],
    ])

def kb_ses_edit_study_time(rid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("25 دقيقة", callback_data=f"ses_edt_s_{rid}_25"),
         InlineKeyboardButton("45 دقيقة", callback_data=f"ses_edt_s_{rid}_45")],
        [InlineKeyboardButton("60 دقيقة", callback_data=f"ses_edt_s_{rid}_60"),
         InlineKeyboardButton("90 دقيقة", callback_data=f"ses_edt_s_{rid}_90")],
        [InlineKeyboardButton("✏️ وقت مخصص", callback_data=f"ses_edt_s_{rid}_c")],
        [InlineKeyboardButton("🔙 إلغاء",    callback_data=f"ses_settings_{rid}")],
    ])

def kb_ses_edit_break_time(rid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("5 دقائق",  callback_data=f"ses_edt_b_{rid}_5"),
         InlineKeyboardButton("10 دقائق", callback_data=f"ses_edt_b_{rid}_10")],
        [InlineKeyboardButton("15 دقيقة", callback_data=f"ses_edt_b_{rid}_15"),
         InlineKeyboardButton("20 دقيقة", callback_data=f"ses_edt_b_{rid}_20")],
        [InlineKeyboardButton("✏️ وقت مخصص", callback_data=f"ses_edt_b_{rid}_c")],
        [InlineKeyboardButton("🔙 إلغاء",    callback_data=f"ses_settings_{rid}")],
    ])

# ══════════════════════════════════════════════════════════════════
# مهام المؤقت (Job Queue)
# ══════════════════════════════════════════════════════════════════

async def _ses_study_end_job(ctx):
    data      = ctx.job.data
    rid, sn   = data["rid"], data["sn"]
    logger.info(f"[SES] مؤقت الدراسة انتهى: غرفة={rid} جلسة={sn}")
    room      = _get_room_any(rid)
    if not room or room["status"] != "studying" or room.get("current_session") != sn:
        logger.info(f"[SES] تجاهل: status={room and room.get('status')} session={room and room.get('current_session')} sn={sn}")
        return
    phase_end = datetime.datetime.utcnow()
    ses_open_attendance(rid, sn, phase_end)
    markup = kb_ses_attendance(rid, sn)
    pts    = ses_get_participants(rid)
    n      = len(pts)
    for p in pts:
        try:
            await ctx.bot.send_message(
                chat_id=p["user_id"],
                text=(f"⏰ *انتهت جلسة الدراسة!*\n\n"
                      f"🏠 {room['name']} | الجلسة *{sn}*\n"
                      f"👥 {n} مشاركين معك\n\n"
                      "⚡ اضغط *أنا موجود* خلال دقيقتين!"),
                parse_mode="Markdown", reply_markup=markup)
        except Exception as e:
            logger.warning(f"[SES] خطأ إرسال حضور uid={p['user_id']}: {e}")
    ctx.job_queue.run_once(
        _ses_attend_close_job, when=ATTENDANCE_WINDOW,
        data={"rid": rid, "sn": sn}, name=f"ses_attend_{rid}_{sn}")
    logger.info(f"[SES] جُدول إغلاق الحضور بعد {ATTENDANCE_WINDOW}ث")

async def _ses_attend_close_job(ctx):
    data    = ctx.job.data
    rid, sn = data["rid"], data["sn"]
    logger.info(f"[SES] إغلاق الحضور: غرفة={rid} جلسة={sn}")
    room    = _get_room_any(rid)
    if not room or room["status"] not in ("attendance", "studying"):
        logger.info(f"[SES] تجاهل إغلاق الحضور: status={room and room.get('status')}")
        return
    ses_start_break(rid)
    room = _get_room_any(rid)
    brk  = room["break_time"]
    pts  = ses_get_participants(rid)
    n    = len(pts)
    for p in pts:
        try:
            await ctx.bot.send_message(
                chat_id=p["user_id"],
                text=(f"☕ *وقت الاستراحة!*\n\n"
                      f"🏠 {room['name']} | ⏱ {brk} دقيقة\n"
                      f"👥 {n} مشاركين معك\n\n"
                      "استرح قليلاً 💤"),
                parse_mode="Markdown",
                reply_markup=kb_ses_back_to_room(rid))
        except Exception as e:
            logger.warning(f"[SES] خطأ إرسال استراحة uid={p['user_id']}: {e}")
    ctx.job_queue.run_once(
        _ses_break_end_job, when=datetime.timedelta(minutes=brk),
        data={"rid": rid}, name=f"ses_break_{rid}_{sn}")
    logger.info(f"[SES] جُدول نهاية الاستراحة بعد {brk}د")

async def _ses_break_end_job(ctx):
    rid  = ctx.job.data["rid"]
    logger.info(f"[SES] انتهت الاستراحة: غرفة={rid}")
    room = _get_room_any(rid)
    if not room or room["status"] != "break":
        logger.info(f"[SES] تجاهل نهاية الاستراحة: status={room and room.get('status')}")
        return
    ses_open_ready_check(rid)
    pts   = ses_get_participants(rid)
    n     = len(pts)
    needed = max(1, int(n * READY_THRESHOLD))
    sn_next = (room.get("current_session") or 0) + 1
    for p in pts:
        is_cr = p["user_id"] == room["creator_id"]
        markup = kb_ses_ready_check(rid, is_creator=is_cr, ready=0, total=n)
        try:
            await ctx.bot.send_message(
                chat_id=p["user_id"],
                text=(f"🔔 *انتهت الاستراحة!*\n\n"
                      f"🏠 {room['name']} | الجلسة *{sn_next}*\n"
                      f"👥 {n} مشاركين\n\n"
                      f"اضغط *جاهز* للبدء — يبدأ تلقائياً عند {needed} جاهزين ({int(READY_THRESHOLD*100)}%)"),
                parse_mode="Markdown",
                reply_markup=markup)
        except Exception as e:
            logger.warning(f"[SES] خطأ إرسال ready_check uid={p['user_id']}: {e}")
    logger.info(f"[SES] فُتحت نافذة الجاهزية للغرفة={rid}")

async def _ses_do_start_study(bot, jq, rid: int):
    """يبدأ مرحلة دراسة جديدة ويُرسل إشعاراً لكل المشاركين."""
    room = _get_room_any(rid)
    if not room or room["status"] != "ready_check":
        return
    sn    = ses_next_study_phase(rid)
    room  = _get_room_any(rid)
    study = room["study_time"]
    pts   = ses_get_participants(rid)
    n     = len(pts)
    for p in pts:
        try:
            await bot.send_message(
                chat_id=p["user_id"],
                text=(f"📚 *ابدأ الدراسة الآن!*\n\n"
                      f"🏠 {room['name']} | الجلسة *{sn}*\n"
                      f"⏱ {study} دقيقة | 👥 {n} مشاركين\n\n"
                      "ركّز وابدأ! 💪"),
                parse_mode="Markdown",
                reply_markup=kb_ses_back_to_room(rid))
        except Exception as e:
            logger.warning(f"[SES] خطأ إرسال بدء الدراسة uid={p['user_id']}: {e}")
    jq.run_once(
        _ses_study_end_job, when=datetime.timedelta(minutes=study),
        data={"rid": rid, "sn": sn}, name=f"ses_study_{rid}_{sn}")
    logger.info(f"[SES] جُدول نهاية الدراسة جلسة={sn} بعد {study}د")

def _cancel_room_jobs(jq, rid: int, sn: int):
    for name in [f"ses_study_{rid}_{sn}", f"ses_attend_{rid}_{sn}",
                 f"ses_break_{rid}_{sn}", f"ses_break_{rid}_{sn-1}"]:
        for job in jq.get_jobs_by_name(name):
            job.schedule_removal()

def ses_recover_active_rooms(jq):
    """يُعيد جدولة مؤقتات الغرف النشطة بعد إعادة تشغيل البوت."""
    now = datetime.datetime.utcnow()
    active = [_strip(r) for r in _col_r().find(
        {"status": {"$in": ["studying", "attendance", "break"]}})]
    if not active:
        return
    logger.info(f"[SES] استئناف {len(active)} غرفة نشطة...")
    for room in active:
        rid    = room["id"]
        sn     = room.get("current_session", 1)
        status = room["status"]
        try:
            if status == "studying":
                phase_start = room.get("current_phase_start") or now
                if isinstance(phase_start, str):
                    phase_start = datetime.datetime.fromisoformat(phase_start)
                study_end = phase_start + datetime.timedelta(minutes=room["study_time"])
                remaining = max((study_end - now).total_seconds(), 2)
                jq.run_once(_ses_study_end_job, when=remaining,
                            data={"rid": rid, "sn": sn}, name=f"ses_study_{rid}_{sn}")
                logger.info(f"[SES] غرفة={rid} دراسة | جلسة={sn} | متبقٍ={remaining:.0f}ث")

            elif status == "attendance":
                last_end = room.get("last_phase_end") or now
                if isinstance(last_end, str):
                    last_end = datetime.datetime.fromisoformat(last_end)
                attend_end = last_end + datetime.timedelta(seconds=ATTENDANCE_WINDOW)
                remaining = max((attend_end - now).total_seconds(), 2)
                jq.run_once(_ses_attend_close_job, when=remaining,
                            data={"rid": rid, "sn": sn}, name=f"ses_attend_{rid}_{sn}")
                logger.info(f"[SES] غرفة={rid} حضور | متبقٍ={remaining:.0f}ث")

            elif status == "break":
                phase_start = room.get("current_phase_start") or now
                if isinstance(phase_start, str):
                    phase_start = datetime.datetime.fromisoformat(phase_start)
                break_end = phase_start + datetime.timedelta(minutes=room["break_time"])
                remaining = max((break_end - now).total_seconds(), 2)
                jq.run_once(_ses_break_end_job, when=remaining,
                            data={"rid": rid}, name=f"ses_break_{rid}_{sn}")
                logger.info(f"[SES] غرفة={rid} استراحة | متبقٍ={remaining:.0f}ث")

            elif status == "ready_check":
                # لا حاجة لمؤقت — ينتظر قرار المالك أو نسبة الجاهزية
                logger.info(f"[SES] غرفة={rid} جاهزية | لا مؤقت مطلوب")

        except Exception as e:
            logger.error(f"[SES] خطأ استئناف غرفة={rid}: {e}")

# ══════════════════════════════════════════════════════════════════
# معالج الـ Callbacks
# ══════════════════════════════════════════════════════════════════

async def handle_ses_callback(q, ctx, uid: int, chat_id: int):
    d         = q.data
    user      = q.from_user
    user_name = user.first_name or user.username or str(uid)

    # ── القائمة الرئيسية ──────────────────────────────────────────
    if d == "ses_menu":
        await q.edit_message_text(ses_menu_text(), parse_mode="Markdown",
                                  reply_markup=kb_ses_main()); return

    # ── قائمة الغرف ───────────────────────────────────────────────
    if d == "ses_rooms":
        rooms = ses_get_active_rooms()
        txt   = "🏠 *الغرف المتاحة:*\n\nاضغط على غرفة لعرض تفاصيلها." if rooms \
                else "🏠 *لا توجد غرف مفتوحة.*\n\nكن الأول وأنشئ غرفتك!"
        await q.edit_message_text(txt, parse_mode="Markdown",
                                  reply_markup=kb_ses_rooms(rooms)); return

    # ── إنشاء غرفة ────────────────────────────────────────────────
    if d == "ses_create":
        owned = list(_col_r().find({"creator_id": uid, "status": {"$in": _ACTIVE}}))
        if owned:
            await q.answer("⚠️ لديك غرفة مفتوحة! أنهها أولاً.", show_alert=True); return
        if ses_is_in_any_room(uid):
            await q.answer("⚠️ أنت منضم لغرفة! غادرها أولاً.", show_alert=True); return
        ctx.user_data["state"] = "wait_ses_study_time_pre"
        await q.edit_message_text(
            "🏗 *إنشاء غرفة جديدة*\n\n📚 اختر وقت الدراسة:",
            parse_mode="Markdown", reply_markup=kb_ses_study_time()); return

    # ── اختيار وقت الدراسة ────────────────────────────────────────
    if d.startswith("ses_ct_"):
        val = d[7:]
        if val == "c":
            ctx.user_data["state"] = "wait_ses_study_time"
            await q.edit_message_text(
                "⏱ أرسل وقت الدراسة بالدقائق (5–180):",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ إلغاء", callback_data="ses_menu")]])); return
        ctx.user_data["ses_study_time"] = int(val)
        ctx.user_data.pop("state", None)
        await q.edit_message_text(
            f"✅ وقت الدراسة: *{val} دقيقة*\n\n☕ اختر وقت الاستراحة:",
            parse_mode="Markdown", reply_markup=kb_ses_break_time()); return

    # ── اختيار وقت الاستراحة ──────────────────────────────────────
    if d.startswith("ses_cb_"):
        val = d[7:]
        if val == "c":
            ctx.user_data["state"] = "wait_ses_break_time"
            await q.edit_message_text(
                "☕ أرسل وقت الاستراحة بالدقائق (1–60):",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ إلغاء", callback_data="ses_menu")]])); return
        ctx.user_data["ses_break_time"] = int(val)
        ctx.user_data.pop("state", None)
        # طلب اسم الغرفة
        ctx.user_data["state"] = "wait_ses_room_name_create"
        await q.edit_message_text(
            f"✅ الدراسة: *{ctx.user_data.get('ses_study_time', '?')}د* | "
            f"الاستراحة: *{val}د*\n\n"
            "✏️ أرسل *اسم الغرفة* أو استخدم اسمك الخاص:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"👤 استخدم اسمي ({user_name})",
                                      callback_data="ses_name_skip")],
                [InlineKeyboardButton("❌ إلغاء", callback_data="ses_menu")],
            ])); return

    # ── تخطي اسم الغرفة (استخدام اسم المنشئ) ─────────────────────
    if d == "ses_name_skip":
        ctx.user_data["ses_room_name"] = user_name
        ctx.user_data.pop("state", None)
        await q.edit_message_text(
            f"✅ اسم الغرفة: *{user_name}*\n\nهل الغرفة عامة أم خاصة؟",
            parse_mode="Markdown", reply_markup=kb_ses_privacy()); return

    # ── الخصوصية ──────────────────────────────────────────────────
    if d == "ses_priv_n":
        study = ctx.user_data.pop("ses_study_time", None)
        brk   = ctx.user_data.pop("ses_break_time", None)
        name  = ctx.user_data.pop("ses_room_name", user_name)
        ctx.user_data.pop("state", None)
        if not study or not brk:
            await q.answer("⚠️ انتهت الجلسة. ابدأ من جديد.", show_alert=True); return
        rid  = ses_create_room(uid, user_name, study, brk, password=None, custom_name=name)
        room = ses_get_room(rid); pts = ses_get_participants(rid)
        await q.edit_message_text(
            "✅ *تم إنشاء الغرفة!*\n\n" + _room_info_text(room, pts) +
            "\n\n🚀 اضغط *بدء الجلسة* عندما يكون الجميع جاهزاً.",
            parse_mode="Markdown", reply_markup=kb_ses_room(room, uid, True)); return

    if d == "ses_priv_y":
        if not ctx.user_data.get("ses_study_time") or not ctx.user_data.get("ses_break_time"):
            await q.answer("⚠️ انتهت الجلسة. ابدأ من جديد.", show_alert=True); return
        ctx.user_data["state"] = "wait_ses_password"
        await q.edit_message_text(
            "🔒 أرسل الرمز السري للغرفة:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ إلغاء", callback_data="ses_menu")]])); return

    # ── عرض غرفة (يجب قبل ses_room_stats_) ───────────────────────
    if d.startswith("ses_room_") and not d.startswith("ses_room_stats_"):
        rid  = int(d[9:])
        room = ses_get_room(rid)
        if not room:
            await q.answer("⚠️ الغرفة غير موجودة أو انتهت.", show_alert=True); return
        pts   = ses_get_participants(rid)
        is_in = ses_is_in_room(rid, uid)
        await q.edit_message_text(_room_info_text(room, pts), parse_mode="Markdown",
                                  reply_markup=kb_ses_room(room, uid, is_in)); return

    # ── انضمام ────────────────────────────────────────────────────
    if d.startswith("ses_join_"):
        rid  = int(d[9:])
        room = ses_get_room(rid)
        if not room:
            await q.answer("⚠️ الغرفة غير موجودة أو انتهت.", show_alert=True); return
        if ses_is_in_room(rid, uid):
            await q.answer("أنت بالفعل في هذه الغرفة!", show_alert=False); return
        if room.get("password"):
            ctx.user_data["state"]        = "wait_ses_join_pw"
            ctx.user_data["ses_join_rid"] = rid
            await q.edit_message_text(
                f"🔒 الغرفة *{room['name']}* مقفلة\n\nأرسل الرمز السري:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ إلغاء", callback_data="ses_rooms")]])); return
        result = ses_join_room(rid, uid, user_name)
        if result is None:
            await q.answer("⚠️ أنت منضم لغرفة أخرى! غادرها أولاً.", show_alert=True); return
        room = ses_get_room(rid); pts = ses_get_participants(rid)
        await q.edit_message_text("✅ *انضممت للغرفة!*\n\n" + _room_info_text(room, pts),
                                  parse_mode="Markdown",
                                  reply_markup=kb_ses_room(room, uid, True)); return

    # ── مغادرة ────────────────────────────────────────────────────
    if d.startswith("ses_leave_"):
        rid  = int(d[10:])
        room = _get_room_any(rid)
        if room and room["creator_id"] == uid:
            await q.answer("❌ المنشئ لا يمكنه المغادرة. أنهِ الغرفة.", show_alert=True); return
        ses_leave_room(rid, uid)
        await q.edit_message_text("✅ *غادرت الغرفة.*", parse_mode="Markdown",
                                  reply_markup=kb_ses_rooms(ses_get_active_rooms())); return

    # ── بدء الجلسة ────────────────────────────────────────────────
    if d.startswith("ses_start_"):
        rid  = int(d[10:])
        room = ses_get_room(rid)
        if not room:
            await q.answer("⚠️ الغرفة غير موجودة.", show_alert=True); return
        if room["creator_id"] != uid:
            await q.answer("❌ فقط المنشئ يمكنه البدء.", show_alert=True); return
        if room["status"] != "waiting":
            await q.answer("⚠️ الجلسة بدأت بالفعل!", show_alert=True); return
        ses_start_room(rid)
        study = room["study_time"]
        pts_all = ses_get_participants(rid)
        n       = len(pts_all)
        for p in pts_all:
            if p["user_id"] != uid:
                try:
                    await ctx.bot.send_message(
                        chat_id=p["user_id"],
                        text=(f"🚀 *بدأت الجلسة!*\n\n"
                              f"🏠 {room['name']} | الجلسة 1\n"
                              f"⏱ {study} دقيقة | 👥 {n} مشاركين\n\n"
                              "ركّز وابدأ! 💪"),
                        parse_mode="Markdown",
                        reply_markup=kb_ses_back_to_room(rid))
                except Exception: pass
        ctx.job_queue.run_once(
            _ses_study_end_job, when=datetime.timedelta(minutes=study),
            data={"rid": rid, "sn": 1}, name=f"ses_study_{rid}_1")
        logger.info(f"[SES] جُدول نهاية الدراسة: غرفة={rid} جلسة=1 بعد {study}د")
        room = ses_get_room(rid); pts = ses_get_participants(rid)
        await q.edit_message_text("🚀 *بدأت الجلسة!*\n\n" + _room_info_text(room, pts),
                                  parse_mode="Markdown",
                                  reply_markup=kb_ses_room(room, uid, True)); return

    # ── الجاهزية لبدء الجلسة التالية ─────────────────────────────
    if d.startswith("ses_ready_"):
        rid  = int(d[10:])
        room = ses_get_room(rid)
        if not room or room["status"] != "ready_check":
            await q.answer("⚠️ لا توجد نافذة جاهزية الآن.", show_alert=True); return
        if not ses_is_in_room(rid, uid):
            await q.answer("⚠️ لست في هذه الغرفة.", show_alert=True); return
        ready, total = ses_mark_ready(rid, uid)
        needed = max(1, int(total * READY_THRESHOLD))
        await q.answer(f"✅ تم تسجيل جاهزيتك! ({ready}/{total})")
        # حدّث الأزرار في رسالة المستخدم لتعكس العدد الجديد
        try:
            is_cr  = uid == room["creator_id"]
            await q.edit_message_reply_markup(
                reply_markup=kb_ses_ready_check(rid, is_creator=is_cr,
                                                ready=ready, total=total))
        except Exception: pass
        # بدء تلقائي إذا بلغ العدد الحد المطلوب
        if ready >= needed:
            logger.info(f"[SES] الحد (25%) بُلغ ({ready}/{total}) → بدء تلقائي")
            await _ses_do_start_study(ctx.bot, ctx.job_queue, rid)
        return

    # ── المالك يبدأ الجلسة التالية يدوياً ──────────────────────────
    if d.startswith("ses_force_start_"):
        rid  = int(d[16:])
        room = ses_get_room(rid)
        if not room:
            await q.answer("⚠️ الغرفة غير موجودة.", show_alert=True); return
        if room["creator_id"] != uid:
            await q.answer("❌ فقط المنشئ يمكنه البدء.", show_alert=True); return
        if room["status"] != "ready_check":
            await q.answer("⚠️ الجلسة ليست في وضع الجاهزية.", show_alert=True); return
        await q.answer("🚀 تم بدء الجلسة!")
        await _ses_do_start_study(ctx.bot, ctx.job_queue, rid)
        room = ses_get_room(rid); pts = ses_get_participants(rid)
        try:
            await q.edit_message_text("🚀 *بدأت الجلسة!*\n\n" + _room_info_text(room, pts),
                                      parse_mode="Markdown",
                                      reply_markup=kb_ses_room(room, uid, True))
        except Exception: pass
        return

    # ── إنهاء الغرفة ──────────────────────────────────────────────
    if d.startswith("ses_end_"):
        rid  = int(d[8:])
        room = _get_room_any(rid)
        if not room:
            await q.answer("⚠️ الغرفة غير موجودة.", show_alert=True); return
        if room["creator_id"] != uid:
            await q.answer("❌ فقط المنشئ يمكنه الإنهاء.", show_alert=True); return
        sn  = room.get("current_session", 1) or 1
        _cancel_room_jobs(ctx.job_queue, rid, sn)
        pts = ses_get_participants(rid)
        ses_end_room(rid)
        for p in pts:
            if p["user_id"] != uid:
                try:
                    await ctx.bot.send_message(
                        chat_id=p["user_id"],
                        text=f"🏁 *انتهت الغرفة*\n\n🏠 {room['name']}\n\nشكراً لمشاركتك! 🎓",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("📊 إحصائيات الغرفة", callback_data=f"ses_room_stats_{rid}")
                        ]]))
                except Exception: pass
        await q.edit_message_text(
            "✅ *تم إنهاء الغرفة.*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 إحصائيات الغرفة", callback_data=f"ses_room_stats_{rid}")],
                [InlineKeyboardButton("🔙 رجوع",            callback_data="ses_menu")],
            ])); return

    # ── تسجيل الحضور ──────────────────────────────────────────────
    if d.startswith("ses_present_"):
        parts = d[12:].rsplit("_", 1)
        rid, sn = int(parts[0]), int(parts[1])
        room = _get_room_any(rid)
        if not room:
            await q.answer("⚠️ الغرفة انتهت.", show_alert=True); return
        result = ses_confirm_attendance(rid, uid, sn)
        if result is False:
            await q.answer("✅ سجّلت حضورك مسبقاً!", show_alert=False); return
        await q.answer(f"✅ تم التسجيل! ({_fmt_time(result)} دراسة)", show_alert=True)
        try: await q.edit_message_reply_markup(reply_markup=None)
        except Exception: pass
        return

    # ── المشاركون ─────────────────────────────────────────────────
    if d.startswith("ses_members_"):
        rid  = int(d[12:])
        room = ses_get_room(rid)
        if not room:
            await q.answer("⚠️ الغرفة غير موجودة.", show_alert=True); return
        pts  = ses_get_participants(rid)
        await q.edit_message_text(
            f"👥 *مشاركو غرفة {room['name']}* ({len(pts)})\n\nاضغط على اسم للتفاصيل:",
            parse_mode="Markdown", reply_markup=kb_ses_members(rid, pts)); return

    # ── تفاصيل مشارك ──────────────────────────────────────────────
    if d.startswith("ses_mbr_"):
        parts      = d[8:].rsplit("_", 1)
        rid        = int(parts[0])
        target_uid = int(parts[1])
        room       = ses_get_room(rid)
        if not room:
            await q.answer("⚠️ الغرفة غير موجودة.", show_alert=True); return
        is_cr    = room["creator_id"] == uid
        is_self  = target_uid == uid
        is_muted = ses_is_muted(rid, target_uid)
        await q.edit_message_text(
            _room_member_stat_text(rid, target_uid), parse_mode="Markdown",
            reply_markup=kb_ses_member_actions(
                rid, target_uid, is_muted,
                is_creator_view=(is_cr and not is_self)
            )); return

    # ── طرد عضو ───────────────────────────────────────────────────
    if d.startswith("ses_kick_"):
        parts      = d[9:].rsplit("_", 1)
        rid        = int(parts[0])
        target_uid = int(parts[1])
        room       = ses_get_room(rid)
        if not room or room["creator_id"] != uid:
            await q.answer("❌ غير مصرح.", show_alert=True); return
        if target_uid == uid:
            await q.answer("❌ لا يمكنك طرد نفسك.", show_alert=True); return
        p_name = (_get_participant(rid, target_uid) or {}).get("user_name", "العضو")
        ses_kick_member(rid, target_uid)
        try:
            await ctx.bot.send_message(
                chat_id=target_uid,
                text=f"🚫 تم طردك من غرفة *{room['name']}*.",
                parse_mode="Markdown")
        except Exception: pass
        pts = ses_get_participants(rid)
        await q.edit_message_text(
            f"✅ تم طرد *{p_name}* من الغرفة.",
            parse_mode="Markdown",
            reply_markup=kb_ses_members(rid, pts)); return

    # ── كتم / فك كتم عضو ──────────────────────────────────────────
    if d.startswith("ses_mute_"):
        parts      = d[9:].rsplit("_", 1)
        rid        = int(parts[0])
        target_uid = int(parts[1])
        room       = ses_get_room(rid)
        if not room or room["creator_id"] != uid:
            await q.answer("❌ غير مصرح.", show_alert=True); return
        new_muted = ses_toggle_mute(rid, target_uid)
        p_name    = (_get_participant(rid, target_uid) or {}).get("user_name", "العضو")
        txt       = f"🔇 تم كتم *{p_name}*" if new_muted else f"🔊 تم فك كتم *{p_name}*"
        await q.answer(txt.replace("*", ""), show_alert=True)
        is_muted = new_muted
        await q.edit_message_reply_markup(
            reply_markup=kb_ses_member_actions(rid, target_uid, is_muted, True)); return

    # ── التعليقات (عرض) ───────────────────────────────────────────
    if d.startswith("ses_chat_r_"):          # تحديث
        rid  = int(d[11:])
        room = ses_get_room(rid)
        if not room:
            await q.answer("⚠️ الغرفة انتهت.", show_alert=True); return
        is_cr   = room["creator_id"] == uid
        is_muted = ses_is_muted(rid, uid)
        open_   = room.get("comments_open", True)
        await q.answer("🔄 تم التحديث", show_alert=False)
        try:
            await q.edit_message_text(
                _ses_comments_text(rid), parse_mode="Markdown",
                reply_markup=kb_ses_comments(rid, uid, is_cr, is_muted, open_))
        except Exception: pass
        return

    if d.startswith("ses_chat_w_"):          # كتابة تعليق
        rid  = int(d[11:])
        room = ses_get_room(rid)
        if not room:
            await q.answer("⚠️ الغرفة انتهت.", show_alert=True); return
        if not room.get("comments_open", True):
            await q.answer("🔒 التعليقات مغلقة.", show_alert=True); return
        if ses_is_muted(rid, uid):
            await q.answer("🔇 أنت مكتوم عن التعليقات.", show_alert=True); return
        ctx.user_data["state"]         = "wait_ses_chat"
        ctx.user_data["ses_chat_rid"]  = rid
        await q.edit_message_text(
            "✏️ أرسل تعليقك الآن:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ إلغاء", callback_data=f"ses_chat_{rid}")]])); return

    if d.startswith("ses_chat_"):            # عرض التعليقات
        rid  = int(d[9:])
        room = ses_get_room(rid)
        if not room:
            await q.answer("⚠️ الغرفة غير موجودة.", show_alert=True); return
        is_cr    = room["creator_id"] == uid
        is_muted = ses_is_muted(rid, uid)
        open_    = room.get("comments_open", True)
        await q.edit_message_text(
            _ses_comments_text(rid), parse_mode="Markdown",
            reply_markup=kb_ses_comments(rid, uid, is_cr, is_muted, open_)); return

    # ── إعدادات الغرفة ────────────────────────────────────────────
    if d.startswith("ses_settings_"):
        rid  = int(d[13:])
        room = ses_get_room(rid)
        if not room or room["creator_id"] != uid:
            await q.answer("❌ غير مصرح.", show_alert=True); return
        await q.edit_message_text(
            f"⚙️ *إعدادات غرفة {room['name']}*\n\n"
            f"📚 الدراسة: *{room['study_time']}د* | ☕ الاستراحة: *{room['break_time']}د*",
            parse_mode="Markdown",
            reply_markup=kb_ses_settings(rid, room.get("comments_open", True))); return

    # ── تعديل وقت الدراسة ─────────────────────────────────────────
    if d.startswith("ses_edit_times_"):
        rid  = int(d[15:])
        room = ses_get_room(rid)
        if not room or room["creator_id"] != uid:
            await q.answer("❌ غير مصرح.", show_alert=True); return
        await q.edit_message_text(
            f"⏱ *تعديل وقت الدراسة والاستراحة*\n\n"
            f"الوقت الحالي: 📚 *{room['study_time']}د* | ☕ *{room['break_time']}د*\n\n"
            "اختر وقت الدراسة الجديد:",
            parse_mode="Markdown",
            reply_markup=kb_ses_edit_study_time(rid)); return

    # ── اختيار وقت الدراسة الجديد ─────────────────────────────────
    if d.startswith("ses_edt_s_"):
        rest    = d[10:]
        rid_str, val = rest.rsplit("_", 1)
        rid  = int(rid_str)
        room = ses_get_room(rid)
        if not room or room["creator_id"] != uid:
            await q.answer("❌ غير مصرح.", show_alert=True); return
        if val == "c":
            ctx.user_data["state"]        = "wait_ses_edit_study"
            ctx.user_data["ses_edit_rid"] = rid
            await q.edit_message_text(
                "⏱ أرسل وقت الدراسة الجديد بالدقائق (5–180):",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ إلغاء", callback_data=f"ses_settings_{rid}")]])); return
        ctx.user_data["ses_edit_study"] = int(val)
        await q.edit_message_text(
            f"✅ وقت الدراسة: *{val} دقيقة*\n\n☕ اختر وقت الاستراحة الجديد:",
            parse_mode="Markdown",
            reply_markup=kb_ses_edit_break_time(rid)); return

    # ── اختيار وقت الاستراحة الجديد ───────────────────────────────
    if d.startswith("ses_edt_b_"):
        rest    = d[10:]
        rid_str, val = rest.rsplit("_", 1)
        rid  = int(rid_str)
        room = ses_get_room(rid)
        if not room or room["creator_id"] != uid:
            await q.answer("❌ غير مصرح.", show_alert=True); return
        if val == "c":
            ctx.user_data["state"]        = "wait_ses_edit_break"
            ctx.user_data["ses_edit_rid"] = rid
            await q.edit_message_text(
                "☕ أرسل وقت الاستراحة الجديد بالدقائق (1–60):",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ إلغاء", callback_data=f"ses_settings_{rid}")]])); return
        study = ctx.user_data.pop("ses_edit_study", None) or room["study_time"]
        brk   = int(val)
        ses_update_room_times(rid, study, brk)
        room  = _get_room_any(rid)
        await q.answer(f"✅ تم التحديث: {study}د دراسة / {brk}د استراحة", show_alert=True)
        await q.edit_message_text(
            f"⚙️ *إعدادات غرفة {room['name']}*\n\n"
            f"📚 الدراسة: *{room['study_time']}د* | ☕ الاستراحة: *{room['break_time']}د*",
            parse_mode="Markdown",
            reply_markup=kb_ses_settings(rid, room.get("comments_open", True))); return

    # ── تغيير اسم الغرفة ──────────────────────────────────────────
    if d.startswith("ses_rename_"):
        rid  = int(d[11:])
        room = ses_get_room(rid)
        if not room or room["creator_id"] != uid:
            await q.answer("❌ غير مصرح.", show_alert=True); return
        ctx.user_data["state"]          = "wait_ses_rename"
        ctx.user_data["ses_rename_rid"] = rid
        await q.edit_message_text(
            f"✏️ أرسل الاسم الجديد للغرفة *{room['name']}*:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ إلغاء", callback_data=f"ses_settings_{rid}")]])); return

    # ── تبديل التعليقات (من الإعدادات أو التعليقات) ───────────────
    if d.startswith("ses_stog_"):
        rid  = int(d[9:])
        room = ses_get_room(rid)
        if not room or room["creator_id"] != uid:
            await q.answer("❌ غير مصرح.", show_alert=True); return
        new_open = ses_toggle_comments(rid)
        txt = "🔓 تم فتح التعليقات" if new_open else "🔒 تم غلق التعليقات"
        await q.answer(txt, show_alert=False)
        room = ses_get_room(rid)
        await q.edit_message_reply_markup(
            reply_markup=kb_ses_settings(rid, room.get("comments_open", True))); return

    # ── إحصائياتي ─────────────────────────────────────────────────
    if d == "ses_my_stats":
        await q.edit_message_text(
            ses_my_stats_text(uid), parse_mode="Markdown",
            reply_markup=kb_ses_my_stats(uid)); return

    # ── إحصائياتي في غرفة محددة ───────────────────────────────────
    if d.startswith("ses_my_room_"):
        rid = int(d[12:])
        await q.edit_message_text(
            _my_room_stat_text(rid, uid), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="ses_my_stats")]])); return

    # ── إحصائيات غرفة (قائمة بالأعضاء) ───────────────────────────
    if d.startswith("ses_room_stats_"):
        rid  = int(d[15:])
        room = _get_room_any(rid)
        if not room:
            await q.answer("⚠️ الغرفة غير موجودة.", show_alert=True); return
        await q.edit_message_text(
            f"📊 *إحصائيات {room['name']}*\n"
            f"📚 {room['study_time']}د | ☕ {room['break_time']}د\n\n"
            "اضغط على اسم لعرض تفاصيله:",
            parse_mode="Markdown",
            reply_markup=kb_ses_room_stats(rid)); return

    # ── تفاصيل عضو في غرفة ────────────────────────────────────────
    if d.startswith("ses_pstat_"):
        parts = d[10:].rsplit("_", 1)
        rid, uid2 = int(parts[0]), int(parts[1])
        back = f"ses_room_stats_{rid}"
        await q.edit_message_text(
            _room_member_stat_text(rid, uid2), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data=back)]])); return

    # ── الإحصائيات العامة (قائمة بالمستخدمين) ─────────────────────
    if d == "ses_global_stats":
        top = ses_get_global_top()
        if not top:
            txt = "🌍 *الإحصائيات العامة*\n\n_لا توجد بيانات بعد._"
            await q.edit_message_text(txt, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup([[
                                          InlineKeyboardButton("🔙 رجوع", callback_data="ses_menu")]])); return
        await q.edit_message_text(
            "🌍 *أفضل المستخدمين (كل الأوقات)*\n\nاضغط على اسم لعرض تفاصيله:",
            parse_mode="Markdown",
            reply_markup=kb_ses_global_stats()); return

    # ── تفاصيل مستخدم عالمي ───────────────────────────────────────
    if d.startswith("ses_gstat_"):
        uid2 = int(d[10:])
        await q.edit_message_text(
            _global_user_stat_text(uid2), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="ses_global_stats")]])); return

    await q.answer()
