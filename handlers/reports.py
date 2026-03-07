# -*- coding: utf-8 -*-
"""
نظام التبليغ: بعد نهاية الجولة أو الانسحاب يظهر زر تبليغ → اختيار اللاعب → نوع التبليغ → رفع لقطات وملاحظة → إرسال للأدمن.
"""
import json
import logging
import os
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import db_query

logger = logging.getLogger(__name__)
router = Router(name="reports")

# استيراد من common عند الحاجة
def _get_replay_players(replay_id: str):
    from handlers.common import replay_data, _get_replay_from_db
    rdata = replay_data.get(replay_id)
    if not rdata and replay_id:
        rdata = _get_replay_from_db(replay_id)
    if not rdata:
        return None
    return rdata.get("players") or []


REPORT_TYPES = [
    ("bad_words", "ألفاظ سيئة"),
    ("sabotage", "تخريب / غش في اللعب"),
    ("harassment", "إهانة أو مضايقة"),
    ("threat", "تهديد"),
    ("impersonation", "انتحال شخصية"),
    ("spam", "إزعاج أو سبام"),
    ("other", "أخرى"),
]


class ReportStates(StatesGroup):
    report_upload = State()
    report_more = State()
    report_confirm = State()


# --- بدء التبليغ: اختيار من كان في الغرفة (زر "تبليغ على لاعب" فقط) ---
def _filter_report_start(callback: types.CallbackQuery) -> bool:
    data = (callback.data or "").strip()
    if not data or not data.startswith("report_"):
        return False
    if data.startswith("report_who_") or data.startswith("report_type_") or data.startswith("report_more_") or data.startswith("report_confirm_"):
        return False
    return True


@router.callback_query(_filter_report_start)
async def report_start(c: types.CallbackQuery, state: FSMContext):
    try:
        data = (c.data or "").strip()
        replay_id = data.replace("report_", "", 1).strip() if data.startswith("report_") else ""
    except Exception:
        replay_id = ""
    if not replay_id or replay_id == "None":
        return await c.answer("⚠️ خطأ أو انتهت الصلاحية.", show_alert=True)
    uid = c.from_user.id
    try:
        players = _get_replay_players(replay_id)
    except Exception:
        players = None
    if not players:
        return await c.answer("⚠️ انتهت صلاحية هذه الشاشة أو لا يوجد لاعبون. جرّب من نهاية لعبة جديدة.", show_alert=True)
    # استبعاد نفسك والبوت
    try:
        from config import BOT_USER_ID
        bot_id = BOT_USER_ID
    except Exception:
        bot_id = None
    choices = [(pid, pname) for pid, pname in players if pid != uid and pid != bot_id]
    if not choices:
        return await c.answer("لا يوجد لاعبون آخرون في الغرفة للتبليغ عليهم.", show_alert=True)
    await state.update_data(report_replay_id=replay_id)
    kb = []
    for pid, pname in choices:
        pname_short = (pname or "لاعب")[:20]
        kb.append([InlineKeyboardButton(text=f"📋 تبليغ على {pname_short}", callback_data=f"report_who_{replay_id}_{pid}")])
    kb.append([InlineKeyboardButton(text="🔙 رجوع", callback_data=f"gameend_back_{replay_id}")])
    await c.message.edit_text(
        "📋 **تبليغ على لاعب**\n\nاختر اللاعب الذي تريد التبليغ عليه:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="Markdown"
    )
    await c.answer()


@router.callback_query(F.data.startswith("report_who_"))
async def report_choose_who(c: types.CallbackQuery, state: FSMContext):
    # report_who_{replay_id}_{reported_id} → ["report", "who", replay_id, reported_id] = 4 أجزاء
    parts = c.data.split("_")
    if len(parts) < 4:
        return await c.answer("⚠️ خطأ في البيانات.", show_alert=True)
    replay_id = parts[2]
    try:
        reported_id = int(parts[3])
    except ValueError:
        return await c.answer("⚠️ خطأ.", show_alert=True)
    uid = c.from_user.id
    if reported_id == uid:
        return await c.answer("لا يمكنك التبليغ على نفسك.", show_alert=True)
    await state.update_data(report_replay_id=replay_id, report_reported_id=reported_id, report_photos=[], report_note=None, report_extra=None)
    kb = []
    for type_key, label in REPORT_TYPES:
        kb.append([InlineKeyboardButton(text=label, callback_data=f"report_type_{replay_id}_{reported_id}_{type_key}")])
    kb.append([InlineKeyboardButton(text="🔙 رجوع", callback_data=f"report_{replay_id}")])
    reported_name = "لاعب"
    for pid, pname in (_get_replay_players(replay_id) or []):
        if pid == reported_id:
            reported_name = pname or "لاعب"
            break
    await c.message.edit_text(
        f"📋 **نوع التبليغ** (على {reported_name})\n\nاختر نوع التبليغ:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="Markdown"
    )
    await c.answer()


@router.callback_query(F.data.startswith("report_type_"))
async def report_choose_type(c: types.CallbackQuery, state: FSMContext):
    parts = c.data.split("_", 4)
    if len(parts) < 5:
        return await c.answer("⚠️ خطأ.", show_alert=True)
    replay_id = parts[2]
    try:
        reported_id = int(parts[3])
    except ValueError:
        return await c.answer("⚠️ خطأ.", show_alert=True)
    report_type = parts[4]
    type_label = next((l for k, l in REPORT_TYPES if k == report_type), report_type)
    await state.update_data(
        report_replay_id=replay_id,
        report_reported_id=reported_id,
        report_type=report_type,
        report_type_label=type_label,
        report_photos=[],
        report_note=None,
        report_extra=None,
    )
    await state.set_state(ReportStates.report_upload)
    kb_upload = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 رجوع", callback_data=f"report_upload_back_{replay_id}_{reported_id}")],
    ])
    await c.message.edit_text(
        "📷 **الخطوة التالية:** أرسل **صورة سكرين شوت** للحالة التي رأيتها (صورة واحدة على الأقل).\n\n"
        "بعد إرسال الصورة سيُطلب منك إضافة المزيد أو كتابة ملاحظة ثم إرسال التبليغ.",
        parse_mode="Markdown",
        reply_markup=kb_upload
    )
    await c.answer()


@router.message(ReportStates.report_upload, F.photo)
async def report_receive_photo(message: types.Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="نعم لدي صورة أو ملاحظة أخرى", callback_data="report_more_yes")],
        [InlineKeyboardButton(text="إرسال التبليغ", callback_data="report_more_done")],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="home")],
    ])
    try:
        data = await state.get_data()
        photos = data.get("report_photos") or []
        file_id = message.photo[-1].file_id if message.photo else None
        if file_id:
            photos.append(file_id)
        await state.update_data(report_photos=photos)
        await state.set_state(ReportStates.report_more)
        await message.answer("✅ تم حفظ الصورة.\n\nهل لديك صورة أخرى أو ملاحظة تريد إضافتها؟", reply_markup=kb)
    except Exception as e:
        logger.exception("report_receive_photo: %s", e)
        await message.answer("✅ تم حفظ الصورة.\n\nهل لديك صورة أخرى أو ملاحظة تريد إضافتها؟", reply_markup=kb)


@router.message(ReportStates.report_upload, F.text)
async def report_upload_expect_photo(message: types.Message, state: FSMContext):
    if message.text and message.text.strip().lower() in ("/cancel", "cancel", "الغاء", "إلغاء", "/start"):
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 رجوع", callback_data="home")]])
        return await message.answer("تم الإلغاء.", reply_markup=kb)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 رجوع", callback_data="home")]])
    await message.answer("يرجى إرسال **صورة سكرين شوت** أولاً (صورة واحدة على الأقل). لإلغاء التبليغ اضغط **رجوع**.", reply_markup=kb, parse_mode="Markdown")


@router.callback_query(ReportStates.report_more, F.data == "report_more_yes")
async def report_more_yes(c: types.CallbackQuery, state: FSMContext):
    await state.set_state(ReportStates.report_more)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 رجوع", callback_data="home")]])
    await c.message.edit_text(
        "أرسل **صورة إضافية** أو اكتب **ملاحظتك** / ما حدث مع اللاعب.\n\n"
        "بعد الإرسال يمكنك إضافة المزيد أو الضغط على «إرسال التبليغ» من الرسالة التالية.",
        reply_markup=kb
    )
    await c.answer()


@router.callback_query(ReportStates.report_more, F.data == "report_more_done")
async def report_more_done(c: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    photos = data.get("report_photos") or []
    if not photos:
        return await c.answer("يجب إرسال صورة واحدة على الأقل (سكرين شوت).", show_alert=True)
    await state.set_state(ReportStates.report_confirm)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ إرسال التبليغ", callback_data="report_confirm_send")],
        [InlineKeyboardButton(text="❌ تراجع", callback_data="report_confirm_cancel")],
    ])
    await c.message.edit_text(
        "هل تريد **إرسال التبليغ** إلى الإدارة أم **التراجع**؟",
        reply_markup=kb
    )
    await c.answer()


@router.message(ReportStates.report_more, F.photo)
async def report_more_receive_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("report_photos") or []
    if message.photo:
        photos.append(message.photo[-1].file_id)
    await state.update_data(report_photos=photos)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="نعم لدي صورة أو ملاحظة أخرى", callback_data="report_more_yes")],
        [InlineKeyboardButton(text="إرسال التبليغ", callback_data="report_more_done")],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="home")],
    ])
    await message.answer("✅ تم حفظ الصورة.\n\nهل لديك صورة أخرى أو ملاحظة؟", reply_markup=kb)


@router.message(ReportStates.report_more, F.text)
async def report_more_receive_text(message: types.Message, state: FSMContext):
    if message.text and message.text.strip().lower() in ("/cancel", "cancel", "الغاء", "إلغاء", "/start"):
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 رجوع", callback_data="home")]])
        return await message.answer("تم الإلغاء.", reply_markup=kb)
    data = await state.get_data()
    note = data.get("report_note")
    extra = (message.text or "").strip()[:2000]
    if not note:
        await state.update_data(report_note=extra)
    else:
        await state.update_data(report_extra=extra)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="نعم لدي صورة أو ملاحظة أخرى", callback_data="report_more_yes")],
        [InlineKeyboardButton(text="إرسال التبليغ", callback_data="report_more_done")],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="home")],
    ])
    await message.answer("✅ تم حفظ الملاحظة.\n\nهل لديك صورة أخرى أو ملاحظة إضافية؟", reply_markup=kb)


@router.callback_query(ReportStates.report_confirm, F.data == "report_confirm_cancel")
async def report_confirm_cancel(c: types.CallbackQuery, state: FSMContext):
    await state.clear()
    from handlers.common import show_main_menu
    user = db_query("SELECT player_name FROM users WHERE user_id = %s", (c.from_user.id,))
    name = (user[0]["player_name"] if user else None) or c.from_user.full_name
    await c.message.edit_text("تم التراجع عن التبليغ.")
    await show_main_menu(c.message, name, c.from_user.id, state=state)
    await c.answer()


def _user_detail_for_admin(u: dict) -> str:
    if not u or not isinstance(u, dict):
        return "—"
    uid = u.get("user_id")
    name = (u.get("player_name") or "—")
    tg_username = (u.get("username") or "").strip() or "—"
    if tg_username != "—":
        tg_username = "@" + tg_username
    uname = u.get("username_key") or "—"
    pts = u.get("online_points", 0)
    return (
        f"🆔 الايدي: {uid}\n"
        f"📱 يوزر تليجرام: {tg_username}\n"
        f"📛 الاسم (باللعبة): {name}\n"
        f"👤 يوزر البوت: @{uname}\n"
        f"⭐ النقاط: {pts}"
    )


@router.callback_query(ReportStates.report_confirm, F.data == "report_confirm_send")
async def report_confirm_send(c: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    reporter_id = c.from_user.id
    reported_id = data.get("report_reported_id")
    replay_id = data.get("report_replay_id") or ""
    report_type = data.get("report_type") or "other"
    type_label = data.get("report_type_label") or "أخرى"
    photos = data.get("report_photos") or []
    note = data.get("report_note") or ""
    extra = data.get("report_extra") or ""
    if not reported_id or not photos:
        await c.answer("بيانات التبليغ ناقصة.", show_alert=True)
        return
    photos_json = json.dumps(photos)
    full_note = note + ("\n" + extra if extra else "")
    try:
        db_query(
            """CREATE TABLE IF NOT EXISTS reports (
                id SERIAL PRIMARY KEY,
                reporter_id BIGINT NOT NULL,
                reported_id BIGINT NOT NULL,
                replay_id VARCHAR(16),
                report_type VARCHAR(32) NOT NULL,
                photos_json TEXT,
                note TEXT,
                extra_note TEXT,
                status VARCHAR(16) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            commit=True
        )
    except Exception:
        pass
    try:
        db_query(
            """INSERT INTO reports (reporter_id, reported_id, replay_id, report_type, photos_json, note, status)
               VALUES (%s, %s, %s, %s, %s, %s, 'pending')""",
            (reporter_id, reported_id, replay_id, report_type, photos_json, full_note or None),
            commit=True
        )
    except Exception as e:
        await c.answer(f"خطأ في حفظ التبليغ: {e}", show_alert=True)
        return
    await state.clear()

    # إرسال التبليغ للأدمن (نفس آلية طلب المساعدة: _get_admin_ids + HELP_CHAT_ID)
    from handlers.common import _get_admin_ids
    admin_ids = _get_admin_ids()
    help_chat_id_raw = os.getenv("HELP_CHAT_ID", "").strip().strip('"').strip("'")
    help_chat_id = help_chat_id_raw.strip() if help_chat_id_raw else ""
    logger.info("report_confirm_send: reporter=%s admin_ids=%s HELP_CHAT_ID=%s", reporter_id, list(admin_ids), help_chat_id or "(غير مضبوط)")
    if not admin_ids and not help_chat_id:
        logger.warning("report_confirm_send: ADMIN_ID و HELP_CHAT_ID غير مضبوطين — التبليغ محفوظ في قاعدة البيانات فقط.")
    reporter_row = db_query("SELECT * FROM users WHERE user_id = %s", (reporter_id,))
    reported_row = db_query("SELECT * FROM users WHERE user_id = %s", (reported_id,))
    reporter_detail = _user_detail_for_admin(reporter_row[0]) if reporter_row else f"🆔 {reporter_id}"
    reported_detail = _user_detail_for_admin(reported_row[0]) if reported_row else f"🆔 {reported_id}"

    head = (
        "📋 **تبليغ جديد**\n\n"
        f"**نوع التبليغ:** {type_label}\n"
        f"**replay_id:** {replay_id or '—'}\n\n"
        "**👤 مقدّم التبليغ:**\n" + reporter_detail + "\n\n"
        "**👤 المبلغ عليه:**\n" + reported_detail + "\n\n"
    )
    if full_note:
        head += f"**📝 الملاحظة:**\n{full_note}\n\n"
    head += "**📷 الصور:**"

    async def _send_report_to_chat(chat_id, label=""):
        try:
            await c.bot.send_message(chat_id, head, parse_mode="Markdown")
            for fid in photos[:10]:
                await c.bot.send_photo(chat_id, fid)
            if len(photos) > 10:
                await c.bot.send_message(chat_id, f"... و {len(photos) - 10} صورة إضافية.")
            return True
        except Exception as e1:
            try:
                plain = head.replace("**", "").replace("`", "'")
                await c.bot.send_message(chat_id, plain)
                for fid in photos[:10]:
                    await c.bot.send_photo(chat_id, fid)
                return True
            except Exception as e2:
                logger.warning("report_confirm_send: send to %s %s failed: %s then %s", label, chat_id, e1, e2)
                return False

    for admin_id in admin_ids:
        await _send_report_to_chat(admin_id, "admin")
    if help_chat_id:
        ch_id = int(help_chat_id) if help_chat_id.lstrip("-").isdigit() else help_chat_id
        await _send_report_to_chat(ch_id, "HELP_CHAT_ID")

    from handlers.common import show_main_menu
    user = db_query("SELECT player_name FROM users WHERE user_id = %s", (c.from_user.id,))
    name = (user[0]["player_name"] if user else None) or c.from_user.full_name
    await c.message.edit_text("✅ تم إرسال التبليغ إلى الإدارة. سنراجعه في أقرب وقت.")
    await show_main_menu(c.message, name, c.from_user.id, state=state)
    await c.answer()
