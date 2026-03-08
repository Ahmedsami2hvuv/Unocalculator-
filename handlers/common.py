import os
import re
import sys
import importlib.util
import logging
from aiogram import Router, types, F
from aiogram.filters import Command, CommandObject, BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from database import db_query
from i18n import t, get_lang, set_lang, TEXTS
import random, string, json, asyncio, uuid, time
from urllib.parse import unquote
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

logger = logging.getLogger(__name__)
router = Router()

# --- اشتراك القناة (CHANNEL_ID) ---
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip() or None  # مثال: @ko_kseb أو -100xxxx

# --- قناة واحدة للنشر (النتائج + منشورات اللاعبين) ---
PUBLISH_CHANNEL_ID = os.getenv("PUBLISH_CHANNEL_ID", "").strip() or None
PUBLISH_CHANNEL_USERNAME = os.getenv("PUBLISH_CHANNEL_USERNAME", "").strip() or None
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip() or None

# تحميل channel_config من نفس مجلد هذا الملف (يعمل أينما شغّلت البوت)
_cc = None
_handlers_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_handlers_dir)
BOT_INFO_FILENAME = "BOT_INFO_MESSAGE.md"
# مسارات محتملة للملف (حتى يعمل مع التشغيل من الجذر أو من داخل الحاوية)
BOT_INFO_CANDIDATES = [
    os.path.join(_handlers_dir, BOT_INFO_FILENAME),
    os.path.join(_project_root, BOT_INFO_FILENAME),
    os.path.join(_project_root, "handlers", BOT_INFO_FILENAME),
    os.path.join(os.getcwd(), "handlers", BOT_INFO_FILENAME),
    os.path.join(os.getcwd(), BOT_INFO_FILENAME),
]


def _read_bot_info_message():
    """يقرأ نص رسالة معلومات البوت من الملف BOT_INFO_MESSAGE.md عند كل طلب (بدون كاش)."""
    for path in BOT_INFO_CANDIDATES:
        try:
            if os.path.isfile(path):
                stat = os.stat(path)
                with open(path, "r", encoding="utf-8") as f:
                    out = f.read().strip()
                if out:
                    # إزالة سطر النسخة من أول الملف إن وُجد (للمطور فقط، لا يظهر للمستخدم)
                    out = re.sub(r"^\s*#\s*BOT_INFO_VERSION=.*\n?", "", out)
                    out = re.sub(r"^\s*<!--\s*BOT_INFO_VERSION.*?-->\s*\n?", "", out, flags=re.IGNORECASE)
                    out = out.strip()
                    if out:
                        logger.info(
                            "BOT_INFO_MESSAGE: loaded from %s (size=%s bytes, mtime=%s)",
                            path, stat.st_size, stat.st_mtime
                        )
                        return out
        except Exception as e:
            logger.debug("BOT_INFO_MESSAGE: could not read %s: %s", path, e)
    logger.warning("BOT_INFO_MESSAGE: file not found, using i18n fallback. Tried: %s", BOT_INFO_CANDIDATES)
    return None


def _markdown_to_html(text):
    """تحويل تنسيق ماركداون بسيط إلى HTML لتيليجرام (ليظهر الخط العريض بشكل صحيح)."""
    if not text:
        return text
    # **نص** -> <b>نص</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    # هروب & فقط (لأن < و > قد تكسر التنسيق)
    text = text.replace("&", "&amp;")
    return text
_config_path = os.path.join(_handlers_dir, "channel_config.py")
if os.path.isfile(_config_path):
    try:
        spec = importlib.util.spec_from_file_location("channel_config", _config_path)
        _cc = importlib.util.module_from_spec(spec)
        sys.modules["channel_config"] = _cc
        spec.loader.exec_module(_cc)
    except Exception as e:
        logger.warning("Could not load channel_config from file: %s", e)
        _cc = None
if _cc is None:
    try:
        from . import channel_config as _cc
    except Exception:
        try:
            import channel_config as _cc
        except Exception:
            pass
if _cc:
    if getattr(_cc, "PUBLISH_CHANNEL_ID", None) is not None:
        PUBLISH_CHANNEL_ID = _cc.PUBLISH_CHANNEL_ID
    if getattr(_cc, "PUBLISH_CHANNEL_USERNAME", None):
        PUBLISH_CHANNEL_USERNAME = _cc.PUBLISH_CHANNEL_USERNAME
    if getattr(_cc, "BOT_USERNAME", None):
        BOT_USERNAME = _cc.BOT_USERNAME

# تحويل PUBLISH_CHANNEL_ID من نص (متغير بيئة) إلى رقم إن لزم — حتى يعمل النشر عند النشر على Railway/Heroku
if PUBLISH_CHANNEL_ID is not None and isinstance(PUBLISH_CHANNEL_ID, str):
    _s = PUBLISH_CHANNEL_ID.strip().strip('"').strip("'")
    if _s:
        try:
            _n = int(_s)
            PUBLISH_CHANNEL_ID = -_n if _n > 0 else _n
        except (TypeError, ValueError):
            PUBLISH_CHANNEL_ID = None
    else:
        PUBLISH_CHANNEL_ID = None

# قيم افتراضية إذا لم تُحمَّل من الملف أو البيئة (تطابق channel_config.py)
if PUBLISH_CHANNEL_ID is None and not (PUBLISH_CHANNEL_USERNAME or "").strip():
    PUBLISH_CHANNEL_ID = -1003308032178
    PUBLISH_CHANNEL_USERNAME = "uno1011"
    BOT_USERNAME = BOT_USERNAME or "UNO101bot"
    logger.info("Using default publish channel: id=%s username=%s", PUBLISH_CHANNEL_ID, PUBLISH_CHANNEL_USERNAME)

# إذا القناة مضبوطة لكن BOT_USERNAME فارغ، استخدم قيمة افتراضية حتى يظهر زر «نشر فوزك»
if (PUBLISH_CHANNEL_ID is not None or PUBLISH_CHANNEL_USERNAME) and not (BOT_USERNAME or "").strip():
    BOT_USERNAME = "UNO101bot"
    logger.info("Publish channel set but BOT_USERNAME was empty; using default: %s", BOT_USERNAME)

# سجل عند التشغيل لمعرفة إن كانت النشر مفعّلة (للتشخيص)
if (PUBLISH_CHANNEL_ID is not None or PUBLISH_CHANNEL_USERNAME) and (BOT_USERNAME or "").strip():
    logger.info("📢 نشر النتائج/المنشورات: مفعّل (قناة=%s، بوت=@%s)", PUBLISH_CHANNEL_ID or PUBLISH_CHANNEL_USERNAME, (BOT_USERNAME or "").strip().lstrip("@"))
    print("📢 نشر النتائج: مفعّل — زر «نشر فوزك» سيظهر للفائز")
else:
    logger.warning("📢 نشر النتائج: معطّل — اضبط PUBLISH_CHANNEL_ID أو PUBLISH_CHANNEL_USERNAME و BOT_USERNAME (في channel_config.py أو متغيرات البيئة)")
    print("⚠️ نشر النتائج: معطّل — اضبط القناة و BOT_USERNAME في channel_config.py أو متغيرات البيئة")

async def is_channel_member(bot, user_id: int) -> bool:
    if not CHANNEL_ID:
        return True
    try:
        m = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return m.status in ("member", "administrator", "creator")
    except Exception:
        return False

def _channel_subscribe_kb():
    if not CHANNEL_ID:
        return None
    s = str(CHANNEL_ID).strip()
    if s.startswith("@"):
        username = s.lstrip("@")
        url = f"https://t.me/{username}"
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📢 اشترك في القناة", url=url)]])
    if s.startswith("-"):
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📢 القناة", url="https://t.me/")]])
    url = f"https://t.me/{s}"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📢 اشترك في القناة", url=url)]])

async def channel_subscribe_message_middleware(handler, event: types.Message, data: dict):
    if not CHANNEL_ID:
        return await handler(event, data)
    user_id = event.from_user.id if event.from_user else None
    if not user_id:
        return await handler(event, data)
    # الأدمن يتخطى اشتراك القناة حتى تصل رسائله (محادثة مع لاعب، نشر في المجتمع، دردشة الغرفة، إلخ)
    if user_id in _get_admin_ids():
        return await handler(event, data)
    # من في وضع «نشر منشور» (خيارات أو انتظار الرسالة) نسمح بمرور رسالته حتى يصل لمعالج النشر
    state = data.get("state")
    if state:
        try:
            s = await state.get_state()
            if s and ("waiting_message" in (s or "") or "waiting_options" in (s or "")):
                return await handler(event, data)
        except Exception:
            pass
    text = (event.text or "").strip()
    # روابط من منشورات القناة: نسمح بالمرور دون اشتراك (بروفايل، لايك، العب معي، add)
    if text.startswith("/start") and (
        "profile_" in text or "add_" in text or "like_" in text or "join_" in text
    ):
        return await handler(event, data)
    # إذا الرسالة /start مع رابط انضمام لغرفة: نحفظ الكود قبل عرض اشتراك القناة حتى لا يضيع
    if text.startswith("/start") and "join_" in text:
        parts = text.split(maxsplit=1)
        if len(parts) >= 2 and parts[1].startswith("join_"):
            code = _normalize_join_code(parts[1])
            if code:
                try:
                    db_query("INSERT INTO users (user_id, username, is_registered) VALUES (%s, %s, FALSE) ON CONFLICT (user_id) DO NOTHING", (user_id, event.from_user.username or ""), commit=True)
                    db_query("UPDATE users SET pending_room_code = %s WHERE user_id = %s", (code, user_id), commit=True)
                except Exception:
                    pass
    if await is_channel_member(event.bot, user_id):
        return await handler(event, data)
    kb = _channel_subscribe_kb()
    if kb and kb.inline_keyboard:
        kb.inline_keyboard.append([InlineKeyboardButton(text="✅ تحقق", callback_data="check_channel_sub")])
    uid = event.from_user.id if event.from_user else 0
    await event.answer(t(uid, "channel_subscribe_required"), reply_markup=kb)
    return

async def channel_subscribe_callback_middleware(handler, event: types.CallbackQuery, data: dict):
    if not CHANNEL_ID:
        return await handler(event, data)
    user_id = event.from_user.id if event.from_user else None
    # الأدمن يتخطى اشتراك القناة دائماً
    if user_id and user_id in _get_admin_ids():
        return await handler(event, data)
    # لا نعترض زر «تحقق» — نترك المعالج يتحقق ويفتح القائمة إن كان مشتركاً
    if getattr(event, "data", None) == "check_channel_sub":
        return await handler(event, data)
    cd = getattr(event, "data", None) or ""
    # أزرار اللعب (ثنائي/جماعي): نسمح بالمرور حتى لو لم يكن مشتركاً في القناة
    if cd.startswith("pl_") or cd.startswith("cl_") or cd.startswith("rs_") or cd.startswith("challenge_") or cd.startswith("clrmul_") or cd.startswith("plmul_") or cd.startswith("colormul_"):
        return await handler(event, data)
    # مجتمع الأونو والنشر: نسمح بالدخول دائماً (القائمة، نشر منشور، منشوراتي، إلخ)
    if cd in ("community_uno_menu", "player_post_start", "post_toggle_profile", "post_toggle_play",
              "post_ready_send", "post_back", "my_posts_list", "player_posts_channel", "my_reports", "help_request", "help_request_back") or cd.startswith("admin_") or cd.startswith("report_") or cd.startswith("user_block_") or cd.startswith("user_unblock_"):
        return await handler(event, data)
    user_id = event.from_user.id if event.from_user else None
    if not user_id:
        return await handler(event, data)
    if await is_channel_member(event.bot, user_id):
        return await handler(event, data)
    try:
        await event.answer()
    except Exception:
        pass
    kb = _channel_subscribe_kb()
    if kb and kb.inline_keyboard:
        kb.inline_keyboard.append([InlineKeyboardButton(text="✅ تحقق", callback_data="check_channel_sub")])
    uid = event.from_user.id if event.from_user else 0
    await event.message.edit_text(t(uid, "channel_subscribe_required"), reply_markup=kb)
    return

router.message.middleware(channel_subscribe_message_middleware)
router.callback_query.middleware(channel_subscribe_callback_middleware)

    
replay_data = {}
random_wait_tasks = {}  # room_id -> asyncio.Task (إلغاؤه عند انضمام لاعب ثانٍ)
pending_invites = {}
pending_next_round = {}
next_round_ready = {}
friend_invite_selections = {}
kick_selections = {}
# رجوع من شاشة البروفايل إلى لوحة المتصدرين (user_id -> callback_data)
_pending_profile_back = {}
# كتم دعوات اللعب: (muter_id, muted_id) -> muted_until (datetime أو None للابد)
invite_mutes = {}
# تعليم تفاعلي: كاش في الذاكرة حتى لو عمود seen_tutorial غير موجود في DB
_tutorial_done_cache = set()

# --- رزمة أونو المرجعية (المصدر الوحيد لعدد وتكوين الأوراق) ---
# الإجمالي 110 ورقة. البوت لا يسحب أبداً من خارج هذه الكومة؛ وإذا نفدت كومة السحب
# يُعاد خلط الأوراق النازلة (ما عدا الورقة العليا) لتكوين كومة سحب جديدة.
#
# 📍 الملفات التي يجب أن تستخدم هذه الدوال (ليست في هذا المجلد إنما في مشروعك):
#    - handlers/room_2p.py  (لعب ثنائي: بداية الجولة، سحب عقوبة، انتهاء وقت الدور)
#    - handlers/room_multi.py (لعب جماعي: نفس الاستخدام)
# في بداية الجولة: draw_pile = create_shuffled_draw_pile()
# عند أي سحب (توزيع أولي أو عقوبة أو +2/+4): drawn = draw_cards_from_pile(draw_pile, discard_pile, n)
# لا تُنشئ أوراقاً عشوائية من خارج الرزمة ولا تسحب بدون draw_cards_from_pile.

UNO_COLORS = ("R", "G", "B", "Y")  # أحمر، أخضر، أزرق، أصفر
UNO_DECK_TOTAL = 110

def build_uno_deck():
    """
    تبني رزمة أونو الكاملة 110 ورقة:
    - أرقام 1–9: ورقتان من كل لون (4 ألوان) = 72
    - رقم 0: ورقة واحدة من كل لون = 4
    - منع (skip): ورقتان من كل لون = 8
    - عكس (reverse): ورقتان من كل لون = 8
    - +2: ورقتان من كل لون = 8
    - جوكر ملون (wild): 4
    - جوكر +4 (wild_draw4): 4
    - أوراق أكشن +1 و +2: ورقة واحدة من كل نوع = 2
    المجموع = 110. لا يُسحب من خارج هذه القائمة أبداً.
    """
    deck = []
    for color in UNO_COLORS:
        deck.append(f"{color}0")
        for n in range(1, 10):
            deck.append(f"{color}{n}")
            deck.append(f"{color}{n}")
        for _ in range(2):
            deck.append(f"{color}_skip")
            deck.append(f"{color}_reverse")
            deck.append(f"{color}_draw2")
    for _ in range(4):
        deck.append("W_wild")
        deck.append("W_draw4")
    deck.append("W_plus1")
    deck.append("W_plus2")
    if len(deck) != UNO_DECK_TOTAL:
        raise RuntimeError(f"عدد الأوراق في الرزمة يجب أن يكون {UNO_DECK_TOTAL}, حصل {len(deck)}")
    return deck


def create_shuffled_draw_pile():
    """تُرجع كومة سحب جديدة (قائمة أوراق مخلوطة) من الرزمة الكاملة. استخدمها عند بداية الجولة."""
    deck = build_uno_deck()
    random.shuffle(deck)
    return deck


def reshuffle_discard_into_draw(discard_pile: list):
    """
    عند نفاد كومة السحب: خذ كل الأوراق النازلة ما عدا الورقة العليا (آخر عنصر)،
    اخلطها واجعلها كومة سحب جديدة. الورقة العليا تبقى على الطاولة.
    يُرجع: (كومة_سحب_جديدة, الورقة_العليا_للمنصة)
    إذا كانت النازلة فارغة أو فيها ورقة واحدة فقط، يُرجع ([], ورقة أو None).
    """
    if not discard_pile:
        return [], None
    if len(discard_pile) == 1:
        return [], discard_pile[0]
    top = discard_pile[-1]
    to_shuffle = discard_pile[:-1]
    random.shuffle(to_shuffle)
    return to_shuffle, top


def draw_cards_from_pile(draw_pile: list, discard_pile: list, count: int) -> list:
    """
    سحب عدد معين من الأوراق من كومة السحب. إذا لم تكفِ الكومة،
    تُعاد خلطة الأوراق النازلة (ما عدا العليا) وتُستخدم ككومة سحب ثم يُكمل السحب.
    يُعدّل draw_pile و discard_pile في المكان (يُفترض أن تكونا قائمتين قابلتين للتعديل).
    يُرجع: قائمة الأوراق المسحوبة (عددها count إن وُجدت أوراق كافية، وإلا ما توفّر).
    """
    drawn = []
    for _ in range(count):
        if not draw_pile:
            new_draw, top = reshuffle_discard_into_draw(discard_pile)
            if not new_draw and top is None:
                break
            if top is not None:
                discard_pile.clear()
                discard_pile.append(top)
            draw_pile.extend(new_draw)
        if not draw_pile:
            break
        drawn.append(draw_pile.pop())
    return drawn

# --- إزالة اللاعب تلقائياً بعد ترك اللعب 5 مرات (للاستدعاء من room_2p / room_multi) ---
_player_skip_count = {}  # (room_id, user_id) -> عدد مرات عدم اللعب
TURN_SKIP_LIMIT = 5

def record_turn_skip(room_id: str, user_id: int) -> bool:
    """
    يُستدعى عندما اللاعب لم يلعب في دوره (انتهى وقت الدور).
    يزيد العداد بواحد. إذا وصل إلى TURN_SKIP_LIMIT (5) تُرجع True = يجب إزالته من اللعب.
    """
    key = (room_id, user_id)
    _player_skip_count[key] = _player_skip_count.get(key, 0) + 1
    return _player_skip_count[key] >= TURN_SKIP_LIMIT

def reset_turn_skip(room_id: str, user_id: int):
    """عندما اللاعب يلعب ورقة، استدعِ هذه الدالة لتصفير عداد تركه."""
    key = (room_id, user_id)
    if key in _player_skip_count:
        del _player_skip_count[key]

def get_turn_skip_count(room_id: str, user_id: int) -> int:
    """عدد مرات ترك اللعب حتى الآن (للعرض أو التحذير)."""
    return _player_skip_count.get((room_id, user_id), 0)

def clear_room_skip_counts(room_id: str):
    """عند انتهاء الجولة أو إغلاق الغرفة، استدعِها لتنظيف العدادات."""
    to_del = [k for k in _player_skip_count if k[0] == room_id]
    for k in to_del:
        del _player_skip_count[k]

# --- إنجازات وبادجات (يُستدعى فتحها من room_2p عند الفوز/نهاية الجولة) ---
ACHIEVEMENTS = {
    "first_win": {"ar": "أول فوز", "en": "First win", "fa": "اولین برد", "emoji": "🏆"},
    "wins_10": {"ar": "10 انتصارات", "en": "10 wins", "fa": "۱۰ برد", "emoji": "🔥"},
    "wins_50": {"ar": "50 انتصاراً", "en": "50 wins", "fa": "۵۰ برد", "emoji": "⭐"},
    "plus4_win": {"ar": "فوز بـ +4", "en": "Won with +4", "fa": "برد با +۴", "emoji": "🌈"},
    "uno_perfect": {"ar": "أونو مثالي", "en": "Perfect Uno", "fa": "اوونوی کامل", "emoji": "🎯"},
}
def get_user_achievements(user_id: int):
    try:
        r = db_query("SELECT achievement_id FROM user_achievements WHERE user_id = %s", (user_id,))
        return [row["achievement_id"] for row in r] if r else []
    except Exception:
        return []
def unlock_achievement(user_id: int, achievement_id: str):
    if achievement_id not in ACHIEVEMENTS:
        return
    try:
        db_query(
            "INSERT INTO user_achievements (user_id, achievement_id) VALUES (%s, %s) ON CONFLICT (user_id, achievement_id) DO NOTHING",
            (user_id, achievement_id), commit=True
        )
    except Exception:
        pass
def format_achievements_badges(uid: int, achievement_ids: list) -> str:
    if not achievement_ids:
        return ""
    parts = []
    for aid in achievement_ids[:10]:
        a = ACHIEVEMENTS.get(aid)
        if not a:
            continue
        lang = get_lang(uid)
        title = a.get(lang) or a.get("ar") or aid
        parts.append(f"{a.get('emoji', '🏅')} {title}")
    return "\n🏅 " + " | ".join(parts) if parts else ""

# --- سجل المباريات وعرض سريع للجولة (للاستدعاء من room_2p / room_multi) ---
def save_round_result(room_id: str, winner_id: int, scores_dict: dict, round_num: int = 1):
    """احفظ نتيجة الجولة في match_results (للسجل والإحصائيات)."""
    try:
        db_query(
            "INSERT INTO match_results (room_id, round_num, winner_id, scores_json) VALUES (%s, %s, %s, %s)",
            (room_id, round_num, json.dumps(scores_dict) if isinstance(scores_dict, dict) else str(scores_dict), winner_id),
            commit=True
        )
    except Exception:
        pass

def get_round_summary_text(uid: int, winner_name: str, scores_list: list) -> str:
    """نص ملخص الجولة: من فاز ونقاط الجميع. scores_list = [(name, points), ...]"""
    lines = [f"🏆 {winner_name} " + t(uid, "round_summary_won")]
    for name, pts in (scores_list or [])[:10]:
        lines.append(f"  • {name}: {pts}")
    return "\n".join(lines)

def prepare_replay_after_game(room_id: str, creator_id: int, max_players: int, score_limit: int, player_ids: list) -> tuple:
    """لإعادة اللعب السريع: يخزن بيانات الغرفة ويُرجع (replay_id, message_text, InlineKeyboardMarkup) لإرساله لكل لاعب."""
    replay_id = f"{room_id}_{creator_id}_{int(__import__('time').time())}"
    replay_data[replay_id] = {
        "creator_id": creator_id,
        "max_players": max_players,
        "score_limit": score_limit,
        "player_ids": list(player_ids) if player_ids else [],
    }
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 لعب مرة أخرى", callback_data=f"replay_{replay_id}")],
        [InlineKeyboardButton(text=t(creator_id, "btn_home"), callback_data="home")]
    ])
    msg = "🏁 انتهت الجولة! اضغط «لعب مرة أخرى» لدعوة نفس الفريق."
    return replay_id, msg, kb


def _get_replay_from_db(replay_id: str):
    """جلب جلسة replay من قاعدة البيانات (لنشر الفوز يعمل حتى من worker آخر)."""
    try:
        row = db_query(
            "SELECT summary, winner_id, players_json, badge_earned FROM replay_sessions WHERE replay_id = %s",
            (replay_id,)
        )
        if not row:
            return None
        r = row[0]
        players = []
        if r.get("players_json"):
            try:
                raw = json.loads(r["players_json"])
                for x in raw:
                    if isinstance(x, (list, tuple)) and len(x) >= 2:
                        players.append((int(x[0]), str(x[1]) or "لاعب"))
                    elif isinstance(x, dict):
                        players.append((int(x.get("user_id") or 0), str(x.get("player_name") or "لاعب")))
            except Exception:
                pass
        out = {
            "summary": r.get("summary") or "🏁 انتهت الجولة!",
            "winner_id": r.get("winner_id"),
            "players": players,
        }
        if r.get("badge_earned") is not None:
            out["badge_just_earned"] = r.get("badge_earned")
        return out
    except Exception:
        try:
            row = db_query(
                "SELECT summary, winner_id, players_json FROM replay_sessions WHERE replay_id = %s",
                (replay_id,)
            )
            if not row:
                return None
            r = row[0]
            players = []
            if r.get("players_json"):
                try:
                    raw = json.loads(r["players_json"])
                    for x in raw:
                        if isinstance(x, (list, tuple)) and len(x) >= 2:
                            players.append((int(x[0]), str(x[1]) or "لاعب"))
                        elif isinstance(x, dict):
                            players.append((int(x.get("user_id") or 0), str(x.get("player_name") or "لاعب")))
                except Exception:
                    pass
            return {
                "summary": r.get("summary") or "🏁 انتهت الجولة!",
                "winner_id": r.get("winner_id"),
                "players": players,
            }
        except Exception:
            return None


def create_replay_session(players: list, room: dict, mode: str, summary_text: str, winner_id: int = None, badge_just_earned: str = None) -> str:
    """ينشئ جلسة replay واحدة لكل اللاعبين ويخزن الملخص. winner_id: للاعب الفائز. badge_just_earned: نص الشارة إن حصل عليها الآن (لزر انشر شارتك)."""
    replay_id = str(uuid.uuid4())[:8]
    players_list = [(p["user_id"], p.get("player_name") or "لاعب") for p in players]
    replay_data[replay_id] = {
        "players": players_list,
        "max_players": room.get("max_players", 2),
        "score_limit": room.get("score_limit", 0),
        "mode": mode,
        "creator_id": room.get("creator_id"),
        "summary": summary_text,
        "winner_id": winner_id,
        "badge_just_earned": badge_just_earned,
    }
    try:
        db_query(
            """CREATE TABLE IF NOT EXISTS replay_sessions (
                replay_id VARCHAR(16) PRIMARY KEY,
                summary TEXT,
                winner_id BIGINT,
                players_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            commit=True
        )
    except Exception:
        pass
    try:
        db_query(
            "INSERT INTO replay_sessions (replay_id, summary, winner_id, players_json) VALUES (%s, %s, %s, %s)",
            (replay_id, summary_text, winner_id, json.dumps(players_list)),
            commit=True
        )
    except Exception:
        pass
    if badge_just_earned:
        try:
            db_query("ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS badge_earned TEXT", commit=True)
            db_query("UPDATE replay_sessions SET badge_earned = %s WHERE replay_id = %s", (badge_just_earned, replay_id), commit=True)
        except Exception:
            pass
    return replay_id


def build_game_end_keyboard(replay_id: str, for_user_id: int) -> InlineKeyboardMarkup:
    """كيبورد نهاية اللعبة: كل اللاعبين مع (✓ أتابعه، ➕ لا أتابعه، 📥 يتابعني، 🔄 نتابع بعض) وزر متابعة/إلغاء. الضغط على متابعة لا يخفي القائمة."""
    rdata = replay_data.get(replay_id)
    if not rdata and replay_id:
        rdata = _get_replay_from_db(replay_id)
    if not rdata:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="home")]
        ])
    players = rdata.get("players") or []
    if not players and rdata.get("player_ids"):
        for pid in rdata["player_ids"]:
            if pid == for_user_id:
                continue
            row = db_query("SELECT player_name FROM users WHERE user_id = %s", (pid,))
            pname = (row[0]["player_name"] if row else None) or "لاعب"
            players.append((pid, pname))
    kb = []
    for pid, pname in players:
        if pid == for_user_id:
            continue
        is_following = db_query(
            "SELECT 1 FROM follows WHERE follower_id = %s AND following_id = %s",
            (for_user_id, pid)
        )
        is_follower = db_query(
            "SELECT 1 FROM follows WHERE follower_id = %s AND following_id = %s",
            (pid, for_user_id)
        )
        if is_following and is_follower:
            icon = "🔄"
            status_label = "نتابع بعض"
            btn_text = "إلغاء المتابعة"
            cb = f"gameend_f_{replay_id}_{pid}"
        elif is_following:
            icon = "✓"
            status_label = "أتابعه"
            btn_text = "إلغاء المتابعة"
            cb = f"gameend_f_{replay_id}_{pid}"
        elif is_follower:
            icon = "📥"
            status_label = "يتابعني"
            btn_text = "متابعة"
            cb = f"gameend_f_{replay_id}_{pid}"
        else:
            icon = "➕"
            status_label = ""
            btn_text = "متابعة"
            cb = f"gameend_f_{replay_id}_{pid}"
        pname_short = (pname or "لاعب")[:16]
        row_label = f"{icon} {pname_short}" + (f" ({status_label})" if status_label else "")
        kb.append([
            InlineKeyboardButton(text=row_label, callback_data=f"gameend_p_{replay_id}_{pid}"),
            InlineKeyboardButton(text=btn_text, callback_data=cb)
        ])
    winner_id = rdata.get("winner_id")
    if winner_id is not None:
        try:
            winner_id = int(winner_id)
        except (TypeError, ValueError):
            winner_id = None
    if winner_id and for_user_id == winner_id and (PUBLISH_CHANNEL_ID or PUBLISH_CHANNEL_USERNAME) and BOT_USERNAME:
        share_btn_text = "📢 نشر فوزك"
        try:
            row = db_query("SELECT online_points FROM users WHERE user_id = %s", (winner_id,))
            if row:
                pts = int(row[0].get("online_points") or 0)
                if pts >= 0:
                    share_btn_text = f"📢 نشر فوزك ({pts} نقطة)"
        except Exception:
            pass
        kb.append([InlineKeyboardButton(text=share_btn_text, callback_data=f"share_result_{replay_id}")])
    badge_earned = rdata.get("badge_just_earned") or (rdata.get("badge_earned") if isinstance(rdata.get("badge_earned"), str) else None)
    if winner_id and for_user_id == winner_id and badge_earned and (PUBLISH_CHANNEL_ID or PUBLISH_CHANNEL_USERNAME):
        kb.append([InlineKeyboardButton(text=t(for_user_id, "badge_publish_btn"), callback_data=f"publish_badge_{replay_id}")])
    kb.append([InlineKeyboardButton(text="🔄 لعب مرة أخرى", callback_data=f"replay_{replay_id}")])
    if replay_id and str(replay_id) != "None":
        kb.append([InlineKeyboardButton(text="📋 تبليغ على لاعب", callback_data=f"report_{replay_id}")])
    kb.append([InlineKeyboardButton(text=t(for_user_id, "btn_home"), callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


# مشاهدون الغرفة (للوضع مشاهدة: room_id -> set(user_id))
room_spectators = {}


def get_user_current_room(user_id: int):
    """إذا كان اللاعب داخل غرفة (انتظار أو لعب)، يُرجع (room_id, room, players) وإلا None."""
    rp = db_query(
        """SELECT rp.room_id, rp.player_name
           FROM room_players rp
           INNER JOIN rooms r ON r.room_id = rp.room_id
           WHERE rp.user_id = %s AND r.status IN ('waiting', 'playing')
           LIMIT 1""",
        (user_id,)
    )
    if not rp:
        return None
    room_id = rp[0]["room_id"]
    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
    if not room:
        return None
    players = db_query("SELECT user_id, player_name FROM room_players WHERE room_id = %s", (room_id,))
    return (room_id, room[0], players or [])


class RoomStates(StatesGroup):
    wait_for_code = State()
    # الحالات الجديدة للتسجيل المطور والترقية
    reg_ask_username = State()
    reg_ask_password = State()
    reg_ask_name = State()
    upgrade_username = State()
    upgrade_password = State()
    search_user = State()
    # ابقينا القديمة لضمان عدم تعطل أي كود مرتبط بها حالياً
    edit_name = State()
    edit_username = State()
    edit_password = State()
    register_name = State()
    register_password = State()
    login_name = State()
    login_password = State()
    complete_profile_name = State()
    complete_profile_password = State()
    help_request = State()
    chat_with_admin = State()  # محادثة مع الإدارة (بعد قبول طلب المحادثة)


# مجتمع الأونو والنشر: تم نقله إلى handlers/community_publish.py

persistent_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="♻️تحديث♻️"), KeyboardButton(text="🧹 تنظيف الرسائل")]],
    resize_keyboard=True,
    persistent=True
)


async def _clean_then_show_menu(message: types.Message):
    """مسح رسائل البوت في المحادثة ثم عرض القائمة. يستخدمه زرّا القائمة الرئيسية وتنظيف الرسائل."""
    chat_id = message.chat.id
    current_msg_id = message.message_id
    for mid in range(current_msg_id, max(current_msg_id - 200, 0), -1):
        try:
            await message.bot.delete_message(chat_id, mid)
        except Exception:
            pass
    name = message.from_user.full_name
    user = db_query("SELECT player_name FROM users WHERE user_id = %s", (message.from_user.id,))
    if user:
        name = user[0]['player_name']
    await show_main_menu(message, name, user_id=message.from_user.id, cleanup=False)


@router.message(F.text == "🧹 تنظيف الرسائل")
async def clean_chat_messages(message: types.Message):
    """زر تنظيف الرسائل: مسح الرسائل ثم القائمة."""
    await _clean_then_show_menu(message)


@router.message(F.text == "♻️تحديث♻️")
async def main_menu_button(message: types.Message, state: FSMContext):
    """زر ♻️تحديث♻️: يحدّث البيانات ويعرض القائمة كما لو اللاعب ضغط /start."""
    uid = message.from_user.id
    try:
        db_query("UPDATE users SET username = %s WHERE user_id = %s", (message.from_user.username or "", uid), commit=True)
    except Exception:
        pass
    user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    if not user:
        try:
            db_query(
                "INSERT INTO users (user_id, username, is_registered) VALUES (%s, %s, FALSE) ON CONFLICT (user_id) DO NOTHING",
                (uid, message.from_user.username or ""),
                commit=True,
            )
        except Exception:
            pass
        user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    if user and user[0].get("is_banned") in (True, 1, "t", "true"):
        await message.answer(t(uid, "banned_from_bot"))
        return
    if user and user[0].get("logged_out") in (True, 1, "t", "true"):
        lang = get_lang(uid)
        set_lang(uid, lang)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(uid, "btn_register"), callback_data="auth_register")],
                [InlineKeyboardButton(text=t(uid, "btn_login"), callback_data="auth_login")],
            ]
        )
        await message.answer(t(uid, "welcome_new"), reply_markup=kb)
        return
    name = user[0]["player_name"] if user else message.from_user.full_name
    await show_main_menu(message, name, user_id=uid, state=state)


class FilterInRoom(BaseFilter):
    """يمرّر فقط إذا كان المرسل داخل غرفة (انتظار أو لعب). لا يمرّر إذا كان في وضع نشر منشور أو تبليغ أو طلب مساعدة."""
    async def __call__(self, *args, **kwargs) -> bool:
        event = args[0] if args else kwargs.get("event")
        data = args[1] if len(args) > 1 else kwargs.get("data", {})
        if event is None:
            return False
        if not isinstance(data, dict):
            data = {}
        user_id = getattr(getattr(event, "from_user", None), "id", None) or 0
        # رسائل الأدمن لا تُعتبر أبداً «دردشة غرفة» — حتى لو داخل غرفة، لا نذيعها ولا نحذفها (محادثة مع لاعب، نشر، إلخ)
        if user_id in _get_admin_ids():
            return False
        state = data.get("state")
        if state is not None:
            try:
                s = await state.get_state() or ""
                # عدم أخذ الرسالة كـ «محادثة غرفة» إذا المستخدم في وضع آخر (بما فيه محادثة الأدمن مع لاعب)
                if (s or "").startswith("admin:"):
                    return False
                if "admin_chat_with_user" in (s or ""):
                    return False
                if "waiting_message" in s or "waiting_options" in s:
                    return False
                if "report_upload" in s or "report_more" in s or "report_confirm" in s:
                    return False
                if "help_request" in s:
                    return False
            except Exception:
                pass
        # حتى لو FSM ضاعت (مثلاً worker آخر): إذا لديه طلب مساعدة معلّق فلا نأخذ رسالته للغرفة
        if _has_pending_help_request(user_id):
            return False
        return get_user_current_room(user_id) is not None


# مراجع لمهام الحذف المؤجل حتى لا تُهمل من الـ event loop
_delete_after_tasks = set()

async def _delete_message_after(bot, chat_id: int, message_id: int, seconds: int = 10):
    """حذف رسالة بعد ثوانٍ بدون تنبيه. يعيد المحاولة مرة إن فشل الحذف (مثلاً لو حُذفت من مكان آخر)."""
    try:
        await asyncio.sleep(seconds)
        try:
            await bot.delete_message(chat_id, message_id)
        except Exception:
            await asyncio.sleep(0.5)
            try:
                await bot.delete_message(chat_id, message_id)
            except Exception:
                pass
    except asyncio.CancelledError:
        raise
    except Exception:
        pass
    finally:
        try:
            _delete_after_tasks.discard(asyncio.current_task())
        except Exception:
            pass


async def send_message_then_delete(bot, chat_id: int, text: str, delete_after_seconds: int = 5, **kwargs):
    """
    يرسل رسالة ثم يحذفها تلقائياً بعد ثوانٍ (بدون تنبيه).
    للاستخدام في room_2p و room_multi لتنبيهات اللعب (قبل السحب، فشل التحدي، إلخ)
    حتى تبقى لوحة اللعب فقط ظاهرة.
    """
    try:
        sent = await bot.send_message(chat_id, text, **kwargs)
        delete_coro = _delete_message_after(bot, chat_id, sent.message_id, delete_after_seconds)
        task = asyncio.create_task(asyncio.shield(delete_coro))
        _delete_after_tasks.add(task)
        task.add_done_callback(lambda t: _delete_after_tasks.discard(t))
        return sent
    except Exception:
        return None


async def _send_media_copy(bot, chat_id: int, message: types.Message, sender_name: str):
    """إعادة إرسال نسخة من الرسالة (نص/صورة/صوت/فيديو/ملصق/...) مع توقيع المرسل. يُرجع message_id أو None."""
    cap = f"👤 {sender_name}\n\n{(message.caption or '').strip()}"
    if cap.endswith("\n\n"):
        cap = cap.rstrip()
    try:
        if message.text:
            sent = await bot.send_message(chat_id, f"👤 {sender_name}\n\n{message.text}")
            return sent.message_id
        if message.photo:
            sent = await bot.send_photo(chat_id, message.photo[-1].file_id, caption=cap or None)
            return sent.message_id
        if message.voice:
            sent = await bot.send_voice(chat_id, message.voice.file_id, caption=cap or None)
            return sent.message_id
        if message.video:
            sent = await bot.send_video(chat_id, message.video.file_id, caption=cap or None)
            return sent.message_id
        if message.animation:
            sent = await bot.send_animation(chat_id, message.animation.file_id, caption=cap or None)
            return sent.message_id
        if message.sticker:
            sent = await bot.send_sticker(chat_id, message.sticker.file_id)
            return sent.message_id
        if message.document:
            sent = await bot.send_document(chat_id, message.document.file_id, caption=cap or None)
            return sent.message_id
        if message.audio:
            sent = await bot.send_audio(chat_id, message.audio.file_id, caption=cap or None)
            return sent.message_id
        if message.video_note:
            sent = await bot.send_video_note(chat_id, message.video_note.file_id)
            return sent.message_id
    except Exception:
        pass
    return None


@router.message(FilterInRoom())
async def room_chat_broadcast(message: types.Message, state: FSMContext):
    """نظام محادثة الغرفة: أي رسالة (نص، صورة، صوت، فيديو، ملصق، ...) من لاعب داخل الغرفة تُذاع للباقين وتُحذف بعد 10 ثوانٍ."""
    # حماية إضافية: لا نذيع ولا نحذف أبداً رسائل الأدمن أو من في وضع النشر/محادثة
    uid = message.from_user.id if message.from_user else 0
    if uid in _get_admin_ids():
        return
    try:
        s = await state.get_state() or ""
        if "waiting_message" in s or "waiting_options" in s or "admin_chat_with_user" in (s or ""):
            return
    except Exception:
        pass
    if message.text and (message.text.strip().startswith("/") and message.text.strip().lower() != "/start"):
        return
    if not message.text and not message.photo and not message.voice and not message.video and not message.animation and not message.sticker and not message.document and not message.audio and not message.video_note:
        return
    info = get_user_current_room(message.from_user.id)
    if not info:
        return
    room_id, room, players = info
    sender_name = None
    for p in players:
        if p["user_id"] == message.from_user.id:
            sender_name = p.get("player_name") or message.from_user.full_name or "لاعب"
            break
    if not sender_name:
        sender_name = message.from_user.full_name or "لاعب"
    for p in players:
        if p["user_id"] == message.from_user.id:
            continue
        try:
            mid = await _send_media_copy(message.bot, p["user_id"], message, sender_name)
            if mid:
                t = asyncio.create_task(_delete_message_after(message.bot, p["user_id"], mid, 10))
                _delete_after_tasks.add(t)
                t.add_done_callback(lambda x: _delete_after_tasks.discard(x))
        except Exception:
            pass
    t2 = asyncio.create_task(_delete_message_after(message.bot, message.chat.id, message.message_id, 10))
    _delete_after_tasks.add(t2)
    t2.add_done_callback(lambda x: _delete_after_tasks.discard(x))


def generate_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))


def _normalize_join_code(payload: str) -> str:
    """استخراج وتنظيف كود الغرفة من رابط الانضمام. يزيل أي رمز زائد (مثل ` أو مسافات)."""
    if not payload or not payload.startswith("join_"):
        return ""
    raw = unquote(payload[5:].strip())
    if not raw:
        return ""
    # كود الغرفة أحرف إنجليزية وأرقام فقط (مثل T736MG). إزالة أي شيء آخر يلصق بالرابط
    allowed = set(string.ascii_letters + string.digits)
    code = "".join(c for c in raw if c in allowed)[:15]
    return code.upper() if code else ""


async def process_start_deeplink(message: types.Message, payload: str, state: FSMContext) -> bool:
    """معالجة روابط أزرار القناة (like_، profile_، join_). تُستدعى من معالج /start أو من community_publish.
    تُرجع True إذا تمت المعالجة وتم إرسال رد للمستخدم."""
    if not payload or not isinstance(payload, str):
        return False
    payload = payload.strip()
    if payload.startswith("like_"):
        try:
            post_id = int(payload.replace("like_", ""))
        except ValueError:
            post_id = None
        if post_id:
            row = db_query("SELECT publisher_uid, channel_id, message_id, likes_count FROM channel_posts WHERE id = %s", (post_id,))
            if row:
                db_query(
                    "UPDATE channel_posts SET likes_count = COALESCE(likes_count, 0) + 1 WHERE id = %s",
                    (post_id,), commit=True
                )
                publisher_uid = row[0]["publisher_uid"]
                ch_id = row[0]["channel_id"]
                msg_id = row[0]["message_id"]
                new_count = (row[0].get("likes_count") or 0) + 1
                try:
                    await message.bot.send_message(
                        publisher_uid,
                        f"❤️ منشورك حصل على لايك! العدد الحالي: {new_count}"
                    )
                except Exception:
                    pass
                try:
                    r2 = db_query(
                        "SELECT publisher_uid, add_profile, join_code FROM channel_posts WHERE id = %s",
                        (post_id,)
                    )
                    if r2:
                        uid_pub = r2[0]["publisher_uid"]
                        add_p = r2[0].get("add_profile", True)
                        jc = r2[0].get("join_code")
                        new_kb = _channel_post_buttons(uid_pub, add_p, jc, post_id=post_id, likes_count=new_count)
                        if new_kb:
                            try:
                                _ch = int(ch_id) if str(ch_id).lstrip("-").isdigit() else ch_id
                                await message.bot.edit_message_reply_markup(chat_id=_ch, message_id=msg_id, reply_markup=new_kb)
                            except Exception:
                                pass
                except Exception:
                    pass
                await message.answer(f"❤️ تم! عدد لايكات المنشور: {new_count}")
                return True
        await message.answer(t(message.from_user.id, "thanks"))
        return True
    if payload.startswith("profile_") or payload.startswith("add_"):
        rest = payload.split("_", 1)[1]
        post_id = None
        target_id = None
        lb_back = None
        try:
            rest_parts = [p for p in rest.split("_") if p]
            if rest_parts:
                try:
                    target_id = int(rest_parts[0])
                except ValueError:
                    target_id = None
                if len(rest_parts) >= 2 and rest_parts[1].isdigit():
                    post_id = int(rest_parts[1])
                if "lb" in rest_parts:
                    lb_i = rest_parts.index("lb")
                    if lb_i + 1 < len(rest_parts):
                        mode = rest_parts[lb_i + 1].strip().lower()
                        if mode in ("global", "friends"):
                            lb_back = "leaderboard_global" if mode == "global" else "leaderboard_friends"
        except Exception:
            pass
        if target_id:
            uid = message.from_user.id
            if lb_back:
                _pending_profile_back[uid] = lb_back
            else:
                _pending_profile_back.pop(uid, None)
            if post_id:
                try:
                    db_query(
                        "UPDATE channel_posts SET profile_clicks_count = COALESCE(profile_clicks_count, 0) + 1 WHERE id = %s",
                        (post_id,), commit=True
                    )
                except Exception:
                    pass
            target = db_query("SELECT * FROM users WHERE user_id = %s", (target_id,))
            if target:
                t_user = target[0]
                if _is_user_blocked(target_id, uid):
                    name = (t_user.get("player_name") or "لاعب")[:50]
                    profile_text = f"⛔ **اللاعب {name} قام بحظرك.**\n\nلا يمكنك عرض بروفايله أو إرسال دعوة له."
                    kb = _profile_back_only_kb(uid, None, from_channel=True)
                    await message.answer(profile_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
                    return True
                profile_text = _build_profile_text(uid, t_user, target_id)
                kb = _build_profile_kb(uid, target_id, from_channel=True)
                await message.answer(profile_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
                return True
            else:
                await message.answer(t(message.from_user.id, "player_not_found"))
                return True
    if payload.startswith("join_"):
        code = _normalize_join_code(payload)
        if code:
            user = db_query("SELECT * FROM users WHERE user_id = %s", (message.from_user.id,))
            if user and user[0].get("is_registered"):
                await _join_room_by_code(message, code, user[0])
                return True
            if not user:
                db_query(
                    "INSERT INTO users (user_id, username, is_registered) VALUES (%s, %s, FALSE)",
                    (message.from_user.id, message.from_user.username or ""),
                    commit=True,
                )
            try:
                db_query("UPDATE users SET pending_room_code = %s WHERE user_id = %s", (code, message.from_user.id), commit=True)
            except Exception:
                pass
            await state.update_data(pending_join=code)
            uid = message.from_user.id
            lang = get_lang(uid)
            set_lang(uid, lang)
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=t(uid, "btn_register"), callback_data="auth_register")],
                    [InlineKeyboardButton(text=t(uid, "btn_login"), callback_data="auth_login")],
                ]
            )
            welcome = t(uid, "welcome_new") + "\n\n" + t(uid, "invite_pending_room")
            await message.answer(welcome, reply_markup=kb)
            return True
        else:
            await message.answer(t(message.from_user.id, "invalid_join_link"))
            return True
    return False


@router.message(Command("start"))
async def cmd_start_with_deeplink(message: types.Message, state: FSMContext, command: CommandObject = None):
    """معالجة /start مع رابط الدعوة (أزرار القناة تُعالَج أولاً في community_publish)."""
    payload = ""
    if command and getattr(command, "args", None):
        payload = (command.args or "").strip()
    if not payload and message.text:
        text = (message.text or "").strip()
        if text.startswith("/start") and len(text) > 6:
            rest = text[6:].strip()
            if rest:
                payload = unquote(rest.split(maxsplit=1)[0] if rest.split() else rest)
    if payload and (payload.startswith("like_") or payload.startswith("profile_") or payload.startswith("add_") or payload.startswith("join_")):
        if await process_start_deeplink(message, payload, state):
            return
    uid = message.from_user.id
    try:
        db_query("UPDATE users SET username = %s WHERE user_id = %s", (message.from_user.username or "", uid), commit=True)
    except Exception:
        pass
    user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    # مستخدم جديد: إنشاء سجل له حتى لا يخرج show_main_menu دون رد
    if not user:
        try:
            db_query(
                "INSERT INTO users (user_id, username, is_registered) VALUES (%s, %s, FALSE) ON CONFLICT (user_id) DO NOTHING",
                (uid, message.from_user.username or ""),
                commit=True,
            )
        except Exception:
            pass
        user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    # إذا كان محظوراً، نعرض رسالة الحظر فقط
    if user and user[0].get("is_banned") in (True, 1, "t", "true"):
        await message.answer(t(uid, "banned_from_bot"))
        return
    # إذا كان مسجّل الخروج، نعرض تسجيل/دخول ولا نفتح القائمة الرئيسية
    if user and user[0].get("logged_out") in (True, 1, "t", "true"):
        lang = get_lang(uid)
        set_lang(uid, lang)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(uid, "btn_register"), callback_data="auth_register")],
                [InlineKeyboardButton(text=t(uid, "btn_login"), callback_data="auth_login")],
            ]
        )
        await message.answer(t(uid, "welcome_new"), reply_markup=kb)
        return
    name = user[0]["player_name"] if user else message.from_user.full_name
    await show_main_menu(message, name, user_id=uid, state=state)


@router.message(RoomStates.upgrade_username)
async def process_upgrade_username(message: types.Message, state: FSMContext):
    new_username = message.text.strip().lower()

    # التأكد من الطول وشكل اليوزر
    if len(new_username) < 3 or not new_username.isalnum():
        return await message.answer(t(message.from_user.id, "username_3_chars"))

    # التأكد إذا اليوزر محجوز لغير لاعب
    check = db_query("SELECT user_id FROM users WHERE username_key = %s", (new_username,))
    if check:
        return await message.answer(t(message.from_user.id, "username_taken"))

    # حفظ اليوزر مؤقتاً بالـ state والانتقال لطلب كلمة السر
    await state.update_data(temp_username=new_username)
    await message.answer(t(message.from_user.id, "username_ok_send_password"))
    await state.set_state(RoomStates.upgrade_password)

@router.message(RoomStates.upgrade_password)
async def process_upgrade_password(message: types.Message, state: FSMContext):
    password = message.text.strip()
    if len(password) < 4:
        return await message.answer(t(message.from_user.id, "password_4_chars"))

    data = await state.get_data()
    username = data.get('temp_username')

    # تحديث قاعدة البيانات بشكل نهائي
    db_query(
        "UPDATE users SET username_key = %s, password_key = %s WHERE user_id = %s",
        (username, password, message.from_user.id),
        commit=True,
    )

    user = db_query("SELECT player_name FROM users WHERE user_id = %s", (message.from_user.id,))
    name = user[0]['player_name'] if user else message.from_user.full_name

    await message.answer(f"🎉 مبارك! تم تحديث حسابك بنجاح.\n👤 يوزرك: @{username}\n🔑 كلمة السر: {password}")
    
    # نرجعه للمنيو الرئيسي (مع عرض سؤال التدريب إن كان أول مرة)
    await _show_training_offer_or_main(message, name, message.from_user.id, state=state, from_registration=True)


@router.callback_query(F.data == "play_friends")
async def on_play_friends(c: types.CallbackQuery):
    if await _ask_badge_color_if_needed(c):
        return
    uid = c.from_user.id
    text = "🎮 **اللعب مع الأصدقاء**\n\nاختر:"
    kb = [
        [InlineKeyboardButton(text="➕ إنشاء غرفة", callback_data="room_create_start")],
        [InlineKeyboardButton(text="🔑 دخول بكود", callback_data="room_join_input")],
        [InlineKeyboardButton(text="🚪 الغرف المتوفرة", callback_data="available_rooms")],
        [InlineKeyboardButton(text="📋 الغرف المفتوحة", callback_data="my_open_rooms")],
        [InlineKeyboardButton(text=t(uid, "btn_public_rooms"), callback_data="public_rooms")],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="home")]
    ]
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")


@router.message(RoomStates.upgrade_username)
async def process_username_step(message: types.Message, state: FSMContext):
    print("DEBUG: وصلت رسالة اليوزر نيم")
    user_id = message.from_user.id
    username = message.text.strip().lower()

    # التحقق من شروط اليوزرنيم
    if not username.isalnum() or len(username) < 3:
        await message.answer(t(message.from_user.id, "enter_username_prompt"))
        return

    check = db_query("SELECT user_id FROM users WHERE username_key = %s", (username,))
    if check:
        await message.answer(t(message.from_user.id, "username_in_use"))
        return

    db_query("UPDATE users SET username_key = %s WHERE user_id = %s", (username, user_id), commit=True)
    user_info = db_query("SELECT player_name FROM users WHERE user_id = %s", (user_id,))
    p_name = user_info[0]['player_name'] if user_info else "لاعب"

    await message.answer(f"✅ تم اختيار اليوزر: {username}\n🎉 تم تفعيل حسابك!")
    await state.clear()
    await _show_training_offer_or_main(message, p_name, user_id, state=state, from_registration=True)

@router.message(RoomStates.upgrade_password)
async def process_password_step(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    password = message.text.strip()
    
    # التأكد من طول الباسورد
    if len(password) < 4:
        return await message.answer(t(user_id, "password_too_short"))

    data = await state.get_data()
    username = data['chosen_username']
    current_state = await state.get_state()
    
    if current_state == RoomStates.upgrade_password:
        # حالة الترقية: اللاعب مسجل أصلاً بس ينقصه يوزر وباسورد جديد
        db_query(
            "UPDATE users SET username_key = %s, password_key = %s WHERE user_id = %s",
            (username, password, user_id),
            commit=True,
        )
        user_info = db_query("SELECT player_name FROM users WHERE user_id = %s", (user_id,))
        p_name = user_info[0]['player_name'] if user_info else "لاعب"
        await message.answer(t(user_id, "reg_success", name=p_name, username=username))
        await state.clear()
        await _show_training_offer_or_main(message, p_name, user_id, state=state, from_registration=True)
    else:
        # حالة التسجيل الجديد: نحفظ اليوزر والباسورد مؤقتاً ونطلب "الاسم"
        await state.update_data(chosen_password=password)
        await message.answer(t(user_id, "ask_name"))
        await state.set_state(RoomStates.reg_ask_name)

@router.message(RoomStates.reg_ask_name)
async def process_final_name(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    name = message.text.strip()[:20]
    
    if len(name) < 2:
        return await message.answer(t(user_id, "name_too_short"))

    data = await state.get_data()
    username = data['chosen_username']
    password = data['chosen_password']
    
    # حفظ اللاعب الجديد كلياً في القاعدة
    db_query("""INSERT INTO users (user_id, username_key, password_key, player_name, is_registered) 
    VALUES (%s, %s, %s, %s, TRUE)""", 
    (user_id, username, password, name), commit=True)
    
    await message.answer(t(user_id, "reg_success", name=name, username=username))
    await state.clear()
    await _show_training_offer_or_main(message, name, user_id, state=state, from_registration=True)
    


@router.callback_query(F.data.startswith("set_lang_"))
async def set_lang_callback(c: types.CallbackQuery, state: FSMContext):
    lang = c.data.split("_")[-1]
    uid = c.from_user.id
    user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    if user:
        db_query("UPDATE users SET language = %s WHERE user_id = %s", (lang, uid), commit=True)
    else:
        db_query("INSERT INTO users (user_id, username, language, is_registered) VALUES (%s, %s, %s, FALSE)", (uid, c.from_user.username or '', lang), commit=True)
    set_lang(uid, lang)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "btn_register"), callback_data="auth_register")],
        [InlineKeyboardButton(text=t(uid, "btn_login"), callback_data="auth_login")]
    ])
    await c.message.edit_text(t(uid, "welcome_new"), reply_markup=kb)

@router.callback_query(F.data == "cp_name_ok")
async def cp_name_ok(c: types.CallbackQuery, state: FSMContext):
    uid = c.from_user.id
    await c.message.edit_text(t(uid, "ask_password"))
    await state.set_state(RoomStates.complete_profile_password)

@router.callback_query(F.data == "cp_edit_name")
async def cp_edit_name(c: types.CallbackQuery, state: FSMContext):
    uid = c.from_user.id
    await c.message.edit_text(t(uid, "ask_name"))
    await state.set_state(RoomStates.complete_profile_name)

@router.message(RoomStates.complete_profile_name)
async def complete_profile_name_handler(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    name = message.text.strip()
    if not name or len(name) < 2:
        await message.answer(t(uid, "name_too_short"))
        return
    if len(name) > 20:
        await message.answer(t(uid, "name_too_long"))
        return
    existing = db_query("SELECT * FROM users WHERE player_name = %s AND user_id != %s", (name, uid))
    if existing:
        await message.answer(t(uid, "name_taken"))
        return
    db_query("UPDATE users SET player_name = %s WHERE user_id = %s", (name, uid), commit=True)
    await message.answer(t(uid, "ask_password"))
    await state.set_state(RoomStates.complete_profile_password)

@router.message(RoomStates.complete_profile_password)
async def complete_profile_password_handler(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    password = message.text.strip()
    if len(password) < 4:
        await message.answer(t(uid, "password_too_short"))
        return
    db_query(
        "UPDATE users SET password_key = %s WHERE user_id = %s",
        (password, uid),
        commit=True,
    )
    user = db_query("SELECT player_name FROM users WHERE user_id = %s", (uid,))
    name = user[0]['player_name'] if user else 'Player'
    data = await state.get_data()
    pending_join = data.get('pending_join')
    await state.clear()
    if not pending_join:
        try:
            row = db_query("SELECT pending_room_code FROM users WHERE user_id = %s", (uid,))
            if row and row[0].get("pending_room_code"):
                pending_join = _normalize_join_code("join_" + str(row[0]["pending_room_code"]))
        except Exception:
            pass
    await message.answer(t(uid, "profile_complete", name=name, password=password))
    if pending_join:
        user_data = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
        if user_data:
            try:
                db_query("UPDATE users SET pending_room_code = NULL WHERE user_id = %s", (uid,), commit=True)
            except Exception:
                pass
            await _join_room_by_code(message, pending_join, user_data[0])
        return
    await _show_training_offer_or_main(message, name, uid, state=state, from_registration=True)

async def _join_room_by_code(message, code, user_data):
    uid = message.from_user.id
    if user_data.get("is_banned") in (True, 1, "t", "true"):
        await message.answer(t(message.from_user.id, "banned_no_rooms"))
        return
    room = db_query("SELECT * FROM rooms WHERE room_id = %s AND status = 'waiting'", (code,))
    if not room:
        await message.answer(t(uid, "room_not_found"))
        await show_main_menu(message, user_data['player_name'], uid)
        return

    existing = db_query("SELECT * FROM room_players WHERE room_id = %s AND user_id = %s", (code, uid))
    if existing:
        await message.answer(t(uid, "already_in_room"))
        return

    p_count = db_query("SELECT count(*) as count FROM room_players WHERE room_id = %s", (code,))[0]['count']
    max_p = room[0]['max_players']
    if p_count >= max_p:
        await message.answer(t(uid, "room_full"))
        await show_main_menu(message, user_data['player_name'], uid)
        return

    u_name = user_data['player_name']
    db_query("INSERT INTO room_players (room_id, user_id, player_name, is_ready) VALUES (%s, %s, %s, TRUE)", (code, uid, u_name), commit=True)

    p_count += 1
    creator_id = room[0]['creator_id']

    all_in_room = db_query("SELECT user_id, player_name FROM room_players WHERE room_id = %s", (code,))
    num_emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
    players_list = ""
    for idx, rp in enumerate(all_in_room):
        marker = num_emojis[idx] if idx < len(num_emojis) else '👤'
        players_list += f"{marker} {rp['player_name']}\n"

    if p_count >= max_p:
        db_query("UPDATE rooms SET status = 'playing' WHERE room_id = %s", (code,), commit=True)
        all_players = db_query("SELECT user_id FROM room_players WHERE room_id = %s", (code,))
        if max_p == 2:
            for p in all_players:
                try:
                    await message.bot.send_message(p['user_id'], t(p['user_id'], "🎮 بدأت اللعبة! استعد..."))
                except Exception:
                    pass
            await asyncio.sleep(0.5)
            from handlers.room_2p import start_new_round
            await start_new_round(code, message.bot, start_turn_idx=0)
        else:
            for p in all_players:
                try:
                    await message.bot.send_message(p['user_id'], t(p['user_id'], "game_starting_multi", n=max_p))
                except Exception:
                    pass
            await asyncio.sleep(0.5)
            from handlers.room_multi import start_game_multi
            await start_game_multi(code, message.bot)
    else:
        wait_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "btn_home"), callback_data="home")]
        ])
        await message.answer(t(uid, "player_joined", name=u_name, count=p_count, max=max_p, list=players_list), reply_markup=wait_kb)
        try:
            notify_text = t(creator_id, "player_joined", name=u_name, count=p_count, max=max_p, list=players_list)
            notify_text += t(creator_id, "waiting_players", n=max_p - p_count)
            await message.bot.send_message(creator_id, notify_text, reply_markup=wait_kb)
        except Exception:
            pass

@router.callback_query(F.data == "auth_register")
async def auth_register(c: types.CallbackQuery, state: FSMContext):
    uid = c.from_user.id
    await c.message.edit_text(t(uid, "ask_name"))
    await state.set_state(RoomStates.register_name)

@router.message(RoomStates.register_name)
async def register_name(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    name = message.text.strip()
    if not name or len(name) < 2:
        await message.answer(t(uid, "name_too_short"))
        return
    if len(name) > 20:
        await message.answer(t(uid, "name_too_long"))
        return
    existing = db_query("SELECT * FROM users WHERE player_name = %s", (name,))
    if existing:
        await message.answer(t(uid, "name_taken"))
        return
    await state.update_data(reg_name=name)
    await message.answer(t(uid, "ask_password"))
    await state.set_state(RoomStates.register_password)

@router.message(RoomStates.register_password)
async def register_password(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    password = message.text.strip()
    if len(password) < 4:
        await message.answer(t(uid, "password_too_short"))
        return
    data = await state.get_data()
    name = data.get('reg_name', 'Player')
    lang = get_lang(uid)
    user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    if user:
        db_query("UPDATE users SET player_name = %s, password_key = %s, is_registered = TRUE, logged_out = FALSE, language = %s WHERE user_id = %s", (name, password, lang, uid), commit=True)
    else:
        db_query("INSERT INTO users (user_id, username, player_name, password_key, is_registered, language) VALUES (%s, %s, %s, %s, TRUE, %s)", (uid, message.from_user.username or '', name, password, lang), commit=True)
    await state.clear()
    await message.answer(t(uid, "register_success", name=name, password=password))
    await message.answer("يرجى إدخال اسم مستخدم (يوزر نيم) خاص بك (حروف إنجليزية وأرقام فقط، 3 أحرف على الأقل):")
    await state.set_state(RoomStates.upgrade_username)
    

@router.callback_query(F.data == "auth_login")
async def auth_login(c: types.CallbackQuery, state: FSMContext):
    uid = c.from_user.id
    await c.message.edit_text(t(uid, "login_ask_name"))
    await state.set_state(RoomStates.login_name)

@router.message(RoomStates.login_name)
async def login_name(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    raw = (message.text or "").strip().lower().replace("@", "")
    # الدخول باليوزر نيم (مثل a1a) أو باسم اللاعب
    user = db_query("SELECT * FROM users WHERE username_key = %s", (raw,))
    if not user:
        user = db_query("SELECT * FROM users WHERE player_name = %s", (message.text.strip(),))
    if not user:
        await message.answer(t(uid, "login_fail"))
        return
    if not user[0].get('password') and not user[0].get('password_key'):
        await message.answer(t(uid, "login_fail"))
        await state.clear()
        return
    # حفظ الاسم المستخدم للبحث (للمرحلة التالية)
    login_name_value = user[0].get("player_name") or user[0].get("username_key") or raw
    await state.update_data(login_target_name=login_name_value)
    await message.answer(t(uid, "login_ask_password"))
    await state.set_state(RoomStates.login_password)

@router.message(RoomStates.login_password)
async def login_password(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    data = await state.get_data()
    name = data.get('login_target_name')
    # البحث بالاسم المحفوظ (قد يكون player_name أو username_key)
    user = db_query("SELECT * FROM users WHERE player_name = %s", (name,))
    if not user:
        user = db_query("SELECT * FROM users WHERE username_key = %s", (name.lower(),))
    if not user:
        await message.answer(t(uid, "login_fail"))
        await state.clear()
        return
    pwd = user[0].get('password_key') or user[0].get('password', '')
    if message.text.strip() != pwd:
        await message.answer(t(uid, "login_fail"))
        return
    old_id = user[0]['user_id']
    db_query("UPDATE users SET user_id = %s, username = %s, is_registered = TRUE, logged_out = FALSE WHERE player_name = %s", (uid, message.from_user.username or '', name), commit=True)
    data_state = await state.get_data()
    pending_join = data_state.get('pending_join')
    await state.clear()
    if not pending_join:
        try:
            row = db_query("SELECT pending_room_code FROM users WHERE user_id = %s", (uid,))
            if row and row[0].get("pending_room_code"):
                pending_join = _normalize_join_code("join_" + str(row[0]["pending_room_code"]))
        except Exception:
            pass
    await message.answer(t(uid, "login_success", name=name))
    if pending_join:
        user_data = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
        if user_data:
            try:
                db_query("UPDATE users SET pending_room_code = NULL WHERE user_id = %s", (uid,), commit=True)
            except Exception:
                pass
            await _join_room_by_code(message, pending_join, user_data[0])
        return
    await show_main_menu(message, name, user_id=uid)

async def _random_wait_30_sec(room_id: str, uid: int, message_id: int, chat_id: int, bot):
    """بعد 30 ثانية: إن بقي اللاعب وحده في الغرفة، نعرض له رسالة «لا يوجد لاعب» مع أزرار نعم/طلب مجدد/رجوع."""
    try:
        await asyncio.sleep(30)
        random_wait_tasks.pop(room_id, None)
        r = db_query("SELECT status FROM rooms WHERE room_id = %s", (room_id,))
        if not r or r[0].get("status") != "waiting":
            return
        cnt = db_query("SELECT COUNT(*) AS c FROM room_players WHERE room_id = %s", (room_id,))
        if not cnt or cnt[0].get("c", 0) != 1:
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "btn_yes_play_bot"), callback_data=f"play_vs_bot_{room_id}")],
            [InlineKeyboardButton(text=t(uid, "btn_random_again"), callback_data=f"random_retry_{room_id}")],
            [InlineKeyboardButton(text=t(uid, "btn_home"), callback_data="home")]
        ])
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text=t(uid, "no_player_after_30"), reply_markup=kb
        )
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


@router.callback_query(F.data == "random_play")
async def menu_random(c: types.CallbackQuery):
    if await _ask_badge_color_if_needed(c):
        return
    uid = c.from_user.id
    user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    if not user:
        await c.answer(t(uid, "room_not_found"), show_alert=True)
        return

    # البحث عن غرفة عشوائية تنتظر لاعب ثانٍ
    waiting = db_query("""
    SELECT r.room_id FROM rooms r 
    WHERE r.max_players = 2 
    AND r.status = 'waiting' 
    AND r.is_random = TRUE 
    AND NOT EXISTS (SELECT 1 FROM room_players rp WHERE rp.room_id = r.room_id AND rp.user_id = %s) 
    LIMIT 1""", (uid,))

    if waiting:
        code = waiting[0]['room_id']
        # إلغاء مهمة الانتظار 30 ثانية لهذه الغرفة (انضم لاعب ثانٍ)
        tsk = random_wait_tasks.pop(code, None)
        if tsk and not tsk.done():
            try:
                tsk.cancel()
            except Exception:
                pass
        u_name = user[0]['player_name']
        db_query("INSERT INTO room_players (room_id, user_id, player_name, is_ready) VALUES (%s, %s, %s, TRUE)",
                 (code, uid, u_name), commit=True)
        db_query("UPDATE rooms SET status = 'playing' WHERE room_id = %s", (code,), commit=True)
        all_players = db_query("SELECT user_id FROM room_players WHERE room_id = %s", (code,))
        for p in all_players:
            try:
                await c.bot.send_message(p['user_id'], t(p['user_id'], "game_starting_2p"))
            except Exception:
                pass
        from handlers.room_2p import start_new_round
        await start_new_round(code, c.bot, start_turn_idx=0)
    else:
        code = generate_room_code()
        u_name = user[0]['player_name']
        db_query("INSERT INTO rooms (room_id, creator_id, max_players, score_limit, status, is_random) VALUES (%s, %s, 2, 0, 'waiting', TRUE)",
                 (code, uid), commit=True)
        db_query("INSERT INTO room_players (room_id, user_id, player_name, is_ready) VALUES (%s, %s, %s, TRUE)",
                 (code, uid, u_name), commit=True)
        await c.message.edit_text(t(uid, "random_wait_30"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
        random_wait_tasks[code] = asyncio.create_task(
            _random_wait_30_sec(code, uid, c.message.message_id, c.message.chat.id, c.bot)
        )


@router.callback_query(F.data == "menu_friends")
async def menu_friends(c: types.CallbackQuery):
    uid = c.from_user.id
    kb = [
        [InlineKeyboardButton(text=t(uid, "➕ إنشاء غرفة"), callback_data="room_create_start")],
        [InlineKeyboardButton(text=t(uid, "🚪 انضمام لغرفة"), callback_data="room_join_input")],
        [InlineKeyboardButton(text="🚪 الغرف المتوفرة", callback_data="available_rooms")],
        [InlineKeyboardButton(text=t(uid, "الغرف المفتوحة"), callback_data="my_open_rooms")],
        [InlineKeyboardButton(text=t(uid, "btn_public_rooms"), callback_data="public_rooms")],
        [InlineKeyboardButton(text=t(uid, "الرجوع"), callback_data="home")]
    ]
    await c.message.edit_text(t(uid, "friends_menu"), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data == "random_play")
async def random_play(c: types.CallbackQuery):
    if await _ask_badge_color_if_needed(c):
        return
    uid = c.from_user.id
    user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    if not user:
        await c.answer(t(uid, "room_not_found"), show_alert=True)
        return
    kb = [
        [InlineKeyboardButton(text="✅ نعم، ابحث عن خصم", callback_data="random_search_confirm")],
        [InlineKeyboardButton(text="❌ لا، رجوع", callback_data="home")]
    ]
    await c.message.edit_text(
        "🎮 **اللعب العشوائي**\n\n"
        "سيتم البحث عن خصم مناسب لك.\n"
        "هل أنت متأكد من البدء؟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )

@router.callback_query(F.data == "random_search_confirm")
async def random_search_confirm(c: types.CallbackQuery):
    uid = c.from_user.id
    user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    if not user:
        await c.answer(t(uid, "room_not_found"), show_alert=True)
        return
    waiting = db_query("""
        SELECT r.room_id FROM rooms r
        WHERE r.max_players = 2
        AND r.status = 'waiting'
        AND r.is_random = TRUE
        AND NOT EXISTS (SELECT 1 FROM room_players rp WHERE rp.room_id = r.room_id AND rp.user_id = %s)
        LIMIT 1""", (uid,))
    if waiting:
        code = waiting[0]['room_id']
        tsk = random_wait_tasks.pop(code, None)
        if tsk and not tsk.done():
            try:
                tsk.cancel()
            except Exception:
                pass
        u_name = user[0]['player_name']
        db_query("INSERT INTO room_players (room_id, user_id, player_name, is_ready) VALUES (%s, %s, %s, TRUE)",
                 (code, uid, u_name), commit=True)
        db_query("UPDATE rooms SET status = 'playing' WHERE room_id = %s", (code,), commit=True)
        all_players = db_query("SELECT user_id FROM room_players WHERE room_id = %s", (code,))
        for p in all_players:
            try:
                await c.bot.send_message(p['user_id'], t(p['user_id'], "game_starting_2p"))
            except Exception:
                pass
        from handlers.room_2p import start_new_round
        await start_new_round(code, c.bot, start_turn_idx=0)
    else:
        code = generate_room_code()
        u_name = user[0]['player_name']
        db_query("INSERT INTO rooms (room_id, creator_id, max_players, score_limit, status, is_random) VALUES (%s, %s, 2, 0, 'waiting', TRUE)",
                 (code, uid), commit=True)
        db_query("INSERT INTO room_players (room_id, user_id, player_name, is_ready) VALUES (%s, %s, %s, TRUE)",
                 (code, uid, u_name), commit=True)
        await c.message.edit_text(t(uid, "random_wait_30"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
        random_wait_tasks[code] = asyncio.create_task(
            _random_wait_30_sec(code, uid, c.message.message_id, c.message.chat.id, c.bot)
        )


@router.callback_query(F.data.startswith("random_retry_"))
async def random_retry(c: types.CallbackQuery):
    """طلب لعب عشوائي مجدداً بعد انتهاء الـ 30 ثانية: مغادرة الغرفة ثم بحث كـ menu_random."""
    uid = c.from_user.id
    room_id = (c.data or "").replace("random_retry_", "").strip()
    if not room_id:
        await c.answer(t(uid, "room_not_found"), show_alert=True)
        return
    tsk = random_wait_tasks.pop(room_id, None)
    if tsk and not tsk.done():
        try:
            tsk.cancel()
        except Exception:
            pass
    db_query("DELETE FROM room_players WHERE room_id = %s AND user_id = %s", (room_id, uid), commit=True)
    still = db_query("SELECT 1 FROM room_players WHERE room_id = %s", (room_id,))
    if not still:
        db_query("DELETE FROM rooms WHERE room_id = %s", (room_id,), commit=True)
    user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    if not user:
        await c.answer(t(uid, "room_not_found"), show_alert=True)
        return
    waiting = db_query("""
    SELECT r.room_id FROM rooms r 
    WHERE r.max_players = 2 AND r.status = 'waiting' AND r.is_random = TRUE 
    AND NOT EXISTS (SELECT 1 FROM room_players rp WHERE rp.room_id = r.room_id AND rp.user_id = %s) 
    LIMIT 1""", (uid,))
    if waiting:
        code = waiting[0]['room_id']
        tsk2 = random_wait_tasks.pop(code, None)
        if tsk2 and not tsk2.done():
            try:
                tsk2.cancel()
            except Exception:
                pass
        u_name = user[0]['player_name']
        db_query("INSERT INTO room_players (room_id, user_id, player_name, is_ready) VALUES (%s, %s, %s, TRUE)",
                 (code, uid, u_name), commit=True)
        db_query("UPDATE rooms SET status = 'playing' WHERE room_id = %s", (code,), commit=True)
        for p in db_query("SELECT user_id FROM room_players WHERE room_id = %s", (code,)):
            try:
                await c.bot.send_message(p['user_id'], t(p['user_id'], "game_starting_2p"))
            except Exception:
                pass
        from handlers.room_2p import start_new_round
        await start_new_round(code, c.bot, start_turn_idx=0)
    else:
        code = generate_room_code()
        u_name = user[0]['player_name']
        db_query("INSERT INTO rooms (room_id, creator_id, max_players, score_limit, status, is_random) VALUES (%s, %s, 2, 0, 'waiting', TRUE)",
                 (code, uid), commit=True)
        db_query("INSERT INTO room_players (room_id, user_id, player_name, is_ready) VALUES (%s, %s, %s, TRUE)",
                 (code, uid, u_name), commit=True)
        await c.message.edit_text(t(uid, "random_wait_30"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
        random_wait_tasks[code] = asyncio.create_task(
            _random_wait_30_sec(code, uid, c.message.message_id, c.message.chat.id, c.bot)
        )


@router.callback_query(F.data == "start_training_game")
async def start_training_game(c: types.CallbackQuery):
    """بدء جولة تدريبية حقيقية مع البوت: البوت يشرح كل ورقة ويترك اللاعب يفوز."""
    if await _ask_badge_color_if_needed(c):
        return
    uid = c.from_user.id
    user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    if not user:
        await c.answer(t(uid, "room_not_found"), show_alert=True)
        return
    u_name = user[0]["player_name"]
    code = generate_room_code()
    try:
        db_query("ALTER TABLE rooms ADD COLUMN IF NOT EXISTS is_training BOOLEAN DEFAULT FALSE", commit=True)
    except Exception:
        pass
    db_query(
        "INSERT INTO rooms (room_id, creator_id, max_players, score_limit, status, is_random) VALUES (%s, %s, 2, 0, 'playing', FALSE)",
        (code, uid), commit=True
    )
    try:
        db_query("UPDATE rooms SET is_training = TRUE WHERE room_id = %s", (code,), commit=True)
    except Exception:
        pass
    db_query(
        "INSERT INTO room_players (room_id, user_id, player_name, is_ready) VALUES (%s, %s, %s, TRUE)",
        (code, uid, u_name), commit=True
    )
    BOT_USER_ID = -1
    db_query(
        "INSERT INTO room_players (room_id, user_id, player_name, is_ready) VALUES (%s, %s, %s, FALSE)",
        (code, BOT_USER_ID, "البوت"), commit=True
    )
    await c.answer()
    try:
        await c.message.edit_text("📚 **وضع التدريب**\n\nجولة حقيقية مع البوت — راح يشرحلك الورقة النازلة وأوراقك ويقولك أي ورقة تقدر تلعب ولماذا.\n\n🎯 الهدف: تفوز أنت!")
    except Exception:
        pass
    from handlers.room_2p import start_new_round
    await start_new_round(code, c.bot, start_turn_idx=1)


@router.callback_query(F.data.startswith("play_vs_bot"))
async def play_vs_bot(c: types.CallbackQuery):
    if await _ask_badge_color_if_needed(c):
        return
    uid = c.from_user.id
    user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    if not user:
        await c.answer(t(uid, "room_not_found"), show_alert=True)
        return
    data = c.data
    if data == "play_vs_bot":
        room_to_leave = None
    else:
        # play_vs_bot_<room_id> — مغادرة غرفة الانتظار أولاً
        room_to_leave = data.replace("play_vs_bot_", "", 1).strip()
        if room_to_leave:
            db_query("DELETE FROM room_players WHERE room_id = %s AND user_id = %s", (room_to_leave, uid), commit=True)
            left = db_query("SELECT COUNT(*) AS c FROM room_players WHERE room_id = %s", (room_to_leave,))
            if left and left[0].get("c", 0) == 0:
                db_query("DELETE FROM rooms WHERE room_id = %s", (room_to_leave,), commit=True)
    u_name = user[0]["player_name"]
    code = generate_room_code()
    db_query(
        "INSERT INTO rooms (room_id, creator_id, max_players, score_limit, status, is_random) VALUES (%s, %s, 2, 0, 'playing', FALSE)",
        (code, uid), commit=True
    )
    db_query(
        "INSERT INTO room_players (room_id, user_id, player_name, is_ready) VALUES (%s, %s, %s, TRUE)",
        (code, uid, u_name), commit=True
    )
    BOT_USER_ID = -1
    db_query(
        "INSERT INTO room_players (room_id, user_id, player_name, is_ready) VALUES (%s, %s, %s, FALSE)",
        (code, BOT_USER_ID, "البوت"), commit=True
    )
    await c.answer()
    try:
        await c.message.edit_text(t(c.from_user.id, "game_started_vs_bot"))
    except Exception:
        pass
    from handlers.room_2p import start_new_round
    # في وضع البوت: الترتيب [البوت، الإنسان] فـ turn_index=1 = دور الإنسان
    await start_new_round(code, c.bot, start_turn_idx=1)


@router.callback_query(F.data == "room_create_start")
async def room_create_menu(c: types.CallbackQuery):
    kb, row = [], []
    for i in range(2, 11):
        row.append(InlineKeyboardButton(text=f"{i} لاعبين", callback_data=f"setp_{i}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton(text="🔙 رجوع", callback_data="menu_friends")])
    await c.message.edit_text(t(c.from_user.id, "choose_player_count"), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))




# --- زر تعديل حسابي داخل خانة حسابي ---
def _get_follow_counts(user_id):
    """عدد المتابعين (الذين يتابعونه) وعدد من يتابع (الذي يتابعهم)"""
    fol = db_query("SELECT COUNT(*) AS c FROM follows WHERE following_id = %s", (user_id,))
    ing = db_query("SELECT COUNT(*) AS c FROM follows WHERE follower_id = %s", (user_id,))
    return (fol[0]['c'] if fol else 0), (ing[0]['c'] if ing else 0)

@router.callback_query(F.data == "my_account")
async def show_profile(c: types.CallbackQuery):
    if await _ask_badge_color_if_needed(c):
        return
    user_data = db_query("SELECT * FROM users WHERE user_id = %s", (c.from_user.id,))
    if not user_data:
        return await c.answer(t(c.from_user.id, "account_not_registered"), show_alert=True)
    user = user_data[0]
    uid = c.from_user.id
    followers_count, following_count = _get_follow_counts(uid)
    try:
        from badges import get_display_badge
        badge = get_display_badge(uid)
        badge_line = f"\n🏅 الشارة: {badge}" if badge else ""
    except Exception:
        badge_line = ""
    txt = (
        f"👤 **معلومات حسابك**\n\n"
        f"📛 اسم اللاعب: {user['player_name']}\n"
        f"🔑 الرمز السري: `{user.get('password_key') or user.get('password') or 'لا يوجد'}`\n"
        f"🆔 اليوزر نيم: @{user.get('username_key') or '---'}\n"
        f"⭐ عدد النقاط: {user.get('online_points', 0)}\n"
        f"📈 عدد المتابعين (الذين يتابعونك): {followers_count}\n"
        f"📉 عدد من تتابعهم: {following_count}"
        f"{badge_line}"
    )
    kb = [
        [InlineKeyboardButton(text="✏️ تعديل بيانات الحساب", callback_data="edit_account"), InlineKeyboardButton(text="⚙️ الإعدادات", callback_data="my_settings")],
        [InlineKeyboardButton(text="📋 تبليغاتي", callback_data="my_reports"), InlineKeyboardButton(text="🆘 طلب مساعدة", callback_data="help_request")],
        [InlineKeyboardButton(text="📜 سجل المباريات", callback_data="match_history")],
        [InlineKeyboardButton(text="🚪 تسجيل خروج", callback_data="account_logout")],
        [InlineKeyboardButton(text=t(uid, "btn_back"), callback_data="home")]
    ]
    await c.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


def _report_status_ar_common(status):
    s = (status or "").strip().lower()
    if s in ("in_progress", "جاري المتابعة"):
        return "جاري المتابعة"
    if s in ("completed", "تم التبليغ", "read"):
        return "تم التبليغ"
    if s in ("rejected", "مرفوض"):
        return "مرفوض"
    return "في الانتظار"


@router.callback_query(F.data == "my_reports")
async def my_reports_list(c: types.CallbackQuery):
    uid = c.from_user.id
    try:
        rows = db_query(
            """SELECT id, reported_id, report_type, status, created_at FROM reports
               WHERE reporter_id = %s ORDER BY created_at DESC LIMIT 30""",
            (uid,)
        ) or []
    except Exception:
        rows = []
    if not rows:
        await c.message.edit_text(
            "📋 **تبليغاتي**\n\nلا توجد تبليغات منك.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 حسابي", callback_data="my_account")]
            ]),
            parse_mode="Markdown"
        )
        return await c.answer()
    text = "📋 **تبليغاتي**\n\n"
    for r in rows:
        rid = r.get("id")
        status_ar = _report_status_ar_common(r.get("status"))
        rep_type = r.get("report_type") or "—"
        created = (str(r.get("created_at") or "")[:16]) if r.get("created_at") else "—"
        text += f"• تبليغ #{rid} — {rep_type} — **{status_ar}** — {created}\n"
    kb = [[InlineKeyboardButton(text="🔙 حسابي", callback_data="my_account")]]
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    await c.answer()


def _get_admin_ids():
    """جلب قائمة معرفات الأدمن من متغيرات البيئة (ADMIN_ID أو ADMIN_IDS).
    يدعم: 123456789 أو \"123456789\" أو 111,222,333 (حتى مع مسافات أو رموز زائدة من Railway).
    ملاحظة: المدير يجب أن يكون قد ضغط /start على البوت مرة واحدة حتى يستطيع البوت إرسال رسائل له."""
    ids = set()
    for key in ("ADMIN_ID", "ADMIN_IDS", "ADMIN_TELEGRAM_ID"):
        raw = os.getenv(key, "")
        if raw is None:
            continue
        raw = str(raw).strip().strip('"').strip("'").replace("\\", "").strip()
        if not raw:
            continue
        for x in raw.split(","):
            # إزالة أي شيء غير الأرقام لتفادي مشاكل الاقتباس أو المسافات من Railway
            cleaned = "".join(c for c in str(x).strip() if c.isdigit())
            if cleaned:
                try:
                    ids.add(int(cleaned))
                except ValueError:
                    pass
    return ids


@router.callback_query(F.data == "help_request")
async def help_request_start(c: types.CallbackQuery, state: FSMContext):
    await state.set_state(RoomStates.help_request)
    _ensure_help_requests_table()
    try:
        db_query(
            "INSERT INTO help_request_pending (user_id, created_at) VALUES (%s, NOW()) ON CONFLICT (user_id) DO UPDATE SET created_at = NOW()",
            (c.from_user.id,), commit=True
        )
    except Exception:
        pass
    await c.message.edit_text(
        "🆘 **طلب مساعدة**\n\nاكتب رسالتك للإدارة أو أرسل صورة/صوت.\n\nسيتم إرسالها فوراً للمدير.\n\nلإلغاء اضغط **رجوع**.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="help_request_back")]
        ]),
        parse_mode="Markdown"
    )
    await c.answer()


@router.callback_query(F.data == "help_request_back")
async def help_request_back(c: types.CallbackQuery, state: FSMContext):
    await state.clear()
    _clear_pending_help_request(c.from_user.id)
    user_data = db_query("SELECT * FROM users WHERE user_id = %s", (c.from_user.id,))
    if not user_data:
        await c.answer(t(c.from_user.id, "account_not_registered"), show_alert=True)
        return
    user = user_data[0]
    uid = c.from_user.id
    followers_count, following_count = _get_follow_counts(uid)
    try:
        from badges import get_display_badge
        badge = get_display_badge(uid)
        badge_line = f"\n🏅 الشارة: {badge}" if badge else ""
    except Exception:
        badge_line = ""
    txt = (
        f"👤 **معلومات حسابك**\n\n"
        f"📛 اسم اللاعب: {user['player_name']}\n"
        f"🔑 الرمز السري: `{user.get('password_key') or user.get('password') or 'لا يوجد'}`\n"
        f"🆔 اليوزر نيم: @{user.get('username_key') or '---'}\n"
        f"⭐ عدد النقاط: {user.get('online_points', 0)}\n"
        f"📈 عدد المتابعين (الذين يتابعونك): {followers_count}\n"
        f"📉 عدد من تتابعهم: {following_count}"
        f"{badge_line}"
    )
    kb = [
        [InlineKeyboardButton(text="✏️ تعديل بيانات الحساب", callback_data="edit_account"), InlineKeyboardButton(text="⚙️ الإعدادات", callback_data="my_settings")],
        [InlineKeyboardButton(text="📋 تبليغاتي", callback_data="my_reports"), InlineKeyboardButton(text="🆘 طلب مساعدة", callback_data="help_request")],
        [InlineKeyboardButton(text="📜 سجل المباريات", callback_data="match_history")],
        [InlineKeyboardButton(text="🚪 تسجيل خروج", callback_data="account_logout")],
        [InlineKeyboardButton(text=t(uid, "btn_back"), callback_data="home")]
    ]
    await c.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await c.answer()


# ترجمة أسماء حقول قاعدة البيانات إلى العربية في ملف اللاعب
_USER_FIELD_AR = {
    "user_id": "معرف المستخدم",
    "userid": "معرف المستخدم",
    "playername": "اسم اللاعب",
    "player_name": "اسم اللاعب",
    "username": "اسم المستخدم (تليجرام)",
    "usernamekey": "يوزر البوت",
    "username_key": "يوزر البوت",
    "password": "كلمة المرور",
    "passwordkey": "رمز السري",
    "password_key": "رمز السري",
    "onlinepoints": "النقاط الإلكترونية",
    "online_points": "النقاط الإلكترونية",
    "language": "اللغة",
    "lastseen": "آخر ظهور",
    "isregistered": "مسجّل",
    "is_registered": "مسجّل",
    "isbanned": "محظور",
    "is_banned": "محظور",
    "loggedout": "تسجيل خروج",
    "logged_out": "تسجيل خروج",
    "isprivate": "حساب خاص",
    "is_private": "حساب خاص",
    "allowspectate": "السماح بالمشاهدة",
    "allow_spectate": "السماح بالمشاهدة",
}


def _build_user_file_text(uid: int, from_user: types.User) -> str:
    """بناء نص ملف اللاعب الكامل من قاعدة البيانات + بيانات تليجرام (الحقول بالعربية)."""
    lines = ["═══════ ملف اللاعب ═══════", f"ايدي تليجرام: {uid}", f"الاسم في تليجرام: {from_user.full_name or '-'}", f"اليوزر: @{from_user.username}" if from_user.username else "اليوزر: -", ""]
    try:
        user_row = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
        if user_row:
            row = user_row[0]
            for key in sorted(row.keys()):
                val = row[key]
                if val is None:
                    val = ""
                label = _USER_FIELD_AR.get(key) or _USER_FIELD_AR.get(key.lower()) or key
                lines.append(f"{label}: {val}")
        else:
            lines.append("(لا يوجد سجل في جدول users بعد)")
    except Exception as e:
        lines.append(f"(خطأ عند قراءة users: {e})")
    return "\n".join(lines)


def _help_request_admin_kb(uid: int) -> InlineKeyboardMarkup:
    """أزرار تحت رسالة طلب المساعدة عند الإدارة: المساعدات، القائمة، طلب دردشة."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 الذهاب لطلبات المساعدة", callback_data="admin_help_requests")],
        [InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="admin_back")],
        [InlineKeyboardButton(text="💬 طلب دردشة", callback_data=f"admin_chat_request_{uid}")],
    ])


# طلبات محادثة الإدارة مع اللاعب: user_id -> admin_id (يُعيّن من admin عند الضغط على «طلب محادثة»)
_pending_chat_requests = {}


def _ensure_help_requests_table():
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
        db_query(
            """CREATE TABLE IF NOT EXISTS help_request_pending (
                user_id BIGINT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            commit=True
        )
    except Exception:
        pass


def _has_pending_help_request(uid: int) -> bool:
    """True إذا المستخدم ضغط «طلب مساعدة» ولم يرسل الرسالة بعد (سجل في DB ليعمل مع عدة workers)."""
    try:
        row = db_query(
            "SELECT 1 FROM help_request_pending WHERE user_id = %s AND created_at > NOW() - INTERVAL '5 minutes'",
            (uid,)
        )
        return bool(row)
    except Exception:
        return False


def _clear_pending_help_request(uid: int):
    try:
        db_query("DELETE FROM help_request_pending WHERE user_id = %s", (uid,), commit=True)
    except Exception:
        pass


class _FilterPendingHelpRequest(BaseFilter):
    """يمرّر عندما المستخدم لديه طلب مساعدة معلّق في DB (وليس في حالة FSM) — ليعمل مع عدة workers.
    المستخدمون الأدمن لا يُعتبرون أبداً «طلب مساعدة معلّق» حتى لا تُلتقط رسالة النشر للأدمن كطلب مساعدة."""
    async def __call__(self, event: types.Message, **kwargs) -> bool:
        uid = event.from_user.id if event.from_user else None
        if not uid:
            return False
        if uid in _get_admin_ids():
            return False
        state = kwargs.get("state")
        if state:
            current = await state.get_state()
            if current == "RoomStates:help_request":
                return False
        return _has_pending_help_request(uid)


@router.message(RoomStates.help_request, F.text)
async def help_request_text(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 رجوع", callback_data="my_account")]])
    if message.text and message.text.strip().lower() in ("/cancel", "cancel", "الغاء", "إلغاء"):
        await state.clear()
        _clear_pending_help_request(uid)
        return await message.answer("تم الإلغاء.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 حسابي", callback_data="my_account")]]))
    try:
        admin_ids = _get_admin_ids()
        help_chat_id_raw = os.getenv("HELP_CHAT_ID", "").strip().strip('"').strip("'")
        logger.info("help_request_text: uid=%s admin_ids=%s HELP_CHAT_ID=%s", uid, list(admin_ids), help_chat_id_raw or "(غير مضبوط)")
        user = db_query("SELECT player_name, username_key FROM users WHERE user_id = %s", (uid,))
        name = (user[0]["player_name"] if user else None) or message.from_user.full_name or "لاعب"
        uname = (user[0].get("username_key") if user else None) or (message.from_user.username or "")
        if uname:
            uname = "@" + str(uname)
        file_text = _build_user_file_text(uid, message.from_user)
        file_text += "\n\n═══════ رسالة طلب المساعدة ═══════\n\n" + (message.text or "")
        _ensure_help_requests_table()
        try:
            db_query(
                "INSERT INTO help_requests (user_id, body_text, has_media) VALUES (%s, %s, FALSE)",
                (uid, file_text[:50000]), commit=True
            )
        except Exception:
            pass
        sent_any = False
        help_chat_id = help_chat_id_raw
        if not admin_ids and not help_chat_id:
            logger.warning("help_request: ADMIN_ID و HELP_CHAT_ID غير مضبوطين — ضع ADMIN_ID في Railway Variables (رقم تليجرام للمدير).")
        msg_body = file_text.replace("`", "'")[:3800]
        if len(file_text) > 3800:
            msg_body += "\n\n...(مختصر)"
        full_msg = "🆘 **طلب مساعدة**\n\n" + msg_body
        kb_admin = _help_request_admin_kb(uid)
        for aid in admin_ids:
            try:
                await message.bot.send_message(aid, full_msg, parse_mode="Markdown", reply_markup=kb_admin)
                sent_any = True
            except Exception as e1:
                try:
                    await message.bot.send_message(aid, "🆘 طلب مساعدة\n\n" + msg_body.replace("*", "").replace("_", ""), reply_markup=kb_admin)
                    sent_any = True
                except Exception as e2:
                    logger.warning("help_request: send to admin %s failed: %s then %s (المدير يجب أن يضغط /start على البوت أولاً)", aid, e1, e2)
        if help_chat_id:
            try:
                ch_id = int(help_chat_id) if help_chat_id.lstrip("-").isdigit() else help_chat_id
                await message.bot.send_message(ch_id, full_msg, parse_mode="Markdown", reply_markup=kb_admin)
                sent_any = True
            except Exception as e1:
                try:
                    await message.bot.send_message(ch_id, "🆘 طلب مساعدة\n\n" + msg_body.replace("*", "").replace("_", ""), reply_markup=kb_admin)
                    sent_any = True
                except Exception as e2:
                    logger.warning("help_request: send to HELP_CHAT_ID %s failed: %s then %s", help_chat_id, e1, e2)
        await state.clear()
        _clear_pending_help_request(uid)
        if sent_any:
            await message.answer("✅ تم إرسال طلب المساعدة للإدارة. المدير يمكنه أيضاً مراجعة جميع الطلبات من: لوحة الإدارة ← طلبات المساعدة.", reply_markup=kb)
        else:
            await message.answer(
                "✅ تم حفظ طلبك.\n\n"
                "المدير سيراه في لوحة الإدارة ← **طلبات المساعدة**.\n\n"
                "إن لم يصل إشعار فوري للمدير، تأكد من:\n"
                "• ضبط **ADMIN_ID** في Railway (Variables) برقم تليجرام للمدير.\n"
                "• أن المدير ضغط **/start** على البوت مرة واحدة على الأقل.",
                reply_markup=kb,
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.exception("help_request_text: uid=%s error", uid)
        await state.clear()
        _clear_pending_help_request(uid)
        await message.answer("⚠️ حدث خطأ أثناء إرسال طلبك. تم حفظه. جرّب لاحقاً أو راجع لوحة الإدارة ← طلبات المساعدة.", reply_markup=kb)


@router.message(_FilterPendingHelpRequest(), F.text)
async def help_request_text_fallback(message: types.Message, state: FSMContext):
    """معالج احتياطي عندما تكون الحالة FSM مفقودة (مثلاً worker آخر) لكن المستخدم مسجّل في help_request_pending."""
    await help_request_text(message, state)


@router.message(RoomStates.help_request, F.photo | F.voice | F.video | F.document)
async def help_request_media(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    admin_ids = _get_admin_ids()
    help_chat_id_raw = os.getenv("HELP_CHAT_ID", "").strip().strip('"').strip("'")
    logger.info("help_request_media: uid=%s admin_ids=%s HELP_CHAT_ID=%s", uid, list(admin_ids), help_chat_id_raw or "(غير مضبوط)")
    user = db_query("SELECT player_name, username_key FROM users WHERE user_id = %s", (uid,))
    name = (user[0]["player_name"] if user else None) or message.from_user.full_name or "لاعب"
    uname = (user[0].get("username_key") if user else None) or (message.from_user.username or "")
    if uname:
        uname = "@" + str(uname)
    file_text = _build_user_file_text(uid, message.from_user)
    file_text += "\n\n═══════ رسالة طلب المساعدة ═══════\n\n" + (message.caption or "(مرفق: صورة/صوت/فيديو/ملف)")
    cap_media = f"🆘 طلب مساعدة من {name} {uname} (ايدي: {uid})"
    caption_long = cap_media + "\n\n" + (message.caption or "")
    _ensure_help_requests_table()
    try:
        db_query(
            "INSERT INTO help_requests (user_id, body_text, has_media) VALUES (%s, %s, TRUE)",
            (uid, file_text[:50000]), commit=True
        )
    except Exception:
        pass
    help_chat_id = help_chat_id_raw
    if not admin_ids and not help_chat_id:
        logger.warning("help_request_media: ADMIN_ID و HELP_CHAT_ID غير مضبوطين.")
    msg_body = file_text.replace("`", "'")[:3800]
    if len(file_text) > 3800:
        msg_body += "\n\n...(مختصر)"
    sent_any = False
    kb_admin = _help_request_admin_kb(uid)
    for aid in admin_ids:
        try:
            await message.bot.send_message(aid, "🆘 **طلب مساعدة**\n\n" + msg_body, parse_mode="Markdown", reply_markup=kb_admin)
            if message.photo:
                await message.bot.send_photo(aid, message.photo[-1].file_id, caption=caption_long[:1000])
            elif message.voice:
                await message.bot.send_message(aid, caption_long[:4000])
                await message.bot.send_voice(aid, message.voice.file_id)
            elif message.video:
                await message.bot.send_video(aid, message.video.file_id, caption=caption_long[:1000])
            elif message.document:
                await message.bot.send_document(aid, message.document.file_id, caption=caption_long[:1000])
            sent_any = True
        except Exception as e:
            try:
                await message.bot.send_message(aid, "🆘 طلب مساعدة\n\n" + msg_body.replace("*", "").replace("_", ""), reply_markup=kb_admin)
                if message.photo:
                    await message.bot.send_photo(aid, message.photo[-1].file_id, caption=caption_long[:1000])
                elif message.voice:
                    await message.bot.send_voice(aid, message.voice.file_id)
                elif message.video:
                    await message.bot.send_video(aid, message.video.file_id, caption=caption_long[:1000])
                elif message.document:
                    await message.bot.send_document(aid, message.document.file_id, caption=caption_long[:1000])
                sent_any = True
            except Exception as e2:
                logger.warning("help_request_media: send to admin %s failed: %s then %s", aid, e, e2)
    if help_chat_id:
        try:
            ch_id = int(help_chat_id) if help_chat_id.lstrip("-").isdigit() else help_chat_id
            await message.bot.send_message(ch_id, "🆘 **طلب مساعدة**\n\n" + msg_body, parse_mode="Markdown")
            if message.photo:
                await message.bot.send_photo(ch_id, message.photo[-1].file_id, caption=caption_long[:1000])
            elif message.voice:
                await message.bot.send_voice(ch_id, message.voice.file_id, caption=caption_long[:1000])
            elif message.video:
                await message.bot.send_video(ch_id, message.video.file_id, caption=caption_long[:1000])
            elif message.document:
                await message.bot.send_document(ch_id, message.document.file_id, caption=caption_long[:1000])
            sent_any = True
        except Exception as e:
            logger.warning("help_request_media: send to HELP_CHAT_ID %s failed: %s", help_chat_id, e)
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 رجوع", callback_data="my_account")]])
    if sent_any:
        await message.answer("✅ تم إرسال طلب المساعدة للإدارة. المدير يمكنه مراجعة الطلبات من: لوحة الإدارة ← طلبات المساعدة.", reply_markup=kb)
    else:
        await message.answer("✅ تم حفظ طلبك. المدير سيراه في لوحة الإدارة ← طلبات المساعدة. (لإشعار فوري للمدير ضع ADMIN_ID في Railway وأن يضغط المدير /start على البوت.)", reply_markup=kb)
    _clear_pending_help_request(uid)


@router.message(_FilterPendingHelpRequest(), F.photo | F.voice | F.video | F.document)
async def help_request_media_fallback(message: types.Message, state: FSMContext):
    """معالج احتياطي لطلب المساعدة مع مرفق عندما تكون الحالة FSM مفقودة (مثلاً worker آخر)."""
    await help_request_media(message, state)


# --- قبول/رفض محادثة الإدارة ---
@router.callback_query(F.data.startswith("accept_chat_"))
async def user_accept_chat(c: types.CallbackQuery, state: FSMContext):
    try:
        uid = int(c.data.replace("accept_chat_", "").strip())
    except ValueError:
        await c.answer("⚠️ خطأ.", show_alert=True)
        return
    if c.from_user.id != uid:
        await c.answer("⚠️ غير مسموح.", show_alert=True)
        return
    admin_id = _pending_chat_requests.pop(uid, None)
    if not admin_id:
        await c.answer("⏱ انتهت صلاحية الطلب.", show_alert=True)
        return
    await state.set_state(RoomStates.chat_with_admin)
    await state.update_data(chat_admin_id=admin_id)
    kb_end = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔚 إنهاء المحادثة", callback_data="user_end_chat")]])
    await c.message.edit_text("💬 تم فتح المحادثة مع الإدارة.\n\nاكتب رسالتك أو اضغط «إنهاء المحادثة» عند الانتهاء.", reply_markup=kb_end)
    await c.answer()
    # إبلاغ الأدمن
    from handlers.admin import _admin_chat_started_with_user
    await _admin_chat_started_with_user(c.bot, admin_id, uid, c.from_user.full_name or "لاعب")


@router.callback_query(F.data.startswith("decline_chat_"))
async def user_decline_chat(c: types.CallbackQuery, state: FSMContext):
    try:
        uid = int(c.data.replace("decline_chat_", "").strip())
    except ValueError:
        await c.answer("⚠️ خطأ.", show_alert=True)
        return
    if c.from_user.id != uid:
        await c.answer("⚠️ غير مسموح.", show_alert=True)
        return
    admin_id = _pending_chat_requests.pop(uid, None)
    await c.message.edit_text("تم رفض المحادثة.")
    await c.answer()
    if admin_id:
        try:
            await c.bot.send_message(admin_id, "❌ رفض اللاعب المحادثة.")
        except Exception:
            pass


@router.callback_query(F.data == "user_end_chat")
async def user_end_chat_callback(c: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    admin_id = data.get("chat_admin_id")
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 رجوع", callback_data="my_account")]])
    await c.message.edit_text("تم إنهاء المحادثة.", reply_markup=kb)
    await c.answer()
    if admin_id:
        try:
            from handlers.admin import _admin_chat_ended
            await _admin_chat_ended(c.bot, admin_id, c.from_user.id)
        except Exception:
            pass


@router.message(RoomStates.chat_with_admin, F.text | F.photo | F.voice | F.video | F.document)
async def user_chat_with_admin_message(message: types.Message, state: FSMContext):
    """إعادة توجيه رسالة اللاعب إلى الأدمن أثناء المحادثة."""
    data = await state.get_data()
    admin_id = data.get("chat_admin_id")
    if not admin_id:
        await state.clear()
        return
    name = message.from_user.full_name or "لاعب"
    kb_end = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔚 إنهاء المحادثة", callback_data="admin_end_chat")]])
    try:
        if message.text:
            await message.bot.send_message(admin_id, f"👤 **من اللاعب ({name}):**\n\n{message.text}", parse_mode="Markdown", reply_markup=kb_end)
        elif message.photo:
            await message.bot.send_photo(admin_id, message.photo[-1].file_id, caption=f"👤 من اللاعب ({name})")
        elif message.voice:
            await message.bot.send_voice(admin_id, message.voice.file_id, caption=f"👤 من اللاعب ({name})")
        elif message.video:
            await message.bot.send_video(admin_id, message.video.file_id, caption=f"👤 من اللاعب ({name})")
        elif message.document:
            await message.bot.send_document(admin_id, message.document.file_id, caption=f"👤 من اللاعب ({name})")
    except Exception as e:
        logger.warning("user_chat_with_admin_message: %s", e)
    kb_user = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔚 إنهاء المحادثة", callback_data="user_end_chat")]])
    await message.answer("✅ تم إرسال رسالتك.", reply_markup=kb_user)


# --- إنشاء غرفة وإعطاء "رابط" بدل الكود ---
@router.callback_query(F.data.startswith("roomset_"))
async def create_friends_room(c: types.CallbackQuery, state: FSMContext):
    limit = int(c.data.split("_")[1])
    data = await state.get_data()
    p_count = data.get("p_count", 2)
    
    import random, string
    room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    
    # حفظ الغرفة في الداتابيز
    db_query("INSERT INTO rooms (room_id, creator_id, max_players, score_limit) VALUES (%s, %s, %s, %s)", 
    (room_id, c.from_user.id, p_count, limit), commit=True)
    
    # إضافة المنشئ
    user_db = db_query("SELECT player_name FROM users WHERE user_id = %s", (c.from_user.id,))
    p_name = user_db[0]['player_name'] if user_db else c.from_user.full_name
    db_query("INSERT INTO room_players (room_id, user_id, player_name, join_order) VALUES (%s, %s, %s, %s)",
    (room_id, c.from_user.id, p_name, 1), commit=True)
    
    # إنشاء الرابط (تلقائياً باستخدام يوزر البوت)
    bot_info = await c.bot.get_me()
    invite_link = f"https://t.me/{bot_info.username}?start=join_{room_id}"
    
    # عرض الرابط بدون علامات ` حتى يعمل النسخ واللصق (داخل تليجرام أو خارجه)
    text = (
    f"✅ تم إنشاء الغرفة بنجاح!\n\n"
    f"🎯 السقف: {limit}\n"
    f"👥 اللاعبين: {p_count}\n\n"
    f"🔗 رابط الدعوة (انسخه أو شاركه):\n{invite_link}\n\n"
    f"أرسل الرابط لصديقك؛ يعمل بالنسخ واللصق أو بزر المشاركة."
    )
    kb = [
        [InlineKeyboardButton(text="📤 مشاركة الرابط", url=f"https://t.me/share/url?url={invite_link}&text=تعال العب وياي اونو!")],
        [InlineKeyboardButton(text="🏠 الرئيسية", callback_data="home")]
    ]
    
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

# 2. دالة عرض أزرار السقف (للعب مع الأصدقاء)
@router.callback_query(F.data.startswith("setp_"))
async def ask_score_limit(c: types.CallbackQuery, state: FSMContext):
    p_count = int(c.data.split("_")[1])
    await state.update_data(p_count=p_count)
    
    limits = [100, 150, 200, 250, 300, 400, 500]
    kb = []
    row = []
    for val in limits:
        row.append(InlineKeyboardButton(text=f"🎯 {val}", callback_data=f"roomset_{val}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton(text="🃏 جولة واحدة", callback_data="roomset_0")])
    kb.append([InlineKeyboardButton(text="🏆 بطولة 3 جولات", callback_data="roomset_tournament_3")])
    kb.append([InlineKeyboardButton(text="🔙 رجوع", callback_data="home")])
    await c.message.edit_text(
        f"🔢 الغرفة لـ {p_count} لاعبين.\nحدد سقف النقاط لإنهاء اللعبة:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )

# 3. دالة إنشاء الغرفة (تشتغل فوراً بعد ما اللاعب يختار السقف)
@router.callback_query(F.data.startswith("roomset_"))
async def create_friends_room(c: types.CallbackQuery, state: FSMContext):
    parts = c.data.split("_")
    if len(parts) >= 3 and parts[1] == "tournament":
        limit = 0
        tournament_rounds = int(parts[2]) if parts[2].isdigit() else 3
        is_tournament = True
    else:
        limit = int(parts[1]) if parts[1].isdigit() else 0
        tournament_rounds = 0
        is_tournament = False
    data = await state.get_data()
    p_count = data.get("p_count", 2)
    
    import random, string
    room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    try:
        db_query("""INSERT INTO rooms (room_id, creator_id, max_players, score_limit, is_tournament, tournament_rounds, tournament_current_round)
        VALUES (%s, %s, %s, %s, %s, %s, 1)""",
            (room_id, c.from_user.id, p_count, limit, is_tournament, tournament_rounds), commit=True)
    except Exception:
        db_query("INSERT INTO rooms (room_id, creator_id, max_players, score_limit) VALUES (%s, %s, %s, %s)",
            (room_id, c.from_user.id, p_count, limit), commit=True)
    
    # إضافة المنشئ للغرفة
    user_db = db_query("SELECT player_name FROM users WHERE user_id = %s", (c.from_user.id,))
    p_name = user_db[0]['player_name'] if user_db else c.from_user.full_name
    db_query("INSERT INTO room_players (room_id, user_id, player_name, join_order) VALUES (%s, %s, %s, %s)",
    (room_id, c.from_user.id, p_name, 1), commit=True)
    
    if is_tournament:
        text = f"✅ **تم إنشاء بطولة مصغرة!**\n\n🔢 الكود: `{room_id}`\n👥 العدد: {p_count}\n🏆 الجولات: {tournament_rounds}\n\nأرسل الكود لأصدقائك للانضمام. الفائز يُحدد بعد {tournament_rounds} جولات."
    else:
        text = f"✅ **تم إنشاء الغرفة بنجاح!**\n\n🔢 الكود: `{room_id}`\n👥 العدد: {p_count}\n🎯 السقف: {limit}\n\nأرسل الكود لأصدقائك للانضمام."
    kb = [[InlineKeyboardButton(text="🔙 القائمة الرئيسية", callback_data="home")]]
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    

@router.callback_query(F.data.startswith("limit_"))
async def finalize_room(c: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    limit = int(c.data.split("_")[1])
    code = generate_room_code()
    uid = c.from_user.id
    u_name = db_query("SELECT player_name FROM users WHERE user_id = %s", (uid,))[0]['player_name']

    db_query("""INSERT INTO rooms (room_id, creator_id, max_players, score_limit, status, game_mode) 
    VALUES (%s, %s, %s, %s, 'waiting', 'friends')""", 
    (code, uid, data.get('p_count', 2), limit), commit=True)
    db_query("INSERT INTO room_players (room_id, user_id, player_name, is_ready) VALUES (%s, %s, %s, TRUE)", (code, uid, u_name), commit=True)

    followed = db_query("""
    SELECT u.user_id, u.player_name FROM follows f
    JOIN users u ON f.following_id = u.user_id
    WHERE f.follower_id = %s
    ORDER BY u.player_name
    """, (uid,))
    bot_info = await c.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=join_{code}"

    kb_invite = []
    if followed:
        for f in followed:
            kb_invite.append([InlineKeyboardButton(text=f"👤 {f['player_name']}", callback_data=f"finv_{code}_{f['user_id']}")])
        kb_invite.append([InlineKeyboardButton(text="📨 إرسال الدعوات", callback_data=f"finvsend_{code}")])
    kb_invite.append([InlineKeyboardButton(text="🔗 رابط الدعوة (أرسله لأي لاعب)", callback_data=f"finvskip_{code}")])
    kb_invite.append([InlineKeyboardButton(text=t(uid, "btn_home"), callback_data="home")])
    if code not in friend_invite_selections:
        friend_invite_selections[code] = set()

    msg = f"✅ تم إنشاء الغرفة!\n\n👥 اختر اللاعبين الذين تتابعهم لإرسال دعوة، أو استخدم الرابط لأي لاعب:\n{link}"
    await c.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_invite))
    await state.clear()

@router.callback_query(F.data == "available_rooms")
async def available_rooms_list(c: types.CallbackQuery):
    """الغرف المتوفرة: انضمام لغرفة، انسحاب من غرفة، أو إلغاء غرفي."""
    uid = c.from_user.id
    text_parts = ["🚪 **الغرف المتوفرة**\n"]
    kb = []

    # غرف مفتوحة يمكن الانضمام لها (ليست مليئة وليست أنا فيها)
    try:
        all_waiting = db_query("""
            SELECT r.room_id, r.max_players, r.creator_id,
                   (SELECT count(*) FROM room_players rp WHERE rp.room_id = r.room_id) as p_count
            FROM rooms r
            WHERE r.status = 'waiting'
            ORDER BY r.room_id DESC LIMIT 25
        """)
    except Exception:
        all_waiting = []
    in_room_codes = set()
    my_created = []
    joinable = []
    for r in all_waiting or []:
        code = r.get("room_id", "") or ""
        cur = int(r.get("p_count") or 0)
        mx = int(r.get("max_players") or 2)
        is_mine = r.get("creator_id") == uid
        am_in = db_query("SELECT 1 FROM room_players WHERE room_id = %s AND user_id = %s", (code, uid))
        if am_in:
            in_room_codes.add(code)
        if is_mine:
            my_created.append((code, cur, mx))
        elif cur < mx and not am_in:
            joinable.append((code, cur, mx))

    if joinable:
        text_parts.append("\n📥 **انضم إلى غرفة:**")
        for code, cur, mx in joinable[:15]:
            kb.append([InlineKeyboardButton(text=f"➕ انضم — {code} ({cur}/{mx})", callback_data=f"join_public_{code}")])

    if in_room_codes:
        text_parts.append("\n📤 **غرف أنت فيها (انسحاب):**")
        for code in list(in_room_codes)[:10]:
            kb.append([InlineKeyboardButton(text=f"🚪 انسحاب من {code}", callback_data=f"leave_room_{code}")])

    if my_created:
        text_parts.append("\n🛏 **غرفك المفتوحة (إلغاء):**")
        for code, cur, mx in my_created[:10]:
            kb.append([InlineKeyboardButton(text=f"❌ إلغاء {code} ({cur}/{mx})", callback_data=f"closeroom_{code}")])
        if len(my_created) > 1:
            kb.append([InlineKeyboardButton(text="🗑 إلغاء كل غرفي", callback_data="close_all_my_rooms")])

    if not kb:
        text_parts.append("\nلا توجد غرف مفتوحة حالياً. أنشئ غرفة أو انضم بكود.")
    kb.append([InlineKeyboardButton(text=t(uid, "btn_back"), callback_data="menu_friends")])
    text = "\n".join(text_parts)
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    await c.answer()


@router.callback_query(F.data.startswith("leave_room_"))
async def leave_room_callback(c: types.CallbackQuery):
    """انسحاب اللاعب من غرفة (قبل بدء اللعب)."""
    code = c.data.replace("leave_room_", "", 1).strip()
    uid = c.from_user.id
    room = db_query("SELECT * FROM rooms WHERE room_id = %s AND status = 'waiting'", (code,))
    if not room:
        return await c.answer(t(uid, "room_gone"), show_alert=True)
    in_room = db_query("SELECT 1 FROM room_players WHERE room_id = %s AND user_id = %s", (code, uid))
    if not in_room:
        return await c.answer(t(uid, "room_gone"), show_alert=True)
    u_name = db_query("SELECT player_name FROM users WHERE user_id = %s", (uid,))
    u_name = u_name[0]["player_name"] if u_name else c.from_user.full_name
    db_query("DELETE FROM room_players WHERE room_id = %s AND user_id = %s", (code, uid), commit=True)
    creator_id = room[0]["creator_id"]
    p_count = db_query("SELECT count(*) as count FROM room_players WHERE room_id = %s", (code,))[0]["count"]
    try:
        await c.bot.send_message(creator_id, f"🚪 انسحب {u_name} من الغرفة. الباقي: {p_count} لاعبين.")
    except Exception:
        pass
    await available_rooms_list(c)


@router.callback_query(F.data == "close_all_my_rooms")
async def close_all_my_rooms_callback(c: types.CallbackQuery):
    """إلغاء كل الغرف التي أنشأها المستخدم (حالة waiting)."""
    uid = c.from_user.id
    rooms = db_query("SELECT room_id FROM rooms WHERE creator_id = %s AND status = 'waiting'", (uid,))
    if not rooms:
        return await c.answer(t(uid, "no_open_rooms"), show_alert=True)
    for r in rooms:
        rid = r["room_id"]
        players = db_query("SELECT user_id FROM room_players WHERE room_id = %s AND user_id != %s", (rid, uid))
        for p in players or []:
            try:
                await c.bot.send_message(p["user_id"], t(p["user_id"], "room_closed_notification"))
            except Exception:
                pass
        db_query("DELETE FROM room_players WHERE room_id = %s", (rid,), commit=True)
        db_query("DELETE FROM rooms WHERE room_id = %s", (rid,), commit=True)
    await c.answer(f"✅ تم إلغاء {len(rooms)} غرفة.", show_alert=True)
    await available_rooms_list(c)


@router.callback_query(F.data == "public_rooms")
async def list_public_rooms(c: types.CallbackQuery):
    uid = c.from_user.id
    try:
        rooms = db_query("""
            SELECT r.room_id, r.max_players,
                   (SELECT count(*) FROM room_players rp WHERE rp.room_id = r.room_id) as p_count
            FROM rooms r
            WHERE r.status = 'waiting'
            ORDER BY r.room_id DESC LIMIT 20
        """)
    except Exception:
        rooms = []
    if not rooms:
        text = t(uid, "public_rooms_title") + "\n\n" + t(uid, "public_rooms_none")
        kb = [[InlineKeyboardButton(text=t(uid, "btn_back"), callback_data="menu_friends")]]
    else:
        text = t(uid, "public_rooms_title")
        kb = []
        for r in rooms:
            code = r.get("room_id", "")
            cur = r.get("p_count") or 0
            mx = r.get("max_players") or 2
            if cur >= mx:
                continue
            kb.append([InlineKeyboardButton(
                text=t(uid, "public_room_row", code=code, current=cur, max=mx),
                callback_data=f"join_public_{code}"
            )])
        kb.append([InlineKeyboardButton(text=t(uid, "btn_back"), callback_data="menu_friends")])
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    await c.answer()

@router.callback_query(F.data.startswith("join_public_"))
async def join_public_room(c: types.CallbackQuery):
    code = c.data.replace("join_public_", "", 1)
    uid = c.from_user.id
    room = db_query("SELECT * FROM rooms WHERE room_id = %s AND status = 'waiting'", (code,))
    if not room:
        return await c.answer(t(uid, "room_gone"), show_alert=True)
    existing = db_query("SELECT 1 FROM room_players WHERE room_id = %s AND user_id = %s", (code, uid))
    if existing:
        return await c.answer(t(uid, "already_in_room"), show_alert=True)
    u_name = db_query("SELECT player_name FROM users WHERE user_id = %s", (uid,))
    u_name = u_name[0]["player_name"] if u_name else c.from_user.full_name
    db_query("INSERT INTO room_players (room_id, user_id, player_name, is_ready) VALUES (%s, %s, %s, TRUE)", (code, uid, u_name), commit=True)
    p_count = db_query("SELECT count(*) as count FROM room_players WHERE room_id = %s", (code,))[0]["count"]
    max_p = room[0]["max_players"]
    if p_count >= max_p:
        db_query("UPDATE rooms SET status = 'playing' WHERE room_id = %s", (code,), commit=True)
        all_players = db_query("SELECT user_id FROM room_players WHERE room_id = %s", (code,))
        for p in all_players:
            try:
                await c.bot.send_message(p["user_id"], t(p["user_id"], "game_starting_multi", n=max_p))
            except Exception:
                pass
        from handlers.room_multi import start_game_multi
        await start_game_multi(code, c.bot)
    else:
        players = db_query("SELECT player_name FROM room_players WHERE room_id = %s", (code,))
        plist = ", ".join([p["player_name"] for p in players])
        await c.message.edit_text(t(uid, "player_joined", name=u_name, count=p_count, max=max_p, list=plist) + t(uid, "waiting_players", n=max_p - p_count))
    await c.answer()

@router.callback_query(F.data == "my_open_rooms")
async def my_open_rooms(c: types.CallbackQuery):
    uid = c.from_user.id
    rooms = db_query("""
    SELECT r.room_id, r.max_players, r.status,
    (SELECT count(*) FROM room_players rp WHERE rp.room_id = r.room_id) as p_count
    FROM rooms r
    WHERE r.creator_id = %s AND r.status = 'waiting'
    ORDER BY r.room_id
    """, (uid,))
    if not rooms:
        await c.answer(t(uid, "no_open_rooms"), show_alert=True)
        return
    kb = []
    for r in rooms:
        label = f"🎮 {r['room_id']} ({r['p_count']}/{r['max_players']})"
        kb.append([
            InlineKeyboardButton(text=label, callback_data=f"viewroom_{r['room_id']}"),
            InlineKeyboardButton(text="❌", callback_data=f"closeroom_{r['room_id']}")
        ])
    kb.append([InlineKeyboardButton(text=t(uid, "btn_back"), callback_data="menu_friends")])
    await c.message.edit_text(t(uid, "open_rooms_list"), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("viewroom_"))
async def view_room(c: types.CallbackQuery):
    uid = c.from_user.id
    code = c.data.split("_", 1)[1]
    room = db_query("SELECT * FROM rooms WHERE room_id = %s AND creator_id = %s", (code, uid))
    if not room:
        await c.answer(t(uid, "room_gone"), show_alert=True)
        return
    players = db_query("SELECT player_name FROM room_players WHERE room_id = %s", (code,))
    num_emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
    plist = ""
    for idx, p in enumerate(players):
        marker = num_emojis[idx] if idx < len(num_emojis) else '👤'
        plist += f"{marker} {p['player_name']}\n"
    bot_info = await c.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=join_{code}"
    text = t(uid, "room_detail", code=code, count=len(players), max=room[0]['max_players'], players=plist, link=link)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "btn_close_room"), callback_data=f"closeroom_{code}")],
        [InlineKeyboardButton(text=t(uid, "btn_back"), callback_data="my_open_rooms")]
    ])
    await c.message.edit_text(text, reply_markup=kb)

@router.callback_query(F.data.startswith("closeroom_"))
async def close_room(c: types.CallbackQuery):
    uid = c.from_user.id
    code = c.data.split("_", 1)[1]
    room = db_query("SELECT * FROM rooms WHERE room_id = %s AND creator_id = %s AND status = 'waiting'", (code, uid))
    if not room:
        await c.answer(t(uid, "room_gone"), show_alert=True)
        return
    players = db_query("SELECT user_id FROM room_players WHERE room_id = %s AND user_id != %s", (code, uid))
    for p in players:
        try:
            await c.bot.send_message(p['user_id'], t(p['user_id'], "room_closed_notification"))
        except Exception:
            pass
    db_query("DELETE FROM room_players WHERE room_id = %s", (code,), commit=True)
    db_query("DELETE FROM rooms WHERE room_id = %s", (code,), commit=True)
    await c.answer(t(uid, "room_closed"), show_alert=True)
    remaining = db_query("SELECT room_id FROM rooms WHERE creator_id = %s AND status = 'waiting'", (uid,))
    if remaining:
        await my_open_rooms(c)
    else:
        await c.message.edit_text(t(uid, "no_open_rooms_text"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "btn_back"), callback_data="menu_friends")]
        ]))

@router.callback_query(F.data == "room_join_input")
async def join_input(c: types.CallbackQuery, state: FSMContext):
    uid = c.from_user.id
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "btn_home"), callback_data="home")]
    ])
    await c.message.edit_text(t(uid, "send_room_code"), reply_markup=kb)
    await state.set_state(RoomStates.wait_for_code)

@router.message(RoomStates.wait_for_code)
async def process_join(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    user_row = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    if user_row and user_row[0].get("is_banned") in (True, 1, "t", "true"):
        await state.clear()
        return await message.answer("🚫 تم حظرك من البوت. لا يمكنك الانضمام للغرف.")
    code = message.text.strip().upper()
    room = db_query("SELECT * FROM rooms WHERE room_id = %s AND status = 'waiting'", (code,))
    if not room:
        return await message.answer(t(uid, "room_not_found"))
    existing = db_query("SELECT * FROM room_players WHERE room_id = %s AND user_id = %s", (code, uid))
    if existing:
        await state.clear()
        return await message.answer(t(uid, "already_in_room"))

    u_name = db_query("SELECT player_name FROM users WHERE user_id = %s", (uid,))[0]['player_name']
    db_query("INSERT INTO room_players (room_id, user_id, player_name, is_ready) VALUES (%s, %s, %s, TRUE)", (code, uid, u_name), commit=True)

    p_count = db_query("SELECT count(*) as count FROM room_players WHERE room_id = %s", (code,))[0]['count']
    max_p = room[0]['max_players']
    creator_id = room[0]['creator_id']

    all_in_room = db_query("SELECT user_id, player_name FROM room_players WHERE room_id = %s", (code,))
    num_emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
    players_list = ""
    for idx, rp in enumerate(all_in_room):
        marker = num_emojis[idx] if idx < len(num_emojis) else '👤'
        players_list += f"{marker} {rp['player_name']}\n"
    await state.clear()
    if p_count >= max_p:
        db_query("UPDATE rooms SET status = 'playing' WHERE room_id = %s", (code,), commit=True)
        all_players = db_query("SELECT user_id FROM room_players WHERE room_id = %s", (code,))
        if max_p == 2:
            for p in all_players:
                try:
                    await message.bot.send_message(p['user_id'], t(p['user_id'], "game_starting_2p"))
                except Exception:
                    pass
            from handlers.room_2p import start_new_round
            await start_new_round(code, message.bot, start_turn_idx=0)
        else:
            for p in all_players:
                try:
                    await message.bot.send_message(p['user_id'], t(p['user_id'], "game_starting_multi", n=max_p))
                except Exception:
                    pass
            from handlers.room_multi import start_game_multi
            await start_game_multi(code, message.bot)
    else:
        wait_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "btn_home"), callback_data="home")]
        ])
        await message.answer(t(uid, "player_joined", name=u_name, count=p_count, max=max_p, list=players_list), reply_markup=wait_kb)
        try:
            notify_text = t(creator_id, "player_joined", name=u_name, count=p_count, max=max_p, list=players_list)
            notify_text += t(creator_id, "waiting_players", n=max_p - p_count)
            notify_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ إعدادات الغرفة", callback_data=f"rsettings_{code}")],
                [InlineKeyboardButton(text=t(creator_id, "btn_home"), callback_data="home")]
            ])
            await message.bot.send_message(creator_id, notify_text, reply_markup=notify_kb)
        except Exception:
            pass

@router.callback_query(F.data.startswith("view_profile_"))
async def view_profile_handler(c: types.CallbackQuery):
    try:
        target_id = int(c.data.split("_")[-1])
        await process_user_search_by_id(c, target_id)
    except Exception as e:
        print(f"view_profile_handler error: {e}")
        await c.answer("⚠️ فشل فتح بروفايل اللاعب.", show_alert=True)


def _build_profile_text(uid: int, t_user: dict, target_id: int) -> str:
    """نص بروفايل اللاعب (مع الإنجازات وعدد المتابعين/المتابَعين)."""
    from datetime import datetime, timedelta
    last_seen = t_user.get("last_seen")
    if last_seen:
        online = (datetime.now() - last_seen < timedelta(minutes=5))
        status = t(uid, "status_online") if online else t(uid, "status_offline", time=last_seen.strftime("%H:%M"))
    else:
        status = t(uid, "status_offline", time="--:--")
    text = t(uid, "profile_title",
        name=t_user.get("player_name", "لاعب"),
        username=t_user.get("username_key", "---"),
        points=t_user.get("online_points", 0),
        status=status)
    # عدد متابعينه (الذين يتابعونه) وعدد الي يتابعهم (الذين هو يتابعهم)
    followers_count, following_count = _get_follow_counts(target_id)
    text += f"\n{t(uid, 'profile_followers_count', count=followers_count)}"
    text += f"\n{t(uid, 'profile_following_count', count=following_count)}"
    try:
        from badges import get_display_badge
        badge = get_display_badge(target_id)
        if badge:
            text += f"\n🏅 الشارة: {badge}"
    except Exception:
        pass
    badges = get_user_achievements(target_id)
    if badges:
        text += format_achievements_badges(uid, badges)
    return text


def _profile_back_only_kb(uid: int, back_to_replay_id: str = None, from_channel: bool = False):
    """كيبورد رجوع فقط (لشاشة «قام بحظرك» أو عند عدم صلاحية عرض البروفايل)."""
    kb = []
    if back_to_replay_id:
        kb.append([InlineKeyboardButton(text="🔙 رجوع لشاشة اللعبة", callback_data=f"gameend_back_{back_to_replay_id}")])
    elif from_channel:
        if PUBLISH_CHANNEL_USERNAME:
            ch_user = PUBLISH_CHANNEL_USERNAME.lstrip("@")
            kb.append([InlineKeyboardButton(text="📢 رجوع للقناة", url=f"https://t.me/{ch_user}")])
        back_to_leaderboard = None
        try:
            back_to_leaderboard = _pending_profile_back.get(uid)
        except Exception:
            pass
        if back_to_leaderboard:
            kb.append([
                InlineKeyboardButton(text="🔙 رجوع", callback_data=back_to_leaderboard),
                InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="home"),
            ])
        else:
            kb.append([InlineKeyboardButton(text="🔙 القائمة الرئيسية", callback_data="home")])
    else:
        kb.append([InlineKeyboardButton(text=t(uid, "btn_back"), callback_data="social_menu")])
    return kb


def _build_profile_kb(uid: int, target_id: int, back_to_replay_id: str = None, from_channel: bool = False):
    """يبني كيبورد بروفايل اللاعب.

    from_channel: متابعة، طلب لعب، رجوع للقناة، الرئيسية.
    back_to_leaderboard: إن وُجد، يضيف زر «رجوع» يعيد للوحة المتصدرين.
    """
    is_following = db_query(
        "SELECT 1 FROM follows WHERE follower_id = %s AND following_id = %s",
        (uid, target_id)
    )
    follow_btn_text = t(uid, "btn_unfollow") if is_following else t(uid, "btn_follow")
    if from_channel:
        follow_callback = f"unfollow_ch_{target_id}" if is_following else f"follow_ch_{target_id}"
        invite_callback = f"invite_ch_{target_id}"
    else:
        follow_callback = f"unfollow_{target_id}" if is_following else f"follow_{target_id}"
        invite_callback = f"invite_{target_id}"
    kb = [
        [InlineKeyboardButton(text=follow_btn_text, callback_data=follow_callback)],
        [InlineKeyboardButton(text=t(uid, "btn_invite_play"), callback_data=invite_callback)],
    ]
    # كتم الدعوات: إما تعديل الكتم (إن كان مكتوماً) أو كتم الدعوات
    if (uid, target_id) in invite_mutes:
        kb.append([InlineKeyboardButton(text="✏️ تعديل الكتم", callback_data=f"mute_inv_{target_id}")])
    else:
        kb.append([InlineKeyboardButton(text="🔇 كتم الدعوات", callback_data=f"mute_inv_{target_id}")])
    # حظر بين اللاعبين: كل لاعب يمكنه حظر الآخر (من جهته)
    if uid != target_id:
        if _is_user_blocked(uid, target_id):
            kb.append([InlineKeyboardButton(text="✅ إلغاء الحظر", callback_data=f"user_unblock_{target_id}")])
        else:
            kb.append([InlineKeyboardButton(text="🚫 حظره", callback_data=f"user_block_{target_id}")])
    # للأدمن: زر حظر اللاعب من البوت (حظر رسمي)
    try:
        from handlers.admin import is_admin
        if is_admin(uid) and uid != target_id:
            kb.append([InlineKeyboardButton(text="🚫 حظر اللاعب (أدمن)", callback_data=f"admin_ban_{target_id}")])
    except Exception:
        pass
    kb.extend(_profile_back_only_kb(uid, back_to_replay_id, from_channel))
    return kb


async def process_user_search_by_id(c: types.CallbackQuery, target_id: int, back_to_replay_id: str = None, from_channel: bool = False):
    """عرض بروفايل اللاعب. من القناة: أزرار متابعة، طلب لعب، رجوع للقناة، الرئيسية."""
    uid = c.from_user.id
    target = db_query("SELECT * FROM users WHERE user_id = %s", (target_id,))
    if not target:
        return await c.answer("❌ اللاعب غير موجود.", show_alert=True)
    t_user = target[0]
    if _is_user_blocked(target_id, uid):
        name = (t_user.get("player_name") or "لاعب")[:50]
        text = f"⛔ **اللاعب {name} قام بحظرك.**\n\nلا يمكنك عرض بروفايله أو إرسال دعوة له."
        kb = _profile_back_only_kb(uid, back_to_replay_id, from_channel)
        await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
        return
    text = _build_profile_text(uid, t_user, target_id)
    kb = _build_profile_kb(uid, target_id, back_to_replay_id=back_to_replay_id, from_channel=from_channel)
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    

def _user_asked_training(user_id: int) -> bool:
    """هل عُرض على اللاعب سؤال التدريب مسبقاً؟"""
    try:
        db_query("ALTER TABLE users ADD COLUMN IF NOT EXISTS asked_training_offer BOOLEAN DEFAULT FALSE", commit=True)
    except Exception:
        pass
    row = db_query("SELECT asked_training_offer FROM users WHERE user_id = %s", (user_id,))
    if not row:
        return True
    v = row[0].get("asked_training_offer")
    return v in (True, 1, "t", "true")


async def _show_training_offer_or_main(message, name, user_id, cleanup=False, state=None, from_admin=False, from_registration=False):
    """بعد إكمال التسجيل: إن لم يُسأل بعد عن التدريب نعرض «هل تريد التدريب»، وإلا القائمة الرئيسية."""
    if from_registration and not from_admin:
        if not _user_asked_training(user_id):
            uid = user_id
            txt = t(uid, "training_offer_question")
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t(uid, "training_btn_yes"), callback_data="training_yes")],
                [InlineKeyboardButton(text=t(uid, "training_btn_no"), callback_data="training_no")],
            ])
            target = message.message if isinstance(message, types.CallbackQuery) else message
            try:
                if isinstance(message, types.CallbackQuery):
                    await message.message.edit_text(txt, reply_markup=kb, parse_mode="Markdown")
                else:
                    await target.answer(txt, reply_markup=kb, parse_mode="Markdown")
                if isinstance(message, types.CallbackQuery):
                    await message.answer()
            except Exception:
                if isinstance(message, types.CallbackQuery):
                    await message.message.answer(txt, reply_markup=kb, parse_mode="Markdown")
                    await message.answer()
                else:
                    await target.answer(txt, reply_markup=kb, parse_mode="Markdown")
            return
    await show_main_menu(message, name, user_id, cleanup=cleanup, state=state, from_admin=from_admin)


async def _ask_badge_color_if_needed(c: types.CallbackQuery) -> bool:
    """إذا اللاعب مسجّل وليس له لون شارة، يعرض له اختيار اللون ويرجع True (لا تكمل المعالج). وإلا يرجع False."""
    try:
        from badges import get_badge_info
        uid = c.from_user.id
        user = db_query("SELECT user_id, logged_out FROM users WHERE user_id = %s", (uid,))
        if not user or user[0].get("logged_out") in (True, 1, "t", "true"):
            return False
        info = get_badge_info(uid)
        if info.get("badge_color") and str(info.get("badge_color", "")).strip():
            return False
        txt = "🆕 **وضع جديد: شارتك لك يا لاعب!**\n\nاختر لون شارتك الآن قبل أن تقوم بأي شيء."
        kb_badge = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔴", callback_data="choose_badge_first_🔴"),
                InlineKeyboardButton(text="🟡", callback_data="choose_badge_first_🟡"),
                InlineKeyboardButton(text="🟢", callback_data="choose_badge_first_🟢"),
                InlineKeyboardButton(text="🔵", callback_data="choose_badge_first_🔵"),
            ]
        ])
        try:
            await c.message.edit_text(txt, reply_markup=kb_badge, parse_mode="Markdown")
        except Exception:
            await c.message.answer(txt, reply_markup=kb_badge, parse_mode="Markdown")
        await c.answer()
        return True
    except Exception:
        return False


async def show_main_menu(message, name, user_id, cleanup=False, state=None, from_admin=False):
    # 1. تنظيف الحالة
    if state:
        await state.clear()
    # 2. جلب بيانات المستخدم
    user_rows = db_query("SELECT * FROM users WHERE user_id = %s", (user_id,))
    if not user_rows:
        # لا سجل في DB: نرد بأقل شيء حتى لا يبقى المستخدم بلا رد
        target_msg = message.message if isinstance(message, types.CallbackQuery) else message
        try:
            await target_msg.answer(t(user_id, "hello_send_start"))
        except Exception:
            pass
        return
    uid = user_id
    # 2.4 إذا كان محظوراً، نعرض له رسالة الحظر فقط
    if not from_admin and user_rows[0].get("is_banned") in (True, 1, "t", "true"):
        target_msg = message.message if isinstance(message, types.CallbackQuery) else message
        try:
            await target_msg.answer(t(uid, "banned_from_bot"))
        except Exception:
            pass
        return
    # 2.5 إذا كان مسجّل الخروج، نعرض له شاشة الدخول/التسجيل
    if not from_admin and user_rows[0].get("logged_out") in (True, 1, "t", "true"):
        target_msg = message.message if isinstance(message, types.CallbackQuery) else message
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(uid, "btn_register"), callback_data="auth_register")],
                [InlineKeyboardButton(text=t(uid, "btn_login"), callback_data="auth_login")],
            ]
        )
        try:
            await target_msg.answer(t(uid, "welcome_new"), reply_markup=kb)
        except Exception:
            pass
        return
    # 3. شرط اليوزر نيم (تخطى إذا رجوع من لوحة الإدارة)
    if not from_admin and not user_rows[0].get('username_key'):
        target_msg = message.message if isinstance(message, types.CallbackQuery) else message
        await target_msg.answer(t(uid, "enter_username_please"))
        if state:
            await state.set_state(RoomStates.upgrade_username)
        return
    # 3.5 تعليم تفاعلي (أول استخدام فقط؛ من لديه يوزر أو مسجّل لا يُعرض له مرة ثانية)
    try:
        seen = (
            from_admin
            or (user_id in _tutorial_done_cache)
            or (user_rows[0].get('seen_tutorial') in (True, 1, 't', 'true'))
            or bool(user_rows[0].get('username_key'))
            or bool(user_rows[0].get('is_registered'))
        )
    except Exception:
        seen = from_admin or (user_id in _tutorial_done_cache)
    if not seen:
        target_msg = message.message if isinstance(message, types.CallbackQuery) else message
        txt = t(uid, "tutorial_title") + "\n\n" + t(uid, "tutorial_body")
        kb_tut = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t(uid, "tutorial_btn"), callback_data="tutorial_done")]])
        try:
            await target_msg.answer(txt, reply_markup=kb_tut, parse_mode="Markdown")
        except Exception:
            pass
        return
    # 3.6 وضع جديد: إذا اللاعب مسجّل وليس له لون شارة بعد، نطلب منه اختيار اللون قبل أي شيء
    if not from_admin:
        try:
            from badges import get_badge_info
            info = get_badge_info(uid)
            if not info.get("badge_color") or not str(info.get("badge_color", "")).strip():
                target_msg = message.message if isinstance(message, types.CallbackQuery) else message
                txt = "🆕 **وضع جديد: شارتك لك يا لاعب!**\n\nاختر لون شارتك الآن قبل أن تقوم بأي شيء."
                kb_badge = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="🔴", callback_data="choose_badge_first_🔴"),
                        InlineKeyboardButton(text="🟡", callback_data="choose_badge_first_🟡"),
                        InlineKeyboardButton(text="🟢", callback_data="choose_badge_first_🟢"),
                        InlineKeyboardButton(text="🔵", callback_data="choose_badge_first_🔵"),
                    ]
                ])
                try:
                    if isinstance(message, types.CallbackQuery):
                        await message.message.edit_text(txt, reply_markup=kb_badge, parse_mode="Markdown")
                    else:
                        await target_msg.answer(txt, reply_markup=kb_badge, parse_mode="Markdown")
                    if isinstance(message, types.CallbackQuery):
                        await message.answer()
                except Exception:
                    if isinstance(message, types.CallbackQuery):
                        await message.message.answer(txt, reply_markup=kb_badge, parse_mode="Markdown")
                        await message.answer()
                    else:
                        await target_msg.answer(txt, reply_markup=kb_badge, parse_mode="Markdown")
                return
        except Exception:
            pass
    # 4. بناء الكيبورد
    kb = [
        [InlineKeyboardButton(text=t(uid, "btn_random_play"), callback_data="random_play"),
         InlineKeyboardButton(text=t(uid, "btn_play_vs_bot"), callback_data="play_vs_bot")],
        [InlineKeyboardButton(text=t(uid, "btn_play_friends"), callback_data="play_friends")],
        [InlineKeyboardButton(text="👥 مجتمع الأونو", callback_data="community_uno_menu")],
        [InlineKeyboardButton(text=t(uid, "btn_friends"), callback_data="social_menu")],
        [InlineKeyboardButton(text=t(uid, "btn_my_account"), callback_data="my_account"),
         InlineKeyboardButton(text=t(uid, "btn_calc"), callback_data="mode_calc")],
        [InlineKeyboardButton(text=t(uid, "btn_rules"), callback_data="rules")],
        [InlineKeyboardButton(text=t(uid, "btn_leaderboard"), callback_data="leaderboard")],
        [InlineKeyboardButton(text=t(uid, "btn_change_lang"), callback_data="change_lang")],
        [InlineKeyboardButton(text=t(uid, "btn_bot_info"), callback_data="bot_info")],
    ]
    try:
        from handlers.admin import is_admin
        if is_admin(uid):
            kb.append([InlineKeyboardButton(text="⚙️ لوحة الإدارة", callback_data="admin_open_panel")])
    except Exception:
        pass
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    
    msg_text = t(uid, "main_menu", name=name)

    # 5. وظيفة تنظيف الرسائل
    async def _cleanup_last_messages(msg_obj, limit=15):
        if not cleanup:
            return
        try:
            last_id = msg_obj.message_id
            for mid in range(last_id, max(last_id - limit, 1), -1):
                try:
                    await msg_obj.bot.delete_message(msg_obj.chat.id, mid)
                except Exception:
                    pass
        except Exception:
            pass
    # 6. إرسال الرسالة النهائية
    if from_admin:
        # العودة من لوحة الإدارة: تعديل الرسالة الحالية دون رسالة إضافية
        target = message.message if isinstance(message, types.CallbackQuery) else message
        try:
            await target.edit_text(msg_text, reply_markup=markup)
        except Exception:
            await target.answer(msg_text, reply_markup=markup)
        if isinstance(message, types.CallbackQuery):
            await message.answer(t(uid, "menu_updated"))
    elif isinstance(message, types.CallbackQuery):
        await _cleanup_last_messages(message.message, limit=15)
        try:
            await message.message.edit_text(msg_text, reply_markup=markup)
        except Exception:
            await message.message.answer(msg_text, reply_markup=markup)
        await message.answer(t(uid, "menu_updated"))
    else:
        await _cleanup_last_messages(message, limit=15)
        await message.answer(msg_text, reply_markup=markup)
        # إظهار أزرار القائمة الرئيسية وتنظيف الرسائل دائماً تحت القائمة عند الدخول من /start أو تنظيف
        try:
            await message.answer("—", reply_markup=persistent_kb)
        except Exception:
            pass

@router.callback_query(F.data == "tutorial_done")
async def tutorial_done(c: types.CallbackQuery, state: FSMContext):
    uid = c.from_user.id
    _tutorial_done_cache.add(uid)
    try:
        db_query("UPDATE users SET seen_tutorial = TRUE WHERE user_id = %s", (uid,), commit=True)
    except Exception:
        pass
    user = db_query("SELECT player_name FROM users WHERE user_id = %s", (uid,))
    name = user[0]['player_name'] if user else c.from_user.full_name
    await c.answer()
    await show_main_menu(c.message, name, uid, state=state)


@router.callback_query(F.data == "training_yes")
async def training_yes_cb(c: types.CallbackQuery, state: FSMContext):
    uid = c.from_user.id
    try:
        db_query("UPDATE users SET asked_training_offer = TRUE WHERE user_id = %s", (uid,), commit=True)
    except Exception:
        pass
    txt = t(uid, "training_title") + "\n\n" + t(uid, "training_content")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "btn_start_training_game"), callback_data="start_training_game")],
        [InlineKeyboardButton(text=t(uid, "btn_back_short"), callback_data="training_done")],
    ])
    try:
        await c.message.edit_text(txt, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await c.message.answer(txt, reply_markup=kb, parse_mode="Markdown")
    await c.answer()


@router.callback_query(F.data == "training_no")
async def training_no_cb(c: types.CallbackQuery, state: FSMContext):
    uid = c.from_user.id
    try:
        db_query("UPDATE users SET asked_training_offer = TRUE WHERE user_id = %s", (uid,), commit=True)
    except Exception:
        pass
    user = db_query("SELECT player_name FROM users WHERE user_id = %s", (uid,))
    name = (user[0]['player_name'] if user else None) or c.from_user.full_name
    await c.answer()
    await show_main_menu(c.message, name, uid, state=state)


@router.callback_query(F.data == "training_done")
async def training_done_cb(c: types.CallbackQuery, state: FSMContext):
    """بعد قراءة التدريب من شاشة «نعم أريد التدريب» → القائمة الرئيسية."""
    uid = c.from_user.id
    user = db_query("SELECT player_name FROM users WHERE user_id = %s", (uid,))
    name = (user[0]['player_name'] if user else None) or c.from_user.full_name
    await c.answer()
    await show_main_menu(c.message, name, uid, state=state)

@router.callback_query(F.data == "change_lang")
async def change_lang_menu(c: types.CallbackQuery):
    """عرض قائمة اختيار اللغة عند الضغط على زر تغيير اللغة"""
    uid = c.from_user.id
    text = t(uid, "choose_language")
    kb = [
        [InlineKeyboardButton(text="🇮🇶 العربية", callback_data="switch_lang_ar")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="switch_lang_en")],
        [InlineKeyboardButton(text="🇮🇷 فارسی", callback_data="switch_lang_fa")],
        [InlineKeyboardButton(text=t(uid, "btn_home"), callback_data="home")]
    ]
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    await c.answer()

@router.callback_query(F.data.startswith("switch_lang_"))
async def switch_lang(c: types.CallbackQuery):
    uid = c.from_user.id
    lang = c.data.split("_")[-1]
    db_query("UPDATE users SET language = %s WHERE user_id = %s", (lang, uid), commit=True)
    set_lang(uid, lang)
    await c.answer(t(uid, "lang_changed"), show_alert=True)
    user = db_query("SELECT player_name FROM users WHERE user_id = %s", (uid,))
    name = user[0]['player_name'] if user else 'Player'
    await show_main_menu(c.message, name, uid)

@router.callback_query(F.data.startswith("nextround_"))
async def next_round_go(c: types.CallbackQuery):
    room_id = c.data.split("_", 1)[1]
    nr = pending_next_round.get(room_id)
    if not nr:
        return await c.answer("⚠️ انتهت صلاحية هذا الخيار.", show_alert=True)
    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
    if not room:
        return await c.message.edit_text(t(c.from_user.id, "room_expired"))
    uid = c.from_user.id
    if room_id not in next_round_ready:
        next_round_ready[room_id] = set()
    if uid in next_round_ready[room_id]:
        return await c.answer("✅ سبق وأكدت! بانتظار البقية...", show_alert=True)

    next_round_ready[room_id].add(uid)
    players = db_query("SELECT user_id FROM room_players WHERE room_id = %s", (room_id,))
    total = len(players)
    ready_count = len(next_round_ready[room_id])

    try:
        await c.message.edit_text(f"✅ جاهز! ({ready_count}/{total}) بانتظار البقية...")
    except Exception:
        pass
    if ready_count >= total:
        await _start_next_round(room_id, c.bot)

async def _start_next_round(room_id, bot):
    nr = pending_next_round.pop(room_id, None)
    next_round_ready.pop(room_id, None)
    if not nr:
        return
    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
    if not room:
        return
    if nr['mode'] == '2p':
        from handlers.room_2p import start_new_round
        await start_new_round(room_id, bot, start_turn_idx=nr.get('start_turn', 0))
    else:
        from handlers.room_multi import start_game_multi
        await start_game_multi(room_id, bot, start_turn_idx=nr.get('start_turn', 0))

async def _next_round_timeout(room_id, bot):
    await asyncio.sleep(20)
    if room_id in pending_next_round:
        await _start_next_round(room_id, bot)

# --- نهاية اللعبة: تبديل متابعة من نفس الشاشة وإعادة رسم القائمة ---
@router.callback_query(F.data.startswith("gameend_f_"))
async def gameend_toggle_follow(c: types.CallbackQuery):
    """تبديل متابعة/إلغاء من شاشة نهاية اللعبة. يبلغ المستخدم ولا يخفي قائمة اللاعبين."""
    parts = c.data.split("_")
    if len(parts) < 4:
        return await c.answer("⚠️ خطأ.", show_alert=True)
    replay_id = parts[2]
    target_id = int(parts[3])
    uid = c.from_user.id
    if uid == target_id:
        return await c.answer("🧐 لا يمكنك متابعة نفسك!", show_alert=True)
    rdata = replay_data.get(replay_id)
    if not rdata:
        return await c.answer("⚠️ انتهت صلاحية هذه الشاشة.", show_alert=True)
    is_following = db_query("SELECT 1 FROM follows WHERE follower_id = %s AND following_id = %s", (uid, target_id))
    if is_following:
        db_query("DELETE FROM follows WHERE follower_id = %s AND following_id = %s", (uid, target_id), commit=True)
        await c.answer("❌ تم إلغاء المتابعة.")
    else:
        try:
            db_query("INSERT INTO follows (follower_id, following_id) VALUES (%s, %s)", (uid, target_id), commit=True)
            await c.answer("✅ تمت متابعة هذا اللاعب. القائمة تبقى لعرض الباقين.")
        except Exception:
            await c.answer("⚠️ أنت تتابع هذا اللاعب بالفعل.", show_alert=True)
    new_kb = build_game_end_keyboard(replay_id, uid)
    try:
        await c.message.edit_reply_markup(reply_markup=new_kb)
    except Exception:
        await c.message.edit_text(c.message.text or rdata.get("summary", "🏁 انتهت الجولة!"), reply_markup=new_kb)


@router.callback_query(F.data.startswith("gameend_p_"))
async def gameend_open_profile(c: types.CallbackQuery):
    """فتح صفحة معلومات اللاعب من شاشة نهاية اللعبة مع زر رجوع واحد فقط."""
    parts = c.data.split("_")
    if len(parts) < 4:
        return await c.answer("⚠️ خطأ.", show_alert=True)
    replay_id = parts[2]
    target_id = int(parts[3])
    rdata = replay_data.get(replay_id)
    if not rdata:
        return await c.answer("⚠️ انتهت صلاحية هذه الشاشة.", show_alert=True)
    await process_user_search_by_id(c, target_id, back_to_replay_id=replay_id)


@router.callback_query(F.data.startswith("publish_badge_"))
async def publish_badge_to_channel(c: types.CallbackQuery):
    """نشر الشارة في القناة عند ضغط «انشر شارتك»."""
    replay_id = c.data.replace("publish_badge_", "").strip()
    if not replay_id:
        return await c.answer("⚠️ خطأ في الرابط.", show_alert=True)
    rdata = replay_data.get(replay_id)
    if not rdata:
        rdata = _get_replay_from_db(replay_id)
    if not rdata:
        return await c.answer("⚠️ انتهت صلاحية النشر.", show_alert=True)
    winner_id = rdata.get("winner_id")
    try:
        winner_id = int(winner_id)
    except (TypeError, ValueError):
        winner_id = None
    if winner_id != c.from_user.id:
        return await c.answer("⚠️ هذا الخيار للفائز فقط.", show_alert=True)
    badge_earned = rdata.get("badge_just_earned") or rdata.get("badge_earned")
    if not badge_earned:
        return await c.answer("⚠️ لا توجد شارة لنشرها.", show_alert=True)
    if not (PUBLISH_CHANNEL_ID or PUBLISH_CHANNEL_USERNAME):
        return await c.answer("⚠️ القناة غير مضبوطة.", show_alert=True)
    row = db_query("SELECT player_name FROM users WHERE user_id = %s", (winner_id,))
    p_name = (row[0]["player_name"] if row else None) or "لاعب"
    text = f"🏅 **حصل {p_name} على شارة {badge_earned}!**"
    try:
        cid = PUBLISH_CHANNEL_ID
        if cid is not None and isinstance(cid, str):
            cid = cid.strip().strip('"').strip("'")
            if cid.lstrip("-").isdigit():
                chat_target = int(cid)
            else:
                chat_target = None
        else:
            chat_target = cid
    except Exception:
        chat_target = None
    if (chat_target is None or not str(chat_target).lstrip("-").isdigit()) and PUBLISH_CHANNEL_USERNAME:
        chat_target = str(PUBLISH_CHANNEL_USERNAME).strip().lstrip("@")
        if not chat_target.startswith("@"):
            chat_target = "@" + chat_target
    try:
        bot_me = await c.bot.get_me()
        profile_url = f"https://t.me/{bot_me.username}?start=profile_{winner_id}" if bot_me.username else None
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="عرض الحساب", url=profile_url)]]) if profile_url else None
        await c.bot.send_message(chat_target, text, parse_mode="Markdown", reply_markup=kb)
        await c.answer("✅ تم نشر شارتك في القناة!", show_alert=True)
    except Exception as e:
        await c.answer("⚠️ فشل النشر: " + str(e)[:50], show_alert=True)


@router.callback_query(F.data.startswith("gameend_back_"))
async def gameend_back_to_list(c: types.CallbackQuery):
    """الرجوع من بروفايل إلى شاشة نهاية اللعبة."""
    replay_id = c.data.replace("gameend_back_", "").strip()
    rdata = replay_data.get(replay_id)
    if not rdata:
        return await c.answer("⚠️ انتهت صلاحية هذه الشاشة.", show_alert=True)
    summary = rdata.get("summary", "🏁 انتهت الجولة!")
    kb = build_game_end_keyboard(replay_id, c.from_user.id)
    await c.message.edit_text(summary, reply_markup=kb)
    await c.answer()


# share_result وكل نشر/مجتمع في handlers/community_publish.py

# طلب الصداقة أُزيل: نستخدم المتابعة الفورية فقط. الضغط على إضافة/متابعة يبلغ المستخدم ولا يخفي قائمة اللاعبين.
@router.callback_query(F.data.startswith("addfrnd_"))
async def add_friend_as_follow(c: types.CallbackQuery):
    target_id = int(c.data.split("_")[1])
    uid = c.from_user.id
    if uid == target_id:
        return await c.answer("🧐 لا يمكنك متابعة نفسك!", show_alert=True)
    try:
        db_query("INSERT INTO follows (follower_id, following_id) VALUES (%s, %s)", (uid, target_id), commit=True)
        await c.answer("✅ تمت متابعة هذا اللاعب. القائمة تبقى لعرض الباقين.")
    except Exception:
        await c.answer("⚠️ أنت تتابع هذا اللاعب بالفعل.", show_alert=True)
    # لا نفتح البروفايل حتى تبقى قائمة اللاعبين ظاهرة لمتابعة الباقين

@router.callback_query(F.data.startswith("finv_"))
async def toggle_friend_invite(c: types.CallbackQuery):
    parts = c.data.split("_")
    code = parts[1]
    friend_id = int(parts[2])
    if code not in friend_invite_selections:
        friend_invite_selections[code] = set()
    sel = friend_invite_selections[code]
    if friend_id in sel:
        sel.discard(friend_id)
    else:
        sel.add(friend_id)
    followed = db_query("""
    SELECT u.user_id, u.player_name FROM follows f
    JOIN users u ON f.following_id = u.user_id
    WHERE f.follower_id = %s
    ORDER BY u.player_name
    """, (c.from_user.id,))
    kb_invite = []
    for f in followed:
        check = "✅" if f['user_id'] in sel else "👤"
        kb_invite.append([InlineKeyboardButton(text=f"{check} {f['player_name']}", callback_data=f"finv_{code}_{f['user_id']}")])
    kb_invite.append([InlineKeyboardButton(text=f"📨 إرسال الدعوات ({len(sel)})", callback_data=f"finvsend_{code}")])
    kb_invite.append([InlineKeyboardButton(text="🔗 رابط الدعوة (أرسله لأي لاعب)", callback_data=f"finvskip_{code}")])
    kb_invite.append([InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="home")])
    bot_info = await c.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=join_{code}"
    await c.message.edit_text(f"✅ تم إنشاء الغرفة!\n\n👥 اختر اللاعبين الذين تتابعهم (اضغط على الاسم لتحديده)، أو أرسل الرابط لأي لاعب:\n{link}", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_invite))

@router.callback_query(F.data.startswith("finvsend_"))
async def send_friend_invites(c: types.CallbackQuery):
    code = c.data.split("_")[1]
    sel = friend_invite_selections.pop(code, set())
    if not sel:
        return await c.answer("⚠️ لم تختر أي لاعب! أو استخدم رابط الدعوة لأي شخص.", show_alert=True)
    u_name = db_query("SELECT player_name FROM users WHERE user_id = %s", (c.from_user.id,))[0]['player_name']
    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (code,))
    max_p = room[0]['max_players'] if room else 10
    bot_info = await c.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=join_{code}"
    sent = 0
    for fid in sel:
        try:
            inv_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ موافق", callback_data=f"invy_{code}"),
                 InlineKeyboardButton(text="❌ رفض", callback_data=f"invn_{code}")]
            ])
            await c.bot.send_message(fid, f"📨 {u_name} يدعوك للعب!\n\n⏳ عندك 30 ثانية للرد\nهل تريد الانضمام؟", reply_markup=inv_kb)
            sent += 1
        except Exception:
            pass
    pending_invites[code] = {
        'creator': c.from_user.id,
        'creator_name': u_name,
        'invited': {fid: '' for fid in sel},
        'accepted': set(),
        'rejected': set(),
        'max_players': max_p,
        'score_limit': room[0].get('score_limit', 0) if room else 0,
        'mode': '2p' if max_p == 2 else 'multi'
    }
    wait_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="home")]
    ])
    await c.message.edit_text(f"📨 تم إرسال {sent} دعوة!\n⏳ بانتظار الردود...\n\n🎮 هذا رابط الدخول للعبة، انقر الرابط للدخول:\n{link}", reply_markup=wait_kb)
    asyncio.create_task(_invite_auto_check(code, c.bot))

@router.callback_query(F.data.startswith("finvskip_"))
async def skip_friend_invite(c: types.CallbackQuery):
    code = c.data.split("_")[1]
    friend_invite_selections.pop(code, None)
    bot_info = await c.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=join_{code}"
    kb_code = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="home")]
    ])
    await c.message.edit_text(f"🎮 هذا رابط الدخول للعبة، انقر الرابط للدخول:\n{link}", reply_markup=kb_code)

@router.callback_query(F.data.startswith("rsettings_"))
async def room_settings(c: types.CallbackQuery):
    code = c.data.split("_", 1)[1]
    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (code,))
    if not room:
        return await c.message.edit_text(t(c.from_user.id, "room_expired"))
    if room[0]['creator_id'] != c.from_user.id:
        return await c.answer("⚠️ فقط صاحب الغرفة يقدر يدخل الإعدادات!", show_alert=True)
    is_playing = room[0]['status'] == 'playing'
    score_text = f"🎯 {room[0]['score_limit']}" if room[0]['score_limit'] > 0 else "🃏 جولة واحدة"
    players = db_query("SELECT user_id, player_name FROM room_players WHERE room_id = %s", (code,))
    p_count = len(players)
    kb = [
        [InlineKeyboardButton(text="🚫 طرد لاعبين", callback_data=f"rkicklist_{code}")],
        [InlineKeyboardButton(text=f"🔢 تغيير سقف اللعب ({score_text})", callback_data=f"rchglimit_{code}")],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data=f"rsetback_{code}")]
    ]
    await c.message.edit_text(f"⚙️ إعدادات الغرفة\n\n👥 عدد اللاعبين: {p_count}/{room[0]['max_players']}\n📊 سقف النقاط: {score_text}", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("rsetback_"))
async def room_settings_back(c: types.CallbackQuery):
    code = c.data.split("_", 1)[1]
    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (code,))
    if not room:
        return await c.message.edit_text(t(c.from_user.id, "room_expired"))
    if room[0]['status'] == 'playing':
        await c.message.edit_text("🔄 جاري العودة للعبة...")
        p_count = len(db_query("SELECT user_id FROM room_players WHERE room_id = %s", (code,)))
        if p_count == 2:
            from handlers.room_2p import refresh_ui
            await refresh_ui(code, c.bot)
        else:
            from handlers.room_multi import refresh_ui_multi
            await refresh_ui_multi(code, c.bot)
        return
    players = db_query("SELECT user_id, player_name FROM room_players WHERE room_id = %s", (code,))
    num_emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
    players_list = ""
    for idx, rp in enumerate(players):
        marker = num_emojis[idx] if idx < len(num_emojis) else '👤'
        players_list += f"{marker} {rp['player_name']}\n"
    p_count = len(players)
    max_p = room[0]['max_players']
    txt = f"👥 اللاعبين ({p_count}/{max_p}):\n{players_list}"
    if p_count < max_p:
        txt += f"\n⏳ بانتظار {max_p - p_count} لاعب آخر..."
    else:
        txt += "\n✅ اكتمل العدد!"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ إعدادات الغرفة", callback_data=f"rsettings_{code}")],
        [InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="home")]
    ])
    await c.message.edit_text(txt, reply_markup=kb)

@router.callback_query(F.data.startswith("rkicklist_"))
async def kick_player_list(c: types.CallbackQuery):
    code = c.data.split("_", 1)[1]
    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (code,))
    if not room:
        return await c.message.edit_text(t(c.from_user.id, "room_expired"))
    if room[0]['creator_id'] != c.from_user.id:
        return await c.answer("⚠️ فقط صاحب الغرفة يقدر يطرد!", show_alert=True)
    players = db_query("SELECT user_id, player_name FROM room_players WHERE room_id = %s AND user_id != %s", (code, c.from_user.id))
    if not players:
        return await c.answer("⚠️ ما في لاعبين ثانيين في الغرفة!", show_alert=True)
    if code not in kick_selections:
        kick_selections[code] = set()
    existing_ids = {p['user_id'] for p in players}
    kick_selections[code] = kick_selections[code] & existing_ids
    kb = []
    for p in players:
        selected = p['user_id'] in kick_selections[code]
        mark = "✅" if selected else "⬜"
        kb.append([InlineKeyboardButton(text=f"{mark} {p['player_name']}", callback_data=f"rkickp_{code}_{p['user_id']}")])
    selected_count = len(kick_selections[code])
    if selected_count > 0:
        kb.append([InlineKeyboardButton(text=f"🚫 طرد المحددين ({selected_count})", callback_data=f"rkickgo_{code}")])
    kb.append([InlineKeyboardButton(text="🔙 رجوع", callback_data=f"rsettings_{code}")])
    await c.message.edit_text("🚫 حدد اللاعبين اللي تبي تطردهم:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("rkickp_"))
async def kick_player_toggle(c: types.CallbackQuery):
    parts = c.data.split("_")
    code = parts[1]
    target_id = int(parts[2])
    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (code,))
    if not room:
        return await c.message.edit_text(t(c.from_user.id, "room_expired"))
    if room[0]['creator_id'] != c.from_user.id:
        return await c.answer("⚠️ فقط صاحب الغرفة يقدر يطرد!", show_alert=True)
    if code not in kick_selections:
        kick_selections[code] = set()
    if target_id in kick_selections[code]:
        kick_selections[code].discard(target_id)
    else:
        kick_selections[code].add(target_id)
    c.data = f"rkicklist_{code}"
    await kick_player_list(c)

@router.callback_query(F.data.startswith("rkickgo_"))
async def kick_player_confirm(c: types.CallbackQuery):
    code = c.data.split("_", 1)[1]
    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (code,))
    if not room:
        return await c.message.edit_text(t(c.from_user.id, "room_expired"))
    if room[0]['creator_id'] != c.from_user.id:
        return await c.answer("⚠️ فقط صاحب الغرفة يقدر يطرد!", show_alert=True)
    selected = kick_selections.get(code, set())
    if not selected:
        return await c.answer("⚠️ ما حددت أحد!", show_alert=True)
    names = []
    for uid in selected:
        p = db_query("SELECT player_name FROM room_players WHERE room_id = %s AND user_id = %s", (code, uid))
        if p:
            names.append(p[0]['player_name'])
    names_text = "، ".join(names)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ نعم، اطردهم", callback_data=f"rkickyes_{code}"),
         InlineKeyboardButton(text="❌ لا", callback_data=f"rkicklist_{code}")]
    ])
    await c.message.edit_text(f"⚠️ هل أنت متأكد من طرد:\n{names_text}؟", reply_markup=kb)

@router.callback_query(F.data.startswith("rkickyes_"))
async def kick_player_execute(c: types.CallbackQuery):
    code = c.data.split("_", 1)[1]
    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (code,))
    if not room:
        return await c.message.edit_text(t(c.from_user.id, "room_expired"))
    if room[0]['creator_id'] != c.from_user.id:
        return await c.answer("⚠️ فقط صاحب الغرفة يقدر يطرد!", show_alert=True)
    selected = kick_selections.pop(code, set())
    if not selected:
        return await c.answer("⚠️ ما حددت أحد!", show_alert=True)
    kicked_names = []
    for target_id in selected:
        target = db_query("SELECT player_name FROM room_players WHERE room_id = %s AND user_id = %s", (code, target_id))
        if target:
            kicked_names.append(target[0]['player_name'])
        db_query("DELETE FROM room_players WHERE room_id = %s AND user_id = %s", (code, target_id), commit=True)
        try:
            await c.bot.send_message(target_id, "🚫 تم طردك من الغرفة بواسطة صاحب الغرفة.")
        except Exception:
            pass
    await c.answer(f"✅ تم طرد {len(kicked_names)} لاعب!", show_alert=True)
    c.data = f"rsettings_{code}"
    await room_settings(c)

@router.callback_query(F.data.startswith("rchglimit_"))
async def change_score_limit(c: types.CallbackQuery):
    code = c.data.split("_", 1)[1]
    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (code,))
    if not room:
        return await c.message.edit_text(t(c.from_user.id, "room_expired"))
    if room[0]['creator_id'] != c.from_user.id:
        return await c.answer("⚠️ فقط صاحب الغرفة يقدر يغير السقف!", show_alert=True)
    limits = [100, 150, 200, 250, 300, 350, 400, 450, 500]
    current = room[0]['score_limit']
    kb = []
    row = []
    for val in limits:
        label = f"✅ {val}" if val == current else f"🎯 {val}"
        row.append(InlineKeyboardButton(text=label, callback_data=f"rnewlimit_{code}_{val}"))
        if len(row) == 3:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    one_round_label = "✅ جولة واحدة" if current == 0 else "🃏 جولة واحدة"
    kb.append([InlineKeyboardButton(text=one_round_label, callback_data=f"rnewlimit_{code}_0")])
    kb.append([InlineKeyboardButton(text="🔙 رجوع", callback_data=f"rsettings_{code}")])
    await c.message.edit_text(f"🔢 اختر سقف النقاط الجديد:\n\n📊 السقف الحالي: {current if current > 0 else 'جولة واحدة'}", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("rnewlimit_"))
async def set_new_score_limit(c: types.CallbackQuery):
    parts = c.data.split("_")
    code = parts[1]
    new_limit = int(parts[2])
    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (code,))
    if not room:
        return await c.message.edit_text(t(c.from_user.id, "room_expired"))
    if room[0]['creator_id'] != c.from_user.id:
        return await c.answer("⚠️ فقط صاحب الغرفة يقدر يغير السقف!", show_alert=True)
    db_query("UPDATE rooms SET score_limit = %s WHERE room_id = %s", (new_limit, code), commit=True)
    limit_text = f"🎯 {new_limit}" if new_limit > 0 else "🃏 جولة واحدة"
    await c.answer(f"✅ تم تغيير سقف النقاط إلى: {limit_text}", show_alert=True)
    players = db_query("SELECT user_id FROM room_players WHERE room_id = %s AND user_id != %s", (code, c.from_user.id))
    for p in players:
        try:
            await c.bot.send_message(p['user_id'], f"📢 صاحب الغرفة غيّر سقف النقاط إلى: {limit_text}")
        except Exception:
            pass
    c.data = f"rsettings_{code}"
    await room_settings(c)

@router.callback_query(F.data == "account_logout")
async def account_logout_ask(c: types.CallbackQuery, state: FSMContext):
    """عرض تأكيد تسجيل الخروج"""
    uid = c.from_user.id
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ نعم، سجّل الخروج", callback_data="account_logout_confirm")],
            [InlineKeyboardButton(text="❌ لا، إلغاء", callback_data="my_account")],
        ]
    )
    text = (
        "🚪 **تسجيل الخروج**\n\n"
        "هل أنت متأكد؟ بعد تسجيل الخروج لن تستطيع الرجوع لحسابك إلا بـ:\n"
        "• كتابة **اليوزر نيم** وكلمة السر (دخول)، أو\n"
        "• إنشاء حساب جديد.\n\n"
        "اختر:"
    )
    try:
        await c.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await c.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await c.answer()


@router.callback_query(F.data == "account_logout_confirm")
async def account_logout_confirm(c: types.CallbackQuery, state: FSMContext):
    """تنفيذ تسجيل الخروج بعد الموافقة"""
    uid = c.from_user.id
    await state.clear()
    # التأكد من وجود عمود logged_out (إن لم يكن في schema)
    try:
        db_query("ALTER TABLE users ADD COLUMN IF NOT EXISTS logged_out BOOLEAN DEFAULT FALSE", commit=True)
    except Exception:
        try:
            db_query("ALTER TABLE users ADD COLUMN logged_out BOOLEAN DEFAULT FALSE", commit=True)
        except Exception:
            pass
    # عمود الحظر (لنظام التبليغ والإدارة)
    try:
        db_query("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE", commit=True)
    except Exception:
        try:
            db_query("ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT FALSE", commit=True)
        except Exception:
            pass
    # جدول حظر اللاعبين لبعضهم (blocker_id حظر blocked_id)
    try:
        db_query(
            """CREATE TABLE IF NOT EXISTS user_blocks (
                blocker_id BIGINT NOT NULL,
                blocked_id BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (blocker_id, blocked_id)
            )""",
            commit=True
        )
    except Exception:
        pass
    try:
        db_query("UPDATE users SET logged_out = TRUE WHERE user_id = %s", (uid,), commit=True)
    except Exception:
        pass
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "btn_register"), callback_data="auth_register")],
            [InlineKeyboardButton(text=t(uid, "btn_login"), callback_data="auth_login")],
        ]
    )
    text = "👋 تم تسجيل الخروج بنجاح.\n\n" + t(uid, "welcome_new")
    try:
        await c.message.edit_text(text, reply_markup=kb)
    except Exception:
        await c.message.answer(text, reply_markup=kb)
    await c.answer("تم تسجيل الخروج. استخدم دخول أو تسجيل للعودة.")

@router.callback_query(F.data == "match_history")
async def show_match_history(c: types.CallbackQuery):
    uid = c.from_user.id
    try:
        rows = db_query(
            "SELECT room_id, round_num, created_at FROM match_results WHERE winner_id = %s ORDER BY created_at DESC LIMIT 15",
            (uid,)
        )
    except Exception:
        rows = []
    if not rows:
        text = t(uid, "match_history_title") + "\n\n" + t(uid, "match_history_none")
    else:
        lines = [t(uid, "match_history_title") + "\n"]
        for r in rows:
            lines.append(t(uid, "match_history_row", round=r.get("round_num", 1), room=r.get("room_id", "—")))
        text = "\n".join(lines)
    kb = [[InlineKeyboardButton(text=t(uid, "btn_back"), callback_data="my_account")]]
    try:
        await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    except Exception:
        await c.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await c.answer()

@router.callback_query(F.data == "my_settings")
async def my_settings_menu(c: types.CallbackQuery):
    uid = c.from_user.id
    try:
        from badges import get_badge_info
        info = get_badge_info(uid)
        badge_line = f"\n🏅 لون الشارة: {info['badge_color'] or 'غير محدد'}"
    except Exception:
        badge_line = ""
    text = "⚙️ **الإعدادات**" + badge_line
    kb = [
        [InlineKeyboardButton(text="🏅 لون الشارة", callback_data="badge_color")],
        [InlineKeyboardButton(text="📩 استقبال الدعوات", callback_data="settings_invites")],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="my_account")]
    ]
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    await c.answer()

def _get_invite_from(uid):
    """من يمكنه إرسال دعوة لعب له: all / following / followers"""
    row = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    if not row:
        return "all"
    return row[0].get("invite_from") or "all"

@router.callback_query(F.data == "settings_invites")
async def settings_invites_ui(c: types.CallbackQuery):
    uid = c.from_user.id
    current = _get_invite_from(uid)
    check = "✅"
    cross = "❌"
    kb = [
        [InlineKeyboardButton(text=f"من الجميع {check if current == 'all' else cross}", callback_data="set_invite_from_all")],
        [InlineKeyboardButton(text=f"من الذين أتابعهم فقط {check if current == 'following' else cross}", callback_data="set_invite_from_following")],
        [InlineKeyboardButton(text=f"من الذين يتابعونني فقط {check if current == 'followers' else cross}", callback_data="set_invite_from_followers")],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="my_settings")]
    ]
    text = (
        "📩 **استقبال الدعوات**\n\n"
        "اختر من يمكنه إرسال دعوة لعب لك:\n"
        "• **من الجميع:** أي شخص يمكنه دعوتك.\n"
        "• **من الذين أتابعهم:** فقط من تتابعهم يمكنهم دعوتك.\n"
        "• **من الذين يتابعونني:** فقط من يتابعونك يمكنهم دعوتك."
    )
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    await c.answer()

@router.callback_query(F.data == "badge_color")
async def badge_color_menu(c: types.CallbackQuery):
    uid = c.from_user.id
    kb = [
        [
            InlineKeyboardButton(text="🔴", callback_data="set_badge_🔴"),
            InlineKeyboardButton(text="🟡", callback_data="set_badge_🟡"),
            InlineKeyboardButton(text="🟢", callback_data="set_badge_🟢"),
            InlineKeyboardButton(text="🔵", callback_data="set_badge_🔵"),
        ],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="my_settings")]
    ]
    await c.message.edit_text(
        "🏅 **اختر لون شارتك**\n\nكل شاراتك (🔴1، 🔴2، … ثم الأكشن والجوكر) ستظهر بهذا اللون.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="Markdown"
    )
    await c.answer()

@router.callback_query(F.data.startswith("choose_badge_first_"))
async def choose_badge_first_cb(c: types.CallbackQuery, state: FSMContext):
    """عند اختيار لون الشارة لأول مرة (قبل الدخول للقائمة) → حفظ اللون ثم عرض القائمة الرئيسية."""
    uid = c.from_user.id
    color = c.data.replace("choose_badge_first_", "").strip()
    try:
        from badges import set_badge_color, BADGE_COLORS
        if color in BADGE_COLORS and set_badge_color(uid, color):
            await c.answer("✅ تم! لون شارتك: " + color, show_alert=True)
            user = db_query("SELECT player_name FROM users WHERE user_id = %s", (uid,))
            name = (user[0]["player_name"] if user else None) or c.from_user.full_name
            await show_main_menu(c.message, name, user_id=uid, state=state)
        else:
            await c.answer("⚠️ اختر لوناً من الأزرار أعلاه.", show_alert=True)
    except Exception:
        await c.answer("⚠️ حدث خطأ، جرّب مرة أخرى.", show_alert=True)

@router.callback_query(F.data.startswith("set_badge_"))
async def set_badge_color_cb(c: types.CallbackQuery):
    uid = c.from_user.id
    color = c.data.replace("set_badge_", "").strip()
    try:
        from badges import set_badge_color, BADGE_COLORS
        if color in BADGE_COLORS and set_badge_color(uid, color):
            await c.answer("✅ تم تعيين لون الشارة: " + color, show_alert=True)
        else:
            await c.answer("⚠️ اختر لوناً من القائمة.", show_alert=True)
    except Exception:
        await c.answer("⚠️ حدث خطأ.", show_alert=True)
    await my_settings_menu(c)

@router.callback_query(F.data.startswith("set_invite_from_"))
async def set_invite_from(c: types.CallbackQuery):
    uid = c.from_user.id
    value = c.data.replace("set_invite_from_", "")
    if value not in ("all", "following", "followers"):
        await c.answer("⚠️ خطأ.", show_alert=True)
        return
    try:
        db_query("UPDATE users SET invite_from = %s WHERE user_id = %s", (value, uid), commit=True)
    except Exception:
        await c.answer("⚠️ تعذر حفظ الإعداد. (قد تحتاج إضافة عمود invite_from لجدول users)", show_alert=True)
        return
    await c.answer("✅ تم الحفظ.", show_alert=True)
    await settings_invites_ui(c)

@router.callback_query(F.data == "edit_account")
async def edit_account_menu(c: types.CallbackQuery):
    kb = [
        [InlineKeyboardButton(text="📛 تغيير الاسم", callback_data="change_name")],
        [InlineKeyboardButton(text="🆔 تغيير اليوزر نيم", callback_data="change_username")],
        [InlineKeyboardButton(text="🔑 تغيير الرمز السري", callback_data="change_password")],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="my_account")]
    ]
    await c.message.edit_text("✏️ ماذا تريد تعديله؟", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data == "change_name")
async def ask_new_name(c: types.CallbackQuery, state: FSMContext):
    await c.message.edit_text("📛 أرسل الاسم الجديد:")
    await state.set_state(RoomStates.edit_name)

@router.message(RoomStates.edit_name)
async def process_new_name(message: types.Message, state: FSMContext):
    new_name = message.text.strip()
    if len(new_name) < 1 or len(new_name) > 30:
        return await message.answer("❌ الاسم لازم يكون بين 1 و 30 حرف. حاول مرة ثانية:")
    db_query("UPDATE users SET player_name = %s WHERE user_id = %s", (new_name, message.from_user.id), commit=True)
    await state.clear()
    await message.answer(f"✅ تم تغيير الاسم إلى: {new_name}")
    user = db_query("SELECT * FROM users WHERE user_id = %s", (message.from_user.id,))
    if user:
        u = user[0]
        uid = message.from_user.id
        fc, ing = _get_follow_counts(uid)
        txt = f"👤 حسابي\n\n📛 اسم اللاعب: {u['player_name']}\n🔑 الرمز السري: {u.get('password_key') or 'لا يوجد'}\n🆔 اليوزر نيم: @{u.get('username_key') or '---'}\n⭐ النقاط: {u.get('online_points', 0)}\n📈 المتابعون: {fc}\n📉 من تتابع: {ing}"
        kb = [
            [InlineKeyboardButton(text="✏️ تعديل الحساب", callback_data="edit_account")],
            [InlineKeyboardButton(text="🚪 تسجيل الخروج", callback_data="logout_confirm")],
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="home")]
        ]
        await message.answer(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data == "change_username")
async def ask_new_username(c: types.CallbackQuery, state: FSMContext):
    await c.message.edit_text("🆔 أرسل اليوزر نيم الجديد (حروف إنجليزية وأرقام فقط، 3 أحرف على الأقل):")
    await state.set_state(RoomStates.edit_username)

@router.message(RoomStates.edit_username)
async def process_new_username(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    new_username = message.text.strip().lower().replace("@", "")
    if len(new_username) < 3 or not new_username.isalnum():
        return await message.answer("❌ اليوزر نيم لازم 3 أحرف أو أكثر (إنجليزي وأرقام فقط). حاول مرة ثانية:")
    existing = db_query("SELECT user_id FROM users WHERE username_key = %s AND user_id != %s", (new_username, uid))
    if existing:
        return await message.answer("❌ هذا اليوزر نيم محجوز لشخص آخر. اختر غيره:")
    db_query("UPDATE users SET username_key = %s WHERE user_id = %s", (new_username, uid), commit=True)
    await state.clear()
    await message.answer(f"✅ تم تغيير اليوزر نيم إلى: @{new_username}")
    user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    if user:
        u = user[0]
        fc, ing = _get_follow_counts(uid)
        txt = f"👤 حسابي\n\n📛 اسم اللاعب: {u['player_name']}\n🔑 الرمز السري: {u.get('password_key') or 'لا يوجد'}\n🆔 اليوزر نيم: @{u.get('username_key') or '---'}\n⭐ النقاط: {u.get('online_points', 0)}\n📈 المتابعون: {fc}\n📉 من تتابع: {ing}"
        kb = [
            [InlineKeyboardButton(text="✏️ تعديل الحساب", callback_data="edit_account")],
            [InlineKeyboardButton(text="🚪 تسجيل الخروج", callback_data="logout_confirm")],
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="home")]
        ]
        await message.answer(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data == "change_password")
async def ask_new_password(c: types.CallbackQuery, state: FSMContext):
    await c.message.edit_text("🔑 أرسل الرمز السري الجديد:")
    await state.set_state(RoomStates.edit_password)

@router.message(RoomStates.edit_password)
async def process_new_password(message: types.Message, state: FSMContext):
    new_pass = message.text.strip()
    if len(new_pass) < 1 or len(new_pass) > 30:
        return await message.answer("❌ الرمز لازم يكون بين 1 و 30 حرف. حاول مرة ثانية:")
    db_query("UPDATE users SET password_key = %s WHERE user_id = %s", (new_pass, message.from_user.id), commit=True)
    await state.clear()
    await message.answer("✅ تم تغيير الرمز السري بنجاح!")
    user = db_query("SELECT * FROM users WHERE user_id = %s", (message.from_user.id,))
    if user:
        u = user[0]
        uid = message.from_user.id
        fc, ing = _get_follow_counts(uid)
        txt = f"👤 حسابي\n\n📛 اسم اللاعب: {u['player_name']}\n🔑 الرمز السري: {u.get('password_key') or 'لا يوجد'}\n🆔 اليوزر نيم: @{u.get('username_key') or '---'}\n⭐ النقاط: {u.get('online_points', 0)}\n📈 المتابعون: {fc}\n📉 من تتابع: {ing}"
        kb = [
            [InlineKeyboardButton(text="✏️ تعديل الحساب", callback_data="edit_account")],
            [InlineKeyboardButton(text="🚪 تسجيل الخروج", callback_data="logout_confirm")],
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="home")]
        ]
        await message.answer(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data == "logout_confirm")
async def logout_confirm(c: types.CallbackQuery):
    kb = [
        [InlineKeyboardButton(text="✅ نعم، خروج", callback_data="logout_yes")],
        [InlineKeyboardButton(text="❌ لا، رجوع", callback_data="my_account")]
    ]
    await c.message.edit_text("🚪 هل أنت متأكد من تسجيل الخروج؟", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data == "logout_yes")
async def logout_yes(c: types.CallbackQuery, state: FSMContext):
    await state.clear()
    db_query("UPDATE users SET is_registered = FALSE WHERE user_id = %s", (c.from_user.id,), commit=True)
    await c.message.edit_text("👋 تم تسجيل الخروج بنجاح!\nأرسل /start للتسجيل مرة أخرى.")

@router.callback_query(F.data.startswith("replay_"))
async def replay_menu(c: types.CallbackQuery):
    replay_id = c.data.split("_", 1)[1]
    rdata = replay_data.get(replay_id)
    kb = []
    kb.append([InlineKeyboardButton(text=t(c.from_user.id, "btn_random_play"), callback_data="random_play")])
    if rdata and rdata.get('creator_id') == c.from_user.id:
        kb.append([InlineKeyboardButton(text="👥 اللعب مع نفس الفريق", callback_data=f"sameteam_{replay_id}")])
    kb.append([InlineKeyboardButton(text="➕ إنشاء غرفة", callback_data="room_create_start")])
    kb.append([InlineKeyboardButton(text="🚪 انضمام لغرفة", callback_data="room_join_input")])
    kb.append([InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="home")])
    await c.message.edit_text("🔄 اختر طريقة اللعب:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("sameteam_"))
async def same_team_invite(c: types.CallbackQuery):
    replay_id = c.data.split("_", 1)[1]
    rdata = replay_data.pop(replay_id, None)
    if not rdata:
        return await c.answer("⚠️ انتهت صلاحية هذا الخيار.", show_alert=True)

    creator_id = c.from_user.id
    other_players = [(uid, uname) for uid, uname in rdata['players'] if uid != creator_id]
    if not other_players:
        return await c.answer("⚠️ لا يوجد لاعبين آخرين للدعوة.", show_alert=True)

    code = generate_room_code()
    u_name = db_query("SELECT player_name FROM users WHERE user_id = %s", (c.from_user.id,))[0]['player_name']
    db_query("""INSERT INTO rooms (room_id, creator_id, max_players, score_limit, status, game_mode) 
    VALUES (%s, %s, %s, %s, 'waiting', 'friends')""",
    (code, creator_id, rdata['max_players'], rdata['score_limit']), commit=True)
    db_query("INSERT INTO room_players (room_id, user_id, player_name) VALUES (%s, %s, %s)", (code, creator_id, u_name), commit=True)

    pending_invites[code] = {
        'creator': creator_id,
        'creator_name': u_name,
        'invited': {uid: uname for uid, uname in other_players},
        'accepted': set(),
        'rejected': set(),
        'max_players': rdata['max_players'],
        'score_limit': rdata['score_limit'],
        'mode': rdata['mode'],
        'replay_id': replay_id
    }
    inv_wait_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="home")]
    ])
    await c.message.edit_text(f"📨 تم إرسال الدعوات لـ {len(other_players)} لاعب...\n⏳ بانتظار الردود...", reply_markup=inv_wait_kb)

    for uid, uname in other_players:
        try:
            inv_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ موافق", callback_data=f"invy_{code}"),
                 InlineKeyboardButton(text="❌ رفض", callback_data=f"invn_{code}")]
            ])
            await c.bot.send_message(uid, f"📨 {u_name} يدعوك للعب مرة أخرى مع نفس الفريق!\n\n⏳ عندك 30 ثانية للرد\nهل تريد الانضمام؟", reply_markup=inv_kb)
        except Exception as e:
            print(f"Invite send error to {uid}: {e}")
            pending_invites[code]['rejected'].add(uid)

    asyncio.create_task(_invite_auto_check(code, c.bot))

async def _invite_auto_check(room_id, bot):
    try:
        reminder_sent = False
        for step in range(30):
            await asyncio.sleep(1)
            inv = pending_invites.get(room_id)
            if not inv:
                return
            total_invited = len(inv['invited'])
            total_responded = len(inv['accepted']) + len(inv['rejected'])
            if total_responded >= total_invited:
                break
            # تذكير بعد 15 ثانية لمن لم يرد بعد
            if step == 14 and not reminder_sent:
                reminder_sent = True
                for fid in inv['invited']:
                    if fid in inv['accepted'] or fid in inv['rejected']:
                        continue
                    try:
                        await bot.send_message(fid, t(fid, "invite_reminder"))
                    except Exception:
                        pass
        inv = pending_invites.pop(room_id, None)
        if not inv:
            return
        room_check = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_check or room_check[0]['status'] != 'waiting':
            return
        accepted_names = [inv['invited'][uid] for uid in inv['accepted']]
        rejected_uids = set(inv['invited'].keys()) - inv['accepted']
        for uid in rejected_uids:
            inv['rejected'].add(uid)
        rejected_names = [inv['invited'][uid] for uid in inv['rejected'] if uid in inv['invited']]
        total_players = 1 + len(inv['accepted'])
        if total_players < 2:
            db_query("DELETE FROM rooms WHERE room_id = %s", (room_id,), commit=True)
            end_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ إنشاء غرفة", callback_data="room_create_start")],
                [InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="home")]
            ])
            msg = "❌ لم يقبل أحد الدعوة."
            if rejected_names:
                msg += f"\n\n🚫 رفضوا: {', '.join(rejected_names)}"
            await bot.send_message(inv['creator'], msg, reply_markup=end_kb)
            return
        db_query("UPDATE rooms SET max_players = %s, status = 'playing' WHERE room_id = %s", (total_players, room_id), commit=True)
        status_msg = f"🎮 بدء اللعب مع {total_players} لاعبين!"
        if rejected_names:
            status_msg += f"\n🚫 رفضوا الانضمام: {', '.join(rejected_names)}"
        if accepted_names:
            status_msg += f"\n✅ انضموا: {', '.join(accepted_names)}"
        all_player_ids = [inv['creator']] + list(inv['accepted'])
        for pid in all_player_ids:
            try:
                await bot.send_message(pid, status_msg)
            except Exception:
                pass
        if total_players == 2:
            from handlers.room_2p import start_new_round
            await start_new_round(room_id, bot, start_turn_idx=0)
        else:
            from handlers.room_multi import start_game_multi
            await start_game_multi(room_id, bot)
    except Exception as e:
        print(f"Auto check invite error: {e}")

@router.callback_query(F.data.startswith("invy_"))
async def accept_invite(c: types.CallbackQuery):
    room_id = c.data.split("_", 1)[1]
    inv = pending_invites.get(room_id)
    if not inv:
        return await c.answer("⚠️ انتهت صلاحية الدعوة.", show_alert=True)
    if c.from_user.id not in inv['invited']:
        return await c.answer("⚠️ هذه الدعوة ليست لك.", show_alert=True)
    if c.from_user.id in inv['accepted'] or c.from_user.id in inv['rejected']:
        return await c.answer("⚠️ سبق ورديت على الدعوة.", show_alert=True)
    inv['accepted'].add(c.from_user.id)
    u_name = db_query("SELECT player_name FROM users WHERE user_id = %s", (c.from_user.id,))[0]['player_name']
    db_query("INSERT INTO room_players (room_id, user_id, player_name) VALUES (%s, %s, %s)", (room_id, c.from_user.id, u_name), commit=True)

    accept_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="home")]
    ])
    await c.message.edit_text("✅ قبلت الدعوة! بانتظار بقية اللاعبين...", reply_markup=accept_kb)
    try:
        await c.bot.send_message(inv['creator'], f"✅ {u_name} قبل الدعوة!")
    except Exception:
        pass

@router.callback_query(F.data.startswith("invn_"))
async def reject_invite(c: types.CallbackQuery):
    room_id = c.data.split("_", 1)[1]
    inv = pending_invites.get(room_id)
    if not inv:
        return await c.answer("⚠️ انتهت صلاحية الدعوة.", show_alert=True)
    if c.from_user.id not in inv['invited']:
        return await c.answer("⚠️ هذه الدعوة ليست لك.", show_alert=True)
    if c.from_user.id in inv['accepted'] or c.from_user.id in inv['rejected']:
        return await c.answer("⚠️ سبق ورديت على الدعوة.", show_alert=True)
    inv['rejected'].add(c.from_user.id)
    p_name = inv['invited'].get(c.from_user.id, "لاعب")
    await c.message.edit_text("❌ رفضت الدعوة.")
    try:
        await c.bot.send_message(inv['creator'], f"❌ {p_name} رفض الدعوة.")
    except Exception:
        pass

# 1. دالة عرض القائمة الاجتماعية (عند الضغط على زر الأصدقاء)
@router.callback_query(F.data == "social_menu")
async def show_social_menu(c: types.CallbackQuery):
    if await _ask_badge_color_if_needed(c):
        return
    uid = c.from_user.id
    
    # نجلب الأعداد من قاعدة البيانات
    followers = db_query("SELECT COUNT(*) as count FROM follows WHERE following_id = %s", (uid,))[0]['count']
    following = db_query("SELECT COUNT(*) as count FROM follows WHERE follower_id = %s", (uid,))[0]['count']
    
    text = (f"👥 **القائمة الاجتماعية**\n\n"
    f"📈 يتابعونني: {followers}\n"
    f"📉 أتابعهم: {following}\n\n"
    "ابحث عن لاعب وتابعه لتصلك إشعارات عندما يلعب!")
    
    kb = [
    [InlineKeyboardButton(text="🔍 البحث عن لاعب", callback_data="search_user")],
    [InlineKeyboardButton(text=t(uid, "btn_followers_list"), callback_data="list_followers"),
    InlineKeyboardButton(text=t(uid, "btn_following_list"), callback_data="list_following")],
    [InlineKeyboardButton(text=t(uid, "btn_back"), callback_data="home")]
    ]
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

# 2. دالة بدء البحث (تغير حالة البوت وتطلب اليوزر نيم)
@router.callback_query(F.data == "search_user")
async def start_search_user(c: types.CallbackQuery, state: FSMContext):
    uid = c.from_user.id
    await c.message.answer("✍️ أرسل الآن اسم المستخدم (اليوزر نيم) للشخص الذي تبحث عنه:")
    await state.set_state(RoomStates.search_user) # هنا البوت ينتظر نص من المستخدم

# 3. معالج البحث (هذه الدالة اللي سألت عنها، توضع هنا)
@router.message(RoomStates.search_user)
async def process_user_search(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    target_username = message.text.strip().lower().replace("@", "") # تنظيف النص من @
    
    target = db_query("SELECT * FROM users WHERE username_key = %s", (target_username,))
    
    if not target:
        return await message.answer("❌ لا يوجد لاعب بهذا اليوزر. تأكد من الحروف وأرسله مرة ثانية:")

    t_user = target[0]
    t_uid = t_user['user_id']
    
    if _is_user_blocked(t_uid, uid):
        name = (t_user.get("player_name") or "لاعب")[:50]
        text = f"⛔ **اللاعب {name} قام بحظرك.**\n\nلا يمكنك عرض بروفايله أو إرسال دعوة له."
        kb = [[InlineKeyboardButton(text=t(uid, "btn_back"), callback_data="social_menu")]]
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
        await state.clear()
        return

    # فحص إذا كنت تتابعه حالياً
    is_following = db_query("SELECT 1 FROM follows WHERE follower_id = %s AND following_id = %s", (uid, t_uid))
    
    # بناء نص البروفايل (مع عدد المتابعين وعدد من يتابعهم)
    text = _build_profile_text(uid, t_user, t_uid)
    
    kb = []
    # زر المتابعة أو الإلغاء
    follow_btn_text = t(uid, "btn_unfollow") if is_following else t(uid, "btn_follow")
    follow_callback = f"unfollow_{t_uid}" if is_following else f"follow_{t_uid}"
    
    kb.append([InlineKeyboardButton(text=follow_btn_text, callback_data=follow_callback)])
    kb.append([InlineKeyboardButton(text=t(uid, "btn_invite_play"), callback_data=f"invite_{t_uid}")])
    if (uid, t_uid) in invite_mutes:
        kb.append([InlineKeyboardButton(text="✏️ تعديل الكتم", callback_data=f"mute_inv_{t_uid}")])
    else:
        kb.append([InlineKeyboardButton(text="🔇 كتم الدعوات", callback_data=f"mute_inv_{t_uid}")])
    if uid != t_uid:
        if _is_user_blocked(uid, t_uid):
            kb.append([InlineKeyboardButton(text="✅ إلغاء الحظر", callback_data=f"user_unblock_{t_uid}")])
        else:
            kb.append([InlineKeyboardButton(text="🚫 حظره", callback_data=f"user_block_{t_uid}")])
    try:
        from handlers.admin import is_admin
        if is_admin(uid) and uid != t_uid:
            kb.append([InlineKeyboardButton(text="🚫 حظر اللاعب (أدمن)", callback_data=f"admin_ban_{t_uid}")])
    except Exception:
        pass
    kb.append([InlineKeyboardButton(text=t(uid, "btn_back"), callback_data="social_menu")])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await state.clear() # إنهاء حالة البحث

# --- تنفيذ المتابعة ---
@router.callback_query(F.data.startswith("follow_"))
async def process_follow(c: types.CallbackQuery):
    uid = c.from_user.id
    from_channel = c.data.startswith("follow_ch_")
    target_id = int(c.data.replace("follow_ch_", "").replace("follow_", ""))
    if uid == target_id:
        return await c.answer("🧐 لا يمكنك متابعة نفسك!", show_alert=True)
    try:
        db_query("INSERT INTO follows (follower_id, following_id) VALUES (%s, %s)", (uid, target_id), commit=True)
        await c.answer("✅ تمت المتابعة بنجاح!")
    except Exception:
        await c.answer("⚠️ أنت تتابع هذا اللاعب بالفعل.")
    await process_user_search_by_id(c, target_id, from_channel=from_channel)

# --- تنفيذ إلغاء المتابعة ---
@router.callback_query(F.data.startswith("unfollow_"))
async def process_unfollow(c: types.CallbackQuery):
    uid = c.from_user.id
    from_channel = c.data.startswith("unfollow_ch_")
    target_id = int(c.data.replace("unfollow_ch_", "").replace("unfollow_", ""))
    db_query("DELETE FROM follows WHERE follower_id = %s AND following_id = %s", (uid, target_id), commit=True)
    await c.answer("❌ تم إلغاء المتابعة.")
    await process_user_search_by_id(c, target_id, from_channel=from_channel)


# --- دالة جديدة: تشغيل حاسبة الأونو (إصلاح الزر) ---
@router.callback_query(F.data == "calc_start")
async def start_calculator(c: types.CallbackQuery):
    uid = c.from_user.id
    text = "🧮 **حاسبة نقاط أونو**\n\nكم عدد اللاعبين؟"
    
    # توزيع الأزرار بشكل مرتب لـ 10 لاعبين
    kb = [
    [InlineKeyboardButton(text="2", callback_data="calc_players_2"), InlineKeyboardButton(text="3", callback_data="calc_players_3"), InlineKeyboardButton(text="4", callback_data="calc_players_4")],
    [InlineKeyboardButton(text="5", callback_data="calc_players_5"), InlineKeyboardButton(text="6", callback_data="calc_players_6"), InlineKeyboardButton(text="7", callback_data="calc_players_7")],
    [InlineKeyboardButton(text="8", callback_data="calc_players_8"), InlineKeyboardButton(text="9", callback_data="calc_players_9"), InlineKeyboardButton(text="10", callback_data="calc_players_10")],
    [InlineKeyboardButton(text="🔙 رجوع", callback_data="home")]
    ]
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("calc_players_"))
async def calc_choose_players(c: types.CallbackQuery, state: FSMContext):
    n = int(c.data.split("_")[-1])
    await state.update_data(calc_players=n)
    kb = [[InlineKeyboardButton(text="🔙 رجوع", callback_data="calc_start")],
    [InlineKeyboardButton(text="🏠 الرئيسية", callback_data="home")]]
    await c.message.edit_text(f"✅ تم اختيار عدد اللاعبين: {n}\n\n(هنا نكمل خطوات الحاسبة بعدين)", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


# 2. تعديل قائمة المتابعين (حذف None وإصلاح الدخول للاعب)
@router.callback_query(F.data == "list_following")
async def show_following_list(c: types.CallbackQuery):
    uid = c.from_user.id
    following = db_query("""
    SELECT u.user_id, u.player_name, u.last_seen 
    FROM follows f 
    JOIN users u ON f.following_id = u.user_id 
    WHERE f.follower_id = %s
    """, (uid,))

    if not following:
        return await c.answer("📉 أنت لا تتابع أحداً حالياً.", show_alert=True)

    text = "📉 **أتابعهم:**\n(اضغط على الاسم لفتح البروفايل)"
    kb = []
    from datetime import datetime, timedelta
    
    for user in following:
        last_seen = user['last_seen'] if user['last_seen'] else datetime.min
        is_online = (datetime.now() - last_seen < timedelta(minutes=5))
        status_icon = "🟢" if is_online else "⚪"
        display_name = user['player_name'] if user['player_name'] else "لاعب"
        kb.append([InlineKeyboardButton(
            text=f"{status_icon} {display_name}",
            callback_data=f"view_profile_{user['user_id']}"
        )])

    kb.append([InlineKeyboardButton(text="🔙 رجوع", callback_data="social_menu")])
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

# --- دالة جديدة: عرض قائمة "المتابعون" ---
@router.callback_query(F.data == "list_followers")
async def show_followers_list(c: types.CallbackQuery):
    uid = c.from_user.id
    # جلب الأشخاص الذين يتابعون المستخدم
    followers = db_query("""
    SELECT u.user_id, u.player_name, u.username_key 
    FROM follows f 
    JOIN users u ON f.follower_id = u.user_id 
    WHERE f.following_id = %s
    """, (uid,))

    if not followers:
        return await c.answer("📈 لا يوجد متابعون لحسابك حالياً.", show_alert=True)

    text = "📈 **يتابعونني:**\n\n"
    kb = []
    for user in followers:
        kb.append([InlineKeyboardButton(
            text=f"👤 {user['player_name']} (@{user['username_key']})",
            callback_data=f"view_profile_{user['user_id']}"
        )])

    kb.append([InlineKeyboardButton(text=t(uid, "btn_back"), callback_data="social_menu")])
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

# --- دالة تفعيل/تعطيل تنبيهات بدء اللعب (🔔) ---
@router.callback_query(F.data.startswith("game_notify_"))
async def toggle_game_notify(c: types.CallbackQuery):
    target_id = int(c.data.split("_")[2])
    uid = c.from_user.id
    
    # فحص الحالة الحالية من جدول المتابعة (سنستخدم عمود notify_games)
    # ملاحظة: إذا لم تكن قد أضفت العمود بعد، سأعطيك أمر SQL لاحقاً
    current = db_query("SELECT notify_games FROM follows WHERE follower_id = %s AND following_id = %s", (uid, target_id))
    
    if not current:
        return await c.answer("⚠️ يجب أن تتابع اللاعب أولاً لتفعيل التنبيهات!", show_alert=True)
    
    new_status = 0 if current[0]['notify_games'] else 1
    db_query("UPDATE follows SET notify_games = %s WHERE follower_id = %s AND following_id = %s", (new_status, uid, target_id), commit=True)
    
    await c.answer("✅ تم تحديث إعدادات التنبيه" if new_status else "❌ تم إيقاف التنبيه")
    # تحديث واجهة البروفايل لإظهار العلامة الجديدة
    await process_user_search_by_id(c, target_id)
    
    # هنا التحكم يكون بخصوصية اللاعب نفسه (هل يسمح للآخرين بدعوته)
    if uid != target_id:
        return await c.answer("🧐 يمكنك تعديل إعداداتك فقط من 'حسابي'.", show_alert=True)
    current = db_query("SELECT allow_invites FROM users WHERE user_id = %s", (uid,))
    new_status = 0 if current[0]['allow_invites'] else 1
    db_query("UPDATE users SET allow_invites = %s WHERE user_id = %s", (new_status, uid), commit=True)
    
    await c.answer("✅ تم السماح بالطلبات" if new_status else "❌ تم قفل الطلبات")
    await process_user_search_by_id(c, target_id)

# وضعه في نهاية ملف room_multi.py
async def notify_followers_game_started(player_id, player_name, bot):
    # جلب المتابعين الذين فعلوا التنبيه
    followers = db_query("SELECT follower_id FROM follows WHERE following_id = %s AND notify_games = 1", (player_id,))
    
    for f in followers:
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👁 مشاهدة اللعبة", callback_data=f"spectate_{player_id}")]
            ])
            await bot.send_message(
                f['follower_id'],
                f"🚀 صديقك {player_name} بدأ لعبة أونو الآن! هل تريد المشاهدة؟",
                reply_markup=kb
            )
        except Exception:
            continue


@router.callback_query(F.data == "rules")
async def show_rules(c: types.CallbackQuery):
    uid = c.from_user.id
    rules_text = t(uid, "rules_text")
    kb = [
        [InlineKeyboardButton(text=t(uid, "btn_training"), callback_data="training_screen")],
        [InlineKeyboardButton(text=t(uid, "btn_back_short"), callback_data="home")],
    ]
    try:
        await c.message.edit_text(
            text=rules_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
            parse_mode="Markdown"
        )
    except Exception:
        pass
    await c.answer()


@router.callback_query(F.data == "training_screen")
async def show_training_screen(c: types.CallbackQuery):
    """عرض شاشة التدريب من داخل القوانين."""
    uid = c.from_user.id
    txt = t(uid, "training_title") + "\n\n" + t(uid, "training_content")
    kb = [
        [InlineKeyboardButton(text=t(uid, "btn_start_training_game"), callback_data="start_training_game")],
        [InlineKeyboardButton(text=t(uid, "btn_back_short"), callback_data="rules")],
        [InlineKeyboardButton(text=t(uid, "btn_home"), callback_data="home")],
    ]
    try:
        await c.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    except Exception:
        await c.message.answer(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    await c.answer()

@router.callback_query(F.data == "bot_info")
async def show_bot_info(c: types.CallbackQuery):
    uid = c.from_user.id
    raw = _read_bot_info_message()
    use_html = False
    if raw:
        text = _markdown_to_html(raw)
        use_html = True
    else:
        text = t(uid, "bot_info_title") + "\n\n" + t(uid, "bot_info_text")
    kb = [[InlineKeyboardButton(text=t(uid, "btn_back_short"), callback_data="home")]]
    parse_mode = "HTML" if use_html else "Markdown"
    try:
        await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode=parse_mode)
    except Exception:
        await c.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode=parse_mode)
    await c.answer()

@router.callback_query(F.data == "leaderboard")
@router.callback_query(F.data == "leaderboard_global")
@router.callback_query(F.data == "leaderboard_friends")
async def show_leaderboard(c: types.CallbackQuery):
    uid = c.from_user.id
    friends_only = c.data == "leaderboard_friends"
    lb_mode = "friends" if friends_only else "global"
    if friends_only:
        friend_ids = {uid}
        rows = db_query(
            "SELECT following_id AS id FROM follows WHERE follower_id = %s UNION SELECT follower_id AS id FROM follows WHERE following_id = %s",
            (uid, uid)
        )
        if rows:
            for r in rows:
                friend_ids.add(r.get('id'))
        if len(friend_ids) < 2:
            await c.answer(t(uid, "leaderboard_empty"), show_alert=True)
            return
        placeholders = ",".join(["%s"] * len(friend_ids))
        rows = db_query(
            f"SELECT user_id, player_name, COALESCE(online_points, 0) as online_points FROM users WHERE user_id IN ({placeholders}) AND (is_registered = TRUE OR online_points > 0) ORDER BY online_points DESC LIMIT 30",
            tuple(friend_ids)
        )
    else:
        rows = db_query(
            "SELECT user_id, player_name, COALESCE(online_points, 0) as online_points FROM users WHERE (is_registered = TRUE OR online_points > 0) ORDER BY online_points DESC LIMIT 50"
        )
    bot_user = (BOT_USERNAME or "").strip().lstrip("@")
    hint = t(uid, "leaderboard_hint") if bot_user else ""
    header = t(uid, "leaderboard_title") + (hint + "\n\n" if hint else "\n\n")
    if not rows:
        text = header + t(uid, "leaderboard_empty")
    else:
        lines = []
        for i, r in enumerate(rows, 1):
            raw_name = (r.get("player_name") or "—")[:20]
            pts = r.get("online_points") or 0
            # جعل الاسم رابطاً أزرقاً: عند النقر يفتح بروفايل اللاعب
            if bot_user:
                name_safe = raw_name.replace("[", "").replace("]", "").replace("(", "").replace(")", "")
                profile_url = f"https://t.me/{bot_user}?start=profile_{r.get('user_id')}_lb_{lb_mode}"
                name = f"[{name_safe}]({profile_url})"
            else:
                name = raw_name
            lines.append(t(uid, "leaderboard_row", rank=i, name=name, points=pts))
        text = header + "\n".join(lines)
    kb = [
        [InlineKeyboardButton(text=t(uid, "leaderboard_friends"), callback_data="leaderboard_friends"),
         InlineKeyboardButton(text=t(uid, "leaderboard_global"), callback_data="leaderboard_global")],
        [InlineKeyboardButton(text=t(uid, "btn_home"), callback_data="home")]
    ]
    try:
        await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    except Exception:
        await c.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    await c.answer()

# --- حظر اللاعبين لبعضهم (من جهة اللاعب فقط: لا استقبال دعوات ولا ظهور في القوائم) ---
def _is_user_blocked(blocker_id: int, blocked_id: int) -> bool:
    """هل blocker_id حظر blocked_id؟"""
    try:
        _ensure_user_blocks_table()
        r = db_query("SELECT 1 FROM user_blocks WHERE blocker_id = %s AND blocked_id = %s", (blocker_id, blocked_id))
        return bool(r)
    except Exception:
        return False

def _ensure_user_blocks_table():
    """التأكد من وجود جدول user_blocks (يُنشأ عند أول حظر إن لم يكن موجوداً)."""
    try:
        db_query(
            """CREATE TABLE IF NOT EXISTS user_blocks (
                blocker_id BIGINT NOT NULL,
                blocked_id BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (blocker_id, blocked_id)
            )""",
            commit=True
        )
    except Exception:
        pass


def _block_user(blocker_id: int, blocked_id: int) -> bool:
    try:
        _ensure_user_blocks_table()
        db_query("INSERT INTO user_blocks (blocker_id, blocked_id) VALUES (%s, %s)", (blocker_id, blocked_id), commit=True)
        return True
    except Exception:
        try:
            _ensure_user_blocks_table()
            db_query("INSERT INTO user_blocks (blocker_id, blocked_id) VALUES (%s, %s)", (blocker_id, blocked_id), commit=True)
            return True
        except Exception:
            return False

def _unblock_user(blocker_id: int, blocked_id: int):
    try:
        _ensure_user_blocks_table()
        db_query("DELETE FROM user_blocks WHERE blocker_id = %s AND blocked_id = %s", (blocker_id, blocked_id), commit=True)
    except Exception:
        pass

# --- دالة إرسال دعوة اللعب من بروفايل اللاعب ---
def _is_invite_muted(muter_id, muted_id):
    import datetime
    key = (muter_id, muted_id)
    if key not in invite_mutes:
        return None
    until = invite_mutes[key]
    if until is None:
        return "للأبد"
    if datetime.datetime.now() > until:
        del invite_mutes[key]
        return None
    delta = until - datetime.datetime.now()
    mins = int(delta.total_seconds() // 60)
    if mins >= 60:
        return f"{mins // 60} ساعة"
    return f"{mins} دقيقة"

@router.callback_query(F.data.startswith("invite_"))
async def send_game_invite(c: types.CallbackQuery):
    import datetime
    sender_id = c.from_user.id
    from_channel = c.data.startswith("invite_ch_")
    try:
        target_id = int(c.data.replace("invite_ch_", "").replace("invite_", ""))
    except (ValueError, AttributeError):
        await c.answer("⚠️ خطأ في البيانات.", show_alert=True)
        return

    if sender_id == target_id:
        await c.answer("🚫 لا يمكنك دعوة نفسك!", show_alert=True)
        return

    if _is_user_blocked(target_id, sender_id):
        await c.answer("⛔ هذا اللاعب حظرك. لا يمكنك إرسال دعوة له.", show_alert=True)
        return

    sender_data = db_query("SELECT player_name FROM users WHERE user_id = %s", (sender_id,))
    sender_name = sender_data[0]["player_name"] if sender_data else c.from_user.full_name or "لاعب"

    muted_remaining = _is_invite_muted(target_id, sender_id)
    if muted_remaining:
        await c.answer(f"⛔ أنت مكتوم من إرسال دعوات لهذا اللاعب خلال: {muted_remaining}", show_alert=True)
        return

    invite_from = _get_invite_from(target_id)
    if invite_from == "following":
        row = db_query("SELECT 1 FROM follows WHERE follower_id = %s AND following_id = %s", (target_id, sender_id))
        if not row:
            await c.answer("⛔ هذا اللاعب يستقبل الدعوات فقط من الذين يتابعهم. أنت لست من قائمة متابعاته.", show_alert=True)
            return
    elif invite_from == "followers":
        row = db_query("SELECT 1 FROM follows WHERE follower_id = %s AND following_id = %s", (sender_id, target_id))
        if not row:
            await c.answer("⛔ هذا اللاعب يستقبل الدعوات فقط من الذين يتابعونه. تابعَه أولاً ثم جرّب الدعوة.", show_alert=True)
            return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ اقبل", callback_data=f"accept_inv_{sender_id}"),
            InlineKeyboardButton(text="❌ ارفض", callback_data=f"reject_inv_{sender_id}"),
            InlineKeyboardButton(text="🔇 اكتم", callback_data=f"mute_inv_{sender_id}")
        ]
    ])
    try:
        await c.bot.send_message(
            target_id,
            f"📩 **{sender_name}** يطلبك للعب معه",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        await c.answer("✅ تم إرسال طلب اللعب بنجاح!", show_alert=True)
        if from_channel:
            await process_user_search_by_id(c, target_id, from_channel=True)
    except Exception:
        await c.answer("⚠️ تعذر إرسال الطلب (ربما قام اللاعب بحظر البوت).", show_alert=True)


@router.callback_query(F.data.startswith("mute_inv_confirm_"))
async def mute_invite_confirm(c: types.CallbackQuery):
    import datetime
    parts = c.data.split("_")
    if len(parts) < 5:
        await c.answer("⚠️ خطأ.", show_alert=True)
        return
    sender_id = int(parts[3])
    minutes = int(parts[4])
    muter_id = c.from_user.id
    if minutes == 0:
        invite_mutes[(muter_id, sender_id)] = None
        msg = "✅ تم كتم هذا اللاعب للأبد من إرسال دعوات لك."
    else:
        invite_mutes[(muter_id, sender_id)] = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
        msg = f"✅ تم كتم هذا اللاعب لمدة {minutes} دقيقة."
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="home")]])
    try:
        await c.message.edit_text(msg, reply_markup=kb)
    except Exception:
        pass


@router.callback_query(F.data.startswith("mute_inv_unmute_"))
async def mute_invite_unmute(c: types.CallbackQuery):
    """إلغاء الكتم عن اللاعب"""
    try:
        sender_id = int(c.data.split("_")[3])
    except (IndexError, ValueError):
        await c.answer("⚠️ خطأ.", show_alert=True)
        return
    muter_id = c.from_user.id
    key = (muter_id, sender_id)
    if key in invite_mutes:
        del invite_mutes[key]
    await c.answer("✅ تم إلغاء الكتم. يمكن لهذا اللاعب إرسال دعوات لك مجدداً.", show_alert=True)
    await process_user_search_by_id(c, sender_id)


@router.callback_query(F.data.startswith("user_block_"))
async def user_block_player(c: types.CallbackQuery):
    """لاعب يحظر لاعباً آخر من جهته (لا يستقبل دعواته)."""
    try:
        target_id = int(c.data.replace("user_block_", "").strip())
    except ValueError:
        await c.answer("⚠️ خطأ.", show_alert=True)
        return
    uid = c.from_user.id
    if uid == target_id:
        await c.answer("لا يمكنك حظر نفسك.", show_alert=True)
        return
    if _block_user(uid, target_id):
        await c.answer("✅ تم حظره. لن يستطيع إرسال دعوات لك ولن يظهر في قوائمك.", show_alert=True)
    else:
        await c.answer("⚠️ أنت حاظره مسبقاً.", show_alert=True)
    await process_user_search_by_id(c, target_id)


@router.callback_query(F.data.startswith("user_unblock_"))
async def user_unblock_player(c: types.CallbackQuery):
    """إلغاء حظر اللاعب (من جهة اللاعب)."""
    try:
        target_id = int(c.data.replace("user_unblock_", "").strip())
    except ValueError:
        await c.answer("⚠️ خطأ.", show_alert=True)
        return
    uid = c.from_user.id
    _unblock_user(uid, target_id)
    await c.answer("✅ تم إلغاء الحظر. يمكنه إرسال دعوات لك مجدداً.", show_alert=True)
    await process_user_search_by_id(c, target_id)


@router.callback_query(F.data.startswith("mute_inv_"))
async def mute_invite_options(c: types.CallbackQuery):
    """عرض خيارات الكتم (لا يطابق confirm أو unmute)"""
    if c.data.startswith("mute_inv_confirm_") or c.data.startswith("mute_inv_unmute_"):
        await c.answer()
        return
    parts = c.data.split("_")
    if len(parts) < 3:
        await c.answer("⚠️ خطأ.", show_alert=True)
        return
    sender_id = int(parts[2])
    kb = [
        [InlineKeyboardButton(text="كتم ساعة", callback_data=f"mute_inv_confirm_{sender_id}_60")],
        [InlineKeyboardButton(text="كتم 5 ساعات", callback_data=f"mute_inv_confirm_{sender_id}_300")],
        [InlineKeyboardButton(text="كتم 10 ساعات", callback_data=f"mute_inv_confirm_{sender_id}_600")],
        [InlineKeyboardButton(text="كتم 24 ساعة", callback_data=f"mute_inv_confirm_{sender_id}_1440")],
        [InlineKeyboardButton(text="كتم للأبد", callback_data=f"mute_inv_confirm_{sender_id}_0")],
        [InlineKeyboardButton(text="❌ إلغاء الكتم", callback_data=f"mute_inv_unmute_{sender_id}")],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data=f"view_profile_{sender_id}")]
    ]
    await c.message.edit_text("🔇 اختر مدة الكتم أو ألغِ الكتم:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await c.answer()

# --- 1. عرض خيارات الوقت (تعديل الرسالة الحالية) ---
@router.callback_query(F.data.startswith("allow_invites_"))
async def show_invite_timer_options(c: types.CallbackQuery):
    target_id = int(c.data.split("_")[2])
    uid = c.from_user.id
    
    if uid != target_id:
        return await c.answer("🧐 يمكنك تعديل إعداداتك فقط من 'حسابي'.", show_alert=True)
    text = "🕒 **مدة استقبال طلبات اللعب**\n\nاختر المدة التي تريد فيها فتح استقبال الطلبات:"
    
    kb = [
    [InlineKeyboardButton(text="⏳ لمدة دقيقة واحدة (للتجربة)", callback_data=f"set_inv_1m_{uid}")],
    [InlineKeyboardButton(text="⌛ لمدة ساعة واحدة", callback_data=f"set_inv_1h_{uid}")],
    [InlineKeyboardButton(text="✅ دائماً", callback_data=f"set_inv_always_{uid}")],
    [InlineKeyboardButton(text="❌ إغلاق الآن", callback_data=f"set_inv_off_{uid}")],
    [InlineKeyboardButton(text="🔙 رجوع", callback_data=f"view_profile_{uid}")]
    ]
    
    # تعديل نص الرسالة الحالية (نظافة تامة)
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

# --- 2. معالجة الحفظ في القاعدة مع المؤقت الجديد ---
@router.callback_query(F.data.startswith("set_inv_"))
async def process_invites_timer(c: types.CallbackQuery):
    data = c.data.split("_")
    action = data[2] # 1m, 1h, always, off
    uid = int(data[3])
    
    expiry_time = None
    status_val = 1
    
    if action == "off":
        status_val = 0
    elif action == "1m":
        expiry_time = datetime.datetime.now() + datetime.timedelta(minutes=1)
    elif action == "1h":
        expiry_time = datetime.datetime.now() + datetime.timedelta(hours=1)
    elif action == "always":
        expiry_time = None
        status_val = 1
    
    # تحديث قاعدة البيانات (تأكد من إضافة عمود invite_expiry)
    db_query("UPDATE users SET allow_invites = %s, invite_expiry = %s WHERE user_id = %s", 
    (status_val, expiry_time, uid), commit=True)
    
    await c.answer("✅ تم التحديث")
    
    # العودة لبروفايل اللاعب باستخدام تعديل الرسالة
    await process_user_search_by_id(c, uid)

# --- قبول الدعوة: إنشاء غرفة ثنائية وبدء اللعب فوراً (ظهور الأوراق) ---
@router.callback_query(F.data.startswith("accept_inv_"))
async def accept_game_invite(c: types.CallbackQuery):
    sender_id = int(c.data.split("_")[2])
    target_id = c.from_user.id

    sender_data = db_query("SELECT player_name FROM users WHERE user_id = %s", (sender_id,))
    target_data = db_query("SELECT player_name FROM users WHERE user_id = %s", (target_id,))
    s_name = sender_data[0]['player_name'] if sender_data else "لاعب"
    t_name = target_data[0]['player_name'] if target_data else "لاعب"

    code = generate_room_code()
    db_query(
        "INSERT INTO rooms (room_id, creator_id, max_players, score_limit, status) VALUES (%s, %s, 2, 0, 'playing')",
        (code, sender_id), commit=True
    )
    db_query("INSERT INTO room_players (room_id, user_id, player_name, is_ready) VALUES (%s, %s, %s, TRUE)", (code, sender_id, s_name), commit=True)
    db_query("INSERT INTO room_players (room_id, user_id, player_name, is_ready) VALUES (%s, %s, %s, TRUE)", (code, target_id, t_name), commit=True)

    try:
        from handlers.room_2p import start_new_round
        await start_new_round(code, c.bot, start_turn_idx=0)
        await c.answer("✅ تم قبول الدعوة! جاري بدء اللعبة...", show_alert=True)
    except Exception as e:
        await c.answer("⚠️ حدث خطأ في بدء اللعبة.", show_alert=True)
        try:
            await c.bot.send_message(sender_id, f"✅ وافق **{t_name}** على دعوتك! لكن حدث خطأ في بدء الجولة.")
            await c.bot.send_message(target_id, f"حدث خطأ في بدء اللعبة. جرّب إنشاء غرفة من القائمة.")
        except Exception:
            pass

# --- 2. دالة رفض الطلب (تنفذ عند ضغط الصديق على ❌ رفض) ---
@router.callback_query(F.data.startswith("reject_inv_"))
async def reject_game_invite(c: types.CallbackQuery):
    sender_id = int(c.data.split("_")[2])
    target_name = c.from_user.full_name
    
    try:
        await c.bot.send_message(sender_id, f"❌ اعتذر **{target_name}** عن اللعب حالياً.")
    except Exception:
        pass
    try:
        await c.message.delete()
        await c.answer("تم رفض الطلب بنجاح.")
    except Exception:
        await c.message.edit_text("❌ تم رفض الطلب.")


def _channel_post_buttons(publisher_uid: int, add_profile: bool, join_code: str = None, post_id: int = None, likes_count: int = 0) -> InlineKeyboardMarkup:
    """أزرار تحت منشور القناة: حساب اللاعب، العب معي، لايك."""
    bot_user = (BOT_USERNAME or "").strip().lstrip("@")
    if not bot_user:
        return None
    rows = []
    if add_profile:
        url = f"https://t.me/{bot_user}?start=profile_{publisher_uid}"
        if post_id:
            url = f"https://t.me/{bot_user}?start=profile_{publisher_uid}_{post_id}"
        rows.append([InlineKeyboardButton(text="👤 حساب اللاعب", url=url)])
    if join_code:
        rows.append([InlineKeyboardButton(text="🎮 العب معي", url=f"https://t.me/{bot_user}?start=join_{join_code}")])
    if post_id is not None:
        rows.append([InlineKeyboardButton(text=f"❤️ لايك ({likes_count})", url=f"https://t.me/{bot_user}?start=like_{post_id}")])
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


# هاندلرز المجتمع والنشر (waiting_options / waiting_message) في handlers/community_publish.py


@router.callback_query(F.data == "check_channel_sub")
async def on_check_channel_sub(c: types.CallbackQuery, state: FSMContext):
    if not CHANNEL_ID:
        await c.answer()
        return
    # التحقق من الاشتراك (لا يعترضه الـ middleware ليكون التحقق هنا فقط)
    try:
        is_member = await is_channel_member(c.bot, c.from_user.id)
    except Exception:
        is_member = False
    if not is_member:
        await c.answer(t(c.from_user.id, "still_not_subscribed"), show_alert=True)
        return
    await state.clear()
    uid = c.from_user.id
    # التأكد من وجود المستخدم في القاعدة (قد يكون جديداً ولم يمرّ بـ /start)
    user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    if not user:
        try:
            db_query(
                "INSERT INTO users (user_id, username, is_registered) VALUES (%s, %s, FALSE)",
                (uid, c.from_user.username or ""),
                commit=True,
            )
        except Exception:
            pass
        user = db_query("SELECT * FROM users WHERE user_id = %s", (uid,))
    # إذا لم يكن مسجّلاً أو ليس لديه حساب، نعرض له تسجيل الدخول أو إنشاء حساب
    if not user or not user[0].get("is_registered") or not user[0].get("username_key"):
        lang = get_lang(uid)
        set_lang(uid, lang)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(uid, "btn_register"), callback_data="auth_register")],
                [InlineKeyboardButton(text=t(uid, "btn_login"), callback_data="auth_login")],
            ]
        )
        try:
            await c.message.edit_text(
                "✅ تم التحقق من الاشتراك.\n\n" + t(uid, "welcome_new"),
                reply_markup=kb,
            )
        except Exception:
            await c.message.answer("✅ تم التحقق من الاشتراك.\n\n" + t(uid, "welcome_new"), reply_markup=kb)
        await c.answer("✅ تم التحقق، سجّل أو ادخل لحسابك.")
        return
    # إذا كان لديه دعوة انضمام محفوظة (ضغط الرابط قبل الاشتراك): ننضمّه للغرفة الآن
    pending_code = None
    try:
        if user[0].get("pending_room_code"):
            pending_code = _normalize_join_code("join_" + str(user[0]["pending_room_code"]))
        if pending_code:
            db_query("UPDATE users SET pending_room_code = NULL WHERE user_id = %s", (uid,), commit=True)
            class _FakeMsg:
                pass
            m = _FakeMsg()
            m.from_user = c.from_user
            m.answer = c.message.answer
            m.bot = c.bot
            m.chat = c.message.chat
            await _join_room_by_code(m, pending_code, user[0])
            await c.answer("✅ تم التحقق، تم انضمامك للغرفة!")
            return
    except Exception:
        pass
    name = user[0].get("player_name") or c.from_user.full_name
    await show_main_menu(c.message, name, user_id=uid, state=state)
    await c.answer("✅ تم التحقق، مرحباً!")

@router.callback_query(F.data == "home")
async def home_callback(c: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user = db_query("SELECT player_name FROM users WHERE user_id = %s", (c.from_user.id,))
    name = user[0]['player_name'] if user else c.from_user.full_name

    # تشغيل المنيو الرئيسي عند الضغط على عودة
    await show_main_menu(c.message, name, user_id=c.from_user.id, state=state)
    await c.answer()


# مجتمع الأونو والنشر: الروتر يُسجّل من bot.py أولاً حتى تعمل رسائل النشر (لا يُسجّل هنا لتجنب التكرار)
# كان: router.include_router(community_publish) — نُقل إلى bot.py
