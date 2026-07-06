from .shared import *
from .study_sessions import ses_recover_active_rooms

def _setup_grade_calc_feature():
    mdb = get_mongo_db()
    b = mdb["buttons"].find_one({"id": 8613})
    if b:
        mdb["buttons"].update_one(
            {"id": 8613},
            {"$set": {"special_action": "grade_calc"}}
        )
        logging.info("تم تعيين special_action=grade_calc للزر #8613.")

def _setup_countdown_feature():
    mdb = get_mongo_db()
    b = mdb["buttons"].find_one({"id": 8615})
    if b:
        mdb["buttons"].update_one(
            {"id": 8615},
            {"$set": {"special_action": "countdown_mgr"}}
        )
        logging.info("تم تعيين special_action=countdown_mgr للزر #8615.")

def _setup_ai_chat_feature():
    mdb = get_mongo_db()
    b = mdb["buttons"].find_one({"id": 8617})
    if b:
        mdb["buttons"].update_one(
            {"id": 8617},
            {"$set": {"special_action": "ai_chat"}}
        )
        logging.info("تم تعيين special_action=ai_chat للزر #8617.")

async def _cd_auto_update_job(ctx):
    if not _CD_WATCH:
        return
    to_remove = []
    for (chat_id, msg_id), (cd_id, user_id) in list(_CD_WATCH.items()):
        cd = cd_get(cd_id)
        if not cd:
            to_remove.append((chat_id, msg_id))
            continue
        text = _cd_message_text(cd)
        kb   = _cd_view_kb(cd["id"], cd.get("owner_id"), user_id, is_admin(user_id), cd["target_dt"])
        try:
            await ctx.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=kb,
            )
        except Exception:
            to_remove.append((chat_id, msg_id))
    for key in to_remove:
        _CD_WATCH.pop(key, None)

# ── إعداد البوت ──────────────────────────────────────────────────
async def post_init(app):
    sid = os.environ.get("SUPER_ADMIN_ID", "").strip()
    if sid.isdigit() and not is_admin(int(sid)):
        add_admin(int(sid)); logging.info(f"Super admin {sid} added.")
    import datetime as _dt
    if sid.isdigit() or get_storage_channel_id():
        app.job_queue.run_daily(
            _auto_backup_job,
            time=_dt.time(hour=3, minute=0, tzinfo=_dt.timezone.utc),
            name="auto_backup"
        )
        logging.info("تم جدولة النسخ الاحتياطي التلقائي يومياً عند 03:00 UTC.")
    _setup_pomodoro_feature()
    logging.info("تم إعداد ميزة البومودورو.")
    _setup_grade_calc_feature()
    _setup_countdown_feature()
    _setup_ai_chat_feature()
    logging.info("تم إعداد ميزة محادثة AI للسادس العلمي.")
    app.job_queue.run_repeating(
        _cd_auto_update_job,
        interval=60,
        first=60,
        name="cd_auto_update"
    )
    logging.info("تم تسجيل مهمة تحديث العداد التنازلي كل دقيقة.")
    ses_recover_active_rooms(app.job_queue)
    logging.info("تم التحقق من استئناف الجلسات النشطة.")
    init_ai_semaphore()
    logging.info("تم تهيئة طابور طلبات AI.")
