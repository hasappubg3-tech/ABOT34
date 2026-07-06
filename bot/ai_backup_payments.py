from .shared import *

def _repair_json(raw: str) -> str:
    """يحاول إغلاق JSON مقطوع بإضافة الأقواس والنصوص المفقودة."""
    stack = []
    in_string = False
    escape_next = False
    for ch in raw:
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            stack.append('}')
        elif ch == '[':
            stack.append(']')
        elif ch in ('}', ']') and stack:
            stack.pop()
    # إذا كنا داخل نص مقطوع أغلقه أولاً
    suffix = '"' if in_string else ''
    suffix += ''.join(reversed(stack))
    return raw + suffix

def _parse_ai_response(raw: str):
    """يستخرج action وقائمة العمليات وقائمة الحذف من JSON.
    يُرجع: (action, operations, del_idx)
    حيث operations = [{"insert": int|str, "buttons": list}, ...]
    """
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    # محاولة التحليل المباشر أولاً، وإصلاح JSON المقطوع عند الفشل
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logging.warning(f"[AI] JSON malformed, attempting repair. Raw snippet: {raw[-200:]}")
        data = json.loads(_repair_json(raw))
    action  = data.get("action", "add")
    del_idx = data.get("delete_indices", [])

    # دعم تنسيق operations (الجديد) وتنسيق buttons المسطح (القديم)
    if "operations" in data:
        operations = []
        for op in data["operations"]:
            operations.append({
                "insert": op.get("insert_after_index", -1),
                "buttons": op.get("buttons", []),
            })
    else:
        operations = [{
            "insert": data.get("insert_after_index", -1),
            "buttons": data.get("buttons", []),
        }]
    return action, operations, del_idx

async def _download_image_base64(bot, file_id: str):
    """يحمّل الصورة من تيليغرام ويحوّلها إلى base64."""
    import base64, io
    tg_file = await bot.get_file(file_id)
    buf = io.BytesIO()
    await tg_file.download_to_memory(buf)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode(), "image/jpeg"

GEMINI_VISION_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.0-flash-lite"]

async def _call_gemini_vision(client: httpx.AsyncClient, prompt: str, images: list):
    """يستدعي Gemini Vision API مع تدوير المفاتيح والنماذج تلقائياً."""
    parts = [{"text": prompt}]
    for img in images:
        parts.append({"inline_data": {"mime_type": img["mime"], "data": img["data"]}})
    payload = {"contents": [{"parts": parts}]}
    for model in GEMINI_VISION_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for key in get_all_gemini_keys():
            try:
                resp = await client.post(url, params={"key": key}, json=payload, timeout=60)
                if resp.status_code in (429, 503):
                    logging.warning(f"Gemini Vision {model} key ...{key[-6:]} rate-limited, trying next...")
                    continue
                if resp.status_code == 404:
                    logging.warning(f"Gemini Vision model {model} not found, trying next model...")
                    break
                resp.raise_for_status()
                data = resp.json()
                candidate = data.get("candidates", [{}])[0]
                finish = candidate.get("finishReason", "")
                if finish in ("SAFETY", "RECITATION", "OTHER"):
                    logging.warning(f"Gemini Vision blocked: {finish}")
                    return None
                text = candidate.get("content", {}).get("parts", [{}])[0].get("text", "")
                if text:
                    logging.info(f"Gemini Vision raw response: {text[:300]}")
                    return text
            except Exception as e:
                logging.warning(f"Gemini Vision {model} exception: {e}")
    return None

async def _process_image_batch(wait_msg, m, ctx, uid, pid, images: list, btn_type: str):
    """يحلّل مجموعة صور ويضيف الأزرار المستخرجة منها بالترتيب."""
    import re
    if not get_all_gemini_keys():
        await wait_msg.edit_text("❌ تحليل الصور يتطلب مفتاح Gemini API. أضفه من الإعدادات ← مفاتيح API.")
        return
    all_added = []
    existing_labels = set()
    last_bid = None
    for img in images:
        existing_str = "، ".join(f'"{l}"' for l in existing_labels) if existing_labels else "لا شيء"
        prompt = (
            "أنت مساعد لاستخراج أسماء أزرار واجهة تيليغرام من الصور.\n"
            "انظر إلى الصورة واستخرج جميع أسماء الأزرار الظاهرة بنفس ترتيبها وتخطيطها.\n"
            f"الأزرار المضافة مسبقاً (لا تكررها أبداً): {existing_str}\n\n"
            "أرجع JSON فقط بهذا الشكل بدون أي نص إضافي:\n"
            '{"buttons": [{"label": "اسم الزر", "new_row": true}, ...]}\n\n'
            "- new_row: true إذا كان الزر في سطر جديد، false إذا في نفس سطر الزر السابق.\n"
            "- لا تضف أزرار تنقل مثل: رجوع، الرئيسية، القائمة الرئيسية، ⬅️، 🏠.\n"
            '- إذا لم توجد أزرار أو كلها مكررة: {"buttons": []}'
        )
        try:
            async with httpx.AsyncClient() as client:
                raw = await _call_gemini_vision(client, prompt, [img])
            if not raw:
                continue
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if not json_match:
                continue
            data = json.loads(json_match.group())
            buttons = data.get("buttons", [])
        except Exception as e:
            logging.warning(f"Image batch parse error: {e}")
            continue
        for btn_data in buttons:
            label = (btn_data.get("label") or "").strip()
            if not label or label in existing_labels:
                continue
            new_row = btn_data.get("new_row", True)
            nr = 1 if new_row else 0
            if last_bid is None:
                last_bid = add_btn(pid, btn_type, label)
            else:
                last_bid = add_btn_after(last_bid, pid, btn_type, label, new_row=nr)
            all_added.append(label)
            existing_labels.add(label)
    if all_added:
        names = "\n".join(f"  • {l}" for l in all_added)
        await wait_msg.edit_text(f"✅ تم إضافة {len(all_added)} زر:\n{names}", parse_mode="Markdown")
        await m.reply_text("🔄", reply_markup=build_kb(uid, pid))
    else:
        await wait_msg.edit_text("⚠️ لم يُعثر على أزرار في الصور.")

async def _call_gemini(client: httpx.AsyncClient, prompt: str):
    """يستدعي Gemini API مع تدوير المفاتيح تلقائياً."""
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    for key in get_all_gemini_keys():
        resp = await client.post(url, params={"key": key}, json=payload, timeout=60)
        if resp.status_code in (429, 503):
            logging.warning(f"Gemini key ...{key[-6:]} rate-limited, trying next key...")
            continue
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    return None

async def generate_quiz_questions(source_text: str, count: int):
    """يستخرج أسئلة كويز MCQ من نص مصدر باستخدام Gemini."""
    import re
    if not get_all_gemini_keys():
        return None, "❌ لم يُعَيَّن مفتاح Gemini API."
    prompt = (
        f"أنت مساعد تعليمي متخصص في إنشاء أسئلة اختيار متعدد (MCQ).\n\n"
        f"اقرأ النص المصدر التالي وأنشئ {count} سؤال اختيار متعدد منه.\n\n"
        "قواعد:\n"
        "- كل سؤال له 4 خيارات (واحد صحيح وثلاثة خاطئة منطقية وغير واضحة)\n"
        "- الخيارات الخاطئة يجب أن تكون معقولة لتصعيب التخمين\n"
        f"- إذا لم يكفِ النص لـ {count} سؤال، أنشئ أكبر عدد ممكن\n"
        "- أرجع JSON صحيح فقط بدون أي نص إضافي\n\n"
        "الشكل المطلوب:\n"
        '[\n  {\n    "question": "نص السؤال",\n'
        '    "options": ["خيار 1", "خيار 2", "خيار 3", "خيار 4"],\n'
        '    "correct": 0\n  }\n]\n\n'
        'حيث "correct" هو رقم الخيار الصحيح (0=الأول، 1=الثاني، 2=الثالث، 3=الرابع).\n\n'
        f"النص المصدر:\n{source_text[:15000]}"
    )
    try:
        async with httpx.AsyncClient() as client:
            result = await _call_gemini(client, prompt)
        if not result:
            return None, "❌ لم يستجب الذكاء الاصطناعي. حاول مجدداً."
        json_match = re.search(r'\[[\s\S]*\]', result)
        if not json_match:
            return None, "❌ لم يتمكن الذكاء الاصطناعي من توليد الأسئلة من هذا النص."
        questions = json.loads(json_match.group())
        if not isinstance(questions, list):
            return None, "❌ صيغة الإجابة غير صحيحة."
        return questions, None
    except json.JSONDecodeError:
        return None, "❌ خطأ في معالجة إجابة الذكاء الاصطناعي."
    except Exception as e:
        logging.error(f"generate_quiz_questions error: {e}")
        return None, f"❌ خطأ أثناء التوليد: {e}"

async def generate_quiz_questions_from_file(b64_data: str, mime_type: str, count: int):
    """يستخرج أسئلة كويز MCQ من ملف (صورة أو PDF) باستخدام Gemini Vision."""
    import re
    if not get_all_gemini_keys():
        return None, "❌ لم يُعَيَّن مفتاح Gemini API."
    prompt = (
        f"أنت مساعد تعليمي متخصص في إنشاء أسئلة اختيار متعدد (MCQ).\n\n"
        f"اقرأ الملف المرفق وأنشئ {count} سؤال اختيار متعدد من محتواه.\n\n"
        "قواعد:\n"
        "- كل سؤال له 4 خيارات (واحد صحيح وثلاثة خاطئة منطقية وغير واضحة)\n"
        "- الخيارات الخاطئة يجب أن تكون معقولة لتصعيب التخمين\n"
        f"- إذا لم يكفِ المحتوى لـ {count} سؤال، أنشئ أكبر عدد ممكن\n"
        "- أرجع JSON صحيح فقط بدون أي نص إضافي\n\n"
        "الشكل المطلوب:\n"
        '[\n  {\n    "question": "نص السؤال",\n'
        '    "options": ["خيار 1", "خيار 2", "خيار 3", "خيار 4"],\n'
        '    "correct": 0\n  }\n]\n\n'
        'حيث "correct" هو رقم الخيار الصحيح (0=الأول، 1=الثاني، 2=الثالث، 3=الرابع).'
    )
    try:
        images = [{"data": b64_data, "mime": mime_type}]
        async with httpx.AsyncClient() as client:
            result = await _call_gemini_vision(client, prompt, images)
        if not result:
            return None, "❌ لم يستجب الذكاء الاصطناعي."
        json_match = re.search(r'\[[\s\S]*\]', result)
        if not json_match:
            return None, "❌ لم يتمكن الذكاء الاصطناعي من توليد الأسئلة من هذا الملف."
        questions = json.loads(json_match.group())
        if not isinstance(questions, list):
            return None, "❌ صيغة الإجابة غير صحيحة."
        return questions, None
    except json.JSONDecodeError:
        return None, "❌ خطأ في معالجة إجابة الذكاء الاصطناعي."
    except Exception as e:
        logging.error(f"generate_quiz_questions_from_file error: {e}")
        return None, f"❌ خطأ أثناء التوليد: {e}"

async def process_ai_request(user_request: str, current_btns: list = None):
    """يستدعي Gemini ويُرجع (action, operations, del_idx, error)."""
    if not get_all_gemini_keys():
        return None, [], [], "❌ لم يُعَيَّن أي مفتاح Gemini API. أضفه من الإعدادات ← مفاتيح API."

    if current_btns:
        ctx_lines = [f"الأزرار الحالية الموجودة ({len(current_btns)} زر) مُجمَّعة حسب الأسطر:"]
        current_row_btns = []
        rows = []
        for i, b in enumerate(current_btns):
            if i == 0 or b.get("new_row", 1):
                if current_row_btns:
                    rows.append(current_row_btns)
                current_row_btns = [(i, b)]
            else:
                current_row_btns.append((i, b))
        if current_row_btns:
            rows.append(current_row_btns)
        for r_idx, row in enumerate(rows):
            btns_str = "،  ".join(
                f"[{i}](زر{pos+1} من السطر) \"{b['label']}\" ({b['type']})"
                for pos, (i, b) in enumerate(row)
            )
            last_idx = row[-1][0]
            ctx_lines.append(f"  السطر {r_idx + 1} ({len(row)} زر): {btns_str}  ← آخر فهرس في هذا السطر: {last_idx}")
        ctx_text = "\n".join(ctx_lines)
    else:
        ctx_text = "لا توجد أزرار حالية (القائمة فارغة)."

    prompt = f"{AI_SYSTEM_PROMPT}\n\n{ctx_text}\n\nطلب المشرف: {user_request}"

    async with httpx.AsyncClient() as client:
        try:
            raw = await _call_gemini(client, prompt)
            if raw:
                action, operations, del_idx = _parse_ai_response(raw)
                return action, operations, del_idx, None
            return None, [], [], "⚠️ جميع مفاتيح Gemini وصلت لحد الطلبات. حاول لاحقاً."
        except json.JSONDecodeError:
            return None, [], [], "⚠️ لم أتمكن من تفسير رد الذكاء الاصطناعي. حاول مرة أخرى."
        except Exception as e:
            logging.warning(f"Gemini exception: {e}")
    return None, [], [], "⚠️ تعذّر الاتصال بـ Gemini. تحقق من المفاتيح وحاول مرة أخرى."

# ── النسخ الاحتياطي ───────────────────────────────────────────────
async def send_backup(bot, chat_id: int):
    """يُنشئ ملف ZIP يحتوي قاعدة البيانات والملفات ويرسله للمستخدم."""
    from telegram.request import HTTPXRequest
    now = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    zip_path = f"/tmp/backup_{now}.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            if os.path.exists(DB):
                zf.write(DB, arcname="data.db")
            if os.path.isdir(MEDIA_DIR):
                for fname in os.listdir(MEDIA_DIR):
                    fpath = os.path.join(MEDIA_DIR, fname)
                    if os.path.isfile(fpath):
                        zf.write(fpath, arcname=os.path.join("media", fname))
        with open(zip_path, "rb") as f:
            await bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=f"backup_{now}.zip",
                caption=f"💾 نسخة احتياطية — {now}",
                write_timeout=300,
                read_timeout=300,
                connect_timeout=60,
            )
    except Exception as e:
        logging.warning(f"فشل إرسال النسخة الاحتياطية: {e}")
        try:
            await bot.send_message(chat_id=chat_id, text=f"❌ فشل إرسال النسخة الاحتياطية:\n{e}")
        except Exception:
            pass
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)

async def restore_backup(zip_path: str) -> tuple[bool, str]:
    """يستعيد النسخة الاحتياطية من ملف ZIP — يُعيد (نجاح, رسالة)."""
    import shutil
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            if "data.db" not in names:
                return False, "⚠️ الملف لا يحتوي على data.db — تأكد أنه نسخة احتياطية صحيحة."
            db_bak = DB + ".bak"
            if os.path.exists(DB):
                shutil.copy2(DB, db_bak)
            zf.extract("data.db", path=".")
            media_files = [n for n in names if n.startswith("media/") and not n.endswith("/")]
            for mf in media_files:
                zf.extract(mf, path=".")
        if os.path.exists(db_bak):
            os.remove(db_bak)
        return True, f"✅ تمت الاستعادة بنجاح!\n🗂 قاعدة البيانات: محدّثة\n📁 ملفات الميديا المستعادة: {len(media_files)}"
    except zipfile.BadZipFile:
        return False, "❌ الملف المرسل ليس ملف ZIP صالح."
    except Exception as e:
        return False, f"❌ فشلت الاستعادة: {e}"

async def _auto_backup_job(ctx):
    """مهمة الجدولة التلقائية — ترسل النسخة للمشرف الرئيسي وقناة التخزين."""
    sid = os.environ.get("SUPER_ADMIN_ID", "").strip()
    ch  = get_storage_channel_id()

    # إرسال للمشرف الرئيسي
    if sid.isdigit():
        await send_backup(ctx.bot, int(sid))

    # إرسال لقناة التخزين (إن كانت مختلفة عن المشرف)
    if ch and (not sid.isdigit() or int(sid) != int(ch)):
        await send_backup(ctx.bot, int(ch))

AI_SIXTH_GRADE_SYSTEM_PROMPT = """أنت مساعد ذكي ودود متخصص في منهج السادس العلمي العراقي.

ثلاث حالات للرد:

1. سؤال دراسي من منهج السادس العلمي (فيزياء، كيمياء، أحياء، رياضيات، عربي، إنجليزي، تربية إسلامية):
   → أجب بإجابة علمية كاملة بالفصحى وفق المنهج العراقي مع توضيح الخطوات كاملة. لا تقصّر.

2. سؤال معرفي أو ثقافي عام (تاريخ، جغرافيا، علوم عامة، أي سؤال يحتاج إجابة فعلية):
   → أجب بإجابة مباشرة وموجزة باللغة العربية. مثال: "عاصمة فرنسا باريس."

3. كلام اجتماعي (تحية، مشاعر، مديح، ثرثرة):
   → ردّ بجملة أو جملتين طبيعيتين باللهجة العراقية البسيطة. لا تطوّل أكثر من ذلك.
   → مثال: "أحبك" → "وأنا أحبك 😊 ويشرفني أساعدك بدراستك!" | "هلا" → "هلا بيك، شبيك اليوم؟ 😊"

اذهب مباشرة للإجابة دون مقدمات في جميع الحالات.
"""

async def ai_chat_respond(uid: int, text: str = None, image_b64: str = None, image_mime: str = None) -> str:
    """يرسل سؤال المستخدم (نص أو صورة) إلى Gemini مع سياق السادس العلمي والذاكرة."""
    async with get_ai_semaphore():
        return await _ai_chat_respond_inner(uid, text=text, image_b64=image_b64, image_mime=image_mime)

async def _ai_chat_respond_inner(uid: int, text: str = None, image_b64: str = None, image_mime: str = None) -> str:
    """التنفيذ الداخلي لمحادثة AI — يُستدعى من خلال الطابور فقط."""
    if not get_all_gemini_keys():
        return "❌ لا يوجد مفتاح Gemini API. يرجى التواصل مع المشرف لإضافة المفاتيح من إعدادات AI."

    memory_on = get_ai_memory_enabled()
    memory_count = get_ai_memory_count()

    # بناء محتوى المحادثة
    if image_b64 and image_mime:
        # سؤال بصورة — نستخدم Vision
        parts = []
        if text:
            parts.append({"text": f"{AI_SIXTH_GRADE_SYSTEM_PROMPT}\n\nسؤال الطالب: {text}"})
        else:
            parts.append({"text": f"{AI_SIXTH_GRADE_SYSTEM_PROMPT}\n\nحلل الصورة وأجب على ما فيها."})
        parts.append({"inline_data": {"mime_type": image_mime, "data": image_b64}})

        # إضافة الذاكرة في حالة الصور (كنص فقط)
        history_parts = []
        if memory_on:
            history = get_ai_chat_history(uid)
            for turn in history[-memory_count:]:
                history_parts.append({"text": f"[محادثة سابقة] الطالب: {turn.get('q','')}\nأنت: {turn.get('a','')}"})

        if history_parts:
            parts = [{"text": AI_SIXTH_GRADE_SYSTEM_PROMPT + "\n\nسياق المحادثة السابقة:\n" + "\n".join(p["text"] for p in history_parts)}] + parts[1:]

        payload = {"contents": [{"parts": parts}]}
        try:
            async with httpx.AsyncClient() as client:
                answer = await _call_gemini_vision(client, "", [{"data": image_b64, "mime": image_mime}])
                if not answer:
                    # محاولة ثانية مع prompt كامل
                    prompt_text = AI_SIXTH_GRADE_SYSTEM_PROMPT
                    if memory_on:
                        history = get_ai_chat_history(uid)
                        for turn in history[-memory_count:]:
                            prompt_text += f"\n[سابق] الطالب: {turn.get('q','')}\nأنت: {turn.get('a','')}"
                    prompt_text += f"\n\nسؤال الطالب: {text or 'حلل الصورة وأجب.'}"
                    answer = await _call_gemini_vision(client, prompt_text, [{"data": image_b64, "mime": image_mime}])
        except Exception as e:
            logging.error(f"ai_chat_respond vision error: {e}")
            return "⚠️ تعذّر تحليل الصورة. حاول مرة أخرى."

        if not answer:
            return "⚠️ لم يستجب الذكاء الاصطناعي. حاول مرة أخرى."

        # حفظ في الذاكرة
        if memory_on:
            history = get_ai_chat_history(uid)
            history.append({"q": text or "[صورة]", "a": answer})
            save_ai_chat_history(uid, history[-memory_count:])

        return answer

    else:
        # سؤال نصي — نبني المحادثة مع الذاكرة
        contents = []

        if memory_on:
            history = get_ai_chat_history(uid)
            # أول رسالة تحتوي system prompt + المحادثة السابقة
            system_with_history = AI_SIXTH_GRADE_SYSTEM_PROMPT
            for turn in history[-memory_count:]:
                system_with_history += f"\n\n[محادثة سابقة]\nالطالب: {turn.get('q','')}\nأنت: {turn.get('a','')}"
            contents.append({"parts": [{"text": system_with_history}]})
        else:
            contents.append({"parts": [{"text": AI_SIXTH_GRADE_SYSTEM_PROMPT}]})

        contents.append({"parts": [{"text": f"سؤال الطالب: {text}"}]})

        payload = {"contents": contents}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

        answer = None
        async with httpx.AsyncClient() as client:
            for key in get_all_gemini_keys():
                try:
                    resp = await client.post(url, params={"key": key}, json=payload, timeout=60)
                    if resp.status_code in (429, 503):
                        logging.warning(f"ai_chat key ...{key[-6:]} rate-limited, trying next...")
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    candidate = data.get("candidates", [{}])[0]
                    finish = candidate.get("finishReason", "")
                    if finish in ("SAFETY", "RECITATION"):
                        return "⚠️ السؤال لا يمكن الإجابة عليه بسبب سياسة الاستخدام."
                    answer = candidate.get("content", {}).get("parts", [{}])[0].get("text", "")
                    if answer:
                        break
                except Exception as e:
                    logging.warning(f"ai_chat text error key ...{key[-6:]}: {e}")

        if not answer:
            return "⚠️ جميع مفاتيح Gemini وصلت للحد المسموح أو تعذّر الاتصال. حاول لاحقاً."

        # حفظ في الذاكرة
        if memory_on:
            history = get_ai_chat_history(uid)
            history.append({"q": text, "a": answer})
            save_ai_chat_history(uid, history[-memory_count:])

        return answer

async def precheckout_callback(update: Update, ctx):
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("stars_donation:"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="فاتورة غير معروفة.")

async def successful_payment_callback(update: Update, ctx):
    payment = update.message.successful_payment
    stars = payment.total_amount if payment and payment.currency == "XTR" else 0
    msg = get_donation_thanks_message(stars)
    try:
        await update.message.reply_text(
            msg,
            api_kwargs={"message_effect_id": "5046509860389126442"}
        )
    except Exception:
        await update.message.reply_text(msg)

# ── مهام البومودورو ───────────────────────────────────────────────
async def _pom_study_end(ctx):
    """يُرسل تنبيه نهاية وقت الدراسة."""
    uid     = ctx.job.data["uid"]
    brk     = ctx.job.data["break_min"]
    study   = ctx.job.data["study_min"]
    chat_id = ctx.job.data["chat_id"]
    try:
        await ctx.bot.send_message(
            chat_id=chat_id,
            text=(
                f"⏰ *انتهى وقت الدراسة!* 🎉\n\n"
                f"أحسنت! خذ استراحة *{brk} دقيقة* الآن. 🧘"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ بدأت الاستراحة", callback_data=f"pom_break_start_{brk}_{study}")],
                [InlineKeyboardButton("✋ إنهاء الجلسة",   callback_data="pom_stop")],
            ])
        )
    except Exception as e:
        logging.warning(f"pom_study_end failed: {e}")

async def _pom_break_end(ctx):
    """يُرسل تنبيه نهاية وقت الاستراحة."""
    uid     = ctx.job.data["uid"]
    study   = ctx.job.data["study_min"]
    chat_id = ctx.job.data["chat_id"]
    try:
        await ctx.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🍅 *انتهت الاستراحة!*\n\n"
                f"حان وقت الدراسة مرة أخرى — *{study} دقيقة*. هل أنت جاهز؟ 💪"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ ابدأ الآن",     callback_data="pom_start")],
                [InlineKeyboardButton("✋ إنهاء الجلسة", callback_data="pom_stop")],
            ])
        )
    except Exception as e:
        logging.warning(f"pom_break_end failed: {e}")
