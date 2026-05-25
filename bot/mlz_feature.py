from .shared import *
import re as _re

# ── الأنواع الشائعة للملزمة ───────────────────────────────────────
MLZ_TYPES = ["مراجعة", "ملخص", "نموذج امتحان", "أسئلة", "كتاب", "واجب"]

# ── استدعاء Gemini نصياً ──────────────────────────────────────────
async def _call_gemini_text(prompt: str) -> str | None:
    keys = get_all_gemini_keys()
    if not keys:
        return None
    models = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.0-flash-lite"]
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    async with httpx.AsyncClient() as client:
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            for key in keys:
                try:
                    resp = await client.post(url, params={"key": key}, json=payload, timeout=30)
                    if resp.status_code in (429, 503):
                        continue
                    if resp.status_code == 404:
                        break
                    resp.raise_for_status()
                    text = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    if text:
                        return text
                except Exception as e:
                    logging.warning(f"[MLZ] Gemini error: {e}")
    return None

# ── استخراج المعلومات الأربع بالذكاء الاصطناعي ───────────────────
def _clean_source_text(text: str) -> str:
    """يُنظّف النص من الرموز الزخرفية قبل إرساله لـ Gemini."""
    # استبدال رموز الزخرفة والفواصل الزخرفية بمسافة
    cleaned = _re.sub(r'[✧✦✩✪✫✬✭✮✯✰★☆⭐━─═●○◆◇■□▪▫»«]+', ' ', text)
    # حذف الروابط
    cleaned = _re.sub(r'https?://\S+', '', cleaned)
    # تقليل المسافات المتعددة
    cleaned = _re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

async def extract_mlz_info(source_text: str) -> dict:
    cleaned_text = _clean_source_text(source_text)
    prompt = (
        "أنت مساعد يستخرج معلومات من نصوص عربية مزخرفة أو عادية.\n\n"
        "استخرج هذه المعلومات من النص:\n"
        "1. المادة الدراسية: اسم المادة (مثل: رياضيات، كيمياء، فيزياء، قواعد، أحياء، عربي، تاريخ، جغرافية، دين، انجليزي)\n"
        "2. اسم المدرس: الاسم الكامل للأستاذ أو المدرس (يأتي بعد كلمة 'الأستاذ' أو 'أ.' أو 'المدرس')\n"
        "3. الصف الدراسي: مثل (السادس الإعدادي، السادس علمي، السادس أدبي، الخامس علمي، الثالث متوسط، الأول ثانوي)\n"
        "4. سنة الإصدار: أربعة أرقام (مثل 2025، 2026، 2027)\n\n"
        f"النص:\n{cleaned_text}\n\n"
        "قواعد مهمة:\n"
        "- أرجع JSON فقط بدون أي شرح\n"
        "- إذا لم تجد معلومة اتركها فارغة ''\n"
        "- لا تخترع معلومات غير موجودة\n"
        '{"subject": "", "teacher": "", "grade": "", "year": ""}'
    )
    try:
        raw = await _call_gemini_text(prompt)
        if not raw:
            return {}
        match = _re.search(r'\{[^{}]*\}', raw, _re.DOTALL)
        if not match:
            return {}
        data = json.loads(match.group())
        return {k: (v or "").strip() for k, v in data.items() if k in ("subject", "teacher", "grade", "year")}
    except Exception as e:
        logging.warning(f"[MLZ] extract_mlz_info error: {e}")
        return {}

# ── تطبيع النص للمقارنة (مع حذف الرموز التعبيرية) ───────────────
def _norm(text: str) -> str:
    text = (text or "").strip()
    # حذف كل ما ليس حرفاً عربياً أو لاتينياً أو رقماً أو مسافة
    text = _re.sub(r'[^\u0600-\u06FFa-zA-Z0-9\s]', ' ', text)
    # حذف التشكيل والتطويل (kashida \u0640) والأرقام العربية الموصولة
    text = _re.sub(r'[\u064B-\u065F\u0670\u0640]', '', text)
    text = text.replace('ة', 'ه').replace('ى', 'ي')
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    return _re.sub(r'\s+', ' ', text).strip().lower()

def _fuzzy_match(query: str, btns: list) -> dict | None:
    if not query or not btns:
        return None
    q = _norm(query)
    if not q:
        return None
    for b in btns:
        if _norm(b['label']) == q:
            return b
    for b in btns:
        lbl = _norm(b['label'])
        if q in lbl or lbl in q:
            return b
    q_words = set(w for w in q.split() if len(w) > 1)
    best, best_score = None, 0
    for b in btns:
        lbl_words = set(w for w in _norm(b['label']).split() if len(w) > 1)
        score = len(q_words & lbl_words)
        if score > best_score:
            best_score = score
            best = b
    return best if best_score >= 1 else None

# ── كشف نمط الرموز التعبيرية من الأزرار الموجودة ────────────────
_EMOJI_RE = _re.compile(
    r'[\U0001F300-\U0001F9FF\U0001FA00-\U0001FA9F'
    r'\U00002600-\U000027BF\U0000FE00-\U0000FE0F'
    r'\U0001F000-\U0001F02F\U00002702-\U000027B0\u2600-\u27BF]+'
)

def _extract_emoji_wrap(btns: list) -> tuple:
    """يستخرج نمط الرمز التعبيري البادئ واللاحق من أزرار الإخوة."""
    for b in btns:
        label = (b.get('label') or '').strip()
        if not label:
            continue
        pm = _EMOJI_RE.match(label)
        prefix = pm.group() if pm else ''
        rest = label[len(prefix):]
        suffix = ''
        sm = _EMOJI_RE.search(rest)
        if sm and sm.end() == len(rest) and sm.start() > 0:
            suffix = sm.group()
        if prefix or suffix:
            return prefix, suffix
    return '', ''

def _apply_emoji_wrap(name: str, prefix: str, suffix: str) -> str:
    return f"{prefix}{name.strip()}{suffix}" if (prefix or suffix) else name.strip()

# ── البحث عن المسار وإنشاء ما يلزم (مع تطبيق نمط الرموز) ────────
def find_or_build_mlz_path(grade: str, subject: str, teacher: str):
    """
    يبحث ويُنشئ المسار: الصف → الملازم → المادة → المدرس (مدمج)
    يُرجع: (grade_btn, mlz_btn, subject_btn, teacher_btn)
    """
    root_btns = [b for b in get_buttons(None) if not b.get('deleted')]
    grade_btn = _fuzzy_match(grade, root_btns)
    if not grade_btn:
        return None, None, None, None

    grade_children = get_buttons(grade_btn['id'])
    mlz_keywords = ['ملزم', 'ملازم', 'ملزمه', 'ملازمه', 'ملازمات', 'ملزمات']
    mlz_btn = None
    for b in grade_children:
        lbl_n = _norm(b['label'])
        if any(kw in lbl_n for kw in mlz_keywords):
            mlz_btn = b
            break
    if not mlz_btn:
        return grade_btn, None, None, None

    mlz_children = [b for b in get_buttons(mlz_btn['id']) if b['type'] == 'menu']
    subject_btn = _fuzzy_match(subject, mlz_children)
    if not subject_btn:
        # كشف نمط الرموز من أزرار المواد الموجودة وتطبيقه
        s_prefix, s_suffix = _extract_emoji_wrap(mlz_children)
        subject_label = _apply_emoji_wrap(subject, s_prefix, s_suffix)
        new_id = add_btn(mlz_btn['id'], 'menu', subject_label)
        subject_btn = get_btn(new_id)

    subject_children = [b for b in get_buttons(subject_btn['id']) if b['type'] == 'compound']
    teacher_btn = _fuzzy_match(teacher, subject_children)
    if not teacher_btn:
        # كشف نمط الرموز من أزرار المدرسين الموجودة وتطبيقه
        t_prefix, t_suffix = _extract_emoji_wrap(subject_children)
        teacher_label = _apply_emoji_wrap(teacher, t_prefix, t_suffix)
        new_id = add_btn(subject_btn['id'], 'compound', teacher_label)
        teacher_btn = get_btn(new_id)

    return grade_btn, mlz_btn, subject_btn, teacher_btn

def _build_desc(subject, teacher, grade, year):
    return f"{subject} - {teacher} - {grade} - {year}"

def _build_btn_name(mlz_type, year):
    return f"📌 {mlz_type} {year}📌"

def _clear_mlz(ctx):
    for key in [
        'mlz_file_type', 'mlz_file_id', 'mlz_subject', 'mlz_teacher',
        'mlz_grade', 'mlz_year', 'mlz_desc', 'mlz_path_str',
        'mlz_panel_mid', 'mlz_panel_chat_id',
    ]:
        ctx.user_data.pop(key, None)
    ctx.user_data.pop('state', None)

# ── بناء محتوى لوحة التأكيد الموحّدة ───────────────────────────
def _mlz_panel_content(ctx) -> tuple:
    subject = ctx.user_data.get('mlz_subject') or '—'
    teacher = ctx.user_data.get('mlz_teacher') or '—'
    grade   = ctx.user_data.get('mlz_grade')   or '—'
    year    = ctx.user_data.get('mlz_year')    or '—'

    text = (
        "📂 *معلومات الملزمة*\n\n"
        f"🏫 الصف:     `{grade}`\n"
        f"📚 المادة:   `{subject}`\n"
        f"👨‍🏫 المدرس:   `{teacher}`\n"
        f"📅 السنة:    `{year}`\n\n"
        "_اضغط ✏️ لتعديل أي حقل_"
    )
    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏫 الصف ✏️",    callback_data="mlz_ef_g"),
            InlineKeyboardButton("📚 المادة ✏️",  callback_data="mlz_ef_s"),
        ],
        [
            InlineKeyboardButton("👨‍🏫 المدرس ✏️", callback_data="mlz_ef_t"),
            InlineKeyboardButton("📅 السنة ✏️",   callback_data="mlz_ef_y"),
        ],
        [
            InlineKeyboardButton("✅ تأكيد",  callback_data="mlz_confirm"),
            InlineKeyboardButton("❌ إلغاء",  callback_data="mlz_cancel"),
        ],
    ])
    return text, markup

async def _refresh_mlz_panel(bot, ctx):
    """يُحدّث رسالة اللوحة الموجودة بالبيانات الحالية."""
    mid     = ctx.user_data.get('mlz_panel_mid')
    chat_id = ctx.user_data.get('mlz_panel_chat_id')
    if not mid or not chat_id:
        return
    text, markup = _mlz_panel_content(ctx)
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=mid,
            text=text, parse_mode='Markdown', reply_markup=markup
        )
    except Exception:
        pass

# ── عرض لوحة اختيار الصف ─────────────────────────────────────────
async def show_grade_picker(q, ctx):
    """يعرض أزرار الصفوف الموجودة كخيارات جاهزة."""
    root_btns = [b for b in get_buttons(None) if not b.get('deleted') and b.get('type') == 'menu']
    rows = []
    chunk = []
    for b in root_btns[:14]:
        chunk.append(InlineKeyboardButton(b['label'], callback_data=f"mlz_g_{b['id']}"))
        if len(chunk) == 2:
            rows.append(chunk)
            chunk = []
    if chunk:
        rows.append(chunk)
    rows.append([InlineKeyboardButton("✏️ اكتب يدوياً", callback_data="mlz_ef_g_text")])

    await q.answer()
    msg = await q.message.reply_text(
        "🏫 *اختر الصف:*",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(rows)
    )
    ctx.user_data['mlz_picker_mid'] = msg.message_id

# ── حذف رسالة الاختيار بعد التحديد ──────────────────────────────
async def _delete_picker(bot, ctx, chat_id):
    mid = ctx.user_data.pop('mlz_picker_mid', None)
    if mid:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass

# ── عرض لوحة نوع الملزمة ─────────────────────────────────────────
async def show_mlz_type_picker(q):
    """يستبدل رسالة اللوحة بمحدد نوع الملزمة."""
    rows = []
    for i in range(0, len(MLZ_TYPES), 2):
        row = [InlineKeyboardButton(MLZ_TYPES[i], callback_data=f"mlz_t_{i}")]
        if i + 1 < len(MLZ_TYPES):
            row.append(InlineKeyboardButton(MLZ_TYPES[i + 1], callback_data=f"mlz_t_{i+1}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("✏️ نوع آخر (اكتب يدوياً)", callback_data="mlz_t_custom")])
    try:
        await q.edit_message_text(
            "📌 *اختر نوع الملزمة:*",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(rows)
        )
    except Exception:
        pass

# ── بدء تدفق الملزمة ─────────────────────────────────────────────
async def start_mlz_flow(m, ctx, uid, chat_id) -> bool:
    from .content_delivery import detect_content
    file_type, caption, file_id = detect_content(m)
    if not file_type or file_type == 'text':
        return False

    ctx.user_data['mlz_file_type'] = file_type
    ctx.user_data['mlz_file_id']   = file_id

    source_text = ""
    if caption:
        source_text += caption + " "
    if m.document and m.document.file_name:
        source_text += m.document.file_name
    source_text = source_text.strip()

    wait_msg = await m.reply_text("⏳ جاري تحليل الملف بالذكاء الاصطناعي...")

    if source_text and get_all_gemini_keys():
        info = await extract_mlz_info(source_text)
    else:
        info = {}

    ctx.user_data['mlz_subject'] = info.get('subject', '')
    ctx.user_data['mlz_teacher'] = info.get('teacher', '')
    ctx.user_data['mlz_grade']   = info.get('grade', '')
    ctx.user_data['mlz_year']    = info.get('year', '')

    try:
        await wait_msg.delete()
    except Exception:
        pass

    # عرض لوحة التأكيد الموحّدة مباشرة
    text, markup = _mlz_panel_content(ctx)
    panel = await m.reply_text(text, parse_mode='Markdown', reply_markup=markup)
    ctx.user_data['mlz_panel_mid']     = panel.message_id
    ctx.user_data['mlz_panel_chat_id'] = chat_id
    return True

# ── callback: تأكيد → عرض محدد النوع ────────────────────────────
async def after_mlz_confirm(q, ctx, uid, chat_id):
    grade   = ctx.user_data.get('mlz_grade', '')
    subject = ctx.user_data.get('mlz_subject', '')
    teacher = ctx.user_data.get('mlz_teacher', '')
    year    = ctx.user_data.get('mlz_year', '')

    if not all([grade, subject, teacher, year]):
        await q.answer("⚠️ يرجى ملء جميع الحقول أولاً.", show_alert=True)
        return

    # التحقق من صحة الصف قبل المتابعة
    root_btns = [b for b in get_buttons(None) if not b.get('deleted')]
    grade_btn = _fuzzy_match(grade, root_btns)
    if not grade_btn:
        await q.answer(f"⚠️ لم أجد صفاً باسم «{grade}» — عدّله من زر ✏️", show_alert=True)
        return

    grade_children = get_buttons(grade_btn['id'])
    _mlz_kw = ['ملزم', 'ملازم', 'ملزمه', 'ملازمه', 'ملازمات', 'ملزمات']
    mlz_btn = None
    for b in grade_children:
        if any(kw in _norm(b['label']) for kw in _mlz_kw):
            mlz_btn = b
            break
    if not mlz_btn:
        await q.answer(f"⚠️ لم أجد زر الملازم داخل «{grade_btn['label']}»", show_alert=True)
        return

    await show_mlz_type_picker(q)

# ── callback: إلغاء ───────────────────────────────────────────────
async def after_mlz_cancel(q, ctx):
    await q.answer("تم الإلغاء.")
    try:
        await q.message.delete()
    except Exception:
        pass
    _clear_mlz(ctx)

# ── callback: تعديل حقل ──────────────────────────────────────────
async def after_mlz_edit_field(q, ctx, field: str):
    """يُعالج ضغط زر تعديل حقل معين."""
    await q.answer()
    if field == 'g':
        await show_grade_picker(q, ctx)
    elif field == 's':
        ctx.user_data['state'] = 'wait_mlz_subject'
        await q.message.reply_text("📚 أرسل *اسم المادة الدراسية:*", parse_mode='Markdown')
    elif field == 't':
        ctx.user_data['state'] = 'wait_mlz_teacher'
        await q.message.reply_text("👨‍🏫 أرسل *اسم المدرس كاملاً:*", parse_mode='Markdown')
    elif field == 'y':
        ctx.user_data['state'] = 'wait_mlz_year'
        await q.message.reply_text("📅 أرسل *سنة الإصدار* (مثال: 2025):", parse_mode='Markdown')
    elif field == 'g_text':
        ctx.user_data['state'] = 'wait_mlz_grade'
        await q.message.reply_text("🏫 أرسل *اسم الصف* كما هو مكتوب في البوت:", parse_mode='Markdown')

# ── callback: اختيار صف من اللوحة ───────────────────────────────
async def after_mlz_grade_pick(q, ctx, bid: int):
    """يحفظ الصف المختار من اللوحة."""
    btn = get_btn(bid)
    if not btn:
        await q.answer("⚠️ الزر غير موجود.", show_alert=True)
        return
    ctx.user_data['mlz_grade'] = btn['label']
    await q.answer(f"✅ {btn['label']}")
    await _delete_picker(ctx.bot, ctx, q.message.chat_id)
    await _refresh_mlz_panel(ctx.bot, ctx)

# ── callback: اختيار نوع الملزمة ─────────────────────────────────
async def after_mlz_type_pick(q, ctx, uid, chat_id, mlz_type: str):
    """يبدأ إنشاء الملزمة بعد اختيار النوع."""
    try:
        await q.message.delete()
    except Exception:
        pass
    ctx.user_data.pop('mlz_panel_mid', None)
    await finish_mlz_flow(q.message, ctx, uid, chat_id, q.get_bot(), mlz_type)

# ── الإنهاء: إنشاء الأزرار وإضافة الملف ─────────────────────────
async def finish_mlz_flow(m, ctx, uid, chat_id, bot, mlz_type: str):
    from .content_delivery import upload_to_channel

    subject   = ctx.user_data.get('mlz_subject', '')
    teacher   = ctx.user_data.get('mlz_teacher', '')
    grade     = ctx.user_data.get('mlz_grade', '')
    year      = ctx.user_data.get('mlz_year', '')
    desc      = ctx.user_data.get('mlz_desc') or _build_desc(subject, teacher, grade, year)
    file_type = ctx.user_data.get('mlz_file_type')
    file_id   = ctx.user_data.get('mlz_file_id')

    if not file_id or not file_type:
        await m.reply_text("⚠️ حدث خطأ: بيانات الملف مفقودة. أعد إرسال الملف.")
        _clear_mlz(ctx)
        return

    wait_msg = await m.reply_text("⏳ جاري الإنشاء وإضافة الملف...")

    grade_btn, mlz_btn, subject_btn, teacher_btn = find_or_build_mlz_path(grade, subject, teacher)

    if not grade_btn or not mlz_btn:
        await wait_msg.edit_text("⚠️ حدث خطأ في تحديد المسار. أعد المحاولة.")
        _clear_mlz(ctx)
        return

    btn_name = _build_btn_name(mlz_type, year)

    # ── كشف التكرار قبل الحفظ ─────────────────────────────────
    existing_children = get_buttons(teacher_btn['id'])
    duplicate = _fuzzy_match(btn_name, existing_children)
    if duplicate:
        await wait_msg.edit_text(
            f"⚠️ *يوجد ملزمة مشابهة بالفعل!*\n\n"
            f"الاسم الموجود: `{duplicate['label']}`\n\n"
            "هل تريد إضافة نسخة جديدة بجانبها؟ أرسل *نعم* للمتابعة أو *لا* للإلغاء.",
            parse_mode='Markdown'
        )
        ctx.user_data['mlz_dup_btn_name']  = btn_name
        ctx.user_data['mlz_dup_desc']      = desc
        ctx.user_data['mlz_dup_file_type'] = file_type
        ctx.user_data['mlz_dup_file_id']   = file_id
        ctx.user_data['mlz_dup_grade']     = grade_btn['label']
        ctx.user_data['mlz_dup_mlz']       = mlz_btn['label']
        ctx.user_data['mlz_dup_subject']   = subject_btn['label']
        ctx.user_data['mlz_dup_teacher']   = teacher_btn['label']
        ctx.user_data['mlz_dup_teacher_id'] = teacher_btn['id']
        ctx.user_data['state'] = 'wait_mlz_dup_confirm'
        return

    await _do_add_mlz(
        wait_msg, ctx, bot,
        teacher_btn['id'], btn_name, file_type, file_id, desc,
        [grade_btn['label'], mlz_btn['label'], subject_btn['label'], teacher_btn['label'], btn_name]
    )
    _clear_mlz(ctx)

async def _do_add_mlz(wait_msg, ctx, bot, teacher_bid, btn_name, file_type, file_id, desc, path_parts):
    from .content_delivery import upload_to_channel
    content_bid = add_btn(teacher_bid, 'content', btn_name)
    channel_msg_id = await upload_to_channel(bot, file_id, file_type, desc)

    if get_storage_channel_id() and not channel_msg_id:
        del_btn(content_bid)
        await wait_msg.edit_text(
            "⚠️ لم يتم الحفظ لأن رفع الملف لقناة التخزين فشل.\n"
            "تأكد أن البوت أدمن في قناة التخزين."
        )
        return

    add_item(content_bid, file_type, desc, file_id, None, channel_msg_id)
    path_str = " ← ".join(path_parts)

    await wait_msg.edit_text(
        f"✅ *تمت الإضافة بنجاح!*\n\n"
        f"📂 *الموقع:*\n`{path_str}`\n\n"
        f"📝 *الوصف:*\n`{desc}`",
        parse_mode='Markdown'
    )

__all__ = [name for name in globals() if not name.startswith("__")]
