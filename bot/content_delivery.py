from .shared import *

def detect_content(m):
    if m.photo:
        return "photo", m.caption, m.photo[-1].file_id
    if m.document:
        return "file", m.caption, m.document.file_id
    if m.video:
        return "video", m.caption, m.video.file_id
    if m.audio:
        return "audio", m.caption, m.audio.file_id
    if m.voice:
        return "audio", m.caption, m.voice.file_id
    if m.text:
        return "text", m.text, None
    return None, None, None

async def upload_to_channel(bot, fid: str, file_type: str, caption: str = None) -> int | None:
    ch = get_storage_channel_id()
    if not ch:
        return None
    try:
        cap = caption or None
        if file_type == "photo":
            msg = await bot.send_photo(ch, fid, caption=cap)
        elif file_type == "file":
            msg = await bot.send_document(ch, fid, caption=cap)
        elif file_type == "video":
            msg = await bot.send_video(ch, fid, caption=cap)
        elif file_type == "audio":
            msg = await bot.send_audio(ch, fid, caption=cap)
        else:
            return None
        return msg.message_id
    except Exception as e:
        logging.warning(f"فشل رفع الملف للقناة: {e}")
        return None

async def upload_item_to_channel(bot, item) -> int | None:
    ch = get_storage_channel_id()
    if not ch:
        return None
    file_type = item.get("type")
    caption = item.get("content") or None
    fid = item.get("file_id")
    local_path = item.get("local_path")
    if local_path and os.path.exists(local_path):
        try:
            with open(local_path, "rb") as f:
                if file_type == "photo":
                    msg = await bot.send_photo(ch, f, caption=caption)
                elif file_type == "file":
                    msg = await bot.send_document(ch, f, caption=caption)
                elif file_type == "video":
                    msg = await bot.send_video(ch, f, caption=caption)
                elif file_type == "audio":
                    msg = await bot.send_audio(ch, f, caption=caption)
                else:
                    return None
            return msg.message_id if msg else None
        except Exception as e:
            logging.warning(f"فشل رفع الملف المحلي للقناة للعنصر {item.get('id')}: {e}")
    if fid:
        return await upload_to_channel(bot, fid, file_type, caption)
    return None

async def send_file_item(target, item, reply_markup=None, extra_caption="", bot=None):
    t = item["type"]
    fid = item.get("file_id")
    cap = item.get("content") or ""
    if extra_caption:
        cap = f"{cap}\n{extra_caption}" if cap else extra_caption
    lpath = item.get("local_path")
    iid = item.get("id")
    channel_msg_id = item.get("channel_msg_id")
    kwargs = {"caption": cap}
    if reply_markup:
        kwargs["reply_markup"] = reply_markup

    async def _send_from_channel():
        ch = get_storage_channel_id()
        if not channel_msg_id or not ch:
            return None
        copy_bot = bot
        if copy_bot is None and hasattr(target, "get_bot"):
            try:
                copy_bot = target.get_bot()
            except Exception:
                copy_bot = None
        if copy_bot is None:
            logging.warning("فشل الإرسال من القناة: لا يوجد كائن بوت للنسخ")
            return None
        try:
            return await copy_bot.copy_message(
                chat_id=target.chat_id,
                from_chat_id=ch,
                message_id=channel_msg_id,
                caption=cap or None,
                reply_markup=reply_markup,
            )
        except Exception as e:
            logging.warning(f"فشل الإرسال من القناة: {e}")
            return None

    async def _send_from_fid():
        if t == "photo":
            return await target.reply_photo(fid, **kwargs)
        elif t == "file":
            return await target.reply_document(fid, **kwargs)
        elif t == "video":
            return await target.reply_video(fid, **kwargs)
        elif t == "audio":
            return await target.reply_audio(fid, **kwargs)
        return None

    async def _send_from_local():
        if not lpath or not os.path.exists(lpath):
            return None
        with open(lpath, "rb") as f:
            if t == "photo":
                msg = await target.reply_photo(f, **kwargs)
            elif t == "file":
                msg = await target.reply_document(f, **kwargs)
            elif t == "video":
                msg = await target.reply_video(f, **kwargs)
            elif t == "audio":
                msg = await target.reply_audio(f, **kwargs)
            else:
                return None
        new_fid = None
        if msg:
            if t == "photo" and msg.photo:
                new_fid = msg.photo[-1].file_id
            elif t == "file" and msg.document:
                new_fid = msg.document.file_id
            elif t == "video" and msg.video:
                new_fid = msg.video.file_id
            elif t == "audio" and msg.audio:
                new_fid = msg.audio.file_id
            if new_fid and iid:
                upd_item_file_id(iid, new_fid)
        return msg

    if t == "text":
        return await target.reply_text(cap, **({"reply_markup": reply_markup} if reply_markup else {}))

    # أولوية 1: الإرسال من قناة التخزين (الأسرع والأكثر موثوقية)
    if channel_msg_id and get_storage_channel_id():
        msg = await _send_from_channel()
        if msg:
            return msg

    # أولوية 2: الملف المحلي (للملفات القديمة قبل تفعيل القناة)
    if lpath and os.path.exists(lpath):
        try:
            msg = await _send_from_local()
            if msg:
                return msg
        except Exception:
            pass

    # أولوية 3: file_id مباشرة كحل أخير
    if fid:
        try:
            return await _send_from_fid()
        except Exception:
            pass

    return None

async def clear_add_content_control(ctx, chat_id):
    msg_id = ctx.user_data.pop("add_content_control_msg_id", None)
    if msg_id:
        try:
            await ctx.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

def kb_confirm_delete(bid):
    b = get_btn(bid)
    pid = b["parent_id"] if b else None
    back_cb = "m_r" if pid is None else f"m_{pid}"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ موافق", callback_data=f"x_{bid}"),
        InlineKeyboardButton("❌ إلغاء", callback_data=back_cb),
    ]])


# ── مساعد اللوحة الثابتة ─────────────────────────────────────────
async def set_panel(ctx, chat_id, text, markup=None):
    msg = await ctx.bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")
    ctx.user_data["panel_id"] = msg.message_id

# ── إذاعة رسالة لجميع المستخدمين ────────────────────────────────
async def do_broadcast(bot, from_chat_id: int, msg_id: int) -> tuple:
    """ينسخ الرسالة msg_id من from_chat_id إلى جميع المستخدمين. يُرجع (نجح, فشل)."""
    import asyncio
    user_ids = [r[0] for r in db().execute("SELECT user_id FROM user_stats").fetchall()]
    success = 0
    failed  = 0
    for uid in user_ids:
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=from_chat_id, message_id=msg_id)
            success += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)   # تجنب flood limits
    return success, failed

# ── إعادة إرسال نافذة التنبيه المعلقة (دون تحديث العداد) ─────────
async def resend_notif_gate(target, uid, bid):
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
            await target.reply_text(msg, parse_mode="Markdown", reply_markup=markup)
        except Exception:
            await target.reply_text(msg, reply_markup=markup)
    except Exception:
        pass

async def deliver_denied_content(bot, chat_id, bid_str):
    """يرسل المحتوى المطلوب مباشرة بعد الرفض النهائي — يتجاوز فحص الاشتراك."""
    if not bid_str or not str(bid_str).isdigit():
        return
    bid_int = int(bid_str)
    items = get_items(bid_int)
    if not items:
        return
    b       = get_btn(bid_int)
    no_cap  = (b.get("no_caption", 0) or 0) if b else 0
    extra   = get_global_caption() if not no_cap else ""
    no_btn  = (b.get("no_btn_caption", 0) or 0) if b else 0
    markup  = build_caption_btn_markup(get_caption_buttons() if not no_btn else [])

    class _T:
        def __init__(self, b, cid):
            self._b = b; self.chat_id = cid
        def get_bot(self): return self._b
        async def reply_text(self, txt, **kw):
            return await self._b.send_message(chat_id=self.chat_id, text=txt, **kw)
        async def reply_photo(self, p, **kw):
            return await self._b.send_photo(chat_id=self.chat_id, photo=p, **kw)
        async def reply_document(self, d, **kw):
            return await self._b.send_document(chat_id=self.chat_id, document=d, **kw)
        async def reply_video(self, v, **kw):
            return await self._b.send_video(chat_id=self.chat_id, video=v, **kw)
        async def reply_audio(self, a, **kw):
            return await self._b.send_audio(chat_id=self.chat_id, audio=a, **kw)

    target = _T(bot, chat_id)
    for item in items:
        try:
            await send_file_item(target, item, extra_caption=extra, reply_markup=markup, bot=bot)
        except Exception as e:
            logging.warning(f"deliver_denied_content: {e}")

# ── عرض عناصر المحتوى للمستخدم ───────────────────────────────────
async def send_items(m, bid, uid=None, bot=None):
    if uid and not is_admin(uid):
        # حظر مؤقت بعد التمادي في رفض الاشتراك
        remaining = get_file_block_remaining(uid)
        if remaining > 0:
            # إذا اشترك المستخدم فعلاً أثناء فترة الحظر — نرفع الحظر فوراً ونشكره
            sub_now = await is_subscribed(bot, uid) if bot else None
            if sub_now is True:
                record_channel_subscription(uid)
                clear_file_block(uid)
                reset_notif_no_count(uid)
                clear_pending_notif(uid)
                thanks_text = get_setting("notif_thanks_text", "✅ *شكراً لك!*\n\nيمكنك الآن الاستمرار في التصفح.")
                try:
                    await m.reply_text(
                        thanks_text,
                        parse_mode="Markdown",
                        message_effect_id="5046509860389126442"
                    )
                except Exception:
                    try:
                        await m.reply_text(thanks_text, parse_mode="Markdown")
                    except Exception:
                        pass
                # نستمر بالتنفيذ الطبيعي لإرسال المحتوى المطلوب أدناه
            else:
                mins = max(1, (remaining + 59) // 60)
                try:
                    await m.reply_text(f"⏳ مزاعلين، ما ارد عليك لمدة {mins} دقيقة .")
                except Exception:
                    pass
                return

        # النظام 1: هل هناك تنبيه منبثق معلق؟
        pending_bid = get_pending_notif(uid)
        if pending_bid:
            await resend_notif_gate(m, uid, pending_bid)
            return

        # فحص الاشتراك في القناة (مرة واحدة فقط)
        # True = مشترك | False = غير مشترك | None = تعذّر الفحص
        subscribed = await is_subscribed(bot, uid) if bot else None

        # النظام 1: تحديث العداد وفحص قبل إرسال المحتوى (فقط إذا تأكدنا أنه غير مشترك)
        if subscribed is False:
            inc_user_opens(uid)
            if should_notify(uid):
                await send_notif_gate(m, uid, bid)
                return  # حجب المحتوى عند ظهور التنبيه المنبثق

    items = get_items(bid)
    if not items:
        await m.reply_text("📭 لا يوجد محتوى بعد.")
        return
    if uid and not is_admin(uid):
        inc_click_count(bid, uid)
    b = get_btn(bid)
    no_cap = (b.get("no_caption", 0) or 0) if b else 0
    extra_cap = get_global_caption() if not no_cap else ""
    no_btn_cap = (b.get("no_btn_caption", 0) or 0) if b else 0
    cap_btns = get_caption_buttons() if not no_btn_cap else []
    link_markup = build_caption_btn_markup(cap_btns)
    unified = (b.get("unified_rating", 0) or 0) if b else 0
    ratings_hidden = get_user_ratings_hidden(uid) if uid and not is_admin(uid) else False
    for item in items:
        sent = await send_file_item(m, item, extra_caption=extra_cap, reply_markup=link_markup, bot=bot)
        if sent and uid and not is_admin(uid) and not unified and not ratings_hidden:
            await send_item_rating_message(m, item, uid=uid)

    # إرسال عبارة تحفيزية عشوائية بعد المحتوى (للمستخدمين فقط)
    if uid and not is_admin(uid):
        phrase = get_random_phrase()
        if phrase:
            try:
                await m.reply_text(phrase, message_effect_id="5046509860389126442")
            except Exception:
                await m.reply_text(phrase)

    # إرسال تقييم موحد واحد في الأسفل إذا كان توحيد التقييم مفعّلاً وغير مخفي
    if uid and not is_admin(uid) and unified and not ratings_hidden:
        await send_btn_unified_rating_message(m, bid, uid=uid)

# ── إرسال سؤال كويز للمستخدم ─────────────────────────────────────
def _quiz_session_key(bid):
    return f"quiz_session_{bid}"

def start_quiz_session(ctx, uid, bid):
    import time as _time
    b = get_btn(bid)
    session = {
        "id": f"{uid}_{bid}_{int(_time.time() * 1000)}",
        "bid": bid,
        "total": len(get_quiz_questions(bid)),
        "sent": 0,
        "answered": 0,
        "correct": 0,
        "answered_qids": [],
        "finished": False,
        "random_q": (b.get("random_quiz", 0) or 0) if b else 0,
    }
    ctx.user_data[_quiz_session_key(bid)] = session
    return session

def get_quiz_session(ctx, bid):
    return ctx.user_data.get(_quiz_session_key(bid))

def quiz_stats_text(session):
    total = session.get("total", 0)
    sent = session.get("sent", 0)
    answered = session.get("answered", 0)
    correct = session.get("correct", 0)
    wrong = max(answered - correct, 0)
    skipped = max(sent - answered, 0)
    percent = round((correct / answered) * 100) if answered else 0
    return (
        "📊 *إحصائية الاختبار*\n\n"
        f"🧩 مجموع الأسئلة: *{total}*\n"
        f"📨 الأسئلة المعروضة: *{sent}*\n"
        f"✍️ الإجابات المسجلة: *{answered}*\n"
        f"✅ الإجابات الصحيحة: *{correct}*\n"
        f"❌ الإجابات الخاطئة: *{wrong}*\n"
        f"⏭️ غير المجابة: *{skipped}*\n\n"
        f"🎯 نسبة الإجابات الصحيحة: *{percent}%*"
    )

def quiz_restart_markup(bid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 إعادة الاختبار", callback_data=f"quiz_start_{bid}")]
    ])

async def finish_quiz_session(target, ctx, bid, uid=None, edit=False):
    session = get_quiz_session(ctx, bid)
    if not session:
        session = start_quiz_session(ctx, uid or 0, bid)
    if session.get("finished"):
        return
    session["finished"] = True
    text = quiz_stats_text(session)
    if edit:
        await target.edit_message_text(text, parse_mode="Markdown", reply_markup=quiz_restart_markup(bid))
    else:
        await target.reply_text(text, parse_mode="Markdown", reply_markup=quiz_restart_markup(bid))

async def send_quiz(m, bid, uid=None, bot=None, ctx=None):
    b = get_btn(bid)
    random_q = (b.get("random_quiz", 0) or 0) if b else 0
    if random_q and uid:
        question = get_next_random_question(bid, uid)
    else:
        questions = get_quiz_questions(bid)
        question = questions[0] if questions else None
    await send_quiz_question(m, bid, question, uid=uid, random_q=random_q, ctx=ctx)

async def send_quiz_ready(m, bid):
    b = get_btn(bid)
    title = b["label"] if b else "الكويز"
    await m.reply_text(
        f"📊 *{title}*\n\nهل أنت مستعد لبدء الكويز؟",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ نعم، مستعد", callback_data=f"quiz_start_{bid}")]
        ])
    )

def get_next_ordered_quiz_question(bid, current_qid=None):
    questions = get_quiz_questions(bid)
    if not questions:
        return None
    if current_qid is None:
        return questions[0]
    for i, q in enumerate(questions):
        if q["id"] == current_qid:
            return questions[i + 1] if i + 1 < len(questions) else None
    return questions[0]

async def send_quiz_question(m, bid, question, uid=None, random_q=0, ctx=None):
    if not question:
        if ctx:
            await finish_quiz_session(m, ctx, bid, uid=uid)
        else:
            await m.reply_text("🎉 انتهت أسئلة الكويز. أحسنت!")
        return
    opts = get_quiz_options(question["id"])
    if len(opts) < 2:
        await m.reply_text("⚠️ السؤال غير مكتمل (يحتاج خيارين على الأقل).")
        return
    correct_idx = question.get("correct_option", 0)
    if correct_idx >= len(opts):
        correct_idx = 0
    explanation = question.get("explanation", "") or ""
    sent_poll = await m.reply_poll(
        question=question["question"],
        options=[opt["text"] for opt in opts],
        type="quiz",
        correct_option_id=correct_idx,
        explanation=explanation if explanation else None,
        is_anonymous=False,
    )
    session = get_quiz_session(ctx, bid) if ctx else None
    if session:
        if question["id"] not in session["answered_qids"]:
            session["sent"] = min(session.get("sent", 0) + 1, session.get("total", 0))
        ctx.bot_data.setdefault("quiz_poll_map", {})[sent_poll.poll.id] = {
            "user_id": uid,
            "chat_id": m.chat_id,
            "bid": bid,
            "qid": question["id"],
            "correct_idx": correct_idx,
            "session_id": session["id"],
        }
    if uid and random_q:
        log_question_sent(uid, question["id"])
    next_question = None
    if random_q:
        all_questions = get_quiz_questions(bid)
        if len(all_questions) > 1:
            next_question = True
    else:
        next_question = get_next_ordered_quiz_question(bid, question["id"])
    if next_question:
        await m.reply_text(
            "🔥 هل مستعد للسؤال التالي؟",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➡️ السؤال التالي", callback_data=f"quiz_next_{bid}_{question['id']}")],
                [InlineKeyboardButton("🏁 إنهاء الاختبار", callback_data=f"quiz_finish_{bid}")]
            ])
        )

# ── جلسات الامتحانات ──────────────────────────────────────────────────────

def _exam_session_key(bid):
    return f"exam_sess_{bid}"

def start_exam_session(ctx, uid, bid):
    import random as _random
    b = get_btn(bid)
    random_e = (b.get("random_exam", 0) or 0) if b else 0
    questions = get_exam_questions(bid)
    q_ids = [q["id"] for q in questions]
    if random_e:
        _random.shuffle(q_ids)
    old_progress = get_exam_progress(uid, bid)
    session = {
        "bid": bid,
        "q_ids": q_ids,
        "total": len(q_ids),
        "finished": False,
        "graded_qids": [],
        "old_progress": old_progress,
    }
    ctx.user_data[_exam_session_key(bid)] = session
    reset_exam_progress(uid, bid, len(q_ids))
    return session

def get_exam_session(ctx, bid):
    return ctx.user_data.get(_exam_session_key(bid))

async def send_exam_ready(m, bid):
    b = get_btn(bid)
    title = b["label"] if b else "الاختبار"
    questions = get_exam_questions(bid)
    await m.reply_text(
        f"📝 *{title}*\n\n_{len(questions)} سؤال_\n\nهل أنت مستعد لبدء الاختبار؟",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ نعم، مستعد!", callback_data=f"ex_start_{bid}")]
        ])
    )

async def _send_exam_item(target, item_type, item_text, item_file_id, reply_markup=None, header="", channel_msg_id=None, bot=None):
    kwargs = {}
    if reply_markup:
        kwargs["reply_markup"] = reply_markup
    full_text = header + (item_text or "")
    if item_type == "text":
        await target.reply_text(full_text or "—", parse_mode="Markdown", **kwargs)
    elif channel_msg_id and get_storage_channel_id() and bot:
        try:
            await bot.copy_message(
                chat_id=target.chat_id,
                from_chat_id=get_storage_channel_id(),
                message_id=channel_msg_id,
                caption=full_text or None,
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
        except Exception as e:
            logging.warning(f"فشل إرسال عنصر الامتحان من القناة: {e}")
            if item_type == "photo":
                await target.reply_photo(item_file_id, caption=full_text or None, parse_mode="Markdown", **kwargs)
            elif item_type == "file":
                await target.reply_document(item_file_id, caption=full_text or None, parse_mode="Markdown", **kwargs)
            elif item_type == "video":
                await target.reply_video(item_file_id, caption=full_text or None, parse_mode="Markdown", **kwargs)
            elif item_type == "audio":
                await target.reply_audio(item_file_id, caption=full_text or None, parse_mode="Markdown", **kwargs)
    elif item_type == "photo":
        await target.reply_photo(item_file_id, caption=full_text or None, parse_mode="Markdown", **kwargs)
    elif item_type == "file":
        await target.reply_document(item_file_id, caption=full_text or None, parse_mode="Markdown", **kwargs)
    elif item_type == "video":
        await target.reply_video(item_file_id, caption=full_text or None, parse_mode="Markdown", **kwargs)
    elif item_type == "audio":
        await target.reply_audio(item_file_id, caption=full_text or None, parse_mode="Markdown", **kwargs)

async def send_exam_question_to_user(target, bid, qid, current_num, total, bot=None):
    q = get_exam_question(qid)
    if not q:
        await target.reply_text("⚠️ السؤال غير موجود.")
        return
    reveal_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("👁 عرض الجواب", callback_data=f"ex_ans_{qid}_{bid}")]
    ])
    await _send_exam_item(
        target,
        q.get("q_type", "text"),
        q.get("q_text"),
        q.get("q_file_id"),
        reply_markup=reveal_markup,
        header=f"📝 *السؤال {current_num}/{total}*\n\n",
        channel_msg_id=q.get("q_channel_msg_id"),
        bot=bot,
    )

async def send_exam_answer_to_user(target, bid, qid, current_idx, total, bot=None):
    q = get_exam_question(qid)
    if not q:
        await target.reply_text("⚠️ الجواب غير موجود.")
        return
    is_last = (current_idx + 1 >= total)
    next_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ عرفته", callback_data=f"ex_mark_{bid}_{qid}_1"),
            InlineKeyboardButton("❌ ما عرفته", callback_data=f"ex_mark_{bid}_{qid}_0"),
        ],
        [InlineKeyboardButton("🏁 إنهاء الاختبار", callback_data=f"ex_finish_{bid}")]
    ])
    a_type = q.get("a_type", "text")
    a_text = q.get("a_text")
    a_file_id = q.get("a_file_id")
    if not a_text and not a_file_id:
        await target.reply_text("⚠️ لم يُضَف جواب لهذا السؤال بعد.", reply_markup=next_markup)
        return
    await _send_exam_item(
        target,
        a_type,
        a_text,
        a_file_id,
        reply_markup=next_markup,
        header="✅ *الجواب:*\n\n",
        channel_msg_id=q.get("a_channel_msg_id"),
        bot=bot,
    )

async def on_poll_answer(update: Update, ctx):
    answer = update.poll_answer
    data = ctx.bot_data.get("quiz_poll_map", {}).get(answer.poll_id)
    if not data or data.get("user_id") != answer.user.id:
        return
    session = get_quiz_session(ctx, data["bid"])
    if not session or session.get("id") != data.get("session_id") or session.get("finished"):
        return
    qid = data["qid"]
    if qid in session["answered_qids"]:
        return
    session["answered_qids"].append(qid)
    session["answered"] = session.get("answered", 0) + 1
    selected = answer.option_ids[0] if answer.option_ids else None
    if selected == data["correct_idx"]:
        session["correct"] = session.get("correct", 0) + 1
    if session.get("sent", 0) >= session.get("total", 0):
        session["finished"] = True
        chat_id = data.get("chat_id")
        if chat_id:
            await ctx.bot.send_message(
                chat_id=chat_id,
                text=quiz_stats_text(session),
                parse_mode="Markdown",
                reply_markup=quiz_restart_markup(data["bid"])
            )
