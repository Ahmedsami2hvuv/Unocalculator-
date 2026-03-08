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
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import BaseFilter, Command

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
    process_start_deeplink,
    _clear_pending_help_request,
)

logger = logging.getLogger(__name__)
router = Router(name="community_publish")


class _FilterStartWithPayload(BaseFilter):
    """يمرّر فقط عندما النص هو /start متبوعاً بمعامل (profile_، like_، join_، add_)."""
    async def __call__(self, *args, **kwargs) -> bool:
        event = args[0] if args else kwargs.get("event")
        if not event or not getattr(event, "text", None):
            return False
        text = (event.text or "").strip()
        if not text.startswith("/start") or len(text) <= 7:
            return False
        rest = text[6:].strip()
        if not rest:
            return False
        first = rest.split(maxsplit=1)[0] if rest.split() else rest
        return first.startswith("profile_") or first.startswith("add_") or first.startswith("like_") or first.startswith("join_")


@router.message(Command("start"), _FilterStartWithPayload())
async def start_deeplink_from_channel(message: types.Message, state: FSMContext):
    """أول معالج لـ /start عند فتح الرابط من أزرار القناة — نستخرج الـ payload من النص مباشرة."""
    text = (message.text or "").strip()
    rest = text[6:].strip()
    payload = rest.split(maxsplit=1)[0] if rest.split() else rest
    logger.info("start_deeplink_from_channel: payload=%s uid=%s", payload[:80], message.from_user.id)
    await process_start_deeplink(message, payload, state)


def _html_esc(text):
    """تهريب النص لاستخدامه داخل HTML تليجرام (تجنّب خطأ can't parse entities)."""
    if text is None:
        return ""
    s = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return s


def _post_text_html(name: str, body: str) -> str:
    """نص المنشور بتنسيق HTML آمن للإرسال إلى القناة."""
    return f"👤 <b>{_html_esc(name)}</b>\n\n{_html_esc(body)}".strip()


class PlayerPostStates(StatesGroup):
    waiting_options = State()
    waiting_message = State()


# قائمة انتظار النشر: الذاكرة + قاعدة البيانات (لتعمل مع Railway عند تشغيل أكثر من worker)
_pending_post: dict = {}
_PENDING_POST_TIMEOUT = 600  # 10 دقائق

# آخر مرة فتح فيها المستخدم «نشر منشور» (للمعالجة إن فُقدت الحالة)
_last_post_options_at: dict = {}
_LAST_POST_OPTIONS_WINDOW = 300  # 5 دقائق

# هل أعمدة pending_post في users موجودة؟ None=لم نتحقق بعد، True/False بعد التحقق
_pending_post_db_available: bool | None = None

# هل جدول channel_posts مُنشأ (لإنشائه تلقائياً مرة واحدة)
_channel_posts_ensured = False


def run_publish_migration():
    """تشغيل مرة واحدة عند بدء البوت — لضمان جدول channel_posts وأعمدة pending_post (حتى يعمل النشر حتى بعد إعادة التشغيل)."""
    _ensure_channel_posts_table()
    _check_pending_post_columns()
    ch = _normalize_channel_target()
    if ch:
        logger.info("📢 قناة النشر: %s (إن لم ينشر البوت في القناة، تأكد أن البوت مضاف كمسؤول ولديه صلاحية «نشر رسائل»)", ch)
    else:
        logger.warning("📢 قناة النشر غير مضبوطة — اضبط PUBLISH_CHANNEL_ID أو PUBLISH_CHANNEL_USERNAME")


def _ensure_channel_posts_table():
    """إنشاء جدول channel_posts إن لم يكن موجوداً (حتى تعمل «منشوراتي» دون تشغيل schema يدوياً)."""
    global _channel_posts_ensured
    if _channel_posts_ensured:
        return
    try:
        db_query(
            """CREATE TABLE IF NOT EXISTS channel_posts (
                id SERIAL PRIMARY KEY,
                channel_id TEXT NOT NULL,
                message_id BIGINT NOT NULL,
                publisher_uid BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                likes_count INT DEFAULT 0,
                profile_clicks_count INT DEFAULT 0,
                add_profile BOOLEAN DEFAULT TRUE,
                join_code VARCHAR(20) DEFAULT NULL
            )""",
            commit=True
        )
        db_query("CREATE INDEX IF NOT EXISTS idx_channel_posts_publisher ON channel_posts(publisher_uid)", commit=True)
        _channel_posts_ensured = True
    except Exception as e:
        logger.warning("ensure channel_posts table: %s", e)


def _check_pending_post_columns():
    """التحقق مرة واحدة من وجود أعمدة pending_post في جدول users؛ إن وُجدت غير موجودة نحاول إضافتها تلقائياً."""
    global _pending_post_db_available
    if _pending_post_db_available is not None:
        return _pending_post_db_available
    try:
        r = db_query(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'pending_post_options' LIMIT 1",
            ()
        )
        if r and len(r) > 0:
            _pending_post_db_available = True
            return True
        # الأعمدة غير موجودة — محاولة إضافتها تلقائياً (PostgreSQL: ADD COLUMN IF NOT EXISTS)
        try:
            db_query("ALTER TABLE users ADD COLUMN IF NOT EXISTS pending_post_options TEXT DEFAULT NULL", commit=True)
            db_query("ALTER TABLE users ADD COLUMN IF NOT EXISTS pending_post_at TIMESTAMP DEFAULT NULL", commit=True)
            r2 = db_query(
                "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'pending_post_options' LIMIT 1",
                ()
            )
            _pending_post_db_available = bool(r2 and len(r2) > 0)
            if _pending_post_db_available:
                logger.info("pending_post: تم إضافة الأعمدة تلقائياً — النشر يعمل عبر قاعدة البيانات.")
        except Exception as e:
            logger.warning("pending_post: فشل إضافة الأعمدة تلقائياً: %s — شغّل run_channel_migration.sql يدوياً", e)
            _pending_post_db_available = False
    except Exception:
        _pending_post_db_available = False
    if not _pending_post_db_available:
        logger.info("pending_post: استخدام الذاكرة فقط — شغّل run_channel_migration.sql لإضافة الأعمدة")
    return _pending_post_db_available


def _get_pending_post(uid: int):
    """يجلب خيارات النشر المعلقة — من الذاكرة أولاً، ثم من قاعدة البيانات إن وُجدت الأعمدة."""
    if uid in _pending_post:
        t = _pending_post[uid].get("at", 0)
        if time.time() - t <= _PENDING_POST_TIMEOUT:
            return _pending_post[uid]
        _pending_post.pop(uid, None)
    if not _check_pending_post_columns():
        return None
    try:
        row = db_query(
            "SELECT pending_post_options, pending_post_at FROM users WHERE user_id = %s AND pending_post_options IS NOT NULL",
            (uid,)
        )
        if row and row[0].get("pending_post_options") and row[0].get("pending_post_at"):
            try:
                opts = json.loads(row[0]["pending_post_options"])
                created = row[0]["pending_post_at"]
                if hasattr(created, "timestamp"):
                    ts = created.timestamp()
                else:
                    ts = time.time()  # fallback
                if time.time() - ts <= _PENDING_POST_TIMEOUT:
                    opts["at"] = ts
                    return opts
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception as e:
        logger.debug("_get_pending_post db: %s", e)
    return None


def _get_and_clear_pending_post(uid: int):
    """يجلب خيارات النشر ويحذفها (من الذاكرة ومن قاعدة البيانات)."""
    opts = _pending_post.pop(uid, None)
    if opts and (time.time() - opts.get("at", 0)) <= _PENDING_POST_TIMEOUT:
        _clear_pending_post_db(uid)
        return opts
    if not _check_pending_post_columns():
        return None
    try:
        row = db_query(
            "SELECT pending_post_options, pending_post_at FROM users WHERE user_id = %s AND pending_post_options IS NOT NULL",
            (uid,)
        )
        if row and row[0].get("pending_post_options") and row[0].get("pending_post_at"):
            try:
                opts = json.loads(row[0]["pending_post_options"])
                created = row[0]["pending_post_at"]
                ts = created.timestamp() if hasattr(created, "timestamp") else time.time()
                if time.time() - ts <= _PENDING_POST_TIMEOUT:
                    opts["at"] = ts
                    _clear_pending_post_db(uid)
                    return opts
            except (json.JSONDecodeError, TypeError):
                pass
        _clear_pending_post_db(uid)
    except Exception as e:
        logger.debug("_get_and_clear_pending_post db: %s", e)
    return None


def _clear_pending_post_db(uid: int):
    """مسح خيارات النشر المعلقة من قاعدة البيانات."""
    if not _check_pending_post_columns():
        return
    try:
        db_query(
            "UPDATE users SET pending_post_options = NULL, pending_post_at = NULL WHERE user_id = %s",
            (uid,), commit=True
        )
    except Exception as e:
        logger.debug("_clear_pending_post_db: %s", e)


def _set_pending_post_db(uid: int, add_profile: bool, add_play: bool):
    """حفظ خيارات النشر المعلقة في قاعدة البيانات (للتشغيل متعدد العمال على Railway)."""
    if not _check_pending_post_columns():
        return
    try:
        opts_json = json.dumps({"add_profile": add_profile, "add_play": add_play})
        db_query(
            "UPDATE users SET pending_post_options = %s, pending_post_at = NOW() WHERE user_id = %s",
            (opts_json, uid), commit=True
        )
    except Exception as e:
        logger.debug("_set_pending_post_db: %s", e)


def _banned_words_path():
    # يدعم banned_words.txt و banned_words.tx (تصحيح خطأ اسم الملف في المستودع)
    names = ("banned_words.txt", "banned_words.tx")
    for base in (os.path.dirname(os.path.abspath(__file__)), os.getcwd()):
        for name in names:
            p = os.path.join(base, name)
            if os.path.isfile(p):
                return p
            p = os.path.join(os.path.dirname(base), name)
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
    # مطابقة كلمة كاملة فقط (حد كلمة) حتى لا تُرفض كلمات مثل «مرحبا» لأنها تحتوي مقطع «حب»
    _letter = r"[a-zA-Z\u0600-\u06FF]"
    for w in words:
        if not w:
            continue
        # أن تظهر الكلمة الممنوعة ككلمة مستقلة (قبلها وبعدها ليس حرفاً)
        pattern = r"(?:^|(?<!" + _letter + r"))" + re.escape(w) + r"(?:$|(?!" + _letter + r"))"
        if re.search(pattern, text_lower):
            return False, "رسالتك تنتهك معاييرنا."
    if _contains_phone(text):
        return False, "رسالتك تنتهك معاييرنا (لا يُسمح بنشر أرقام هواتف)."
    return True, None


def _has_pending_post(message: types.Message) -> bool:
    uid = message.from_user.id if message.from_user else None
    if not uid:
        return False
    return _get_pending_post(uid) is not None


class _FilterNotHelpRequest(BaseFilter):
    """يمرّر عندما المستخدم ليس في حالة طلب المساعدة (حتى لا تُلتقط رسالة المساعدة كنشر)."""
    async def __call__(self, *args, **kwargs) -> bool:
        data = args[1] if len(args) > 1 else kwargs.get("data", {})
        state = (data.get("state") if isinstance(data, dict) else None) or kwargs.get("state")
        if not state:
            return True
        current = (await state.get_state()) or ""
        return "help_request" not in (current or "")


class _FilterNotReportState(BaseFilter):
    """يمرّر عندما المستخدم ليس في وضع التبليغ (report_upload/report_more) — حتى لا تُلتقط صورة السكرين كنشر."""
    async def __call__(self, *args, **kwargs) -> bool:
        data = args[1] if len(args) > 1 else kwargs.get("data", {})
        state = (data.get("state") if isinstance(data, dict) else None) or kwargs.get("state")
        if not state:
            return True
        current = (await state.get_state()) or ""
        if "report_upload" in (current or "") or "report_more" in (current or ""):
            return False
        return True


@router.message(F.text, _FilterNotHelpRequest(), _FilterNotReportState(), _has_pending_post)
async def player_post_receive_text_pending(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    logger.info("player_post_receive_text_pending: processing uid=%s", uid)
    try:
        opts = _get_and_clear_pending_post(uid)
        if not opts:
            await state.clear()
            await message.answer(
                "⏱ انتهت مهلة النشر (10 دقائق).\n\nمن فضلك ادخل من جديد: **مجتمع الأونو** ← **نشر منشور** ثم أرسل رسالتك خلال 10 دقائق.",
                parse_mode="Markdown"
            )
            return
        await state.clear()
        add_profile = opts.get("add_profile", True)
        add_play = opts.get("add_play", False)
        chat_target = _normalize_channel_target()
        if not chat_target:
            logger.warning("player_post_receive_text_pending: لا توجد قناة — PUBLISH_CHANNEL_ID و PUBLISH_CHANNEL_USERNAME غير مضبوطين")
            await message.answer(
                "⚠️ نشر المنشورات غير متاح حالياً.\n\n"
                "اضبط القناة في Railway (Variables):\n"
                "• PUBLISH_CHANNEL_ID = معرف القناة الرقمي (سالب، مثل -1001234567890)\n"
                "• PUBLISH_CHANNEL_USERNAME = يوزر القناة بدون @\n\n"
                "أو في الملف handlers/channel_config.py"
            )
            return
        text = (message.text or "").strip()
        ok, reason = check_post_content(text)
        if not ok:
            await message.answer(_violation_message(reason, text), reply_markup=_violation_reply_kb())
            return
        share_replay_id = opts.get("share_replay_id")
        if share_replay_id:
            rdata = replay_data.get(share_replay_id)
            if not rdata:
                rdata = _get_replay_from_db(share_replay_id)
            if rdata:
                winner_id = rdata.get("winner_id")
                if winner_id is not None:
                    try:
                        winner_id = int(winner_id)
                    except (TypeError, ValueError):
                        winner_id = None
                if winner_id == uid:
                    w_name = next((pname for pid, pname in (rdata.get("players") or []) if pid == winner_id), "لاعب")
                    losers = [pname for pid, pname in (rdata.get("players") or []) if pid != winner_id]
                    losers_text = " و ".join(_html_esc(n) for n in losers) if losers else "الخصم"
                    total_pts = 0
                    try:
                        pr = db_query("SELECT online_points FROM users WHERE user_id = %s", (winner_id,))
                        if pr:
                            total_pts = int(pr[0].get("online_points") or 0)
                    except Exception:
                        pass
                    summary = rdata.get("summary", "")
                    round_pts_match = re.search(r"\(\+(\d+)\s*نقطة\)", summary) if summary else None
                    round_pts = int(round_pts_match.group(1)) if round_pts_match else 0
                    text_to_send = (
                        f"👤 <b>{_html_esc(w_name)}</b> فاز\n"
                        f"الخاسر {losers_text}\n"
                        f"ربح {round_pts} نقطه\n"
                        f"نقاطه الكلية {total_pts}\n"
                        f"رسالته\n"
                        f"{_html_esc(text)}"
                    )
                    join_code = None
                    if add_play:
                        try:
                            join_code = _create_deferred_2p_room(winner_id, w_name)
                        except Exception:
                            pass
                    reply_kb = _channel_post_buttons(winner_id, add_profile, join_code)
                    sent_msg_id, err = await _send_to_channel_safe(message.bot, chat_target, text_to_send, reply_markup=reply_kb)
                    if not err and sent_msg_id is not None:
                        try:
                            post_id = _save_channel_post_and_get_id(chat_target, sent_msg_id, winner_id, add_profile, join_code)
                            if post_id is not None and reply_kb:
                                new_kb = _channel_post_buttons(winner_id, add_profile, join_code, post_id=post_id, likes_count=0)
                                if new_kb:
                                    try:
                                        await message.bot.edit_message_reply_markup(chat_id=chat_target, message_id=sent_msg_id, reply_markup=new_kb)
                                    except Exception as e:
                                        logger.warning("edit_message_reply_markup (share_result pending) failed: %s", e)
                        except Exception as e:
                            logger.exception("player_post: save_post share_result: %s", e)
                        kb_after = []
                        if PUBLISH_CHANNEL_USERNAME:
                            kb_after.append([InlineKeyboardButton(text="📢 الذهاب للقناة", url=f"https://t.me/{PUBLISH_CHANNEL_USERNAME.lstrip('@')}")])
                        kb_after.append([InlineKeyboardButton(text="🔙 رجوع للقائمة الرئيسية", callback_data="home")])
                        await message.answer("✅ تم نشر منشورك في القناة.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_after))
                        return
        name = _get_player_name_for_post(uid, message.from_user.full_name)
        text_to_send = _post_text_html(name, text)
        join_code = None
        if add_play:
            try:
                join_code = _create_deferred_2p_room(uid, name)
            except Exception as e:
                logger.warning("player_post: create_room: %s", e)
        reply_kb = _channel_post_buttons(uid, add_profile, join_code)
        sent_msg_id = None
        logger.info("player_post: إرسال نص إلى القناة ch=%s uid=%s", chat_target, uid)
        sent_msg_id, err = await _send_to_channel_safe(message.bot, chat_target, text_to_send, reply_markup=reply_kb)
        if err:
            await message.answer(
                "❌ فشل النشر في القناة.\n\n"
                "• أضف البوت في القناة كـ **مسؤول (Admin)** وامنحه صلاحية **«Post messages» / «نشر رسائل»**.\n"
                "• تأكد أن معرف القناة صحيح في Variables أو channel_config.py (PUBLISH_CHANNEL_ID سالب مثل -1001234567890).\n\n"
                "خطأ تيليجرام: " + str(err)[:250]
            )
            return
        if sent_msg_id is not None:
            try:
                post_id = _save_channel_post_and_get_id(chat_target, sent_msg_id, uid, add_profile, join_code)
                if post_id is not None:
                    new_kb = _channel_post_buttons(uid, add_profile, join_code, post_id=post_id, likes_count=0)
                    if new_kb:
                        try:
                            await message.bot.edit_message_reply_markup(chat_id=chat_target, message_id=sent_msg_id, reply_markup=new_kb)
                        except Exception as e:
                            logger.warning("edit_message_reply_markup (like+buttons) failed: %s", e)
                    else:
                        logger.warning("BOT_USERNAME not set: أزرار المنشور (لايك) لن تظهر.")
            except Exception as e:
                logger.exception("player_post: save_post: %s", e)
                if "channel_posts" in str(e).lower() or "relation" in str(e).lower():
                    logger.warning("جرّب تشغيل schema_additions.sql لإنشاء جدول channel_posts")
        kb_after = []
        if PUBLISH_CHANNEL_USERNAME:
            kb_after.append([InlineKeyboardButton(text="📢 الذهاب للقناة", url=f"https://t.me/{PUBLISH_CHANNEL_USERNAME.lstrip('@')}")])
        kb_after.append([InlineKeyboardButton(text="🔙 رجوع للقائمة الرئيسية", callback_data="home")])
        await message.answer("✅ تم نشر منشورك في القناة.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_after))
    except Exception as e:
        logger.exception("player_post_receive_text_pending: uid=%s error", uid)
        try:
            await message.answer(
                "❌ حدث خطأ أثناء النشر ولم تُنشر رسالتك.\n\nجرّب مرة أخرى: مجتمع الأونو ← نشر منشور ← تم ثم أرسل رسالتك.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 رجوع", callback_data="post_back")]]),
            )
        except Exception:
            pass


@router.message(F.photo | F.voice | F.video | F.animation | F.sticker | F.document | F.audio | F.video_note, _FilterNotHelpRequest(), _FilterNotReportState(), _has_pending_post)
async def player_post_receive_media_pending(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    try:
        opts = _get_and_clear_pending_post(uid)
        if not opts:
            await state.clear()
            await message.answer(
                "⏱ انتهت مهلة النشر (10 دقائق).\n\nمن فضلك ادخل من جديد: **مجتمع الأونو** ← **نشر منشور** ثم أرسل ميديا خلال 10 دقائق.",
                parse_mode="Markdown"
            )
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
                await message.answer(_violation_message(reason, caption_text), reply_markup=_violation_reply_kb())
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
                post_id = _save_channel_post_and_get_id(chat_target, sent_msg_id, uid, add_profile, join_code)
                if post_id is not None:
                    new_kb = _channel_post_buttons(uid, add_profile, join_code, post_id=post_id, likes_count=0)
                    if new_kb:
                        try:
                            await message.bot.edit_message_reply_markup(chat_id=chat_target, message_id=sent_msg_id, reply_markup=new_kb)
                        except Exception as e:
                            logger.warning("edit_message_reply_markup (ميديا pending) failed: %s", e)
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
    except Exception as e:
        logger.exception("player_post_receive_media_pending: uid=%s error", uid)
        try:
            await message.answer(
                "❌ حدث خطأ أثناء النشر ولم تُنشر رسالتك.\n\nجرّب مرة أخرى: مجتمع الأونو ← نشر منشور ← تم ثم أرسل ميديا.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 رجوع", callback_data="post_back")]]),
            )
        except Exception:
            pass


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


def _save_channel_post_and_get_id(channel_id, message_id, publisher_uid, add_profile, join_code):
    """حفظ منشور في channel_posts وإرجاع post_id. (db_query مع commit=True قد يعيد bool بدل الصفوف.)"""
    try:
        db_query(
            "INSERT INTO channel_posts (channel_id, message_id, publisher_uid, add_profile, join_code) VALUES (%s, %s, %s, %s, %s)",
            (str(channel_id), message_id, publisher_uid, bool(add_profile), join_code), commit=True
        )
        row = db_query(
            "SELECT id FROM channel_posts WHERE channel_id = %s AND message_id = %s ORDER BY id DESC LIMIT 1",
            (str(channel_id), message_id)
        )
        if row and isinstance(row, list) and len(row) > 0 and hasattr(row[0], "get"):
            return row[0].get("id")
    except Exception as e:
        logger.warning("_save_channel_post_and_get_id: %s", e)
    return None


async def _send_to_channel_safe(bot, ch, text_html: str, reply_markup=None, **send_kw):
    """إرسال نص إلى القناة بتنسيق HTML مع إعادة محاولة بدون تنسيق عند الفشل."""
    logger.info("publish: إرسال إلى القناة ch=%s (نص %s حرف)", ch, len(text_html or ""))
    kwargs = {"parse_mode": "HTML", **send_kw}
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    try:
        sent = await bot.send_message(ch, text_html, **kwargs)
        logger.info("publish: تم النشر في القناة message_id=%s", sent.message_id)
        return sent.message_id, None
    except Exception as e1:
        err1 = str(e1).replace("'", "").strip()[:300]
        logger.warning("publish: فشل الإرسال (HTML) ch=%s: %s", ch, err1)
        try:
            plain = text_html.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            plain = re.sub(r"<b>(.*?)</b>", r"\1", plain)
            retry_kw = {**send_kw}
            if reply_markup is not None:
                retry_kw["reply_markup"] = reply_markup
            sent = await bot.send_message(ch, plain, **retry_kw)
            logger.info("publish: تم النشر (بدون HTML) message_id=%s", sent.message_id)
            return sent.message_id, None
        except Exception as e2:
            err2 = str(e2).replace("'", "").strip()[:300]
            logger.error("publish: فشل الإرسال نهائياً ch=%s: %s", ch, err2)
            return None, err2[:220]


async def _publish_media_to_channel(bot, message: types.Message, name: str, channel_id=None, reply_markup=None):
    ch = channel_id if channel_id is not None else _normalize_channel_target()
    if not ch:
        return False, None, "القناة غير مضبوطة (PUBLISH_CHANNEL_ID / USERNAME)"
    cap_body = (message.caption or "").strip()
    cap = _post_text_html(name, cap_body) if cap_body else f"👤 <b>{_html_esc(name)}</b>"
    kwargs = {}
    if reply_markup:
        kwargs["reply_markup"] = reply_markup
    try:
        if message.text:
            text_html = _post_text_html(name, message.text or "")
            mid, err = await _send_to_channel_safe(bot, ch, text_html, **kwargs)
            return (True, mid, None) if mid else (False, None, err or "فشل الإرسال")
        if message.photo:
            sent = await bot.send_photo(ch, message.photo[-1].file_id, caption=cap, parse_mode="HTML", **kwargs)
            return True, sent.message_id, None
        if message.voice:
            sent = await bot.send_voice(ch, message.voice.file_id, caption=cap, parse_mode="HTML", **kwargs)
            return True, sent.message_id, None
        if message.video:
            sent = await bot.send_video(ch, message.video.file_id, caption=cap, parse_mode="HTML", **kwargs)
            return True, sent.message_id, None
        if message.animation:
            sent = await bot.send_animation(ch, message.animation.file_id, caption=cap, parse_mode="HTML", **kwargs)
            return True, sent.message_id, None
        if message.sticker:
            await bot.send_sticker(ch, message.sticker.file_id)
            mid, err = await _send_to_channel_safe(bot, ch, f"👤 <b>{_html_esc(name)}</b>", **kwargs)
            return (True, mid, None) if mid else (False, None, err or "فشل الإرسال")
        if message.document:
            sent = await bot.send_document(ch, message.document.file_id, caption=cap, parse_mode="HTML", **kwargs)
            return True, sent.message_id, None
        if message.audio:
            sent = await bot.send_audio(ch, message.audio.file_id, caption=cap, parse_mode="HTML", **kwargs)
            return True, sent.message_id, None
        if message.video_note:
            await bot.send_video_note(ch, message.video_note.file_id)
            mid, err = await _send_to_channel_safe(bot, ch, f"👤 <b>{_html_esc(name)}</b>", **kwargs)
            return (True, mid, None) if mid else (False, None, err or "فشل الإرسال")
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
        [InlineKeyboardButton(text="✅ تم، أرسل رسالتك الآن", callback_data="post_ready_send")],
        [InlineKeyboardButton(text="🔙 تراجع", callback_data="post_back")],
    ])


@router.callback_query(F.data == "player_post_start")
async def player_post_start(c: types.CallbackQuery, state: FSMContext):
    await c.answer()
    if not _normalize_channel_target():
        await c.message.answer("⚠️ نشر المنشورات غير متاح حالياً. تحقق من إعدادات القناة (channel_config أو Variables).")
        return
    _last_post_options_at[c.from_user.id] = time.time()
    await state.set_state(PlayerPostStates.waiting_options)
    await state.update_data(post_add_profile=True, post_add_play=False)
    await c.message.edit_text(
        "📢 **نشر منشور**\n\nاختر ما تريد إضافته تحت منشورك، ثم أرسل **رسالة واحدة** (نص أو صورة أو ميديا) — سيُنشر فوراً في القناة.\n\n"
        "• **زر حسابي:** يظهر زر يفتح بروفايلك (متابعة، طلب لعب، رجوع للقناة).\n"
        "• **العب معي:** يظهر زر من يضغطه ينضم معك في كيم ثنائي فوراً.\n\n"
        "⚠️ لا يُسمح بنشر أرقام هواتف أو كلمات تخالف المعايير.\n\n"
        "_اضغط «تم، أرسل رسالتك الآن» ثم أرسل النص أو الصورة في الرسالة التالية._",
        reply_markup=_post_options_kb({"post_add_profile": True, "post_add_play": False}),
        parse_mode="Markdown"
    )


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
    await c.answer()
    if await state.get_state() != PlayerPostStates.waiting_options.state:
        return
    data = await state.get_data()
    add_profile = data.get("post_add_profile", True)
    add_play = data.get("post_add_play", False)
    uid = c.from_user.id
    # إزالة طلب المساعدة المعلّق حتى لا يلتقط common.py الرسالة التالية كـ «طلب مساعدة» بدل النشر
    try:
        _clear_pending_help_request(uid)
    except Exception:
        pass
    share_replay_id = data.get("share_replay_id")
    _pending_post[uid] = {"add_profile": add_profile, "add_play": add_play, "at": time.time(), "share_replay_id": share_replay_id}
    _last_post_options_at[uid] = time.time()
    try:
        db_query(
            "INSERT INTO users (user_id, username, is_registered) VALUES (%s, %s, FALSE) ON CONFLICT (user_id) DO NOTHING",
            (uid, c.from_user.username or ""), commit=True
        )
    except Exception as e:
        logger.warning("post_ready_send: %s", e)
    _set_pending_post_db(uid, add_profile, add_play)
    await state.set_state(PlayerPostStates.waiting_message)
    await c.message.edit_text(
        "📢 أرسل الآن النص أو الصور أو الصوت أو الفيديو أو الملصقات أو أي ميديا للنشر في القناة.\n\n⚠️ لا يُسمح بنشر أرقام هواتف أو كلمات تخالف المعايير.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="post_back")],
        ]),
    )


def _violation_message(reason: str, rejected_content: str = None) -> str:
    """رسالة الرفض مع إظهار ما أرسله المستخدم حتى لا يضيع ويستطيع نسخه وتعديله وإعادة الإرسال."""
    msg = f"⛔ {reason}"
    if rejected_content and str(rejected_content).strip():
        raw = str(rejected_content).strip()
        preview = (raw[:400] + "…") if len(raw) > 400 else raw
        msg += f"\n\n📝 ما أرسلته (انسخه إن أردت تعديله ثم اضغط «تجربة نشر من جديد» وأرسله):\n«{preview}»"
    return msg


def _violation_reply_kb():
    """زر تحت رسالة «رسالتك تنتهك معاييرنا»: تجربة نشر من جديد."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 تجربة نشر من جديد", callback_data="post_retry_publish")],
    ])


@router.callback_query(F.data == "post_retry_publish")
async def post_retry_publish(c: types.CallbackQuery, state: FSMContext):
    """بعد رفض المنشور: إعادة عرض شاشة «أرسل الآن النص...» مع زر رجوع."""
    uid = c.from_user.id
    opts = _get_pending_post(uid)
    if not opts:
        await state.clear()
        await c.message.edit_text(
            "⏱ انتهت مهلة النشر.\n\nادخل من: مجتمع الأونو ← نشر منشور.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 رجوع", callback_data="post_back")]]),
        )
        return await c.answer()
    _set_pending_post_db(uid, opts.get("add_profile", True), opts.get("add_play", False))
    await state.set_state(PlayerPostStates.waiting_message)
    await c.message.edit_text(
        "📢 أرسل الآن النص أو الصور أو الصوت أو الفيديو أو الملصقات أو أي ميديا للنشر في القناة.\n\n⚠️ لا يُسمح بنشر أرقام هواتف أو كلمات تخالف المعايير.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="post_back")],
        ]),
    )
    await c.answer("أرسل رسالتك من جديد.")


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
    try:
        await c.message.edit_text(
            "👥 **مجتمع الأونو**\n\nاختر:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            parse_mode="Markdown"
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in (str(e.message or "")):
            raise
    await c.answer()


@router.callback_query(F.data == "community_uno_menu")
async def community_uno_menu(c: types.CallbackQuery):
    _ensure_channel_posts_table()
    rows = [
        [InlineKeyboardButton(text="📢 نشر منشور بالقناة", callback_data="player_post_start")],
    ]
    if PUBLISH_CHANNEL_USERNAME:
        rows.append([InlineKeyboardButton(text="📜 عرض القناة", url=f"https://t.me/{PUBLISH_CHANNEL_USERNAME.lstrip('@')}")])
    else:
        rows.append([InlineKeyboardButton(text="📜 عرض القناة", callback_data="player_posts_channel")])
    rows.append([InlineKeyboardButton(text="📋 منشوراتي", callback_data="my_posts_list")])
    rows.append([InlineKeyboardButton(text="🔙 رجوع", callback_data="home")])
    try:
        await c.message.edit_text(
            "👥 **مجتمع الأونو**\n\nاختر:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            parse_mode="Markdown"
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in (str(e.message or "")):
            raise
    await c.answer()


def _post_link(post: dict):
    """رابط المنشور في القناة (يتطلب PUBLISH_CHANNEL_USERNAME)."""
    ch = (PUBLISH_CHANNEL_USERNAME or "").strip().lstrip("@")
    mid = post.get("message_id")
    if not ch or mid is None:
        return None
    return f"https://t.me/{ch}/{mid}"


@router.callback_query(F.data == "my_posts_list")
async def my_posts_list(c: types.CallbackQuery):
    _ensure_channel_posts_table()
    uid = int(c.from_user.id)
    try:
        posts = db_query(
            "SELECT id, message_id, channel_id, created_at, likes_count, profile_clicks_count, publisher_uid FROM channel_posts WHERE publisher_uid = %s ORDER BY created_at DESC LIMIT 30",
            (uid,)
        )
        if not posts and uid:
            posts = db_query(
                "SELECT id, message_id, channel_id, created_at, likes_count, profile_clicks_count, publisher_uid FROM channel_posts WHERE CAST(publisher_uid AS TEXT) = %s ORDER BY created_at DESC LIMIT 30",
                (str(uid),)
            )
    except Exception as e:
        logger.warning("my_posts_list query failed for uid=%s: %s", uid, e)
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
    kb_rows = []
    for i, p in enumerate(posts, 1):
        created = p.get("created_at")
        when = created.strftime("%Y-%m-%d %H:%M") if hasattr(created, "strftime") else str(created)
        likes = p.get("likes_count") or 0
        clicks = p.get("profile_clicks_count") or 0
        lines.append(f"{i}. 📅 {when}  |  ❤️ لايك: {likes}  |  👤 نقرات: {clicks}")
        row_btns = []
        link = _post_link(p)
        if link:
            row_btns.append(InlineKeyboardButton(text="🔗 فتح المنشور", url=link))
        row_btns.append(InlineKeyboardButton(text="🗑 مسح منشور", callback_data=f"delete_post_confirm_{p['id']}"))
        kb_rows.append(row_btns)
    kb_rows.append([InlineKeyboardButton(text="🔙 رجوع", callback_data="community_uno_menu")])
    text = "\n".join(lines) + "\n\n_اضغط «فتح المنشور» للذهاب للمنشور في القناة._"
    await c.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
        parse_mode="Markdown"
    )
    await c.answer()


@router.callback_query(F.data.startswith("delete_post_confirm_"))
async def delete_post_confirm(c: types.CallbackQuery):
    post_id = c.data.replace("delete_post_confirm_", "").strip()
    if not post_id or not post_id.isdigit():
        await c.answer("⚠️ خطأ.", show_alert=True)
        return
    post_id = int(post_id)
    row = db_query("SELECT id, publisher_uid, channel_id, message_id FROM channel_posts WHERE id = %s", (post_id,))
    try:
        pub_uid = row[0].get("publisher_uid") if row else None
        if pub_uid is not None:
            pub_uid = int(pub_uid)
    except (TypeError, ValueError):
        pub_uid = None
    if not row or pub_uid != c.from_user.id:
        await c.answer("⚠️ لا يمكنك حذف هذا المنشور.", show_alert=True)
        return
    await c.message.edit_text(
        "⚠️ **هل أنت متأكد من حذف هذا المنشور من القناة؟**\n\nسيُحذف المنشور ولا يمكن استعادته.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ نعم، احذف المنشور", callback_data=f"delete_post_yes_{post_id}")],
            [InlineKeyboardButton(text="🔙 إلغاء", callback_data="my_posts_list")]
        ]),
        parse_mode="Markdown"
    )
    await c.answer()


@router.callback_query(F.data.startswith("delete_post_yes_"))
async def delete_post_yes(c: types.CallbackQuery):
    post_id = c.data.replace("delete_post_yes_", "").strip()
    if not post_id or not post_id.isdigit():
        await c.answer("⚠️ خطأ.", show_alert=True)
        return
    post_id = int(post_id)
    uid = c.from_user.id
    row = db_query("SELECT id, publisher_uid, channel_id, message_id FROM channel_posts WHERE id = %s", (post_id,))
    try:
        pub_uid = row[0].get("publisher_uid") if row else None
        if pub_uid is not None:
            pub_uid = int(pub_uid)
    except (TypeError, ValueError):
        pub_uid = None
    if not row or pub_uid != uid:
        await c.answer("⚠️ لا يمكنك حذف هذا المنشور.", show_alert=True)
        return
    ch_id = row[0].get("channel_id")
    msg_id = row[0].get("message_id")
    try:
        if ch_id is not None and msg_id is not None:
            await c.bot.delete_message(chat_id=ch_id, message_id=int(msg_id))
    except Exception as e:
        logger.warning("delete_post: delete_message failed %s", e)
    try:
        db_query("DELETE FROM channel_posts WHERE id = %s AND publisher_uid = %s", (post_id, uid), commit=True)
    except Exception as e:
        logger.warning("delete_post: db %s", e)
    await c.message.edit_text(
        "✅ تم حذف المنشور من القناة.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 منشوراتي", callback_data="my_posts_list")],
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="community_uno_menu")]
        ])
    )
    await c.answer("✅ تم حذف المنشور.")


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
        return await message.answer(_violation_message(reason, text) + "\n\nيمكنك إرسال رسالة أخرى الآن (نص أو صورة).", reply_markup=_violation_reply_kb())
    await state.clear()
    if share_replay_id:
        rdata = replay_data.get(share_replay_id)
        if not rdata:
            rdata = _get_replay_from_db(share_replay_id)
        if not rdata:
            return await message.answer("⚠️ انتهت صلاحية النشر. جرّب النشر مباشرة بعد انتهاء الجولة.")
        winner_id = rdata.get("winner_id")
        if winner_id is not None:
            try:
                winner_id = int(winner_id)
            except (TypeError, ValueError):
                winner_id = None
        w_name = next((pname for pid, pname in (rdata.get("players") or []) if pid == winner_id), "لاعب")
        losers = [pname for pid, pname in (rdata.get("players") or []) if pid != winner_id]
        losers_text = " و ".join(_html_esc(n) for n in losers) if losers else "الخصم"
        total_pts = 0
        if winner_id is not None:
            try:
                pr = db_query("SELECT online_points FROM users WHERE user_id = %s", (winner_id,))
                if pr:
                    total_pts = int(pr[0].get("online_points") or 0)
            except Exception:
                pass
        summary = rdata.get("summary", "")
        round_pts_match = re.search(r"\(\+(\d+)\s*نقطة\)", summary) if summary else None
        round_pts = int(round_pts_match.group(1)) if round_pts_match else 0
        text_to_send = (
            f"👤 <b>{_html_esc(w_name)}</b> فاز\n"
            f"الخاسر {losers_text}\n"
            f"ربح {round_pts} نقطه\n"
            f"نقاطه الكلية {total_pts}\n"
            f"رسالته\n"
            f"{_html_esc(text)}"
        )
        join_code = None
        if add_play:
            try:
                join_code = _create_deferred_2p_room(winner_id, w_name)
            except Exception:
                pass
        reply_kb = _channel_post_buttons(winner_id, add_profile, join_code)
        sent_mid, send_err = await _send_to_channel_safe(message.bot, chat_target, text_to_send, reply_markup=reply_kb)
        if send_err or not sent_mid:
            logger.warning("share_result: publish to channel failed: %s", send_err)
            err = (send_err or "فشل الإرسال")[:220]
            await state.set_state(PlayerPostStates.waiting_options)
            await state.update_data(share_replay_id=share_replay_id, post_add_profile=add_profile, post_add_play=add_play)
            await message.answer(
                "❌ فشل النشر.\n\nتحقق أن البوت مضاف في القناة كـ **مسؤول** وله صلاحية «نشر رسائل».\n\nالخطأ: " + err
                + "\n\nيمكنك إرسال رسالة أخرى للمحاولة."
            )
            return
        try:
            post_id = _save_channel_post_and_get_id(chat_target, sent_mid, winner_id, add_profile, join_code)
            if post_id is not None:
                new_kb = _channel_post_buttons(winner_id, add_profile, join_code, post_id=post_id, likes_count=0)
                if new_kb:
                    try:
                        await message.bot.edit_message_reply_markup(chat_id=chat_target, message_id=sent_mid, reply_markup=new_kb)
                    except Exception as e:
                        logger.warning("edit_message_reply_markup (نشر فوزي) failed: %s", e)
        except Exception:
            pass
        kb_after = []
        if PUBLISH_CHANNEL_USERNAME:
            ch = PUBLISH_CHANNEL_USERNAME.lstrip("@")
            kb_after.append([InlineKeyboardButton(text="📢 الذهاب للقناة", url=f"https://t.me/{ch}")])
        kb_after.append([InlineKeyboardButton(text="🔙 رجوع للقائمة الرئيسية", callback_data="home")])
        ch_name = f"@{PUBLISH_CHANNEL_USERNAME.lstrip('@')}" if PUBLISH_CHANNEL_USERNAME else "القناة"
        await message.answer("✅ تم نشر منشورك في " + ch_name + ".", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_after))
        return
    name = _get_player_name_for_post(uid, message.from_user.full_name)
    text_to_send = _post_text_html(name, text)
    join_code = _create_deferred_2p_room(uid, name) if add_play else None
    reply_kb = _channel_post_buttons(uid, add_profile, join_code)
    sent_msg_id, send_err = await _send_to_channel_safe(message.bot, chat_target, text_to_send, reply_markup=reply_kb)
    if send_err:
        await state.set_state(PlayerPostStates.waiting_options)
        await state.update_data(post_add_profile=add_profile, post_add_play=add_play)
        await message.answer(
            "❌ فشل النشر.\n\n"
            "• تأكد أن البوت مضاف في القناة كـ **مسؤول** وله صلاحية «نشر رسائل».\n"
            "• تأكد أن المتغيرين PUBLISH_CHANNEL_ID و PUBLISH_CHANNEL_USERNAME في Variables يطابقان قناتك (مثلاً مجتمع الاونو).\n\n"
            "الخطأ: " + send_err[:220] + "\n\nيمكنك إرسال رسالة أخرى للمحاولة."
        )
        return
    if sent_msg_id is not None:
        try:
            post_id = _save_channel_post_and_get_id(chat_target, sent_msg_id, uid, add_profile, join_code)
            if post_id is not None:
                new_kb = _channel_post_buttons(uid, add_profile, join_code, post_id=post_id, likes_count=0)
                if new_kb:
                    try:
                        await message.bot.edit_message_reply_markup(chat_id=chat_target, message_id=sent_msg_id, reply_markup=new_kb)
                    except Exception as e:
                        logger.warning("edit_message_reply_markup (نشر منشور نص) failed: %s", e)
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
            return await message.answer(_violation_message(reason, caption_text), reply_markup=_violation_reply_kb())
    name = _get_player_name_for_post(uid, message.from_user.full_name)
    join_code = _create_deferred_2p_room(uid, name) if add_play else None
    reply_kb = _channel_post_buttons(uid, add_profile, join_code)
    ok, sent_msg_id, err = await _publish_media_to_channel(message.bot, message, name, reply_markup=reply_kb)
    if not ok and reply_kb:
        ok, sent_msg_id, err = await _publish_media_to_channel(message.bot, message, name, reply_markup=None)
    if ok and sent_msg_id is not None:
        try:
            post_id = _save_channel_post_and_get_id(chat_target, sent_msg_id, uid, add_profile, join_code)
            if post_id is not None:
                new_kb = _channel_post_buttons(uid, add_profile, join_code, post_id=post_id, likes_count=0)
                if new_kb:
                    try:
                        await message.bot.edit_message_reply_markup(chat_id=chat_target, message_id=sent_msg_id, reply_markup=new_kb)
                    except Exception as e:
                        logger.warning("edit_message_reply_markup (ميديا من خيارات) failed: %s", e)
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
    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
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
            return await message.answer(_violation_message(reason, text), reply_markup=_violation_reply_kb())
        name = _get_player_name_for_post(uid, message.from_user.full_name)
        text_to_send = _post_text_html(name, text)
        join_code = None
        if add_play:
            try:
                join_code = _create_deferred_2p_room(uid, name)
            except Exception as e:
                logger.warning("player_post: create_room: %s", e)
        reply_kb = _channel_post_buttons(uid, add_profile, join_code)
        sent_msg_id, send_err = await _send_to_channel_safe(message.bot, chat_target, text_to_send, reply_markup=reply_kb)
        if send_err:
            await message.answer(
                "❌ فشل النشر في القناة.\n\n"
                "• أضف البوت في القناة كـ **مسؤول** وامنحه صلاحية «نشر رسائل».\n"
                "• أو جرّب من لوحة الأدمن: **اختبار النشر في القناة** لمعرفة السبب.\n\n"
                "الخطأ: " + send_err[:250]
            )
            return
        if sent_msg_id is not None:
            try:
                post_id = _save_channel_post_and_get_id(chat_target, sent_msg_id, uid, add_profile, join_code)
                if post_id is not None:
                    new_kb = _channel_post_buttons(uid, add_profile, join_code, post_id=post_id, likes_count=0)
                    if new_kb:
                        try:
                            await message.bot.edit_message_reply_markup(chat_id=chat_target, message_id=sent_msg_id, reply_markup=new_kb)
                        except Exception as e:
                            logger.warning("edit_message_reply_markup (waiting_message text) failed: %s", e)
            except Exception as e:
                logger.exception("player_post: save_post: %s", e)
        kb_after = []
        if PUBLISH_CHANNEL_USERNAME:
            kb_after.append([InlineKeyboardButton(text="📢 الذهاب للقناة", url=f"https://t.me/{PUBLISH_CHANNEL_USERNAME.lstrip('@')}")])
        kb_after.append([InlineKeyboardButton(text="🔙 رجوع للقائمة الرئيسية", callback_data="home")])
        await message.answer("✅ تم نشر منشورك في القناة.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_after))
    except Exception as e:
        logger.exception("player_post_receive_text: uid=%s error", message.from_user.id)
        try:
            await message.answer(
                "❌ حدث خطأ أثناء النشر ولم تُنشر رسالتك.\n\nجرّب مرة أخرى: مجتمع الأونو ← نشر منشور ← تم ثم أرسل رسالتك.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 رجوع", callback_data="post_back")]]),
            )
        except Exception:
            pass


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
            return await message.answer(_violation_message(reason, caption_text), reply_markup=_violation_reply_kb())
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
            post_id = _save_channel_post_and_get_id(chat_target_media, sent_msg_id, uid, add_profile, join_code)
            if post_id is not None:
                new_kb = _channel_post_buttons(uid, add_profile, join_code, post_id=post_id, likes_count=0)
                if new_kb:
                    try:
                        await message.bot.edit_message_reply_markup(chat_id=chat_target_media, message_id=sent_msg_id, reply_markup=new_kb)
                    except Exception as e:
                        logger.warning("edit_message_reply_markup (waiting_message media) failed: %s", e)
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
    """يمرّر عندما المستخدم فتح «نشر منشور» منذ دقائق ورسالته لم تُلتقط بمعالج آخر (حالة أو pending ضاعت)."""
    async def __call__(self, *args, **kwargs) -> bool:
        message = args[0] if args else kwargs.get("event")
        data = args[1] if len(args) > 1 else kwargs.get("data", {})
        if not message or not getattr(message, "text", None) or (message.text or "").strip().startswith("/"):
            return False
        uid = message.from_user.id if getattr(message, "from_user", None) else None
        if not uid:
            return False
        # إن وُجدت حالة وكانت انتظار رسالة أو خيارات، نترك المعالج الآخر يتولاها — لا نسرق
        # استثناء حالة الأدمن (محادثة مع لاعب، بث، إلخ) حتى لا تُسرق رسائل المدير
        state = (data.get("state") if isinstance(data, dict) else None) or kwargs.get("state")
        if state:
            current = (await state.get_state()) or ""
            if "help_request" in (current or ""):
                return False
            if (current or "").startswith("admin:"):
                return False
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
    async def __call__(self, *args, **kwargs) -> bool:
        message = args[0] if args else kwargs.get("event")
        data = args[1] if len(args) > 1 else kwargs.get("data", {})
        if not message or not getattr(message, "text", None) or (message.text or "").strip().startswith("/"):
            return False
        uid = message.from_user.id if getattr(message, "from_user", None) else None
        if not uid:
            return False
        state = (data.get("state") if isinstance(data, dict) else None) or kwargs.get("state")
        if state:
            current = (await state.get_state()) or ""
            if "help_request" in (current or ""):
                return False
            if (current or "").startswith("admin:"):
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


# معالجة عندما فُقدت الحالة لكن المستخدم فتح «نشر منشور» منذ دقائق — نعالج الرسالة كنشر ونتأكد من الرد دائماً
@router.message(F.text, _FilterPostFallback())
async def player_post_fallback_recent(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    try:
        chat_target = _normalize_channel_target()
        if not chat_target:
            await message.answer("⚠️ النشر غير متاح حالياً (القناة غير مضبوطة).")
            return
        text = (message.text or "").strip()
        if len(text) > 4000:
            await message.answer("⚠️ النص طويل جداً (حد أقصى 4000 حرف). اختصر ثم أعد المحاولة.")
            return
        ok, reason = check_post_content(text)
        if not ok:
            await message.answer(_violation_message(reason, text) + "\n\nللنشر من جديد: اضغط «تجربة نشر من جديد» أو ادخل مجتمع الأونو ← نشر منشور.", reply_markup=_violation_reply_kb())
            return
        await state.clear()
        name = _get_player_name_for_post(uid, message.from_user.full_name)
        text_to_send = _post_text_html(name, text)
        add_profile, add_play = True, False
        join_code = _create_deferred_2p_room(uid, name) if add_play else None
        reply_kb = _channel_post_buttons(uid, add_profile, join_code)
        sent_msg_id, send_err = await _send_to_channel_safe(message.bot, chat_target, text_to_send, reply_markup=reply_kb)
        if send_err:
            await message.answer(
                "❌ فشل النشر (الحالة انتهت لكن حاولنا النشر).\n\n"
                "تأكد أن البوت مسؤول في القناة وله صلاحية «نشر رسائل». جرّب: مجتمع الأونو ← نشر منشور ثم أرسل رسالتك مرة واحدة.\n\nالخطأ: " + send_err[:180]
            )
            return
        if sent_msg_id is not None:
            try:
                post_id = _save_channel_post_and_get_id(chat_target, sent_msg_id, uid, add_profile, join_code)
                if post_id is not None:
                    new_kb = _channel_post_buttons(uid, add_profile, join_code, post_id=post_id, likes_count=0)
                    if new_kb:
                        try:
                            await message.bot.edit_message_reply_markup(chat_id=chat_target, message_id=sent_msg_id, reply_markup=new_kb)
                        except Exception as e:
                            logger.warning("edit_message_reply_markup (fallback) failed: %s", e)
            except Exception:
                pass
        kb_after = []
        if PUBLISH_CHANNEL_USERNAME:
            kb_after.append([InlineKeyboardButton(text="📢 الذهاب للقناة", url=f"https://t.me/{PUBLISH_CHANNEL_USERNAME.lstrip('@')}")])
        kb_after.append([InlineKeyboardButton(text="🔙 رجوع للقائمة الرئيسية", callback_data="home")])
        ch_txt = f"@{PUBLISH_CHANNEL_USERNAME.lstrip('@')}" if PUBLISH_CHANNEL_USERNAME else "القناة"
        await message.answer("✅ تم نشر منشورك في " + ch_txt + " (تمت المعالجة تلقائياً). اضغط الزر أعلاه لمعاينة القناة.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_after))
    except Exception as e:
        logger.exception("player_post_fallback_recent: uid=%s error", uid)
        try:
            await message.answer(
                "❌ حدث خطأ أثناء النشر.\n\nجرّب: مجتمع الأونو ← نشر منشور ← اضغط «تم، أرسل رسالتك الآن» ثم أرسل رسالتك فوراً. تأكد أن البوت يعمل بنسخة واحدة فقط.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 رجوع", callback_data="post_back")]]),
            )
        except Exception:
            pass
