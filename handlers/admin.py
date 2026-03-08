# -*- coding: utf-8 -*-
"""
لوحة إدارة البوت. الأدمن فقط (ADMIN_ID من متغيرات البيئة).
"""
import os
import html
import json
import logging

logger = logging.getLogger(__name__)
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import db_query

router = Router(name="admin")

def _admin_ids():
    """نفس منطق common._get_admin_ids: إزالة علامات الاقتباس والرموز الزائدة لدعم Railway Variables."""
    ids = set()
    for key in ("ADMIN_ID", "ADMIN_IDS", "ADMIN_TELEGRAM_ID"):
        raw = os.getenv(key, "")
        if raw is None:
            continue
        raw = str(raw).strip().strip('"').strip("'").replace("\\", "").strip()
        if not raw:
            continue
        for x in raw.split(","):
            cleaned = "".join(c for c in str(x).strip() if c.isdigit())
            if cleaned:
                try:
                    ids.add(int(cleaned))
                except ValueError:
                    pass
    return ids

def is_admin(user_id: int) -> bool:
    return user_id in _admin_ids()

def _admin_only(callback_or_message):
    uid = callback_or_message.from_user.id if hasattr(callback_or_message, "from_user") else callback_or_message.chat.id
    return is_admin(uid)


class AdminStates(StatesGroup):
    broadcast_text = State()
    edit_user_target = State()
    edit_user_field = State()
    edit_user_value = State()
    report_reply_to_reporter = State()
    admin_chat_with_user = State()  # محادثة مع لاعب (بعد قبوله)


# --- /admin وزر القائمة الرئيسية ---
@router.message(Command("admin"))
async def cmd_admin(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await _send_admin_menu(message, message.from_user.id)


@router.message(Command("channel_id"), F.text)
async def cmd_channel_id(message: types.Message):
    """أمر للأدمن: يعرض آيدي القناة من يوزرها. الاستخدام: /channel_id uno1011 أو /channel_id @uno1011"""
    if not is_admin(message.from_user.id):
        return
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    username = (parts[1] if len(parts) > 1 else "").strip().lstrip("@")
    if not username:
        await message.answer("📌 الاستخدام: `/channel_id uno1011` أو `/channel_id @uno1011`\n\nضع يوزر القناة بعد الأمر.", parse_mode="Markdown")
        return
    try:
        chat = await message.bot.get_chat(f"@{username}")
        cid = chat.id
        title = getattr(chat, "title", "") or "—"
        await message.answer(
            f"🆔 **آيدي القناة**\n\n"
            f"• اليوزر: `@{username}`\n"
            f"• الآيدي: `{cid}`\n"
            f"• الاسم: {title}\n\n"
            f"استخدم في الإعدادات: `PUBLISH_CHANNEL_ID = {cid}` أو `{cid}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(f"❌ لا يمكن جلب القناة. تأكد أن البوت داخل القناة أو أن القناة عامة.\n\nالتفاصيل: {e}")


@router.message(Command("test_publish_channel"))
async def cmd_test_publish_channel(message: types.Message):
    """أمر للأدمن: إرسال رسالة تجريبية إلى قناة النشر للتحقق من أن البوت يستطيع النشر."""
    if not is_admin(message.from_user.id):
        return
    try:
        from handlers.common import PUBLISH_CHANNEL_ID, PUBLISH_CHANNEL_USERNAME
    except Exception:
        await message.answer("❌ تعذر تحميل إعدادات القناة.")
        return
    chat_target = None
    if PUBLISH_CHANNEL_ID is not None:
        try:
            raw = str(PUBLISH_CHANNEL_ID).strip().strip('"').strip("'")
            if raw:
                ch = int(raw)
                chat_target = -ch if ch > 0 else ch
        except (TypeError, ValueError):
            pass
    if chat_target is None and (PUBLISH_CHANNEL_USERNAME or "").strip():
        un = (PUBLISH_CHANNEL_USERNAME or "").strip().lstrip("@")
        chat_target = f"@{un}"
    if not chat_target:
        await message.answer(
            "⚠️ قناة النشر غير مضبوطة.\n\n"
            "اضبط PUBLISH_CHANNEL_ID أو PUBLISH_CHANNEL_USERNAME في channel_config.py أو متغيرات البيئة."
        )
        return
    try:
        await message.bot.send_message(
            chat_target,
            "✅ رسالة تجريبية من البوت — النشر يعمل بشكل سليم.",
            parse_mode=None
        )
        await message.answer(
            f"✅ تم إرسال رسالة تجريبية إلى القناة (chat_id={chat_target}).\n\n"
            "إن لم تظهر الرسالة في القناة، تأكد أن البوت مضاف كـ **مسؤول** وله صلاحية «نشر رسائل»."
        )
    except Exception as e:
        err = str(e).replace("'", "")[:250]
        await message.answer(
            "❌ فشل إرسال الرسالة التجريبية إلى القناة.\n\n"
            "• أضف البوت في القناة كـ **مسؤول** وامنحه صلاحية «نشر رسائل».\n"
            "• تأكد أن معرف القناة أو اليوزر صحيح.\n\n"
            f"الخطأ: {err}"
        )


@router.callback_query(F.data == "admin_test_publish")
async def admin_test_publish_callback(c: types.CallbackQuery):
    """زر اختبار النشر من لوحة الأدمن."""
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    await c.answer()
    try:
        from handlers.common import PUBLISH_CHANNEL_ID, PUBLISH_CHANNEL_USERNAME
    except Exception:
        await c.message.edit_text("❌ تعذر تحميل إعدادات القناة.")
        return
    chat_target = None
    if PUBLISH_CHANNEL_ID is not None:
        try:
            raw = str(PUBLISH_CHANNEL_ID).strip().strip('"').strip("'")
            if raw:
                ch = int(raw)
                chat_target = -ch if ch > 0 else ch
        except (TypeError, ValueError):
            pass
    if chat_target is None and (PUBLISH_CHANNEL_USERNAME or "").strip():
        un = (PUBLISH_CHANNEL_USERNAME or "").strip().lstrip("@")
        chat_target = f"@{un}"
    if not chat_target:
        await c.message.edit_text(
            "⚠️ قناة النشر غير مضبوطة.\n\n"
            "اضبط PUBLISH_CHANNEL_ID أو PUBLISH_CHANNEL_USERNAME في channel_config.py أو متغيرات البيئة."
        )
        return
    try:
        await c.bot.send_message(
            chat_target,
            "✅ رسالة تجريبية من البوت — النشر يعمل بشكل سليم.",
            parse_mode=None
        )
        await c.message.edit_text(
            f"✅ تم إرسال رسالة تجريبية إلى القناة (chat_id={chat_target}).\n\n"
            "تحقق من القناة. إن لم تظهر الرسالة، أضف البوت كـ **مسؤول** مع صلاحية «نشر رسائل».",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 رجوع", callback_data="admin_back")]
            ])
        )
    except Exception as e:
        err = str(e).replace("'", "")[:280]
        await c.message.edit_text(
            "❌ فشل إرسال الرسالة التجريبية إلى القناة.\n\n"
            "• أضف البوت في القناة كـ **مسؤول** وامنحه صلاحية «نشر رسائل».\n"
            "• تأكد أن معرف القناة أو اليوزر صحيح.\n\n"
            f"الخطأ: {err}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 رجوع", callback_data="admin_back")]
            ])
        )


@router.callback_query(F.data == "admin_open_panel")
async def admin_open_from_menu(c: types.CallbackQuery, state: FSMContext):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    await state.clear()
    await _send_admin_menu(c.message, c.from_user.id)
    await c.answer()


def _admin_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 اذاعة بث للجميع", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="📡 اختبار النشر في القناة", callback_data="admin_test_publish")],
        [InlineKeyboardButton(text="📋 التبليغات", callback_data="admin_reports")],
        [InlineKeyboardButton(text="🆘 طلبات المساعدة", callback_data="admin_help_requests")],
        [InlineKeyboardButton(text="📊 عدد اللاعبين وإحصائيات", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 قائمة اللاعبين / بحث وتعديل", callback_data="admin_players")],
        [InlineKeyboardButton(text="🛏 الغرف المفتوحة والمتروكة", callback_data="admin_rooms")],
        [InlineKeyboardButton(text="🔙 إغلاق لوحة الإدارة", callback_data="admin_close")],
    ])


async def _send_admin_menu(target, uid: int, text: str = None):
    msg = text or "⚙️ **لوحة إدارة البوت**\n\nاختر:"
    kb = _admin_menu_kb()
    if isinstance(target, types.Message):
        await target.answer(msg, reply_markup=kb, parse_mode="Markdown")
    else:
        try:
            await target.edit_text(msg, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            await target.message.answer(msg, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data == "admin_close")
async def admin_close(c: types.CallbackQuery, state: FSMContext):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    await state.clear()
    from handlers.common import show_main_menu
    user = db_query("SELECT player_name FROM users WHERE user_id = %s", (c.from_user.id,))
    name = user[0]["player_name"] if user else c.from_user.full_name
    await show_main_menu(c.message, name, c.from_user.id, state=state, from_admin=True)
    await c.answer()


@router.callback_query(F.data == "admin_goto_main")
async def admin_goto_main(c: types.CallbackQuery, state: FSMContext):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    await state.clear()
    from handlers.common import show_main_menu
    user = db_query("SELECT player_name FROM users WHERE user_id = %s", (c.from_user.id,))
    name = user[0]["player_name"] if user else c.from_user.full_name
    await show_main_menu(c.message, name, c.from_user.id, state=state, from_admin=True)
    await c.answer()


@router.callback_query(F.data == "admin_back")
async def admin_back(c: types.CallbackQuery, state: FSMContext):
    if not _admin_only(c):
        return
    await state.clear()
    await _send_admin_menu(c.message, c.from_user.id)
    await c.answer()


@router.callback_query(F.data.startswith("admin_chat_request_"))
async def admin_chat_request_user(c: types.CallbackQuery, state: FSMContext):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    try:
        uid = int(c.data.replace("admin_chat_request_", "").strip())
    except ValueError:
        return await c.answer("⚠️ خطأ.", show_alert=True)
    from handlers.common import _pending_chat_requests
    _pending_chat_requests[uid] = c.from_user.id
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ قبول", callback_data=f"accept_chat_{uid}"), InlineKeyboardButton(text="❌ رفض", callback_data=f"decline_chat_{uid}")],
    ])
    try:
        await c.bot.send_message(uid, "💬 **الإدارة تريد التحدث معك.**\n\nهل تقبل فتح محادثة؟ (يمكن إنهاؤها من قبل أي طرف)", reply_markup=kb, parse_mode="Markdown")
        await c.answer("تم إرسال طلب المحادثة للاعب.")
    except Exception as e:
        _pending_chat_requests.pop(uid, None)
        await c.answer(f"فشل الإرسال للاعب: {e}", show_alert=True)


async def _admin_chat_started_with_user(bot, admin_id: int, user_id: int, user_name: str):
    """استدعاء من common عند قبول اللاعب للمحادثة — نرسل للأدمن زراً لبدء المحادثة."""
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 بدء المحادثة مع اللاعب", callback_data=f"admin_start_chat_{user_id}")]])
    await bot.send_message(admin_id, f"✅ قبل اللاعب **{user_name}** المحادثة.\n\nاضغط الزر أدناه لبدء المحادثة وكتابة رسالتك.", parse_mode="Markdown", reply_markup=kb)


@router.callback_query(F.data.startswith("admin_start_chat_"))
async def admin_start_chat_click(c: types.CallbackQuery, state: FSMContext):
    if not _admin_only(c):
        return
    try:
        user_id = int(c.data.replace("admin_start_chat_", "").strip())
    except ValueError:
        return await c.answer("⚠️ خطأ.", show_alert=True)
    await state.set_state(AdminStates.admin_chat_with_user)
    await state.update_data(admin_chat_with_uid=user_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔚 إنهاء المحادثة", callback_data="admin_end_chat")]])
    await c.message.edit_text("💬 المحادثة مفتوحة مع اللاعب.\n\nاكتب رسالتك أو اضغط «إنهاء المحادثة».", reply_markup=kb)
    await c.answer()


async def _admin_chat_ended(bot, admin_id: int, user_id: int):
    """استدعاء عند إنهاء اللاعب للمحادثة."""
    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 رجوع", callback_data="admin_back")]])
        await bot.send_message(admin_id, "🔚 أنهى اللاعب المحادثة.", reply_markup=kb)
    except Exception:
        pass


@router.callback_query(F.data == "admin_end_chat")
async def admin_end_chat_callback(c: types.CallbackQuery, state: FSMContext):
    if not _admin_only(c):
        return
    data = await state.get_data()
    user_id = data.get("admin_chat_with_uid")
    await state.clear()
    kb_admin = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 رجوع", callback_data="admin_back")]])
    await c.message.edit_text("تم إنهاء المحادثة.", reply_markup=kb_admin)
    await c.answer()
    if user_id:
        try:
            kb_user = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 رجوع", callback_data="my_account")]])
            await c.bot.send_message(user_id, "🔚 أنهت الإدارة المحادثة.", reply_markup=kb_user)
        except Exception:
            pass


@router.message(AdminStates.admin_chat_with_user, F.text | F.photo | F.voice | F.video | F.document)
async def admin_chat_send_to_user(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    logger.info("admin_chat_send_to_user: admin=%s", message.from_user.id)
    data = await state.get_data()
    user_id = data.get("admin_chat_with_uid")
    if not user_id:
        await state.clear()
        await message.answer("⚠️ انتهت جلسة المحادثة. اطلب محادثة جديدة من لوحة الإدارة.")
        return
    admin_name = message.from_user.full_name or "الإدارة"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔚 إنهاء المحادثة", callback_data="admin_end_chat")]])
    try:
        if message.text:
            await message.bot.send_message(user_id, f"👤 **من الإدارة ({admin_name}):**\n\n{message.text}", parse_mode="Markdown")
        elif message.photo:
            await message.bot.send_photo(user_id, message.photo[-1].file_id, caption=f"👤 من الإدارة ({admin_name})")
        elif message.voice:
            await message.bot.send_voice(user_id, message.voice.file_id, caption=f"👤 من الإدارة ({admin_name})")
        elif message.video:
            await message.bot.send_video(user_id, message.video.file_id, caption=f"👤 من الإدارة ({admin_name})")
        elif message.document:
            await message.bot.send_document(user_id, message.document.file_id, caption=f"👤 من الإدارة ({admin_name})")
    except Exception as e:
        logger.warning("admin_chat_send_to_user: send to user_id=%s failed: %s", user_id, e)
        err = str(e).strip()[:300]
        await message.answer(
            f"❌ فشل إرسال الرسالة للاعب.\n\nقد يكون اللاعب حظر البوت أو أوقف المحادثة.\n\nالتفاصيل: {err}",
            reply_markup=kb
        )
        return
    await message.answer("✅ تم إرسال رسالتك.", reply_markup=kb)


@router.callback_query(F.data == "admin_help_requests")
async def admin_help_requests_list(c: types.CallbackQuery, state: FSMContext):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    try:
        db_query(
            """CREATE TABLE IF NOT EXISTS help_requests (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                body_text TEXT NOT NULL,
                has_media BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            commit=True
        )
    except Exception:
        pass
    try:
        rows = db_query(
            "SELECT id, user_id, body_text, has_media, created_at FROM help_requests ORDER BY created_at DESC LIMIT 40",
            ()
        )
    except Exception:
        rows = []
    if not rows:
        text = "🆘 **طلبات المساعدة**\n\nلا توجد طلبات مساعدة حتى الآن."
    else:
        text = "🆘 **طلبات المساعدة** (آخر 40)\n\n"
        for r in rows:
            rid = r.get("id")
            uid = r.get("user_id")
            created = r.get("created_at")
            when = created.strftime("%Y-%m-%d %H:%M") if hasattr(created, "strftime") else str(created)
            body = (r.get("body_text") or "")[:400]
            if len((r.get("body_text") or "")) > 400:
                body += "..."
            text += f"——— #{rid} — ايدي: {uid} — {when} —\n{body}\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="admin_back")]
    ])
    try:
        await c.message.edit_text(text[:4000], reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await c.message.edit_text(text[:4000].replace("*", ""), reply_markup=kb)
    await c.answer()


# --- اذاعة بث (نص، صورة، فيديو، ملف، أي وسائط) ---
@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(c: types.CallbackQuery, state: FSMContext):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    await state.set_state(AdminStates.broadcast_text)
    await c.message.edit_text(
        "📢 **اذاعة بث**\n\nأرسل **أي شيء** تريد إرساله للجميع:\n• نص\n• صورة\n• فيديو\n• ملف (مستند)\n• صوت\n• صوتية\n\nلإلغاء اضغط **رجوع**.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="admin_back")]
        ]),
        parse_mode="Markdown")
    await c.answer()


def _row_user_id(r) -> int:
    """استخراج user_id من صف قاعدة البيانات. RealDictCursor يعيد dict بمفتاح user_id."""
    if r is None:
        return 0
    try:
        if hasattr(r, "get") and callable(r.get):
            uid = r.get("user_id") or r.get("USER_ID") or r.get("userid")
            if uid is not None:
                return int(uid)
            if hasattr(r, "items"):
                for k, v in r.items():
                    if str(k).lower() == "user_id" and v is not None:
                        return int(v)
            if r:
                return int(next(iter(r.values())))
        if hasattr(r, "user_id"):
            v = getattr(r, "user_id", None)
            if v is not None:
                return int(v)
        if hasattr(r, "__getitem__"):
            return int(r[0])
        if hasattr(r, "__iter__") and not isinstance(r, (str, bytes)):
            return int(next(iter(r)))
    except (IndexError, KeyError, TypeError, ValueError, StopIteration):
        pass
    return 0


def _admin_broadcast_done_kb():
    """أزرار بعد انتهاء الإذاعة: اذاعة جديدة، رجوع، القائمة الرئيسية."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 اذاعة جديدة", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="admin_back")],
        [InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="admin_close")],
    ])


def _broadcast_caption():
    return "📢 اذاعة من الإدارة"

async def _send_broadcast_to_user(bot, uid: int, message: types.Message, text: str):
    """يرسل نفس نوع الرسالة (نص/صورة/فيديو/ملف...) للمستخدم uid."""
    try:
        if message.photo:
            cap = (message.caption or "").strip() or text or _broadcast_caption()
            await bot.send_photo(int(uid), message.photo[-1].file_id, caption=cap)
        elif message.video:
            cap = (message.caption or "").strip() or text or _broadcast_caption()
            await bot.send_video(int(uid), message.video.file_id, caption=cap)
        elif message.document:
            cap = (message.caption or "").strip() or text or _broadcast_caption()
            await bot.send_document(int(uid), message.document.file_id, caption=cap)
        elif message.audio:
            cap = (message.caption or "").strip() or text or _broadcast_caption()
            await bot.send_audio(int(uid), message.audio.file_id, caption=cap)
        elif message.voice:
            await bot.send_voice(int(uid), message.voice.file_id, caption=text or _broadcast_caption())
        else:
            await bot.send_message(int(uid), f"📢 اذاعة من الإدارة:\n\n{text or '(بدون نص)'}")
        return True
    except Exception:
        return False

@router.message(AdminStates.broadcast_text, F.text)
async def admin_broadcast_send_text(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text and message.text.strip().lower() in ("/cancel", "cancel", "الغاء", "إلغاء"):
        await state.clear()
        return await message.answer("تم الإلغاء.", reply_markup=_admin_broadcast_done_kb())
    text = message.text or ""
    try:
        raw_rows = db_query("SELECT user_id FROM users WHERE user_id IS NOT NULL")
        rows = list(raw_rows) if raw_rows else []
        if not rows:
            await state.clear()
            await message.answer("❌ لا يوجد لاعبون في القاعدة.", reply_markup=_admin_broadcast_done_kb())
            return
        total = len(rows)
        sent = 0
        import logging
        log = logging.getLogger(__name__)
        for r in rows:
            uid = _row_user_id(r)
            if not uid:
                log.warning("Broadcast: could not get user_id from row type=%s row=%s", type(r).__name__, r)
                continue
            try:
                await message.bot.send_message(int(uid), f"📢 اذاعة من الإدارة:\n\n{text}")
                sent += 1
            except Exception as e:
                log.warning("Broadcast: send to %s failed: %s", uid, e)
        await state.clear()
        await message.answer(
            f"✅ تم إرسال الإذاعة إلى {sent}/{total} لاعب.",
            reply_markup=_admin_broadcast_done_kb()
        )
    except Exception as e:
        await state.clear()
        await message.answer(f"❌ خطأ: {e}", reply_markup=_admin_broadcast_done_kb())


@router.message(AdminStates.broadcast_text, F.photo | F.video | F.document | F.audio | F.voice)
async def admin_broadcast_send_media(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = (message.caption or message.text or "").strip() or _broadcast_caption()
    try:
        raw_rows = db_query("SELECT user_id FROM users WHERE user_id IS NOT NULL")
        rows = list(raw_rows) if raw_rows else []
        if not rows:
            await state.clear()
            await message.answer("❌ لا يوجد لاعبون في القاعدة.", reply_markup=_admin_broadcast_done_kb())
            return
        total = len(rows)
        sent = 0
        import logging
        log = logging.getLogger(__name__)
        for r in rows:
            uid = _row_user_id(r)
            if not uid:
                log.warning("Broadcast: could not get user_id from row type=%s row=%s", type(r).__name__, r)
                continue
            if await _send_broadcast_to_user(message.bot, uid, message, text):
                sent += 1
        await state.clear()
        await message.answer(
            f"✅ تم إرسال الإذاعة (وسائط) إلى {sent}/{total} لاعب.",
            reply_markup=_admin_broadcast_done_kb()
        )
    except Exception as e:
        await state.clear()
        await message.answer(f"❌ خطأ: {e}", reply_markup=_admin_broadcast_done_kb())


# --- رد الأدمن على المبلّغ (بعد تم إكمال التبليغ أو مرفوض) ---
async def _send_to_reporter_like_broadcast(bot, reporter_id: int, message: types.Message, header: str):
    try:
        if message.photo:
            cap = (message.caption or "").strip() or header
            await bot.send_photo(reporter_id, message.photo[-1].file_id, caption=cap)
        elif message.video:
            cap = (message.caption or "").strip() or header
            await bot.send_video(reporter_id, message.video.file_id, caption=cap)
        elif message.document:
            cap = (message.caption or "").strip() or header
            await bot.send_document(reporter_id, message.document.file_id, caption=cap)
        elif message.audio:
            cap = (message.caption or "").strip() or header
            await bot.send_audio(reporter_id, message.audio.file_id, caption=cap)
        elif message.voice:
            await bot.send_message(reporter_id, header)
            await bot.send_voice(reporter_id, message.voice.file_id)
        else:
            text = (message.text or "").strip() or header
            await bot.send_message(reporter_id, f"{header}\n\n{text}")
        return True
    except Exception:
        return False


@router.message(AdminStates.report_reply_to_reporter, F.text)
async def admin_report_reply_text(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        return await message.answer("تم الإلغاء.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin_back")]
        ]))
    data = await state.get_data()
    report_id = data.get("admin_report_id")
    outcome = data.get("admin_report_outcome") or "completed"
    if not report_id:
        await state.clear()
        return await message.answer("انتهت الجلسة. أعد فتح التبليغ.")
    row = db_query("SELECT reporter_id FROM reports WHERE id = %s", (report_id,))
    if not row:
        await state.clear()
        return await message.answer("التبليغ غير موجود.")
    reporter_id = row[0]["reporter_id"]
    header = "📩 تم مراجعة تبليغك وتم حظره." if outcome == "completed" else "📩 تم مراجعة تبليغك — التبليغ مرفوض."
    await message.bot.send_message(reporter_id, f"{header}\n\n{message.text or ''}")
    db_query("UPDATE reports SET status = %s WHERE id = %s", ("completed" if outcome == "completed" else "rejected", report_id), commit=True)
    await state.clear()
    await message.answer("✅ تم إرسال رسالتك للمبلّغ وتحديث حالة التبليغ.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 قائمة التبليغات", callback_data="admin_reports")],
        [InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin_back")],
    ]))


@router.message(AdminStates.report_reply_to_reporter, F.photo | F.voice | F.video | F.document | F.audio)
async def admin_report_reply_media(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    report_id = data.get("admin_report_id")
    outcome = data.get("admin_report_outcome") or "completed"
    if not report_id:
        await state.clear()
        return await message.answer("انتهت الجلسة.")
    row = db_query("SELECT reporter_id FROM reports WHERE id = %s", (report_id,))
    if not row:
        await state.clear()
        return await message.answer("التبليغ غير موجود.")
    reporter_id = row[0]["reporter_id"]
    header = "📩 تم مراجعة تبليغك وتم حظره." if outcome == "completed" else "📩 تم مراجعة تبليغك — التبليغ مرفوض."
    if await _send_to_reporter_like_broadcast(message.bot, reporter_id, message, header):
        db_query("UPDATE reports SET status = %s WHERE id = %s", ("completed" if outcome == "completed" else "rejected", report_id), commit=True)
        await state.clear()
        await message.answer("✅ تم إرسال رسالتك للمبلّغ وتحديث حالة التبليغ.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 قائمة التبليغات", callback_data="admin_reports")],
            [InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin_back")],
        ]))
    else:
        await message.answer("⚠️ تعذر إرسال الرسالة للمبلّغ (ربما حظر البوت).")


# --- إحصائيات ---
@router.callback_query(F.data == "admin_stats")
async def admin_stats(c: types.CallbackQuery):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    try:
        total = db_query("SELECT COUNT(*) AS c FROM users WHERE user_id IS NOT NULL")
        total = total[0]["c"] if total else 0
        registered = db_query("SELECT COUNT(*) AS c FROM users WHERE is_registered = TRUE")
        registered = registered[0]["c"] if registered else 0
        rooms_open = db_query("SELECT COUNT(*) AS c FROM rooms WHERE status IN ('waiting', 'playing')")
        rooms_open = rooms_open[0]["c"] if rooms_open else 0
    except Exception:
        total = registered = rooms_open = 0
    text = (
        f"📊 **إحصائيات البوت**\n\n"
        f"👥 إجمالي المستخدمين: **{total}**\n"
        f"✅ مسجلون (حساب كامل): **{registered}**\n"
        f"🛏 غرف مفتوحة/قيد اللعب: **{rooms_open}**"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 رجوع", callback_data="admin_back")]])
    await c.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await c.answer()


# --- التبليغات: أزرار أرقام، عرض كامل، تم متابعة / إكمال / مرفوض ---
def _reports_count():
    try:
        r = db_query("SELECT COUNT(*) AS c FROM reports")
        return r[0]["c"] if r else 0
    except Exception:
        return 0

def _reports_list(offset: int = 0, limit: int = 50):
    try:
        return db_query(
            """SELECT id, reporter_id, reported_id, report_type, note, status, created_at
               FROM reports ORDER BY created_at DESC LIMIT %s OFFSET %s""",
            (limit, offset)
        ) or []
    except Exception:
        return []


def _report_status_ar(status):
    s = (status or "").strip().lower()
    if s == "in_progress" or s == "جاري المتابعة":
        return "جاري المتابعة"
    if s == "completed" or s == "تم التبليغ":
        return "تم التبليغ"
    if s == "rejected" or s == "مرفوض":
        return "مرفوض"
    return "في الانتظار"


@router.callback_query(F.data == "admin_reports")
async def admin_reports_list(c: types.CallbackQuery, state: FSMContext):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    await state.clear()
    total = _reports_count()
    if total == 0:
        await c.message.edit_text(
            "📋 لا توجد تبليغات.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 رجوع", callback_data="admin_back")]
            ])
        )
        return await c.answer()
    rows = _reports_list(0, 50)
    text = f"📋 **التبليغات** — العدد: **{total}**\n\nاضغط على رقم لفتح التبليغ كاملاً:"
    kb = []
    row_btns = []
    for i, r in enumerate(rows):
        rid = r.get("id")
        row_btns.append(InlineKeyboardButton(text=str(i + 1), callback_data=f"admin_report_view_{rid}"))
        if len(row_btns) >= 5:
            kb.append(row_btns)
            row_btns = []
    if row_btns:
        kb.append(row_btns)
    kb.append([InlineKeyboardButton(text="🔙 رجوع", callback_data="admin_back")])
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    await c.answer()


@router.callback_query(F.data.startswith("admin_report_view_"))
async def admin_report_view(c: types.CallbackQuery):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    try:
        report_id = int(c.data.replace("admin_report_view_", "").strip())
    except ValueError:
        return await c.answer("خطأ.", show_alert=True)
    row = db_query("SELECT * FROM reports WHERE id = %s", (report_id,))
    if not row:
        return await c.answer("التبليغ غير موجود.", show_alert=True)
    r = row[0]
    reporter_id = r.get("reporter_id")
    reported_id = r.get("reported_id")
    rep_type = r.get("report_type") or "—"
    note = (r.get("note") or "").strip() or "—"
    photos_json = r.get("photos_json")
    status_ar = _report_status_ar(r.get("status"))
    reporter_row = db_query("SELECT * FROM users WHERE user_id = %s", (reporter_id,))
    reported_row = db_query("SELECT * FROM users WHERE user_id = %s", (reported_id,))
    rep_detail = _user_detail_text(reporter_row[0]) if reporter_row else f"🆔 {reporter_id}"
    reped_detail = _user_detail_text(reported_row[0]) if reported_row else f"🆔 {reported_id}"
    text = (
        f"📋 <b>تبليغ #{report_id}</b> — الحالة: <b>{status_ar}</b>\n\n"
        f"<b>نوع التبليغ:</b> {html.escape(rep_type)}\n\n"
        f"<b>👤 مقدّم التبليغ:</b>\n{rep_detail}\n\n"
        f"<b>👤 المبلغ عليه:</b>\n{reped_detail}\n\n"
        f"<b>📝 الملاحظة:</b>\n{html.escape(note)}\n\n"
        "الصور أدناه (إن وُجدت)."
    )
    status_raw = (r.get("status") or "").strip().lower()
    kb = [
        [InlineKeyboardButton(text="📌 تم متابعة التبليغ", callback_data=f"admin_report_inprogress_{report_id}")],
        [InlineKeyboardButton(text="✅ تم إكمال التبليغ", callback_data=f"admin_report_complete_{report_id}")],
        [InlineKeyboardButton(text="❌ مرفوض", callback_data=f"admin_report_reject_{report_id}")],
        [InlineKeyboardButton(text="🚫 حظر المبلغ عليه", callback_data=f"admin_report_ban_{report_id}")],
        [InlineKeyboardButton(text="◀️ السابق", callback_data=f"admin_report_prev_{report_id}")],
        [InlineKeyboardButton(text="▶️ التالي", callback_data=f"admin_report_next_{report_id}")],
        [InlineKeyboardButton(text="🔙 قائمة التبليغات", callback_data="admin_reports")],
    ]
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    if photos_json:
        try:
            fids = json.loads(photos_json)
            for fid in (fids or [])[:10]:
                try:
                    await c.bot.send_photo(c.from_user.id, fid)
                except Exception:
                    pass
        except Exception:
            pass
    await c.answer()


@router.callback_query(F.data.startswith("admin_report_ban_"))
async def admin_report_ban(c: types.CallbackQuery):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    try:
        report_id = int(c.data.replace("admin_report_ban_", "").strip())
    except ValueError:
        return await c.answer("خطأ.", show_alert=True)
    row = db_query("SELECT reported_id FROM reports WHERE id = %s", (report_id,))
    if not row:
        return await c.answer("التبليغ غير موجود.", show_alert=True)
    reported_id = row[0]["reported_id"]
    try:
        db_query("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE", commit=True)
    except Exception:
        try:
            db_query("ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT FALSE", commit=True)
        except Exception:
            pass
    db_query("UPDATE users SET is_banned = TRUE WHERE user_id = %s", (reported_id,), commit=True)
    await c.answer("✅ تم حظر اللاعب المبلغ عليه.", show_alert=True)
    c.data = f"admin_report_view_{report_id}"
    await admin_report_view(c)


@router.callback_query(F.data.startswith("admin_report_inprogress_"))
async def admin_report_inprogress(c: types.CallbackQuery):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    try:
        report_id = int(c.data.replace("admin_report_inprogress_", "").strip())
    except ValueError:
        return await c.answer("خطأ.", show_alert=True)
    row = db_query("SELECT reporter_id FROM reports WHERE id = %s", (report_id,))
    if not row:
        return await c.answer("التبليغ غير موجود.", show_alert=True)
    try:
        db_query("UPDATE reports SET status = 'in_progress' WHERE id = %s", (report_id,), commit=True)
    except Exception:
        pass
    reporter_id = row[0]["reporter_id"]
    try:
        await c.bot.send_message(
            reporter_id,
            "📩 **الإدارة استلمت تبليغك وجاري المتابعة.**\n\nسيتم إعلامك عند الانتهاء من المراجعة.",
            parse_mode="Markdown"
        )
    except Exception:
        pass
    await c.answer("✅ تم. تم إشعار المبلّغ بأن التبليغ جاري متابعته.", show_alert=True)
    c.data = f"admin_report_view_{report_id}"
    await admin_report_view(c)


@router.callback_query(F.data.startswith("admin_report_complete_"))
async def admin_report_complete_ask(c: types.CallbackQuery, state: FSMContext):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    try:
        report_id = int(c.data.replace("admin_report_complete_", "").strip())
    except ValueError:
        return await c.answer("خطأ.", show_alert=True)
    await state.set_state(AdminStates.report_reply_to_reporter)
    await state.update_data(admin_report_id=report_id, admin_report_outcome="completed")
    await c.message.edit_text(
        "✅ **تم إكمال التبليغ**\n\nأرسل الآن **رسالتك للمبلّغ** (مثل: تم مراجعة تبليغك وتم حظره).\n\nيمكنك إرسال: نص، صورة، صوت، أو أي وسائط.\n\nلإلغاء اضغط **رجوع**.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="admin_back")]
        ]),
        parse_mode="Markdown"
    )
    await c.answer()


@router.callback_query(F.data.startswith("admin_report_reject_"))
async def admin_report_reject_ask(c: types.CallbackQuery, state: FSMContext):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    try:
        report_id = int(c.data.replace("admin_report_reject_", "").strip())
    except ValueError:
        return await c.answer("خطأ.", show_alert=True)
    await state.set_state(AdminStates.report_reply_to_reporter)
    await state.update_data(admin_report_id=report_id, admin_report_outcome="rejected")
    await c.message.edit_text(
        "❌ **مرفوض**\n\nأرسل الآن **رسالتك للمبلّغ** (مثل: تم مراجعة تبليغك - التبليغ مرفوض).\n\nيمكنك إرسال: نص، صورة، صوت، أو أي وسائط.\n\nلإلغاء اضغط **رجوع**.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="admin_back")]
        ]),
        parse_mode="Markdown"
    )
    await c.answer()


@router.callback_query(F.data.startswith("admin_report_prev_"))
async def admin_report_prev(c: types.CallbackQuery):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    try:
        report_id = int(c.data.replace("admin_report_prev_", "").strip())
    except ValueError:
        return await c.answer()
    prev = db_query("SELECT id FROM reports WHERE id < %s ORDER BY id DESC LIMIT 1", (report_id,))
    if not prev:
        return await c.answer("لا يوجد تبليغ سابق.", show_alert=True)
    c.data = f"admin_report_view_{prev[0]['id']}"
    await admin_report_view(c)


@router.callback_query(F.data.startswith("admin_report_next_"))
async def admin_report_next(c: types.CallbackQuery):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    try:
        report_id = int(c.data.replace("admin_report_next_", "").strip())
    except ValueError:
        return await c.answer()
    nxt = db_query("SELECT id FROM reports WHERE id > %s ORDER BY id ASC LIMIT 1", (report_id,))
    if not nxt:
        return await c.answer("لا يوجد تبليغ تالي.", show_alert=True)
    c.data = f"admin_report_view_{nxt[0]['id']}"
    await admin_report_view(c)


# --- قائمة اللاعبين مع ترقيم (التالي / السابق) ---
PLAYERS_PAGE_SIZE = 15

def _admin_players_query(offset: int = 0, limit: int = PLAYERS_PAGE_SIZE):
    return db_query(
        """SELECT user_id, player_name, username_key, username, COALESCE(online_points, 0) AS online_points
           FROM users WHERE user_id IS NOT NULL ORDER BY user_id DESC LIMIT %s OFFSET %s""",
        (limit, offset)
    )

def _admin_players_count():
    r = db_query("SELECT COUNT(*) AS c FROM users WHERE user_id IS NOT NULL")
    return r[0]["c"] if r else 0


@router.callback_query(F.data == "admin_players")
async def admin_players_list(c: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await _admin_players_list_page(c, 0)


@router.callback_query(F.data.startswith("admin_players_page_"))
async def admin_players_page(c: types.CallbackQuery, state: FSMContext):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    await state.clear()
    try:
        page = int(c.data.replace("admin_players_page_", "").strip())
    except ValueError:
        page = 0
    await _admin_players_list_page(c, page)


async def _admin_players_list_page(c: types.CallbackQuery, page: int):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    offset = page * PLAYERS_PAGE_SIZE
    try:
        rows = _admin_players_query(offset=offset, limit=PLAYERS_PAGE_SIZE)
        total_count = _admin_players_count()
    except Exception:
        rows = []
        total_count = 0
    kb_rows = []
    if not rows:
        text = "👥 لا يوجد لاعبون مسجلون."
    else:
        total_pages = (total_count + PLAYERS_PAGE_SIZE - 1) // PLAYERS_PAGE_SIZE if total_count else 0
        text = f"👥 اللاعبون (صفحة {page + 1}/{total_pages or 1}) — من {offset + 1} إلى {min(offset + PLAYERS_PAGE_SIZE, total_count)} من أصل {total_count}\n"
        text += "اضغط على لاعب للتعديل أو استخدم «بحث برسالة» وأرسل الايدي، اليوزر، الاسم، أو النقاط.\n\n"
        for r in rows:
            name = (r.get("player_name") or "—")[:20]
            uname = r.get("username_key") or "—"
            pts = r.get("online_points") or 0
            uid = r.get("user_id")
            text += f"• {name} | @{uname} | {pts} pts | ايدي: {uid}\n"
        kb_rows = [[InlineKeyboardButton(text=f"✏️ {r.get('player_name', r['user_id'])}", callback_data=f"admin_view_{r['user_id']}")] for r in rows[:15]]
        if page > 0:
            kb_rows.append([InlineKeyboardButton(text="◀️ السابق", callback_data=f"admin_players_page_{page - 1}")])
        if offset + len(rows) < total_count:
            kb_rows.append([InlineKeyboardButton(text="▶️ التالي", callback_data=f"admin_players_page_{page + 1}")])
    kb_rows.append([InlineKeyboardButton(text="🔍 بحث برسالة (ايدي / يوزر / اسم / نقاط)", callback_data="admin_search_ask")])
    kb_rows.append([InlineKeyboardButton(text="🔙 رجوع", callback_data="admin_back")])
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await c.answer()


@router.callback_query(F.data == "admin_search_ask")
async def admin_search_ask(c: types.CallbackQuery, state: FSMContext):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    await state.set_state(AdminStates.edit_user_target)
    await state.update_data(admin_action="search")
    await c.message.edit_text(
        "🔍 أرسل أي من التالي للبحث:\n"
        "• رقم الايدي (user_id)\n"
        "• يوزر البوت (بدون @)\n"
        "• يوزر التليجرام (بدون @)\n"
        "• اسم اللاعب (باللعبة)\n"
        "• عدد النقاط (رقم)\n\nلإلغاء اضغط **رجوع**."
    )
    await c.answer()


@router.message(AdminStates.edit_user_target, F.text)
async def admin_search_or_edit_target(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text and message.text.strip().lower() == "/cancel":
        await state.clear()
        await message.answer("تم الإلغاء.")
        await _send_admin_menu(message, message.from_user.id)
        return
    raw = (message.text or "").strip().replace("@", "").strip()
    if not raw:
        return await message.answer("❌ أرسل نصاً للبحث.")
    user = None
    try:
        if raw.isdigit():
            uid_val = int(raw)
            user = db_query("SELECT * FROM users WHERE user_id = %s", (uid_val,))
            if not user:
                user = db_query("SELECT * FROM users WHERE online_points = %s LIMIT 1", (uid_val,))
        else:
            q = (
                "SELECT * FROM users WHERE user_id IS NOT NULL AND ("
                "LOWER(COALESCE(username_key,'')) = %s OR LOWER(COALESCE(username,'')) = %s OR "
                "LOWER(COALESCE(player_name,'')) LIKE %s"
                ") LIMIT 5"
            )
            pattern = f"%{raw.lower()}%"
            user = db_query(q, (raw.lower(), raw.lower(), pattern))
        if not user:
            return await message.answer("❌ لا يوجد لاعب يطابق البحث.")
        if len(user) > 1:
            msg = "🔍 أكثر من نتيجة. اختر بالضغط على زر:\n\n"
            kb = []
            for u in user[:10]:
                name = (u.get("player_name") or u.get("user_id"))[:25]
                kb.append([InlineKeyboardButton(text=f"👤 {name}", callback_data=f"admin_view_{u['user_id']}")])
            kb.append([InlineKeyboardButton(text="🔙 إلغاء", callback_data="admin_players")])
            await state.clear()
            await message.answer(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
            return
        user = user[0]
    except Exception as e:
        return await message.answer(f"❌ خطأ في البحث: {e}")
    await state.clear()
    await _send_admin_user_detail(message.bot, message.chat.id, user, message.from_user.id)


def _esc(s):
    if s is None:
        return "—"
    return html.escape(str(s))


def _user_detail_text(u: dict) -> str:
    uid = u.get("user_id")
    name = _esc(u.get("player_name") or "—")
    tg_username = (u.get("username") or "").strip() or "—"
    if tg_username != "—":
        tg_username = "@" + _esc(tg_username)
    else:
        tg_username = "—"
    uname = _esc(u.get("username_key") or "—")
    pwd = _esc(u.get("password_key") or u.get("password") or "—")
    pts = u.get("online_points", 0)
    reg = u.get("is_registered")
    lang = _esc(u.get("language") or "ar")
    banned = u.get("is_banned") in (True, 1, "t", "true")
    ban_line = "\n🚫 <b>محظور:</b> نعم" if banned else "\n🚫 <b>محظور:</b> لا"
    # رابط tg://user?id= يفتح محادثة اللاعب حتى بدون يوزرنيم (نص الرابط ليس أرقاماً فقط لئلا يفسّره تيليجرام كرقم هاتف)
    open_chat_link = f'<a href="tg://user?id={uid}">🔗 اضغط هنا لفتح محادثة اللاعب</a>'
    return (
        "👤 معلومات اللاعب\n\n"
        f"🆔 الايدي: {uid}\n"
        f"{open_chat_link}\n"
        f"📱 يوزر تليجرام: {tg_username}\n"
        f"📛 الاسم: {name}\n"
        f"👤 يوزر البوت: @{uname}\n"
        f"🔑 كلمة السر: {pwd}\n"
        f"⭐ النقاط: {pts}\n"
        f"✅ مسجل: {reg}\n"
        f"🌐 اللغة: {lang}"
        f"{ban_line}"
    )


def _admin_user_detail_kb(uid: int, is_banned: bool = False):
    rows = [
        [InlineKeyboardButton(text="💬 طلب دردشة", callback_data=f"admin_chat_request_{uid}")],
        [InlineKeyboardButton(text="📉 من يتابع (قائمة)", callback_data=f"admin_list_following_{uid}")],
        [InlineKeyboardButton(text="📈 من يتابعونه (قائمة)", callback_data=f"admin_list_followers_{uid}")],
        [InlineKeyboardButton(text="✏️ تعديل الاسم", callback_data=f"admin_ef_name_{uid}")],
        [InlineKeyboardButton(text="✏️ تعديل اليوزر نيم", callback_data=f"admin_ef_username_{uid}")],
        [InlineKeyboardButton(text="✏️ تعديل كلمة السر", callback_data=f"admin_ef_password_{uid}")],
        [InlineKeyboardButton(text="✏️ تعديل النقاط", callback_data=f"admin_ef_points_{uid}")],
        [InlineKeyboardButton(text="🔓 إصلاح الدخول", callback_data=f"admin_fix_login_{uid}")],
    ]
    if is_banned:
        rows.append([InlineKeyboardButton(text="✅ إلغاء حظر اللاعب", callback_data=f"admin_unban_{uid}")])
    else:
        rows.append([InlineKeyboardButton(text="🚫 حظر اللاعب", callback_data=f"admin_ban_{uid}")])
    rows.append([InlineKeyboardButton(text="🔙 رجوع للقائمة", callback_data="admin_players")])
    return rows


async def _send_admin_user_detail(bot, chat_id: int, user: dict, admin_uid: int):
    uid = user.get("user_id")
    is_banned = user.get("is_banned") in (True, 1, "t", "true")
    followers = db_query("SELECT COUNT(*) AS c FROM follows WHERE following_id = %s", (uid,))
    following = db_query("SELECT COUNT(*) AS c FROM follows WHERE follower_id = %s", (uid,))
    fc = followers[0]["c"] if followers else 0
    ing = following[0]["c"] if following else 0
    text = _user_detail_text(user) + f"\n\n📈 يتابعونه: {fc} | 📉 يتابع: {ing}"
    await bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=_admin_user_detail_kb(uid, is_banned)), parse_mode="HTML")


async def _edit_admin_user_detail(message, user: dict, admin_uid: int):
    uid = user.get("user_id")
    is_banned = user.get("is_banned") in (True, 1, "t", "true")
    followers = db_query("SELECT COUNT(*) AS c FROM follows WHERE following_id = %s", (uid,))
    following = db_query("SELECT COUNT(*) AS c FROM follows WHERE follower_id = %s", (uid,))
    fc = followers[0]["c"] if followers else 0
    ing = following[0]["c"] if following else 0
    text = _user_detail_text(user) + f"\n\n📈 يتابعونه: {fc} | 📉 يتابع: {ing}"
    await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=_admin_user_detail_kb(uid, is_banned)), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_list_following_"))
async def admin_list_following(c: types.CallbackQuery):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    try:
        uid = int(c.data.replace("admin_list_following_", ""))
    except ValueError:
        return await c.answer("خطأ.", show_alert=True)
    rows = db_query(
        """SELECT u.user_id, u.player_name FROM follows f
           JOIN users u ON f.following_id = u.user_id WHERE f.follower_id = %s ORDER BY u.player_name""",
        (uid,)
    )
    if not rows:
        return await c.answer("هذا اللاعب لا يتابع أحداً.", show_alert=True)
    text = f"📉 **من يتابع (اللاعب ايدي {uid}):**\nاضغط على شخص لإزالته من متابعات هذا اللاعب.\n\n"
    kb = []
    for r in rows[:20]:
        name = (r.get("player_name") or r["user_id"])[:20]
        kb.append([InlineKeyboardButton(text=f"❌ إزالة متابعة: {name}", callback_data=f"admin_rm_follow_{uid}_{r['user_id']}")])
    kb.append([InlineKeyboardButton(text="🔙 رجوع للاعب", callback_data=f"admin_view_{uid}")])
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    await c.answer()


@router.callback_query(F.data.startswith("admin_list_followers_"))
async def admin_list_followers(c: types.CallbackQuery):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    try:
        uid = int(c.data.replace("admin_list_followers_", ""))
    except ValueError:
        return await c.answer("خطأ.", show_alert=True)
    rows = db_query(
        """SELECT u.user_id, u.player_name FROM follows f
           JOIN users u ON f.follower_id = u.user_id WHERE f.following_id = %s ORDER BY u.player_name""",
        (uid,)
    )
    if not rows:
        return await c.answer("لا يتابعه أحد.", show_alert=True)
    text = f"📈 **من يتابعونه (اللاعب ايدي {uid}):**\nاضغط على شخص لإزالته من متابعي هذا اللاعب.\n\n"
    kb = []
    for r in rows[:20]:
        name = (r.get("player_name") or r["user_id"])[:20]
        kb.append([InlineKeyboardButton(text=f"❌ إزالة متابعة: {name}", callback_data=f"admin_rm_follower_{uid}_{r['user_id']}")])
    kb.append([InlineKeyboardButton(text="🔙 رجوع للاعب", callback_data=f"admin_view_{uid}")])
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    await c.answer()


@router.callback_query(F.data.startswith("admin_rm_follow_"))
async def admin_remove_follow(c: types.CallbackQuery):
    """إزالة متابعة: اللاعب (الأول) كان يتابع (الثاني) — نحذف العلاقة."""
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    parts = c.data.split("_")
    if len(parts) < 5:
        return await c.answer("خطأ.", show_alert=True)
    follower_uid = int(parts[3])
    following_uid = int(parts[4])
    db_query("DELETE FROM follows WHERE follower_id = %s AND following_id = %s", (follower_uid, following_uid), commit=True)
    await c.answer("✅ تمت إزالة المتابعة.", show_alert=True)
    user = db_query("SELECT * FROM users WHERE user_id = %s", (follower_uid,))
    if user:
        await _edit_admin_user_detail(c.message, user[0], c.from_user.id)
    else:
        await c.message.edit_text("✅ تمت إزالة المتابعة.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 قائمة اللاعبين", callback_data="admin_players")]
        ]))


@router.callback_query(F.data.startswith("admin_rm_follower_"))
async def admin_remove_follower(c: types.CallbackQuery):
    """إزالة متابع: اللاعب (الأول) كان يتابعه (الثاني) — نحذف العلاقة."""
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    parts = c.data.split("_")
    if len(parts) < 5:
        return await c.answer("خطأ.", show_alert=True)
    following_uid = int(parts[3])
    follower_uid = int(parts[4])
    db_query("DELETE FROM follows WHERE follower_id = %s AND following_id = %s", (follower_uid, following_uid), commit=True)
    await c.answer("✅ تمت إزالة المتابعة.", show_alert=True)
    user = db_query("SELECT * FROM users WHERE user_id = %s", (following_uid,))
    if user:
        await _edit_admin_user_detail(c.message, user[0], c.from_user.id)
    else:
        await c.message.edit_text("✅ تمت إزالة المتابعة.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 قائمة اللاعبين", callback_data="admin_players")]
        ]))


@router.callback_query(F.data.startswith("admin_view_"))
async def admin_view_user(c: types.CallbackQuery, state: FSMContext):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    await state.clear()
    try:
        uid = int(c.data.replace("admin_view_", ""))
        user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
        if not user:
            return await c.answer("❌ اللاعب غير موجود.", show_alert=True)
        u = user[0]
        is_banned = u.get("is_banned") in (True, 1, "t", "true")
        followers = db_query("SELECT COUNT(*) AS c FROM follows WHERE following_id = %s", (uid,))
        following = db_query("SELECT COUNT(*) AS c FROM follows WHERE follower_id = %s", (uid,))
        fc = followers[0]["c"] if followers else 0
        ing = following[0]["c"] if following else 0
        text = _user_detail_text(u) + f"\n\n📈 يتابعونه: {fc} | 📉 يتابع: {ing}"
        kb = _admin_user_detail_kb(uid, is_banned)
        await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except Exception as e:
        await c.answer(f"خطأ: {e}", show_alert=True)
    await c.answer()


@router.callback_query(F.data.startswith("admin_ban_"))
async def admin_ban_user(c: types.CallbackQuery):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    try:
        uid = int(c.data.replace("admin_ban_", "").strip())
    except ValueError:
        return await c.answer("خطأ.", show_alert=True)
    try:
        db_query("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE", commit=True)
    except Exception:
        try:
            db_query("ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT FALSE", commit=True)
        except Exception:
            pass
    db_query("UPDATE users SET is_banned = TRUE WHERE user_id = %s", (uid,), commit=True)
    await c.answer("✅ تم حظر اللاعب.", show_alert=True)
    user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    if user:
        await _edit_admin_user_detail(c.message, user[0], c.from_user.id)


@router.callback_query(F.data.startswith("admin_unban_"))
async def admin_unban_user(c: types.CallbackQuery):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    try:
        uid = int(c.data.replace("admin_unban_", "").strip())
    except ValueError:
        return await c.answer("خطأ.", show_alert=True)
    db_query("UPDATE users SET is_banned = FALSE WHERE user_id = %s", (uid,), commit=True)
    await c.answer("✅ تم إلغاء حظر اللاعب.", show_alert=True)
    user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    if user:
        await _edit_admin_user_detail(c.message, user[0], c.from_user.id)


@router.callback_query(F.data.startswith("admin_fix_login_"))
async def admin_fix_login(c: types.CallbackQuery):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    try:
        uid = int(c.data.replace("admin_fix_login_", ""))
    except ValueError:
        return await c.answer("خطأ في الايدي.", show_alert=True)
    try:
        db_query("UPDATE users SET logged_out = FALSE WHERE user_id = %s", (uid,), commit=True)
    except Exception:
        pass
    await c.answer("✅ تم إصلاح الدخول.", show_alert=True)
    user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    if user:
        u = user[0]
        is_banned = u.get("is_banned") in (True, 1, "t", "true")
        followers = db_query("SELECT COUNT(*) AS c FROM follows WHERE following_id = %s", (uid,))
        following = db_query("SELECT COUNT(*) AS c FROM follows WHERE follower_id = %s", (uid,))
        fc = followers[0]["c"] if followers else 0
        ing = following[0]["c"] if following else 0
        text = _user_detail_text(u) + f"\n\n📈 يتابعونه: {fc} | 📉 يتابع: {ing}"
        kb = _admin_user_detail_kb(uid, is_banned)
        await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_ef_name_"))
@router.callback_query(F.data.startswith("admin_ef_username_"))
@router.callback_query(F.data.startswith("admin_ef_password_"))
@router.callback_query(F.data.startswith("admin_ef_points_"))
async def admin_edit_field_ask(c: types.CallbackQuery, state: FSMContext):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    parts = c.data.split("_")
    if len(parts) < 4:
        return await c.answer()
    field = parts[2]
    try:
        target_uid = int(parts[3])
    except ValueError:
        return await c.answer("خطأ في الايدي.", show_alert=True)
    await state.set_state(AdminStates.edit_user_value)
    await state.update_data(admin_edit_uid=target_uid, admin_edit_field=field)
    prompts = {
        "name": "أرسل الاسم الجديد للاعب:",
        "username": "أرسل اليوزر نيم الجديد (بدون @):",
        "password": "أرسل كلمة السر الجديدة:",
        "points": "أرسل عدد النقاط (رقم صحيح):",
    }
    await c.message.edit_text(prompts.get(field, "أرسل القيمة الجديدة:") + "\n\nلإلغاء اضغط **رجوع**.")
    await c.answer()


@router.message(AdminStates.edit_user_value, F.text)
async def admin_edit_value_done(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text and message.text.strip().lower() == "/cancel":
        await state.clear()
        await message.answer("تم الإلغاء.")
        await _send_admin_menu(message, message.from_user.id)
        return
    data = await state.get_data()
    target_uid = data.get("admin_edit_uid")
    field = data.get("admin_edit_field")
    value = (message.text or "").strip()
    if not value:
        return await message.answer("القيمة فارغة. أعد المحاولة أو اضغط رجوع.")
    try:
        if field == "name":
            db_query("UPDATE users SET player_name = %s WHERE user_id = %s", (value[:100], target_uid), commit=True)
        elif field == "username":
            db_query("UPDATE users SET username_key = %s WHERE user_id = %s", (value.lower()[:50], target_uid), commit=True)
        elif field == "password":
            db_query("UPDATE users SET password_key = %s WHERE user_id = %s", (value[:100], target_uid), commit=True)
        elif field == "points":
            pts = int(value)
            db_query("UPDATE users SET online_points = %s WHERE user_id = %s", (pts, target_uid), commit=True)
        else:
            await message.answer("حقل غير مدعوم.")
            await state.clear()
            return
    except ValueError:
        await message.answer("❌ النقاط يجب أن تكون رقماً صحيحاً.")
        return
    except Exception as e:
        await message.answer(f"❌ خطأ: {e}")
        await state.clear()
        return
    await state.clear()
    kb_back = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 رجوع لقائمة اللاعبين", callback_data="admin_players")]
    ])
    await message.answer(f"✅ تم تحديث الحقل للاعب {target_uid}.", reply_markup=kb_back)


# --- الغرف المفتوحة والمتروكة ---
@router.callback_query(F.data == "admin_rooms")
async def admin_rooms_list(c: types.CallbackQuery, skip_answer: bool = False):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    try:
        rooms = db_query("""
            SELECT r.room_id, r.creator_id, r.status, r.max_players, r.score_limit,
            (SELECT COUNT(*) FROM room_players rp WHERE rp.room_id = r.room_id) AS p_count,
            u.player_name AS creator_name, u.username_key AS creator_username
            FROM rooms r
            LEFT JOIN users u ON u.user_id = r.creator_id
            WHERE r.status IN ('waiting', 'playing')
            ORDER BY r.room_id
            LIMIT 50
        """)
    except Exception:
        rooms = []
    if not rooms:
        text = "🛏 لا توجد غرف مفتوحة حالياً."
        kb = [[InlineKeyboardButton(text="🔙 رجوع", callback_data="admin_back")]]
    else:
        text = "🛏 الغرف المفتوحة\n(اضغط على غرفة لإغلاقها)\n\n"
        for r in rooms[:20]:
            name = (r.get("creator_name") or "—")[:15]
            uname = r.get("creator_username") or "—"
            cid = r.get("creator_id") or "—"
            code = r.get("room_id", "")
            cnt = r.get("p_count") or 0
            mx = r.get("max_players") or 0
            st = r.get("status") or ""
            text += f"👤 الاسم: {name}\n   يوزر البوت: @{uname} | الايدي: {cid}\n   غرفة: {code} | {cnt}/{mx} | {st}\n\n"
        kb = []
        for r in rooms[:15]:
            kb.append([InlineKeyboardButton(text=f"🚪 إغلاق {r['room_id']}", callback_data=f"admin_closeroom_{r['room_id']}")])
        kb.append([InlineKeyboardButton(text="🗑 إغلاق كل الغرف", callback_data="admin_closeallrooms")])
        kb.append([InlineKeyboardButton(text="⏳ إغلاق المتروكة (>24 ساعة)", callback_data="admin_closeabandoned")])
        kb.append([InlineKeyboardButton(text="🔙 رجوع", callback_data="admin_back")])
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    if not skip_answer:
        await c.answer()


@router.callback_query(F.data.startswith("admin_closeroom_"))
async def admin_close_one_room(c: types.CallbackQuery):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    room_id = c.data.replace("admin_closeroom_", "").strip()
    try:
        db_query("DELETE FROM room_players WHERE room_id = %s", (room_id,), commit=True)
        db_query("DELETE FROM rooms WHERE room_id = %s", (room_id,), commit=True)
        await c.answer(f"✅ تم إغلاق الغرفة {room_id}.", show_alert=True)
    except Exception as e:
        await c.answer(f"خطأ: {e}", show_alert=True)
    await admin_rooms_list(c, skip_answer=True)


@router.callback_query(F.data == "admin_closeallrooms")
async def admin_close_all_rooms(c: types.CallbackQuery):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    try:
        rooms = db_query("SELECT room_id FROM rooms WHERE status IN ('waiting', 'playing')")
        count = 0
        for r in (rooms or []):
            rid = r.get("room_id")
            db_query("DELETE FROM room_players WHERE room_id = %s", (rid,), commit=True)
            db_query("DELETE FROM rooms WHERE room_id = %s", (rid,), commit=True)
            count += 1
        await c.answer(f"✅ تم إغلاق {count} غرفة.", show_alert=True)
    except Exception as e:
        await c.answer(f"خطأ: {e}", show_alert=True)
    await admin_rooms_list(c, skip_answer=True)


@router.callback_query(F.data == "admin_closeabandoned")
async def admin_close_abandoned(c: types.CallbackQuery):
    if not _admin_only(c):
        return await c.answer("⛔ غير مسموح.", show_alert=True)
    try:
        rooms = db_query("""
            SELECT room_id FROM rooms
            WHERE status IN ('waiting', 'playing')
            AND created_at < NOW() - INTERVAL '24 hours'
        """)
    except Exception:
        try:
            rooms = db_query("""
                SELECT room_id FROM rooms
                WHERE status IN ('waiting', 'playing')
                AND created_at < DATE_SUB(NOW(), INTERVAL 24 HOUR)
            """)
        except Exception:
            await c.answer("⚠️ أضف عمود created_at لجدول rooms لتفعيل إغلاق المتروكة.", show_alert=True)
            return
    if not rooms:
        await c.answer("لا توجد غرف متروكة أكثر من 24 ساعة.", show_alert=True)
        await admin_rooms_list(c, skip_answer=True)
        return
    count = 0
    for r in rooms:
        rid = r.get("room_id")
        db_query("DELETE FROM room_players WHERE room_id = %s", (rid,), commit=True)
        db_query("DELETE FROM rooms WHERE room_id = %s", (rid,), commit=True)
        count += 1
    await c.answer(f"✅ تم إغلاق {count} غرفة متروكة.", show_alert=True)
    await admin_rooms_list(c, skip_answer=True)
