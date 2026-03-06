# -*- coding: utf-8 -*-
"""
مجتمع الأونو والنشر في القناة: نشر منشور، نشر فوزك، منشوراتي، لايك، إلخ.
مستقل عن common.py لتنظيم الكود.
"""
import os
import re
import json
import time
import logging
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import BaseFilter

from database import db_query

# استيراد من common (يُبقى _channel_post_buttons و الثوابت في common لاستخدامها في /start أيضاً)
from handlers.common import (
    replay_data,
    _get_replay_from_db,
    generate_room_code,
    PUBLISH_CHANNEL_ID,
    PUBLISH_CHANNEL_USERNAME,
    BOT_USERNAME,
    _channel_post_buttons,
)

logger = logging.getLogger(__name__)
router = Router(name="community_publish")


class PlayerPostStates(StatesGroup):
    waiting_options = State()
    waiting_message = State()


# قائمة انتظار النشر: في الذاكرة فقط
_pending_post: dict = {}
_PENDING_POST_TIMEOUT = 600  # 10 دقائق

# آخر مرة فتح فيها المستخدم «نشر منشور» (للمعالجة إن فُقدت الحالة)
_last_post_options_at: dict = {}
_LAST_POST_OPTIONS_WINDOW = 300  # 5 دقائق


def _get_pending_post(uid: int):
    if uid in _pending_post:
        t = _pending_post[uid].get("at", 0)
        if time.time() - t <= _PENDING_POST_TIMEOUT:
            return _pending_post[uid]
        _pending_post.pop(uid, None)
    return None


def _get_and_clear_pending_post(uid: int):
    opts = _pending_post.pop(uid, None)
    if opts and (time.time() - opts.get("at", 0)) <= _PENDING_POST_TIMEOUT:
        return opts
    return None


def _banned_words_path():
    for base in (os.path.dirname(os.path.abspath(__file__)), os.getcwd()):
        p = os.path.join(base, "banned_words.txt")
        if os.path.isfile(p):
            return p
        p = os.path.join(os.path.dirname(base), "banned_words.txt")
        if os.path.isfile(p):
            return p
    return None


_banned_words_cache = None


def _load_banned_words():
    global _banned_words_cache
    if _banned_words_cache is not None:
        return _banned_words_cache
    path = _banned_words_path()
    if not path:
        _banned_words_cache = []
        return _banned_words_cache
    try:
        with open(path, "r", encoding="utf-8") as f:
            words = [ln.strip().lower() for ln in f if ln.strip() and not ln.strip().startswith("#")]
        _banned_words_cache = words
    except Exception:
        _banned_words_cache = []
    return _banned_words_cache


def _contains_phone(text):
    if not text or not text.strip():
        return False
    digits_only = re.sub(r"\D", " ", text)
    if re.search(r"\d{10,11}", digits_only):
        return True
    if re.search(r"07[789]", text):
        return True
    return False


def check_post_content(text):
    if not text or not str(text).strip():
        return False, "الرسالة فارغة."
    text_lower = (text if isinstance(text, str) else getattr(text, "text", "") or "").strip().lower()
    words = _load_banned_words()
    for w in words:
        if w and w in text_lower:
            return False, "رسالتك تنتهك معاييرنا."
    if _contains_phone(text):
        return False, "رسالتك تنتهك معاييرنا (لا يُسمح بنشر أرقام هواتف)."
    return True, None


def _has_pending_post(message: types.Message) -> bool:
    uid = message.from_user.id if message.from_user else None
    if not uid:
        return False
    return _get_pending_post(uid) is not None


@router.message(F.text, _has_pending_post)
async def player_post_receive_text_pending(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    logger.info("player_post_receive_text_pending: processing uid=%s", uid)
    opts = _get_and_clear_pending_post(uid)
    if not opts:
        return
    await state.clear()
    add_profile = opts.get("add_profile", True)
    add_play = opts.get("add_play", False)
    chat_target = _normalize_channel_target()
    if not chat_target:
        await message.answer("⚠️ نشر المنشورات غير متاح حالياً.\n\nتحقق من إعدادات القناة في handlers/channel_config.py.")
        return
    text = (message.text or "").strip()
    ok, reason = check_post_content(text)
    if not ok:
        await message.answer(f"⛔ {reason}")
        return
    name = _get_player_name_for_post(uid, message.from_user.full_name)
    text_to_send = f"👤 **{name}**\n\n{text}"
    join_code = None
    if add_play:
        try:
            join_code = _create_deferred_2p_room(uid, name)
        except Exception as e:
            logger.warning("player_post: create_room: %s", e)
    reply_kb = _channel_post_buttons(uid, add_profile, join_code)
    if (add_profile or join_code) and not reply_kb:
        await message.answer("⚠️ تم ضبط الخيارات لكن **BOT_USERNAME** غير مضبوط. اضبطه ثم أعد المحاولة.")
        return
    sent_msg_id = None
    logger.info("player_post: sending text to channel chat_id=%s (pending)", chat_target)
    try:
        sent = await message.bot.send_message(chat_id=chat_target, text=text_to_send, parse_mode="Markdown", reply_markup=reply_kb)
        sent_msg_id = sent.message_id
    except Exception as e:
        logger.exception("player_post: send_message failed: %s", e)
        try:
            sent = await message.bot.send_message(chat_id=chat_target, text=text_to_send, parse_mode="Markdown")
            sent_msg_id = sent.message_id
        except Exception as e2:
            logger.exception("player_post: send without buttons failed: %s", e2)
            await message.answer("❌ فشل النشر. تأكد أن البوت مسؤول في القناة وله صلاحية «نشر رسائل». الخطأ: " + str(e2)[:150])
            return
    if sent_msg_id is not None:
        try:
            row = db_query(
                "INSERT INTO channel_posts (channel_id, message_id, publisher_uid, add_profile, join_code) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (str(chat_target), sent_msg_id, uid, bool(add_profile), join_code), commit=True
            )
            if row:
                post_id = row[0].get("id")
                new_kb = _channel_post_buttons(uid, add_profile, join_code, post_id=post_id, likes_count=0)
                if new_kb:
                    await message.bot.edit_message_reply_markup(chat_id=chat_target, message_id=sent_msg_id, reply_markup=new_kb)
        except Exception as e:
            logger.exception("player_post: save_post: %s", e)
    kb_after = []
    if PUBLISH_CHANNEL_USERNAME:
        kb_after.append([InlineKeyboardButton(text="📢 الذهاب للقناة", url=f"https://t.me/{PUBLISH_CHANNEL_USERNAME.lstrip('@')}")])
    kb_after.append([InlineKeyboardButton(text="🔙 رجوع للقائمة الرئيسية", callback_data="home")])
    await message.answer("✅ تم نشر منشورك في القناة.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_after))


@router.message(F.photo | F.voice | F.video | F.animation | F.sticker | F.document | F.audio | F.video_note, _has_pending_post)
async def player_post_receive_media_pending(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    opts = _get_and_clear_pending_post(uid)
    if not opts:
        return
    await state.clear()
    add_profile = opts.get("add_profile", True)
    add_play = opts.get("add_play", False)
    chat_target = _normalize_channel_target()
    if not chat_target:
        await message.answer("⚠️ نشر المنشورات غير متاح حالياً.")
        return
    caption_text = (message.caption or "").strip()
    if caption_text:
        ok, reason = check_post_content(caption_text)
        if not ok:
            await message.answer(f"⛔ {reason}")
            return
    name = _get_player_name_for_post(uid, message.from_user.full_name)
    join_code = None
    if add_play:
        try:
            join_code = _create_deferred_2p_room(uid, name)
        except Exception:
            pass
    reply_kb = _channel_post_buttons(uid, add_profile, join_code)
    ok, sent_msg_id, err = await _publish_media_to_channel(message.bot, message, name, reply_markup=reply_kb)
    if not ok and reply_kb:
        ok, sent_msg_id, err = await _publish_media_to_channel(message.bot, message, name, reply_markup=None)
    if ok and sent_msg_id is not None:
        try:
            row = db_query(
                "INSERT INTO channel_posts (channel_id, message_id, publisher_uid, add_profile, join_code) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (str(chat_target), sent_msg_id, uid, bool(add_profile), join_code), commit=True
            )
            if row:
                post_id = row[0].get("id")
                new_kb = _channel_post_buttons(uid, add_profile, join_code, post_id=post_id, likes_count=0)
                if new_kb:
                    await message.bot.edit_message_reply_markup(chat_id=chat_target, message_id=sent_msg_id, reply_markup=new_kb)
        except Exception as e:
            logger.exception("player_post: save_post media: %s", e)
    if ok:
        kb_after = []
        if PUBLISH_CHANNEL_USERNAME:
            kb_after.append([InlineKeyboardButton(text="📢 الذهاب للقناة", url=f"https://t.me/{PUBLISH_CHANNEL_USERNAME.lstrip('@')}")])
        kb_after.append([InlineKeyboardButton(text="🔙 رجوع للقائمة الرئيسية", callback_data="home")])
        await message.answer("✅ تم نشر منشورك في القناة.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_after))
    else:
        msg = "❌ فشل النشر. تأكد أن البوت مسؤول في القناة وله صلاحية «نشر رسائل»."
        if err:
            msg += f"\n\nالخطأ: {err}"
        await message.answer(msg)


def _get_player_name_for_post(user_id: int, full_name: str = None) -> str:
    name = "لاعب"
    try:
        row = db_query("SELECT player_name FROM users WHERE user_id = %s", (user_id,))
        if row:
            name = row[0].get("player_name") or full_name or name
    except Exception:
        name = full_name or name
    return name


def _normalize_channel_target():
    """يرجع معرف القناة للنشر (رقم سالب أو @username). يدعم القيم النصية من متغيرات البيئة."""
    raw = PUBLISH_CHANNEL_ID
    if raw is not None:
        try:
            s = str(raw).strip().strip('"').strip("'")
            if s:
                ch = int(s)
                if ch > 0:
                    ch = -ch
                return ch
        except (TypeError, ValueError):
            pass
    un = (PUBLISH_CHANNEL_USERNAME or "").strip().strip('"').strip("'").lstrip("@")
    if un:
        return f"@{un}"
    return None


async def _publish_media_to_channel(bot, message: types.Message, name: str, channel_id=None, reply_markup=None):
    ch = channel_id if channel_id is not None else _normalize_channel_target()
    if not ch:
        return False, None, "القناة غير مضبوطة (PUBLISH_CHANNEL_ID / USERNAME)"
    cap = f"👤 **{name}**\n\n{(message.caption or '').strip()}" if (message.caption or "").strip() else f"👤 **{name}**"
    if cap.endswith("\n\n"):
        cap = cap.rstrip()
    kwargs = {"parse_mode": "Markdown"}
    if reply_markup:
        kwargs["reply_markup"] = reply_markup
    try:
        if message.text:
            sent = await bot.send_message(ch, f"👤 **{name}**\n\n{message.text}", **kwargs)
            return True, sent.message_id, None
        if message.photo:
            sent = await bot.send_photo(ch, message.photo[-1].file_id, caption=cap, **kwargs)
            return True, sent.message_id, None
        if message.voice:
            sent = await bot.send_voice(ch, message.voice.file_id, caption=cap, **kwargs)
            return True, sent.message_id, None
        if message.video:
            sent = await bot.send_video(ch, message.video.file_id, caption=cap, **kwargs)
            return True, sent.message_id, None
        if message.animation:
            sent = await bot.send_animation(ch, message.animation.file_id, caption=cap, **kwargs)
            return True, sent.message_id, None
        if message.sticker:
            await bot.send_sticker(ch, message.sticker.file_id)
            sent = await bot.send_message(ch, f"👤 **{name}**", **kwargs)
            return True, sent.message_id, None
        if message.document:
            sent = await bot.send_document(ch, message.document.file_id, caption=cap, **kwargs)
            return True, sent.message_id, None
        if message.audio:
            sent = await bot.send_audio(ch, message.audio.file_id, caption=cap, **kwargs)
            return True, sent.message_id, None
        if message.video_note:
            await bot.send_video_note(ch, message.video_note.file_id)
            sent = await bot.send_message(ch, f"👤 **{name}**", **kwargs)
            return True, sent.message_id, None
    except Exception as e:
        logger.exception("player_post: _publish_media_to_channel failed for ch=%s: %s", ch, e)
        return False, None, str(e).replace("'", "").strip()[:220]
    return False, None, "نوع المحتوى غير مدعوم"


def _create_deferred_2p_room(creator_uid: int, creator_name: str) -> str:
    code = generate_room_code()
    db_query(
        "INSERT INTO rooms (room_id, creator_id, max_players, score_limit, status, is_random) VALUES (%s, %s, 2, 0, 'waiting', TRUE)",
        (code, creator_uid), commit=True
    )
    db_query(
        "INSERT INTO room_players (room_id, user_id, player_name, is_ready) VALUES (%s, %s, %s, TRUE)",
        (code, creator_uid, creator_name), commit=True
    )
    return code


# --- نشر فوزك ---
@router.callback_query(F.data.startswith("share_result_"))
async def share_result_to_channel(c: types.CallbackQuery, state: FSMContext):
    chat_target = _normalize_channel_target()
    if not chat_target or not BOT_USERNAME:
        logger.warning("share_result: skipped - chat_target=%s BOT_USERNAME=%s", chat_target, bool(BOT_USERNAME))
        return await c.answer("⚠️ نشر النتائج غير متاح حالياً. سيتم تفعيله من الإدارة لاحقاً.", show_alert=True)
    replay_id = c.data.replace("share_result_", "").strip()
    rdata = replay_data.get(replay_id)
    if not rdata:
        rdata = _get_replay_from_db(replay_id)
    if not rdata:
        return await c.answer("⚠️ انتهت صلاحية النشر. جرّب النشر مباشرة بعد انتهاء الجولة.", show_alert=True)
    winner_id = rdata.get("winner_id")
    if winner_id is not None:
        try:
            winner_id = int(winner_id)
        except (TypeError, ValueError):
            winner_id = None
    if not winner_id or winner_id != c.from_user.id:
        return await c.answer("⚠️ غير مصرح.", show_alert=True)
    await state.set_state(PlayerPostStates.waiting_options)
    await state.update_data(share_replay_id=replay_id, post_add_profile=True, post_add_play=False)
    await c.message.edit_text(
        "📢 **نشر فوزك**\n\nاختر ما تريد إضافته تحت المنشور، ثم أرسل رسالتك مباشرة (مثلاً: هل من متحدي؟).\n\n"
        "• **زر حسابي:** يظهر زر يفتح بروفايلك.\n"
        "• **العب معي:** يظهر زر ينضم من يضغطه معك في كيم ثنائي.\n\n"
        "⚠️ لا يُسمح بنشر أرقام هواتف أو كلمات تخالف المعايير.",
        reply_markup=_post_options_kb({"post_add_profile": True, "post_add_play": False}),
        parse_mode="Markdown"
    )
    await c.answer()


def _post_options_kb(data: dict) -> InlineKeyboardMarkup:
    add_p = data.get("post_add_profile", True)
    add_play = data.get("post_add_play", False)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"👤 زر حسابي {'✓' if add_p else ''}", callback_data="post_toggle_profile")],
        [InlineKeyboardButton(text=f"🎮 العب معي {'✓' if add_play else ''}", callback_data="post_toggle_play")],
        [InlineKeyboardButton(text="🔙 تراجع", callback_data="post_back")],
    ])


@router.callback_query(F.data == "player_post_start")
async def player_post_start(c: types.CallbackQuery, state: FSMContext):
    if not _normalize_channel_target():
        return await c.answer("⚠️ نشر المنشورات غير متاح حالياً.", show_alert=True)
    _last_post_options_at[c.from_user.id] = time.time()
    await state.set_state(PlayerPostStates.waiting_options)
    await state.update_data(post_add_profile=True, post_add_play=False)
    await c.message.edit_text(
        "📢 **نشر منشور**\n\nاختر ما تريد إضافته تحت منشورك، ثم أرسل **رسالة واحدة** (نص أو صورة أو ميديا) — سيُنشر فوراً في القناة.\n\n"
        "• **زر حسابي:** يظهر زر يفتح بروفايلك (متابعة، طلب لعب، رجوع للقناة).\n"
        "• **العب معي:** يظهر زر من يضغطه ينضم معك في كيم ثنائي فوراً.\n\n"
        "⚠️ لا يُسمح بنشر أرقام هواتف أو كلمات تخالف المعايير.\n\n"
        "_بعد إرسال الرسالة ستظهر لك «تم نشر منشورك» أو رسالة خطأ إن فشل النشر._",
        reply_markup=_post_options_kb({"post_add_profile": True, "post_add_play": False}),
        parse_mode="Markdown"
    )
    await c.answer()


@router.callback_query(F.data == "post_toggle_profile")
async def post_toggle_profile(c: types.CallbackQuery, state: FSMContext):
    if await state.get_state() != PlayerPostStates.waiting_options.state:
        return await c.answer()
    data = await state.get_data()
    data["post_add_profile"] = not data.get("post_add_profile", True)
    await state.update_data(**data)
    await c.message.edit_reply_markup(reply_markup=_post_options_kb(data))
    await c.answer()


@router.callback_query(F.data == "post_toggle_play")
async def post_toggle_play(c: types.CallbackQuery, state: FSMContext):
    if await state.get_state() != PlayerPostStates.waiting_options.state:
        return await c.answer()
    data = await state.get_data()
    data["post_add_play"] = not data.get("post_add_play", False)
    await state.update_data(**data)
    await c.message.edit_reply_markup(reply_markup=_post_options_kb(data))
    await c.answer()


@router.callback_query(F.data == "post_ready_send")
async def post_ready_send(c: types.CallbackQuery, state: FSMContext):
    if await state.get_state() != PlayerPostStates.waiting_options.state:
        return await c.answer()
    data = await state.get_data()
    add_profile = data.get("post_add_profile", True)
    add_play = data.get("post_add_play", False)
    uid = c.from_user.id
    _pending_post[uid] = {"add_profile": add_profile, "add_play": add_play, "at": time.time()}
    try:
        db_query(
            "INSERT INTO users (user_id, username, is_registered) VALUES (%s, %s, FALSE) ON CONFLICT (user_id) DO NOTHING",
            (uid, c.from_user.username or ""), commit=True
        )
    except Exception as e:
        logger.warning("post_ready_send: %s", e)
    await state.set_state(PlayerPostStates.waiting_message)
    await c.message.edit_text(
        "📢 أرسل الآن النص أو الصور أو الصوت أو الفيديو أو الملصقات أو أي ميديا للنشر في القناة.\n\n⚠️ لا يُسمح بنشر أرقام هواتف أو كلمات تخالف المعايير."
    )
    await c.answer()


@router.callback_query(F.data == "post_back")
async def post_back(c: types.CallbackQuery, state: FSMContext):
    await state.clear()
    rows = [
        [InlineKeyboardButton(text="📢 نشر منشور بالقناة", callback_data="player_post_start")],
    ]
    if PUBLISH_CHANNEL_USERNAME:
        rows.append([InlineKeyboardButton(text="📜 عرض القناة", url=f"https://t.me/{PUBLISH_CHANNEL_USERNAME.lstrip('@')}")])
    else:
        rows.append([InlineKeyboardButton(text="📜 عرض القناة", callback_data="player_posts_channel")])
    rows.append([InlineKeyboardButton(text="📋 منشوراتي", callback_data="my_posts_list")])
    rows.append([InlineKeyboardButton(text="🔙 رجوع", callback_data="home")])
    await c.message.edit_text(
        "👥 **مجتمع الأونو**\n\nاختر:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="Markdown"
    )
    await c.answer()


@router.callback_query(F.data == "community_uno_menu")
async def community_uno_menu(c: types.CallbackQuery):
    rows = [
        [InlineKeyboardButton(text="📢 نشر منشور بالقناة", callback_data="player_post_start")],
    ]
    if PUBLISH_CHANNEL_USERNAME:
        rows.append([InlineKeyboardButton(text="📜 عرض القناة", url=f"https://t.me/{PUBLISH_CHANNEL_USERNAME.lstrip('@')}")])
    else:
        rows.append([InlineKeyboardButton(text="📜 عرض القناة", callback_data="player_posts_channel")])
    rows.append([InlineKeyboardButton(text="📋 منشوراتي", callback_data="my_posts_list")])
    rows.append([InlineKeyboardButton(text="🔙 رجوع", callback_data="home")])
    await c.message.edit_text(
        "👥 **مجتمع الأونو**\n\nاختر:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="Markdown"
    )
    await c.answer()


@router.callback_query(F.data == "my_posts_list")
async def my_posts_list(c: types.CallbackQuery):
    uid = c.from_user.id
    try:
        posts = db_query(
            "SELECT id, message_id, created_at, likes_count, profile_clicks_count FROM channel_posts WHERE publisher_uid = %s ORDER BY created_at DESC LIMIT 30",
            (uid,)
        )
    except Exception:
        posts = []
    if not posts:
        await c.message.edit_text(
            "📋 **منشوراتي**\n\nلا توجد منشورات بعد. انشر منشوراً من مجتمع الأونو.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📢 نشر منشور", callback_data="player_post_start")],
                [InlineKeyboardButton(text="🔙 رجوع", callback_data="community_uno_menu")]
            ]),
            parse_mode="Markdown"
        )
        await c.answer()
        return
    lines = ["📋 **منشوراتي**\n"]
    for i, p in enumerate(posts, 1):
        created = p.get("created_at")
        when = created.strftime("%Y-%m-%d %H:%M") if hasattr(created, "strftime") else str(created)
        likes = p.get("likes_count") or 0
        clicks = p.get("profile_clicks_count") or 0
        lines.append(f"{i}. 📅 {when}\n   ❤️ لايك: {likes}  |  👤 نقرات الحساب: {clicks}")
    text = "\n".join(lines)
    await c.message.edit_text(
        text + "\n\n_الإحصائيات تُحدَّث عند كل لايك أو نقر على زر حساب اللاعب._",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="community_uno_menu")]
        ]),
        parse_mode="Markdown"
    )
    await c.answer()


@router.callback_query(F.data == "player_posts_channel")
async def player_posts_channel_link(c: types.CallbackQuery):
    if PUBLISH_CHANNEL_USERNAME:
        await c.answer()
        return
    await c.answer("📜 القناة غير متاحة حالياً. سيتم تفعيلها من الإدارة لاحقاً.", show_alert=True)


# --- استقبال من خيارات (نص/ميديا) ---
@router.message(PlayerPostStates.waiting_options, F.text)
async def player_post_receive_text_from_options(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    data = await state.get_data()
    share_replay_id = data.get("share_replay_id")
    add_profile = data.get("post_add_profile", True)
    add_play = data.get("post_add_play", False)
    chat_target = _normalize_channel_target()
    if not chat_target:
        logger.warning("player_post_receive_text_from_options: no chat_target")
        return await message.answer(
            "⚠️ **النشر معطّل:** لم يتم ضبط القناة.\n\n"
            "في Railway (أو Variables): أضف:\n"
            "• **PUBLISH_CHANNEL_ID** = معرف القناة الرقمي (سالب، مثل -1001234567890)\n"
            "• **PUBLISH_CHANNEL_USERNAME** = يوزر القناة بدون @\n\n"
            "وأضف البوت في القناة كـ **مسؤول** مع صلاحية «نشر رسائل».",
            parse_mode="Markdown"
        )
    text = (message.text or "").strip()
    ok, reason = check_post_content(text)
    if not ok:
        return await message.answer(f"⛔ {reason}\n\nيمكنك إرسال رسالة أخرى الآن (نص أو صورة).")
    await state.clear()
    if share_replay_id:
        rdata = replay_data.get(share_replay_id)
        if not rdata:
            rdata = _get_replay_from_db(share_replay_id)
        if not rdata:
            return await message.answer("⚠️ انتهت صلاحية النشر. جرّب النشر مباشرة بعد انتهاء الجولة.")
        summary = rdata.get("summary", "🏁 انتهت الجولة!")
        winner_id = rdata.get("winner_id")
        if winner_id is not None:
            try:
                winner_id = int(winner_id)
            except (TypeError, ValueError):
                winner_id = None
        w_name = next((pname for pid, pname in (rdata.get("players") or []) if pid == winner_id), "لاعب")
        total_pts = 0
        if winner_id is not None:
            try:
                pr = db_query("SELECT online_points FROM users WHERE user_id = %s", (winner_id,))
                if pr:
                    total_pts = int(pr[0].get("online_points") or 0)
            except Exception:
                pass
        points_line = f"\n⭐ **مجموع نقاطه:** {total_pts}" if winner_id is not None else ""
        text_to_send = f"{summary}{points_line}\n\n💬 **{w_name}:** {text}"
        join_code = None
        if add_play:
            try:
                join_code = _create_deferred_2p_room(winner_id, w_name)
            except Exception:
                pass
        reply_kb = _channel_post_buttons(winner_id, add_profile, join_code)
        try:
            sent = await message.bot.send_message(chat_id=chat_target, text=text_to_send, parse_mode="Markdown", reply_markup=reply_kb)
            if sent and sent.message_id and reply_kb:
                try:
                    row = db_query(
                        "INSERT INTO channel_posts (channel_id, message_id, publisher_uid, add_profile, join_code) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (str(chat_target), sent.message_id, winner_id, bool(add_profile), join_code), commit=True
                    )
                    if row:
                        post_id = row[0].get("id")
                        new_kb = _channel_post_buttons(winner_id, add_profile, join_code, post_id=post_id, likes_count=0)
                        if new_kb:
                            await message.bot.edit_message_reply_markup(chat_id=chat_target, message_id=sent.message_id, reply_markup=new_kb)
                except Exception:
                    pass
        except Exception as e:
            logger.exception("share_result: publish to channel failed: %s", e)
            err = str(e).replace("'", "").strip()[:220]
            await state.set_state(PlayerPostStates.waiting_options)
            await state.update_data(share_replay_id=share_replay_id, post_add_profile=add_profile, post_add_play=add_play)
            await message.answer(
                "❌ فشل النشر.\n\nتحقق أن البوت مضاف في القناة كـ **مسؤول** وله صلاحية «نشر رسائل».\n\nالخطأ: " + err
                + "\n\nيمكنك إرسال رسالة أخرى للمحاولة."
            )
            return
        kb_after = []
        if PUBLISH_CHANNEL_USERNAME:
            ch = PUBLISH_CHANNEL_USERNAME.lstrip("@")
            kb_after.append([InlineKeyboardButton(text="📢 الذهاب للقناة", url=f"https://t.me/{ch}")])
        kb_after.append([InlineKeyboardButton(text="🔙 رجوع للقائمة الرئيسية", callback_data="home")])
        ch_name = f"@{PUBLISH_CHANNEL_USERNAME.lstrip('@')}" if PUBLISH_CHANNEL_USERNAME else "القناة"
        await message.answer("✅ تم نشر منشورك في " + ch_name + ".", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_after))
        return
    name = _get_player_name_for_post(uid, message.from_user.full_name)
    text_to_send = f"👤 **{name}**\n\n{text}"
    join_code = _create_deferred_2p_room(uid, name) if add_play else None
    reply_kb = _channel_post_buttons(uid, add_profile, join_code)
    try:
        sent = await message.bot.send_message(chat_id=chat_target, text=text_to_send, parse_mode="Markdown", reply_markup=reply_kb)
        sent_msg_id = sent.message_id if sent else None
    except Exception as e:
        logger.exception("player_post: send_message failed: %s", e)
        err_str = str(e).replace("'", "").strip()[:220]
        await state.set_state(PlayerPostStates.waiting_options)
        await state.update_data(post_add_profile=add_profile, post_add_play=add_play)
        await message.answer(
            "❌ فشل النشر.\n\n"
            "• تأكد أن البوت مضاف في القناة كـ **مسؤول** وله صلاحية «نشر رسائل».\n"
            "• تأكد أن المتغيرين PUBLISH_CHANNEL_ID و PUBLISH_CHANNEL_USERNAME في Variables يطابقان قناتك (مثلاً مجتمع الاونو).\n\n"
            "الخطأ: " + err_str + "\n\nيمكنك إرسال رسالة أخرى للمحاولة."
        )
        return
    if sent_msg_id is not None:
        try:
            row = db_query(
                "INSERT INTO channel_posts (channel_id, message_id, publisher_uid, add_profile, join_code) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (str(chat_target), sent_msg_id, uid, bool(add_profile), join_code), commit=True
            )
            if row:
                post_id = row[0].get("id")
                new_kb = _channel_post_buttons(uid, add_profile, join_code, post_id=post_id, likes_count=0)
                if new_kb:
                    await message.bot.edit_message_reply_markup(chat_id=chat_target, message_id=sent_msg_id, reply_markup=new_kb)
        except Exception:
            pass
    kb_after = []
    if PUBLISH_CHANNEL_USERNAME:
        ch = PUBLISH_CHANNEL_USERNAME.lstrip("@")
        kb_after.append([InlineKeyboardButton(text="📢 الذهاب للقناة", url=f"https://t.me/{ch}")])
    kb_after.append([InlineKeyboardButton(text="🔙 رجوع للقائمة الرئيسية", callback_data="home")])
    ch_txt = f"@{PUBLISH_CHANNEL_USERNAME.lstrip('@')}" if PUBLISH_CHANNEL_USERNAME else "القناة"
    await message.answer("✅ تم نشر منشورك في " + ch_txt + ". اضغط الزر أعلاه لمعاينة القناة.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_after))


@router.message(PlayerPostStates.waiting_options, F.photo | F.voice | F.video | F.animation | F.sticker | F.document | F.audio | F.video_note)
async def player_post_receive_media_from_options(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    data = await state.get_data()
    share_replay_id = data.get("share_replay_id")
    if share_replay_id:
        await state.clear()
        return await message.answer("📢 نشر فوزك يدعم **نصاً فقط**. أرسل رسالتك نصاً (مثلاً: هل من متحدي؟).", parse_mode="Markdown")
    add_profile = data.get("post_add_profile", True)
    add_play = data.get("post_add_play", False)
    await state.clear()
    chat_target = _normalize_channel_target()
    if not chat_target:
        return await message.answer("⚠️ نشر المنشورات غير متاح حالياً.")
    caption_text = (message.caption or "").strip()
    if caption_text:
        ok, reason = check_post_content(caption_text)
        if not ok:
            return await message.answer(f"⛔ {reason}")
    name = _get_player_name_for_post(uid, message.from_user.full_name)
    join_code = _create_deferred_2p_room(uid, name) if add_play else None
    reply_kb = _channel_post_buttons(uid, add_profile, join_code)
    ok, sent_msg_id, err = await _publish_media_to_channel(message.bot, message, name, reply_markup=reply_kb)
    if not ok and reply_kb:
        ok, sent_msg_id, err = await _publish_media_to_channel(message.bot, message, name, reply_markup=None)
    if ok and sent_msg_id is not None:
        try:
            row = db_query(
                "INSERT INTO channel_posts (channel_id, message_id, publisher_uid, add_profile, join_code) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (str(chat_target), sent_msg_id, uid, bool(add_profile), join_code), commit=True
            )
            if row:
                post_id = row[0].get("id")
                new_kb = _channel_post_buttons(uid, add_profile, join_code, post_id=post_id, likes_count=0)
                if new_kb:
                    await message.bot.edit_message_reply_markup(chat_id=chat_target, message_id=sent_msg_id, reply_markup=new_kb)
        except Exception:
            pass
    if ok:
        kb_after = []
        if PUBLISH_CHANNEL_USERNAME:
            kb_after.append([InlineKeyboardButton(text="📢 الذهاب للقناة", url=f"https://t.me/{PUBLISH_CHANNEL_USERNAME.lstrip('@')}")])
        kb_after.append([InlineKeyboardButton(text="🔙 رجوع للقائمة الرئيسية", callback_data="home")])
        await message.answer("✅ تم نشر منشورك في القناة.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_after))
    else:
        msg = "❌ فشل النشر. تأكد أن البوت مضاف في القناة كـ مسؤول."
        if err:
            msg += f"\n\nالخطأ: {err}"
        await message.answer(msg)


# --- استقبال في وضع انتظار الرسالة (waiting_message) ---
@router.message(PlayerPostStates.waiting_message, F.text)
async def player_post_receive_text(message: types.Message, state: FSMContext):
    logger.info("player_post_receive_text: got text from user %s, state=%s", message.from_user.id, await state.get_state())
    uid = message.from_user.id
    data = await state.get_data()
    add_profile = data.get("post_add_profile", True)
    add_play = data.get("post_add_play", False)
    await state.clear()
    chat_target = _normalize_channel_target()
    if not chat_target:
        return await message.answer(
            "⚠️ نشر المنشورات غير متاح حالياً.\n\n"
            "تحقق من إعدادات القناة في handlers/channel_config.py (PUBLISH_CHANNEL_ID و PUBLISH_CHANNEL_USERNAME) أو في متغيرات البيئة."
        )
    text = (message.text or "").strip()
    ok, reason = check_post_content(text)
    if not ok:
        return await message.answer(f"⛔ {reason}")
    name = _get_player_name_for_post(uid, message.from_user.full_name)
    text_to_send = f"👤 **{name}**\n\n{text}"
    join_code = None
    if add_play:
        try:
            join_code = _create_deferred_2p_room(uid, name)
        except Exception as e:
            logger.warning("player_post: create_room: %s", e)
    reply_kb = _channel_post_buttons(uid, add_profile, join_code)
    if (add_profile or join_code) and not reply_kb:
        await message.answer(
            "⚠️ تم ضبط الخيارات لكن **BOT_USERNAME** غير مضبوط، فالأزرار (حساب اللاعب، العب معي، لايك) لن تظهر.\n\n"
            "اضبط BOT_USERNAME في Variables أو في channel_config ثم أعد المحاولة."
        )
        return
    sent_msg_id = None
    try:
        sent = await message.bot.send_message(chat_id=chat_target, text=text_to_send, parse_mode="Markdown", reply_markup=reply_kb)
        sent_msg_id = sent.message_id
    except Exception as e:
        logger.exception("player_post: send_message with buttons failed: %s", e)
        try:
            sent = await message.bot.send_message(chat_id=chat_target, text=text_to_send, parse_mode="Markdown")
            sent_msg_id = sent.message_id
        except Exception as e2:
            logger.exception("player_post: send_message without buttons failed: %s", e2)
            await message.answer("❌ فشل النشر.\n\nتأكد أن البوت مضاف في القناة كـ **مسؤول** وله صلاحية «نشر رسائل». الخطأ: " + str(e2)[:200])
            return
    if sent_msg_id is not None:
        try:
            row = db_query(
                "INSERT INTO channel_posts (channel_id, message_id, publisher_uid, add_profile, join_code) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (str(chat_target), sent_msg_id, uid, bool(add_profile), join_code), commit=True
            )
            if row:
                post_id = row[0].get("id")
                new_kb = _channel_post_buttons(uid, add_profile, join_code, post_id=post_id, likes_count=0)
                if new_kb:
                    await message.bot.edit_message_reply_markup(chat_id=chat_target, message_id=sent_msg_id, reply_markup=new_kb)
        except Exception as e:
            logger.exception("player_post: save_post: %s", e)
    kb_after = []
    if PUBLISH_CHANNEL_USERNAME:
        kb_after.append([InlineKeyboardButton(text="📢 الذهاب للقناة", url=f"https://t.me/{PUBLISH_CHANNEL_USERNAME.lstrip('@')}")])
    kb_after.append([InlineKeyboardButton(text="🔙 رجوع للقائمة الرئيسية", callback_data="home")])
    msg = "✅ تم نشر منشورك في القناة."
    if not reply_kb and (add_profile or join_code):
        msg += "\n\n⚠️ لم تظهر الأزرار لأن BOT_USERNAME غير مضبوط. اضبطه في الإعدادات لنشرات لاحقة."
    await message.answer(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_after))


@router.message(PlayerPostStates.waiting_message, F.photo | F.voice | F.video | F.animation | F.sticker | F.document | F.audio | F.video_note)
async def player_post_receive_media(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    data = await state.get_data()
    add_profile = data.get("post_add_profile", True)
    add_play = data.get("post_add_play", False)
    await state.clear()
    chat_target_media = _normalize_channel_target()
    if not chat_target_media:
        return await message.answer("⚠️ نشر المنشورات غير متاح حالياً.")
    caption_text = (message.caption or "").strip()
    if caption_text:
        ok, reason = check_post_content(caption_text)
        if not ok:
            return await message.answer(f"⛔ {reason}")
    name = _get_player_name_for_post(uid, message.from_user.full_name)
    join_code = None
    if add_play:
        try:
            join_code = _create_deferred_2p_room(uid, name)
        except Exception:
            pass
    reply_kb = _channel_post_buttons(uid, add_profile, join_code)
    ok, sent_msg_id, err = await _publish_media_to_channel(message.bot, message, name, reply_markup=reply_kb)
    if not ok and reply_kb:
        ok, sent_msg_id, err = await _publish_media_to_channel(message.bot, message, name, reply_markup=None)
    if ok and sent_msg_id is not None:
        try:
            row = db_query(
                "INSERT INTO channel_posts (channel_id, message_id, publisher_uid, add_profile, join_code) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (str(chat_target_media), sent_msg_id, uid, bool(add_profile), join_code), commit=True
            )
            if row:
                post_id = row[0].get("id")
                new_kb = _channel_post_buttons(uid, add_profile, join_code, post_id=post_id, likes_count=0)
                if new_kb:
                    await message.bot.edit_message_reply_markup(chat_id=chat_target_media, message_id=sent_msg_id, reply_markup=new_kb)
        except Exception as e:
            logger.exception("player_post: save_post media: %s", e)
    if ok:
        kb_after = []
        if PUBLISH_CHANNEL_USERNAME:
            kb_after.append([InlineKeyboardButton(text="📢 الذهاب للقناة", url=f"https://t.me/{PUBLISH_CHANNEL_USERNAME.lstrip('@')}")])
        kb_after.append([InlineKeyboardButton(text="🔙 رجوع للقائمة الرئيسية", callback_data="home")])
        await message.answer("✅ تم نشر منشورك في القناة.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_after))
    else:
        msg = "❌ فشل النشر (الميديا). تأكد أن البوت مضاف في القناة كـ مسؤول وله صلاحية «نشر رسائل»."
        if err:
            msg += f"\n\nالخطأ: {err}"
        await message.answer(msg)


@router.message(PlayerPostStates.waiting_message)
async def player_post_unsupported(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("⚠️ يمكنك إرسال: نص، صورة، صوت، فيديو، صورة متحركة، ملصق، أو ملف. غير ذلك غير مدعوم.")


class _FilterPostFallback(BaseFilter):
    """يمرّر فقط عندما الحالة ليست «نشر» لكن المستخدم فتح «نشر منشور» منذ دقائق."""
    async def __call__(self, message: types.Message, data: dict) -> bool:
        if not message.text or (message.text or "").strip().startswith("/"):
            return False
        uid = message.from_user.id if message.from_user else None
        if not uid:
            return False
        state = data.get("state")
        if not state:
            return False
        current = await state.get_state()
        if current in (PlayerPostStates.waiting_options.state, PlayerPostStates.waiting_message.state):
            return False
        if _get_pending_post(uid):
            return False
        if time.time() - (_last_post_options_at.get(uid) or 0) > _LAST_POST_OPTIONS_WINDOW:
            return False
        if not _normalize_channel_target():
            return False
        return True


class _FilterPostFallbackChannelMissing(BaseFilter):
    """يمرّر عندما المستخدم فتح «نشر منشور» منذ دقائق لكن القناة غير مضبوطة — لردّ توجيهي."""
    async def __call__(self, message: types.Message, data: dict) -> bool:
        if not message.text or (message.text or "").strip().startswith("/"):
            return False
        uid = message.from_user.id if message.from_user else None
        if not uid:
            return False
        if time.time() - (_last_post_options_at.get(uid) or 0) > _LAST_POST_OPTIONS_WINDOW:
            return False
        if _normalize_channel_target():
            return False
        return True


# عندما فتح «نشر منشور» مؤخراً لكن القناة غير مضبوطة — نردّ بتوجيه واضح
@router.message(F.text, _FilterPostFallbackChannelMissing())
async def player_post_channel_missing_reply(message: types.Message):
    await message.answer(
        "⚠️ **النشر معطّل:** القناة غير مضبوطة في الإعدادات.\n\n"
        "في **Variables** (Railway أو السيرفر) أضف:\n"
        "• **PUBLISH_CHANNEL_ID** = معرف القناة الرقمي (سالب، مثل -1001234567890)\n"
        "• **PUBLISH_CHANNEL_USERNAME** = يوزر القناة بدون @\n\n"
        "ثم أضف البوت في القناة كـ **مسؤول** مع صلاحية «نشر رسائل» وأعد تشغيل التطبيق.",
        parse_mode="Markdown"
    )


# معالجة عندما فُقدت الحالة لكن المستخدم فتح «نشر منشور» منذ دقائق — نعالج الرسالة كنشر
@router.message(F.text, _FilterPostFallback())
async def player_post_fallback_recent(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    chat_target = _normalize_channel_target()
    if not chat_target:
        return
    text = (message.text or "").strip()
    if len(text) > 4000:
        return
    ok, reason = check_post_content(text)
    if not ok:
        await message.answer(f"⛔ {reason}\n\nللنشر من جديد: مجتمع الأونو ← نشر منشور.")
        return
    await state.clear()
    name = _get_player_name_for_post(uid, message.from_user.full_name)
    text_to_send = f"👤 **{name}**\n\n{text}"
    add_profile, add_play = True, False
    join_code = _create_deferred_2p_room(uid, name) if add_play else None
    reply_kb = _channel_post_buttons(uid, add_profile, join_code)
    try:
        sent = await message.bot.send_message(chat_id=chat_target, text=text_to_send, parse_mode="Markdown", reply_markup=reply_kb)
        sent_msg_id = sent.message_id if sent else None
    except Exception as e:
        logger.exception("player_post fallback: send failed: %s", e)
        await message.answer(
            "❌ فشل النشر (الحالة انتهت لكن حاولنا النشر).\n\n"
            "تأكد أن البوت مسؤول في القناة وله صلاحية «نشر رسائل». جرّب: مجتمع الأونو ← نشر منشور ثم أرسل رسالتك مرة واحدة.\n\nالخطأ: " + str(e).replace("'", "")[:180]
        )
        return
    if sent_msg_id is not None:
        try:
            db_query(
                "INSERT INTO channel_posts (channel_id, message_id, publisher_uid, add_profile, join_code) VALUES (%s, %s, %s, %s, %s)",
                (str(chat_target), sent_msg_id, uid, bool(add_profile), join_code), commit=True
            )
            row = db_query("SELECT id FROM channel_posts WHERE message_id = %s AND channel_id = %s", (sent_msg_id, str(chat_target)))
            if row:
                new_kb = _channel_post_buttons(uid, add_profile, join_code, post_id=row[0].get("id"), likes_count=0)
                if new_kb:
                    await message.bot.edit_message_reply_markup(chat_id=chat_target, message_id=sent_msg_id, reply_markup=new_kb)
        except Exception:
            pass
    kb_after = []
    if PUBLISH_CHANNEL_USERNAME:
        kb_after.append([InlineKeyboardButton(text="📢 الذهاب للقناة", url=f"https://t.me/{PUBLISH_CHANNEL_USERNAME.lstrip('@')}")])
    kb_after.append([InlineKeyboardButton(text="🔙 رجوع للقائمة الرئيسية", callback_data="home")])
    ch_txt = f"@{PUBLISH_CHANNEL_USERNAME.lstrip('@')}" if PUBLISH_CHANNEL_USERNAME else "القناة"
    await message.answer("✅ تم نشر منشورك في " + ch_txt + " (تمت المعالجة تلقائياً). اضغط الزر أعلاه لمعاينة القناة.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_after))
