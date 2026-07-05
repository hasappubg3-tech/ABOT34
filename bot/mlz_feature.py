from .shared import *
import re as _re

# ── الأنواع الشائعة للملزمة ───────────────────────────────────────
MLZ_TYPES = ["ملزمة", "مراجعة", "وزاريات", "واجبات", "ملخص", "أسئلة", "كتاب"]

# ── المواد الواضحة التي تتجاوز picker المادة ─────────────────────
_CLEAR_SUBJECTS = {
    'رياضيات', 'كيمياء', 'فيزياء', 'انكليزي', 'انجليزي',
    'عربي', 'العربي', 'احياء', 'أحياء', 'إسلامية', 'اسلامية',
    'فرنسي', 'اقتصاد', 'تاريخ', 'جغرافية', 'جغرافيا',
}

def _is_clear_subject(subject: str) -> bool:
    """يتحقق إذا كانت المادة واضحة ومحددة (لا تحتاج picker)."""
    n = _norm(subject)
    return any(_norm(cs) == n for cs in _CLEAR_SUBJECTS)

def _strip_emoji(text: str) -> str:
    """يُزيل الرموز التعبيرية والأيقونات من النص."""
    cleaned = _re.sub(
        r'[\U0001F000-\U0001FFFF'
        r'\U00002700-\U000027BF'
        r'\U00002600-\U000026FF'
        r'\U00002300-\U000023FF'
        r'\U00002B00-\U00002BFF'
        r'\uFE00-\uFE0F]+',
        '', text
    )
    return _re.sub(r'\s+', ' ', cleaned).strip()

_TYPE_KEYWORDS = {
    'مراجعة':  ['مراجعة', 'مراجعه', 'مراجعات', 'مركزه', 'مركزة'],
    'وزاريات': ['وزاريات', 'وزارية', 'وزاريه', 'الوزاري', 'وزاري'],
    'واجبات':  ['واجبات', 'واجب'],
    'ملخص':    ['ملخص', 'ملخصات', 'ملخصه'],
    'أسئلة':   ['اسئلة', 'أسئلة', 'اسئله', 'أسئله'],
    'كتاب':    ['كتاب', 'كتيب'],
}

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
    """يُنظّف النص من الرموز الزخرفية."""
    cleaned = _re.sub(r'[✧✦✩✪✫✬✭✮✯✰★☆⭐━─═●○◆◇■□▪▫»«\-_=~^*]{2,}', ' ', text)
    cleaned = _re.sub(r'https?://\S+', '', cleaned)
    cleaned = _re.sub(r'[\u0640]', '', cleaned)          # kashida
    cleaned = _re.sub(r'[\u064B-\u065F\u0670]', '', cleaned)  # harakat
    cleaned = _re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

# ── الاستخراج المحلي بدون Gemini ─────────────────────────────────
_GRADE_LEVELS = r'(?:السادس|الخامس|الرابع|الثالث|الثاني|الأول|الاول|السابع|الثامن|التاسع|العاشر)'
_GRADE_TYPES  = r'(?:علمي|أدبي|ادبي|إعدادي|اعدادي|أعدادي|الإعدادي|الاعدادي|الأعدادي|متوسط|ابتدائي|ثانوي|تطبيقي|مهني|الأعدادية|الاعدادية)'
_TEACHER_PREFIX = r'(?:الأستاذ|الاستاذ|أستاذ|استاذ|للأستاذ|للاستاذ|المدرس|للمدرس|الدكتور|للدكتور|أ\.|م\.)'

_ORDINAL_TO_NUM = {
    'الأول': '1', 'الاول': '1', 'أول': '1', 'اول': '1', 'الأولى': '1', 'الاولى': '1',
    'الثاني': '2', 'ثاني': '2', 'الثانية': '2', 'ثانية': '2',
    'الثالث': '3', 'ثالث': '3', 'الثالثة': '3',
    'الرابع': '4', 'رابع': '4', 'الرابعة': '4',
    'الخامس': '5', 'خامس': '5', 'الخامسة': '5',
}

_SUBJECTS = {
    'رياضيات':   ['رياضيات'],
    'فيزياء':    ['فيزياء', 'فيزيا'],
    'كيمياء':    ['كيمياء'],
    'أحياء':     ['احياء', 'أحياء', 'بيولوجي'],
    'قواعد':     ['قواعد', 'نحو', 'صرف', 'اساسيات القواعد', 'قواعد اللغة'],
    'عربي':      ['لغة عربية', 'الادب', 'الأدب', 'بلاغة'],
    'إنجليزي':   ['انجليزي', 'إنجليزي', 'english'],
    'تاريخ':     ['تاريخ'],
    'جغرافية':   ['جغرافية', 'جغرافيا'],
    'دين':       ['تربية اسلامية', 'إسلامية', 'فقه', 'تفسير', 'حديث'],
    'اجتماعيات': ['اجتماعيات', 'تربية وطنية', 'التربية الوطنية'],
    'حاسبات':    ['حاسبات', 'حاسوب', 'كومبيوتر'],
    'علوم':      ['علوم'],
}

def _extract_info_local(text: str) -> dict:
    """استخراج المعلومات بالأنماط دون الحاجة لـ Gemini."""
    result = {}
    cleaned = _clean_source_text(text)

    # ── السنة: أي رقم 20xx ────────────────────────────────────────
    yr = _re.search(r'\b(20[0-9]{2})\b', cleaned)
    if yr:
        result['year'] = yr.group(1)

    # ── الصف: مستوى + نوع ────────────────────────────────────────────
    # الرابع/الخامس/السادس: يجب وجود (علمي أو أدبي) وإلا يُترك الصف فارغاً
    _BRANCH_RE = r'(?:علمي|أدبي|ادبي)'
    high_grade_m = _re.search(
        r'(?:السادس|الخامس|الرابع)\s+' + _BRANCH_RE,
        cleaned
    )
    # الصفوف الأخرى: تقبل أي نوع أو بدون نوع
    other_grade_m = _re.search(
        r'(?:الثالث|الثاني|الأول|الاول|السابع|الثامن|التاسع|العاشر)'
        r'(?:\s+(?:علمي|أدبي|ادبي|إعدادي|اعدادي|أعدادي|الإعدادي|الاعدادي|الأعدادي'
        r'|الأعدادية|الاعدادية|متوسط|ابتدائي|ثانوي|تطبيقي|مهني))?',
        cleaned
    )
    if high_grade_m:
        result['grade'] = high_grade_m.group(0).strip()
    elif other_grade_m:
        result['grade'] = other_grade_m.group(0).strip()
    # إذا الصف السادس/الخامس/الرابع موجود بدون تفرع → يُترك فارغاً ليملأه المشرف

    # ── المدرس: بعد كلمة الأستاذ/المدرس/الدكتور ──────────────────
    teacher_m = _re.search(
        r'(?:الأستاذ|الاستاذ|أستاذ|استاذ|للأستاذ|للاستاذ|المدرس|للمدرس|الدكتور|للدكتور|أ\.|م\.)'
        r'\s*[:\-]?\s*'
        r'((?:[\u0600-\u06FF]+\s*){1,5})',
        cleaned
    )
    if teacher_m:
        name = teacher_m.group(1).strip()
        name = _re.sub(r'\s+', ' ', name).strip()
        # حذف كلمات ليست أسماء (مثل: للصف، في، من)
        stop = {'للصف', 'في', 'من', 'على', 'عن', 'مع', 'الصف', 'سنة', 'عام'}
        words = [w for w in name.split() if w not in stop]
        name = ' '.join(words[:4])   # أقصى 4 كلمات
        if len(name) > 3:
            result['teacher'] = name

    # ── رقم الجزء: بعد كلمة الجزء/جزء ──────────────────────────
    part_m = _re.search(
        r'(?:الجزء|جزء)\s+'
        r'(الأول|الاول|الأولى|الاولى|الثاني|الثانية|الثالث|الثالثة'
        r'|الرابع|الرابعة|الخامس|الخامسة|[١-٩]|[1-9])',
        cleaned
    )
    if part_m:
        raw = part_m.group(1).strip()
        if raw.isdigit():
            result['part'] = raw
        elif '\u0661' <= raw <= '\u0669':
            result['part'] = str(ord(raw) - 0x0660)
        else:
            result['part'] = _ORDINAL_TO_NUM.get(raw, raw)

    # ── المادة: بحث في قائمة المعروفة ────────────────────────────
    c_norm = _norm(cleaned)
    for subj, keywords in _SUBJECTS.items():
        for kw in keywords:
            if _norm(kw) in c_norm:
                result['subject'] = subj
                break
        if 'subject' in result:
            break

    # ── نوع الملزمة: بحث في كلمات مفتاحية ──────────────────────
    for typ, keywords in _TYPE_KEYWORDS.items():
        for kw in keywords:
            if _norm(kw) in c_norm:
                result['mlz_type'] = typ
                break
        if 'mlz_type' in result:
            break

    return result

async def extract_mlz_info(source_text: str) -> dict:
    """يستخرج المعلومات محلياً أولاً، ثم يُحسّنها بـ Gemini إن توفّر مفتاحه."""
    local = _extract_info_local(source_text)

    if not get_all_gemini_keys():
        return local

    cleaned_text = _clean_source_text(source_text)
    prompt = (
        "أنت مساعد يستخرج معلومات من نصوص عربية.\n\n"
        "استخرج من النص:\n"
        "- subject: اسم المادة الدراسية (أي مادة دراسية عراقية)\n"
        "- teacher: الاسم الكامل لأي شخص مذكور (أستاذ أو مدرس)\n"
        "- grade: الصف الدراسي — قاعدة مهمة: الصفوف الرابع والخامس والسادس يجب أن تحتوي صراحةً على كلمة (علمي أو أدبي)، مثل: الخامس علمي، السادس أدبي، الرابع علمي — إن لم يُذكر النوع (علمي/أدبي) بوضوح اترك الحقل فارغاً تماماً\n"
        "- year: أي سنة من 4 أرقام (2020-2030)\n"
        "- part: رقم الجزء إن وجد (مثال: 1 أو 2)، اتركه فارغاً إن لم يُذكر\n"
        "- mlz_type: نوع المحتوى (مراجعة أو وزاريات أو واجبات أو ملخص أو أسئلة أو كتاب أو ملزمة)، اتركه فارغاً إن لم يُذكر\n\n"
        f"النص:\n{cleaned_text}\n\n"
        "قاعدة: أرجع JSON فقط، اتركها فارغة إن لم تجد\n"
        '{"subject": "", "teacher": "", "grade": "", "year": "", "part": "", "mlz_type": ""}'
    )
    try:
        raw = await _call_gemini_text(prompt)
        if raw:
            match = _re.search(r'\{[^{}]*\}', raw, _re.DOTALL)
            if match:
                gemini = json.loads(match.group())
                for k in ('subject', 'teacher', 'grade', 'year', 'part', 'mlz_type'):
                    val = gemini.get(k, '').strip()
                    if not local.get(k) and val:
                        # الصفوف الرابع/الخامس/السادس يجب أن تحتوي علمي أو أدبي
                        if k == 'grade':
                            is_high = _re.search(r'(?:السادس|الخامس|الرابع)', val)
                            has_branch = _re.search(r'(?:علمي|أدبي|ادبي)', val)
                            if is_high and not has_branch:
                                continue  # رفض الصف الناقص
                        local[k] = val
    except Exception as e:
        logging.warning(f"[MLZ] Gemini enhancement error: {e}")

    return local

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
    # للأسماء المكونة من كلمتين يجب تطابق كلتيهما، وإلا يُعدّ اشتراك الاسم الأول فقط مصادفة
    min_needed = len(q_words) if len(q_words) <= 2 else max(2, round(len(q_words) * 0.6))
    best, best_score = None, 0
    for b in btns:
        lbl_words = set(w for w in _norm(b['label']).split() if len(w) > 1)
        score = len(q_words & lbl_words)
        if score > best_score:
            best_score = score
            best = b
    return best if best_score >= min_needed else None

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
        return grade_btn, mlz_btn, None, None  # لا ننشئ زر مادة جديد

    subject_children = [b for b in get_buttons(subject_btn['id'])
                        if b['type'] == 'compound' and not b.get('deleted')]
    teacher_btn = _fuzzy_match(teacher, subject_children)
    if not teacher_btn:
        # كشف نمط الرموز من أزرار المدرسين الموجودة وتطبيقه
        t_prefix, t_suffix = _extract_emoji_wrap(subject_children)
        teacher_label = _apply_emoji_wrap(teacher, t_prefix, t_suffix)
        # زرين في كل سطر: إذا العدد فردي → أضف بجانب الأخير، إذا زوجي → سطر جديد
        if len(subject_children) % 2 == 1:
            last_bid = subject_children[-1]['id']
            new_id = add_btn_after(last_bid, subject_btn['id'], 'compound', teacher_label, new_row=0)
        else:
            new_id = add_btn(subject_btn['id'], 'compound', teacher_label)
        teacher_btn = get_btn(new_id)

    return grade_btn, mlz_btn, subject_btn, teacher_btn

def _with_al(subject: str) -> str:
    """يُضيف 'ال' التعريف للمادة إن لم تكن موجودة مسبقاً."""
    s = subject.strip()
    if not s:
        return s
    if s.startswith('ال'):
        return s
    return f"ال{s}"

def _build_desc(subject, teacher, grade, year, part='', mlz_type='ملزمة'):
    part_str = f" الجزء {part}" if part else ""
    clean_grade = _strip_emoji(grade)
    clean_subject = _strip_emoji(subject).strip()
    subject_with_al = _with_al(clean_subject)
    return (
        f"⚜️ | {mlz_type} {subject_with_al}{part_str} {year}\n"
        f"⚜️ | للاستاذ {teacher}\n"
        f"⚜️ | {clean_grade}\n"
        f"⚜️ | سنة الاصدار : {year}\n"
        f"⚜️ | دقة عالية قابلة للسحب"
    )

def _build_btn_name(mlz_type, year):
    return f"📌{mlz_type} {year}📌"

def _clear_mlz(ctx):
    for key in [
        'mlz_file_type', 'mlz_file_id', 'mlz_subject', 'mlz_teacher',
        'mlz_grade', 'mlz_year', 'mlz_part', 'mlz_type', 'mlz_desc', 'mlz_path_str',
        'mlz_panel_mid', 'mlz_panel_chat_id', 'mlz_picker_mid',
    ]:
        ctx.user_data.pop(key, None)
    ctx.user_data.pop('state', None)

# ── بناء محتوى لوحة التأكيد الموحّدة ───────────────────────────
def _mlz_panel_content(ctx) -> tuple:
    subject  = ctx.user_data.get('mlz_subject') or '—'
    teacher  = ctx.user_data.get('mlz_teacher') or '—'
    grade    = ctx.user_data.get('mlz_grade')   or '—'
    year     = ctx.user_data.get('mlz_year')    or '—'
    part     = ctx.user_data.get('mlz_part')    or ''
    mlz_type = ctx.user_data.get('mlz_type')    or 'ملزمة'
    part_display = f"الجزء {part}" if part else '—'

    text = (
        "📂 *معلومات الملزمة*\n\n"
        f"🏫 الصف:     `{grade}`\n"
        f"📚 المادة:   `{subject}`\n"
        f"👨‍🏫 المدرس:   `{teacher}`\n"
        f"📅 السنة:    `{year}`\n"
        f"📑 الجزء:    `{part_display}`\n"
        f"🏷 النوع:    `{mlz_type}`\n\n"
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
            InlineKeyboardButton("📑 الجزء ✏️",   callback_data="mlz_ef_p"),
            InlineKeyboardButton("🏷 النوع ✏️",   callback_data="mlz_ef_tp"),
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

# ── عرض لوحة اختيار نوع الملزمة ─────────────────────────────────
async def show_type_picker(q, ctx):
    current = ctx.user_data.get('mlz_type', 'ملزمة')
    def _mark(val):
        return " ✓" if current == val else ""
    rows = []
    for i in range(0, len(MLZ_TYPES), 3):
        row = []
        for j in range(3):
            if i + j < len(MLZ_TYPES):
                t = MLZ_TYPES[i + j]
                row.append(InlineKeyboardButton(f"{t}{_mark(t)}", callback_data=f"mlz_tp_{i+j}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("✏️ اكتب نوعاً آخر", callback_data="mlz_tp_text")])
    await q.answer()
    msg = await q.message.reply_text(
        "🏷 *اختر نوع الملزمة:*",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(rows)
    )
    ctx.user_data['mlz_picker_mid'] = msg.message_id

async def after_mlz_type_pick(q, ctx, val: str):
    """يحفظ نوع الملزمة المختار."""
    if val == 'text':
        await q.answer()
        ctx.user_data['state'] = 'wait_mlz_type'
        await q.message.reply_text("🏷 أرسل نوع الملزمة (مثال: وزاريات):")
        return
    idx = int(val)
    chosen = MLZ_TYPES[idx] if idx < len(MLZ_TYPES) else 'ملزمة'
    ctx.user_data['mlz_type'] = chosen
    await q.answer(f"✅ {chosen}")
    await _delete_picker(ctx.bot, ctx, q.message.chat_id)
    await _refresh_mlz_panel(ctx.bot, ctx)

# ── عرض لوحة اختيار رقم الجزء ───────────────────────────────────
async def show_part_picker(q, ctx):
    current = ctx.user_data.get('mlz_part', '')
    def _mark(val):
        return " ✓" if current == val else ""
    rows = [
        [
            InlineKeyboardButton(f"❌ لا يوجد{_mark('')}", callback_data="mlz_p_0"),
            InlineKeyboardButton(f"1{_mark('1')}",         callback_data="mlz_p_1"),
            InlineKeyboardButton(f"2{_mark('2')}",         callback_data="mlz_p_2"),
        ],
        [
            InlineKeyboardButton(f"3{_mark('3')}",         callback_data="mlz_p_3"),
            InlineKeyboardButton(f"4{_mark('4')}",         callback_data="mlz_p_4"),
            InlineKeyboardButton(f"5{_mark('5')}",         callback_data="mlz_p_5"),
        ],
        [InlineKeyboardButton("✏️ اكتب رقماً آخر", callback_data="mlz_p_text")],
    ]
    await q.answer()
    msg = await q.message.reply_text(
        "📑 *اختر رقم الجزء:*",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(rows)
    )
    ctx.user_data['mlz_picker_mid'] = msg.message_id

async def after_mlz_part_pick(q, ctx, val: str):
    """يحفظ رقم الجزء المختار."""
    if val == 'text':
        await q.answer()
        ctx.user_data['state'] = 'wait_mlz_part'
        await q.message.reply_text("📑 أرسل رقم الجزء (مثال: 3):")
        return
    ctx.user_data['mlz_part'] = '' if val == '0' else val
    label = "بدون جزء" if val == '0' else f"الجزء {val}"
    await q.answer(f"✅ {label}")
    await _delete_picker(ctx.bot, ctx, q.message.chat_id)
    await _refresh_mlz_panel(ctx.bot, ctx)

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

    wait_msg = await m.reply_text("⏳ جاري تحليل الملف...")

    info = await extract_mlz_info(source_text) if source_text else {}

    ctx.user_data['mlz_subject'] = _strip_emoji(info.get('subject', ''))
    ctx.user_data['mlz_teacher'] = _strip_emoji(info.get('teacher', ''))
    ctx.user_data['mlz_grade']   = _strip_emoji(info.get('grade', ''))
    ctx.user_data['mlz_year']    = info.get('year', '')
    ctx.user_data['mlz_part']    = info.get('part', '')
    ctx.user_data['mlz_type']    = info.get('mlz_type', '') or 'ملزمة'

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

    # جلب أزرار المواد الموجودة داخل زر الملازم
    mlz_subject_btns = [b for b in get_buttons(mlz_btn['id'])
                        if b['type'] == 'menu' and not b.get('deleted')]
    matched = _fuzzy_match(subject, mlz_subject_btns)

    # مادة واضحة + تطابق موجود → تابع مباشرة
    if matched and _is_clear_subject(subject):
        ctx.user_data['mlz_subject'] = matched['label']
        await q.answer()
        try:
            await q.message.delete()
        except Exception:
            pass
        ctx.user_data.pop('mlz_panel_mid', None)
        await finish_mlz_flow(q.message, ctx, uid, chat_id, q.get_bot())
        return

    # في كل الحالات الأخرى → عرض picker المواد
    await _show_subject_picker(q, ctx, mlz_subject_btns, subject)

# ── picker اختيار المادة من الأزرار الموجودة ─────────────────────
async def _show_subject_picker(q, ctx, subject_btns: list, hint: str = ''):
    """يعرض قائمة أزرار المواد الموجودة لاختيار المادة الصحيحة."""
    await q.answer()
    if not subject_btns:
        await q.message.reply_text(
            "⚠️ لا توجد أزرار مواد داخل زر الملازم بعد.\n"
            "أضف أزرار المواد يدوياً ثم أعد المحاولة."
        )
        return
    rows = []
    for i in range(0, len(subject_btns), 2):
        row = []
        for j in range(2):
            if i + j < len(subject_btns):
                b = subject_btns[i + j]
                row.append(InlineKeyboardButton(b['label'], callback_data=f"mlz_sub_{b['id']}"))
        rows.append(row)
    hint_text = f"\n💡 المادة المكتوبة: *{hint}*" if hint else ""
    msg = await q.message.reply_text(
        f"📚 *اختر المادة من الأزرار الموجودة:*{hint_text}",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(rows)
    )
    ctx.user_data['mlz_picker_mid'] = msg.message_id

async def after_mlz_subject_pick(q, ctx, uid, chat_id, bid: int):
    """يحفظ المادة المختارة من الـ picker ويكمل عملية الإنشاء."""
    btn = get_btn(bid)
    if not btn:
        await q.answer("⚠️ الزر غير موجود.", show_alert=True)
        return
    ctx.user_data['mlz_subject'] = btn['label']
    await q.answer(f"✅ {btn['label']}")
    await _delete_picker(ctx.bot, ctx, q.message.chat_id)
    panel_mid = ctx.user_data.pop('mlz_panel_mid', None)
    if panel_mid:
        try:
            await ctx.bot.delete_message(chat_id=q.message.chat_id, message_id=panel_mid)
        except Exception:
            pass
    await finish_mlz_flow(q.message, ctx, uid, chat_id, q.get_bot())

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
    elif field == 'p':
        await show_part_picker(q, ctx)
    elif field == 'tp':
        await show_type_picker(q, ctx)

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

# ── الإنهاء: إنشاء الأزرار وإضافة الملف ─────────────────────────
async def finish_mlz_flow(m, ctx, uid, chat_id, bot):
    from .content_delivery import upload_to_channel

    subject   = ctx.user_data.get('mlz_subject', '')
    teacher   = ctx.user_data.get('mlz_teacher', '')
    grade     = ctx.user_data.get('mlz_grade', '')
    year      = ctx.user_data.get('mlz_year', '')
    part      = ctx.user_data.get('mlz_part', '')
    mlz_type  = ctx.user_data.get('mlz_type') or 'ملزمة'
    desc      = ctx.user_data.get('mlz_desc') or _build_desc(subject, teacher, grade, year, part, mlz_type)
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

    if not subject_btn:
        await wait_msg.edit_text(
            f"❌ لم أجد زر مادة «{subject}» داخل الملازم.\n"
            "تأكد من أن زر المادة موجود ثم أعد المحاولة."
        )
        _clear_mlz(ctx)
        return

    btn_name = _build_btn_name(mlz_type, year)

    # ── كشف التكرار قبل الحفظ ─────────────────────────────────
    existing_children = get_buttons(teacher_btn['id'])
    duplicate = _fuzzy_match(btn_name, existing_children)
    if duplicate:
        if part:
            # الملزمة لها جزء محدد → أضف الملف لنفس الزر الموجود تلقائياً
            await _do_add_mlz(
                wait_msg, ctx, bot,
                teacher_btn['id'], btn_name, file_type, file_id, desc,
                [grade_btn['label'], mlz_btn['label'], subject_btn['label'], teacher_btn['label'], duplicate['label']],
                existing_bid=duplicate['id']
            )
            _clear_mlz(ctx)
            return
        # لا يوجد جزء محدد → اسأل المشرف لتأكيد التكرار
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

async def _do_add_mlz(wait_msg, ctx, bot, teacher_bid, btn_name, file_type, file_id, desc, path_parts, existing_bid=None):
    from .content_delivery import upload_to_channel
    # إذا مُرِّر existing_bid → أضف لزر موجود بدلاً من إنشاء زر جديد
    if existing_bid:
        content_bid = existing_bid
        created_new = False
    else:
        content_bid = add_btn(teacher_bid, 'content', btn_name)
        created_new = True

    channel_msg_id = await upload_to_channel(bot, file_id, file_type, desc)

    if get_storage_channel_id() and not channel_msg_id:
        if created_new:
            del_btn(content_bid)
        await wait_msg.edit_text(
            "⚠️ لم يتم الحفظ لأن رفع الملف لقناة التخزين فشل.\n"
            "تأكد أن البوت أدمن في قناة التخزين."
        )
        return

    add_item(content_bid, file_type, desc, file_id, None, channel_msg_id)
    path_str = " ← ".join(path_parts)
    note = "" if created_new else "📎 *أُضيف لنفس زر المحتوى الموجود*\n\n"

    await wait_msg.edit_text(
        f"✅ *تمت الإضافة بنجاح!*\n\n"
        f"{note}"
        f"📂 *الموقع:*\n`{path_str}`\n\n"
        f"📝 *الوصف:*\n`{desc}`",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✏️ كتابة الوصف يدوياً", callback_data=f"mlz_ed_{content_bid}")
        ]])
    )

__all__ = [name for name in globals() if not name.startswith("__")]
