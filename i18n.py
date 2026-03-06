# -*- coding: utf-8 -*-
"""
ترجمة البوت: عربي (ar)، إنجليزي (en)، فارسي إيراني (fa)
⚠️ لا تستورد من handlers أبداً (مثل from handlers.common import ...) لتجنب الاستيراد الدائري.
"""
from database import db_query

# الترجمة الافتراضية عند غياب المفتاح
DEFAULT_LANG = "ar"

# كاش لتقليل استدعاءات قاعدة البيانات (لغة المستخدم)
_lang_cache = {}

def get_lang(user_id: int) -> str:
    if user_id in _lang_cache:
        return _lang_cache[user_id]
    try:
        r = db_query("SELECT language FROM users WHERE user_id = %s", (user_id,))
        if r and r[0].get("language") in ("ar", "en", "fa"):
            _lang_cache[user_id] = r[0]["language"]
            return _lang_cache[user_id]
    except Exception:
        pass
    _lang_cache[user_id] = DEFAULT_LANG
    return DEFAULT_LANG

def set_lang(user_id: int, lang: str):
    _lang_cache[user_id] = lang if lang in ("ar", "en", "fa") else DEFAULT_LANG
    try:
        db_query("UPDATE users SET language = %s WHERE user_id = %s", (lang, user_id), commit=True)
    except Exception:
        pass

def t(user_id: int, key: str, **kwargs) -> str:
    lang = get_lang(user_id)
    texts = TEXTS.get(lang) or TEXTS.get(DEFAULT_LANG) or {}
    s = texts.get(key) or TEXTS.get("ar", {}).get(key) or key
    if kwargs:
        try:
            s = s.format(**kwargs)
        except KeyError:
            pass
    return s

# --- النصوص حسب اللغة ---
TEXTS = {
    "ar": {
        "welcome_new": "مرحباً! 👋\nسجّل الدخول أو أنشئ حساباً للعب.",
        "btn_register": "📝 تسجيل",
        "btn_login": "🔐 دخول",
        "ask_name": "✍️ أرسل اسمك (اسم اللاعب):",
        "ask_password": "🔑 أرسل كلمة السر (4 أحرف أو أكثر):",
        "name_too_short": "❌ الاسم قصير جداً. أرسل اسمك مرة ثانية:",
        "name_too_long": "❌ الاسم طويل جداً. اختصر وأرسل:",
        "name_taken": "❌ هذا الاسم مستخدم. اختر غيره:",
        "password_too_short": "❌ كلمة السر ضعيفة. أرسل 4 أحرف أو أكثر:",
        "reg_success": "✅ تم التسجيل! مرحباً {name}، يوزرك: @{username}",
        "profile_complete": "✅ تم! مرحباً {name}. كلمة السر محفوظة.",
        "register_success": "✅ تم التسجيل بنجاح! مرحباً {name}، كلمة السر: {password}",
        "login_ask_name": "🔐 أدخل اسم المستخدم (اليوزر نيم) للدخول:",
        "login_ask_password": "🔑 أدخل كلمة السر:",
        "login_fail": "❌ فشل الدخول. تحقق من اليوزر نيم وكلمة السر.",
        "login_success": "✅ تم الدخول! مرحباً {name}.",
        "room_not_found": "❌ الغرفة غير موجودة أو انتهت.",
        "already_in_room": "⚠️ أنت بالفعل في غرفة.",
        "room_full": "⚠️ الغرفة ممتلئة.",
        "game_starting_2p": "🎮 بدأت اللعبة! استعد...",
        "game_starting_multi": "🎮 بدأت اللعبة! عدد اللاعبين: {n}. استعد...",
        "🎮 بدأت اللعبة! استعد...": "🎮 بدأت اللعبة! استعد...",
        "btn_home": "🏠 الرئيسية",
        "player_joined": "✅ انضم {name} للغرفة ({count}/{max}). اللاعبون: {list}",
        "waiting_players": " ⏳ بانتظار {n} لاعب.",
        "🤌🏻اصبر شوي ": "🤌🏻 اصبر شوي",
        "➕ إنشاء غرفة": "➕ إنشاء غرفة",
        "🚪 انضمام لغرفة": "🚪 انضمام لغرفة",
        "الغرف المفتوحة": "الغرف المفتوحة",
        "الرجوع": "🔙 رجوع",
        "friends_menu": "🎮 اللعب مع الأصدقاء\n\nاختر:",
        "no_open_rooms": "⚠️ لا توجد غرف مفتوحة.",
        "open_rooms_list": "📋 غرفك المفتوحة:",
        "room_detail": "🛏 غرفة: {code}\n👥 اللاعبون ({count}/{max}): {players}\n\n🔗 رابط الدخول:\n{link}",
        "btn_close_room": "🚪 إغلاق الغرفة",
        "btn_back": "🔙 رجوع",
        "my_open_rooms": "الغرف المفتوحة",
        "room_gone": "⚠️ الغرفة لم تعد موجودة.",
        "room_closed_notification": "⚠️ تم إغلاق الغرفة من قبل صاحبها.",
        "room_closed": "✅ تم إغلاق الغرفة.",
        "no_open_rooms_text": "لا توجد غرف مفتوحة. أنشئ غرفة أو انضم بكود.",
        "send_room_code": "🔑 أرسل رمز الغرفة (5 أحرف):",
        "btn_random_play": "🎲 لعب عشوائي",
        "btn_play_vs_bot": "🤖 اللعب مع البوت",
        "btn_play_friends": "👥 لعب مع الأصدقاء",
        "no_players_offer_bot": "لا يوجد لاعبين الآن.\n\nهل تود اللعب مع البوت (بالذكاء الصناعي)؟",
        "no_players_offer_bot_btn": "🤖 نعم، العب مع البوت",
        "random_wait_30": "⏳ جاري البحث عن خصم... لديك 30 ثانية.\nإذا لم ينضم أحد سنعرض عليك اللعب مع البوت.",
        "no_player_after_30": "⏳ انتهت الـ 30 ثانية.\n\nلا يوجد لاعب. هل تريد اللعب مع البوت؟",
        "btn_yes_play_bot": "🤖 نعم، العب",
        "btn_random_again": "🎲 طلب لعب عشوائي مجدداً",
        "btn_my_account": "👤 حسابي",
        "main_menu": "🎮 أهلاً {name}\n\nاختر:",
        "lang_changed": "✅ تم تغيير اللغة.",
        "status_online": "🟢 متصل الآن",
        "status_offline": "⚫ آخر ظهور: {time}",
        "profile_title": "اسم الاعب 👤 **{name}**\nيوزر الاعب 🆔 @{username}\n⭐ نقاط: {points}\n{status}",
        "profile_followers_count": "عدد متابعينه {count}",
        "profile_following_count": "عدد الي يتابعهم {count}",
        "btn_follow": "➕ متابعة",
        "btn_unfollow": "➖ إلغاء المتابعة",
        "btn_invite_play": "🎮 دعوة للعب",
        "btn_followers_list": "👥 يتابعونني",
        "btn_following_list": "👥 أتابعهم",
        "btn_friends": "👥 الأصدقاء",
        "btn_calc": "🧮 حاسبة أونو",
        "btn_rules": "📜 القوانين",
        "btn_leaderboard": "📊 الإحصائيات",
        "btn_bot_info": "ℹ️ معلومات البوت",
        "btn_change_lang": "🌍 تغيير اللغة",
        "choose_language": "🌍 **اختر اللغة:**",
        "menu_updated": "تم تحديث القائمة 🎮",
        "invite_pending_room": "🎮 لديك دعوة للانضمام إلى غرفة! سجّل الدخول أو أنشئ حساباً ثم سيتم إدخالك للغرفة تلقائياً.",
        "rules_text": (
        "📜 **قوانين اللعب - أونو العراق 🇮🇶**\n\n"
        "**أساسيات اللعبة**\n"
        "• كل لاعب يسحب ٧ أوراق.\n"
        "• الباقي من الورق يسمى «كومة السحب».\n"
        "• أول ورقة تنزل يضعها البوت من كومة السحب.\n"
        "• اللعب يكون مع عقارب الساعة.\n\n"
        "**من يلعب أولاً؟**\n"
        "• **اللعب العشوائي:** أول واحد يلعب هو من يرسل طلب لعب عشوائي أولاً.\n"
        "• **وضع الغرف:** صاحب الغرفة يلعب أولاً ويبدأ اللعب.\n\n"
        "**هدفك**\n"
        "أن تخلص الأوراق التي في يدك كلها. الورقة التي تلعبها يجب أن تكون:\n"
        "• إما نفس لون الورقة النازلة (حتى لو الرقم يختلف)،\n"
        "• أو نفس الرقم النازل (حتى لو اللون يختلف).\n\n"
        "**أوراق الأكشن**\n"
        "• **لون معين +2:** في اللعب العشوائي الخصم يتعاقب بسحب ورقتين واللعب يرجع لك، ولازم تلعب نفس لونها. في وضع الغرف: الذي بعدك يتعاقب ويسحب ورقتين وينتقل اللعب للاعب الذي بعده، ولازم يلعب نفس لونها.\n"
        "• **لون معين 🚫:** في اللعب العشوائي يرجع اللعب لك ولازم تلعب نفس لونها. في وضع الغرف: الذي بعدك يُمنع وينتقل الدور للي بعده، ولازم يلعب نفس لونها.\n"
        "• **لون معين 🔄:** في الوضع العشوائي الدور يرجع لك ولازم تلعب نفس لونها. في وضع الغرف: اتجاه اللعب يتحول عكس عقارب الساعة.\n\n"
        "**أوراق الجوكر**\n"
        "• **جوكر 💧 +1:** في اللعب العشوائي يمكنك لعبها في أي وقت وعلى أي ورقة ولون ورقم؛ تجبر الخصم أن يسحب ورقة من كومة السحب ويعود الدور لك ويمكنك أن تلعب أي ورقة. في وضع الغرف: عند لعبها تختار لوناً، واللاعب التالي يسحب ورقة من كومة السحب ولا يلعب، وينتقل الدور للي بعده وهو مجبر أن يلعب باللون الذي اخترته.\n"
        "• **جوكر 🌊 +2:** نفس الفكرة مع سحب ورقتين. في وضع الغرف: تختار لون، التالي يسحب ورقتين ولا يلعب، والدور للي بعده وهو مجبر أن يلعب باللون الذي اخترته.\n"
        "• **🔥 +4:** مثل جوكر +1 و +2 إلا أن لها قانوناً خاصاً: **لا تلعب هذه الورقة إلا إذا لم يكن لديك ورقة أخرى صالحة للعب.** إذا لعبتها:\n"
        "  - **اللعب العشوائي:** ينتظر خصمك إما يقبل السحب ويصمت ويعود الدور لك، أو يختار التحدي. **التحدي:** البوت يفحص أوراقك؛ إن كنت لعبتها فعلاً وليس لديك ورقة مناسبة يُعاقب اللاعب الآخر (يسحب ٦ ورقات كلياً) ويرجع اللعب لك. وإن كنت لعبتها وكان لديك ورقة مناسبة يُرجع البوت الورقة عليك ويسحبك ٦ ورقات عقوبة.\n"
        "  - **وضع الغرف:** عند لعبها تختار لوناً، ونفس موضوع التحدي إلا أن الدور لا يعود لك بل ينتقل للي بعده وهو مجبر أن يلعب نفس اللون الذي اخترته.\n"
        "• **ورقة 🌈:** في اللعب العشوائي والغرف تجبر اللاعب التالي أن يلعب بلون تختاره؛ عند لعبها عليك اختيار لون.\n\n"
        "**ملاحظات**\n"
        "• إن أُجبرت على اختيار لون وليس لديك ذلك اللون، يمكنك لعب ورقة جوكر إن كنت تملكها.\n"
        "• إن لعبت ورقة خطأ يعاقبك البوت لمحاولة الغش، ويرجع الورقة لك ويرجع اللعب لك ويسحبك ورقة.\n"
        "• لكل لاعب مهلة ٢٠ ثانية للعب.\n"
        "• لكل لاعب مهلة ١٠ ثوانٍ لقرار السحب أو التحدي.\n"
        "• يمكنك إرسال رسائل للاعبين وستُقرأ وتختفي خلال ٥ ثوانٍ.\n"
        "• يمكن للاعبين التبليغ على لاعب أساء الأدب وسيُحظر أو يُعاقب."
    ),
        "btn_back_short": "🔙 عودة",
        "tutorial_title": "🎓 مرحباً! جولة سريعة على البوت",
        "tutorial_body": "• **لعب عشوائي:** البوت يلاقي لك خصم وتبدأون.\n• **لعب مع الأصدقاء:** تنشئ غرفة أو تنضم بكود أو رابط.\n• **حسابي:** تعديل الاسم والإعدادات.\n• **القوانين:** قوانين أونو كاملة.\n\nاضغط «جرب الآن» لفتح القائمة والبدء!",
        "tutorial_btn": "✅ جرب الآن",
        "invite_reminder": "⏰ تذكير: ما زال عندك دعوة للعب! الرد خلال 15 ثانية المتبقية.",
        "leaderboard_title": "📊 **لوحة المتصدرين**",
        "leaderboard_global": "🌍 الكل",
        "leaderboard_friends": "👥 متابعيني فقط",
        "leaderboard_empty": "لا يوجد لاعبون بعد.",
        "leaderboard_row": "{rank}. {name} — {points} نقطة",
        "leaderboard_hint": "\n_انقر على اسم اللاعب لعرض معلوماته._",
        "round_summary_won": "فاز بالجولة",
        "match_history_title": "📜 آخر مبارياتك",
        "match_history_none": "لا توجد مباريات مسجلة بعد.",
        "match_history_row": "جولة {round} — فزت 🏆 (غرفة {room})",
        "public_rooms_title": "🚪 **غرف عامة**\nاختر غرفة للانضمام:",
        "public_rooms_none": "لا توجد غرف مفتوحة حالياً.",
        "public_room_row": "غرفة {code} — {current}/{max} لاعبين",
        "btn_join": "انضم",
        "replay_again_btn": "🔄 لعب مرة أخرى",
        "replay_again_msg": "🏁 انتهت الجولة! اضغط «لعب مرة أخرى» لدعوة نفس الفريق.",
        "btn_public_rooms": "🚪 غرف عامة",
        "player_removed_5_skips": "⛔ تم إزالتك من اللعب تلقائياً لأنك تركت الدور 5 مرات.",
        "player_removed_5_skips_others": "⛔ تم إزالة {name} من اللعب (ترك الدور 5 مرات).",
        "bot_info_title": "ℹ️ **معلومات البوت**",
        "bot_info_text": (
            "🎮 **مرحباً بكم في بوت أونو**\n\n"
            "هنا كل شيء تقدر تسويه داخل البوت 👇\n\n"
            "🎲 **1) لعب عشوائي**\n"
            "• 🔍 البوت يدور لك خصم وتبدون فوراً.\n"
            "• ⏳ لكل لاعب وقت محدد حتى يلعب.\n"
            "• 🃏 تلعب نفس **اللون** أو نفس **الرقم/الرمز** مثل الورقة النازلة.\n"
            "• ✅ إذا بقي عندك ورقتين و\"تشتغل\" تقدر تستخدم زر **🚨 اونو!**\n"
            "• 🪤 إذا خصمك بقى عنده ورقة وحدة وما صاح \"اونو\"، تقدر تسوي **صيدة** (إذا متاحة).\n"
            "• 📢 إذا ما فيه لاعبين، يظهرلك خيار **اللعب مع البوت بالذكاء الصناعي**.\n\n"
            "🤖 **2) اللعب مع البوت (الذكاء الصناعي)**\n"
            "• 🎮 من القائمة: زر **اللعب مع البوت** وتبدأ جولة ضد البوت مباشرة.\n"
            "• 🧠 البوت يلعب تلقائياً (يختار الورقة، اللون للجوكر، يقبل/يتحدى +4).\n"
            "• 📢 من **لعب عشوائي**: إذا ما فيه خصم، يظهر خيار «هل تود اللعب مع البوت؟».\n\n"
            "👥 **3) لعب مع الأصدقاء (الغرف)**\n"
            "تقدر:\n"
            "• ➕ **تنشئ غرفة** وتحدد:\n"
            "  - 👥 عدد اللاعبين\n"
            "  - 🎯 سقف النقاط (أو جولة واحدة)\n"
            "• 🔑 **تنضم بكود** أو **برابط دعوة**.\n"
            "• 🚪 تشوف **الغرف المتوفرة** وتدخل/تنسحب.\n"
            "• 📋 تشوف **غرفك المفتوحة** وتلغيها.\n"
            "• 🚪 تدخل **غرف عامة** (إذا مفعلة).\n\n"
            "👤 **4) حسابك وبروفايلات اللاعبين**\n"
            "• 👤 **حسابي**: تشوف معلوماتك ونقاطك وتقدر تعدّل بياناتك.\n"
            "• 🔍 تقدر تفتح **بروفايل أي لاعب** وتشوف نقاطه وحالته.\n"
            "• ➕ **متابعة / إلغاء المتابعة** لأي لاعب.\n"
            "• 🎮 **دعوة للعب** من داخل بروفايل اللاعب.\n\n"
            "📊 **5) لوحة المتصدرين (الإحصائيات)**\n"
            "• 📊 تعرض أفضل اللاعبين حسب النقاط.\n"
            "• 🔵 **انقر على اسم اللاعب لعرض معلوماته** (يفتح بروفايله مباشرة).\n\n"
            "👥 **6) القائمة الاجتماعية**\n"
            "• 📈 تشوف **المتابعين** و **اللي تتابعهم**.\n"
            "• 🔍 تبحث عن لاعب وتفتح بروفايله.\n"
            "• 🔕 تحكم بكتم دعوات لاعب (إذا ظهر الخيار).\n\n"
            "🧮 **7) حاسبة نقاط أونو**\n"
            "• تحسب النقاط بسهولة من داخل البوت.\n\n"
            "📜 **8) القوانين**\n"
            "• شرح كامل للقوانين + شرح أوراق الأكشن والجوكر.\n"
            "• 🔥 جوكر +4 فيه **تحدي** والبوت يفحص إذا اللعب صحيح أو غش.\n\n"
            "🏁 **9) بعد نهاية الجولة**\n"
            "• 🔄 زر **لعب مرة أخرى** لدعوة نفس الفريق بسرعة.\n"
            "• 📢 قد يظهر زر **نشر فوزك** (مع مجموع نقاطك) إذا ميزة النشر مفعلة.\n\n"
            "👥 **10) مجتمع الأونو (القناة)**\n"
            "إذا ميزة المجتمع مفعلة:\n"
            "• 📢 تقدر **تنشر منشور بالقناة** (نص/صورة/فيديو…).\n"
            "• 👤 تقدر تضيف زر \"حسابي\" تحت المنشور.\n"
            "• 🎮 تقدر تضيف زر \"العب معي\" حتى أي شخص ينضم لك بسرعة.\n\n"
            "🌍 **11) تغيير اللغة**\n"
            "• 🇮🇶 عربي  • 🇬🇧 English  • 🇮🇷 فارسی\n\n"
            "──────────────\n"
            "📩 **اقتراحاتكم وملاحظاتكم نستقبلها عبر** @Branch"
        ),
    },
    "en": {
        "welcome_new": "Welcome! 👋\nLog in or register to play.",
        "btn_register": "📝 Register",
        "btn_login": "🔐 Log in",
        "ask_name": "✍️ Send your name (player name):",
        "ask_password": "🔑 Send your password (4+ characters):",
        "name_too_short": "❌ Name too short. Send again:",
        "name_too_long": "❌ Name too long. Shorten and send:",
        "name_taken": "❌ This name is taken. Choose another:",
        "password_too_short": "❌ Password too weak. Send 4+ characters:",
        "reg_success": "✅ Registered! Hi {name}, username: @{username}",
        "profile_complete": "✅ Done! Welcome {name}. Password saved.",
        "register_success": "✅ Registered! Hi {name}, password: {password}",
        "login_ask_name": "🔐 Enter username to log in:",
        "login_ask_password": "🔑 Enter password:",
        "login_fail": "❌ Login failed. Check username and password.",
        "login_success": "✅ Logged in! Hi {name}.",
        "room_not_found": "❌ Room not found or expired.",
        "already_in_room": "⚠️ You are already in a room.",
        "room_full": "⚠️ Room is full.",
        "game_starting_2p": "🎮 Game started! Get ready...",
        "game_starting_multi": "🎮 Game started! Players: {n}. Get ready...",
        "🎮 بدأت اللعبة! استعد...": "🎮 Game started! Get ready...",
        "btn_home": "🏠 Home",
        "player_joined": "✅ {name} joined the room ({count}/{max}). Players: {list}",
        "waiting_players": " ⏳ Waiting for {n} player(s).",
        "🤌🏻اصبر شوي ": "🤌🏻 Hold on...",
        "➕ إنشاء غرفة": "➕ Create room",
        "🚪 انضمام لغرفة": "🚪 Join room",
        "الغرف المفتوحة": "Open rooms",
        "الرجوع": "🔙 Back",
        "friends_menu": "🎮 Play with friends\n\nChoose:",
        "no_open_rooms": "⚠️ No open rooms.",
        "open_rooms_list": "📋 Your open rooms:",
        "room_detail": "🛏 Room: {code}\n👥 Players ({count}/{max}): {players}\n\n🔗 Join link:\n{link}",
        "btn_close_room": "🚪 Close room",
        "btn_back": "🔙 Back",
        "my_open_rooms": "Open rooms",
        "room_gone": "⚠️ Room no longer exists.",
        "room_closed_notification": "⚠️ The room was closed by the host.",
        "room_closed": "✅ Room closed.",
        "no_open_rooms_text": "No open rooms. Create one or join with a code.",
        "send_room_code": "🔑 Send the room code (5 characters):",
        "btn_random_play": "🎲 Random play",
        "btn_play_vs_bot": "🤖 Play vs Bot",
        "btn_play_friends": "👥 Play with friends",
        "no_players_offer_bot": "No players available right now.\n\nWould you like to play with the Bot (AI)?",
        "no_players_offer_bot_btn": "🤖 Yes, play with Bot",
        "random_wait_30": "⏳ Searching for an opponent... You have 30 seconds.\nIf no one joins, we'll offer you to play with the Bot.",
        "no_player_after_30": "⏳ 30 seconds are up.\n\nNo player joined. Would you like to play with the Bot?",
        "btn_yes_play_bot": "🤖 Yes, play",
        "btn_random_again": "🎲 Search again for random match",
        "btn_my_account": "👤 My account",
        "main_menu": "🎮 Hello {name}\n\nChoose:",
        "lang_changed": "✅ Language changed.",
        "status_online": "🟢 Online",
        "status_offline": "⚫ Last seen: {time}",
        "profile_title": "👤 **{name}**\n🆔 @{username}\n⭐ Points: {points}\n{status}",
        "profile_followers_count": "Followers: {count}",
        "profile_following_count": "Following: {count}",
        "btn_follow": "➕ Follow",
        "btn_unfollow": "➖ Unfollow",
        "btn_invite_play": "🎮 Invite to play",
        "btn_followers_list": "👥 Follow me",
        "btn_following_list": "👥 I follow",
        "btn_friends": "👥 Friends",
        "btn_calc": "🧮 Uno Calculator",
        "btn_rules": "📜 Rules",
        "btn_leaderboard": "📊 Statistics",
        "btn_bot_info": "ℹ️ Bot info",
        "btn_change_lang": "🌍 Change language",
        "choose_language": "🌍 **Choose language:**",
        "menu_updated": "Menu updated 🎮",
        "invite_pending_room": "🎮 You have an invite to join a room! Log in or register and you will join automatically.",
        "rules_text": "📜 **Uno Iraq 🇮🇶 - Full Rules**\n\nThe goal is to get rid of all your cards first. When you have one card left, you must press \"Uno\" immediately, or you draw penalty cards!\n\n🔹 **Special cards:**\n1️⃣ **Draw 2 (+2):** The next player draws 2 and skips their turn, unless they have +2 and stack it (draw 4).\n2️⃣ **Reverse (🔄):** Reverses play direction.\n3️⃣ **Skip (🚫):** The next player is skipped.\n4️⃣ **Wild (🌈):** Choose the new color.\n5️⃣ **Wild Draw 4 (🌈+4):** Strongest card! Choose color and the next player draws 4. They can challenge if they think you had a matching color.\n\n🔹 **Challenge & penalties:**\n- **+4 challenge:** If you get +4 and suspect the player had a matching color, you can challenge. If they cheated, they draw 4. If not, you draw 6!\n- **Forgot Uno:** If you had one card and didn't say \"Uno\" and get caught, you draw 2.\n\n🔹 **End of game:**\nThe round ends when one player runs out of cards. Remaining cards in others' hands are counted as points and added to the winner's score.",
        "btn_back_short": "🔙 Back",
        "tutorial_title": "🎓 Hi! Quick tour of the bot",
        "tutorial_body": "• **Random play:** The bot finds you an opponent and you start.\n• **Play with friends:** Create a room or join with a code/link.\n• **My account:** Edit name and settings.\n• **Rules:** Full Uno rules.\n\nPress «Try now» to open the menu and start!",
        "tutorial_btn": "✅ Try now",
        "invite_reminder": "⏰ Reminder: You still have a game invite! Reply within the next 15 seconds.",
        "leaderboard_title": "📊 **Leaderboard**",
        "leaderboard_global": "🌍 Everyone",
        "leaderboard_friends": "👥 My follows only",
        "leaderboard_empty": "No players yet.",
        "leaderboard_row": "{rank}. {name} — {points} pts",
        "leaderboard_hint": "\n\n_Tap a player name to open their profile._",
        "round_summary_won": "won the round",
        "match_history_title": "📜 Your last matches",
        "match_history_none": "No matches recorded yet.",
        "match_history_row": "Round {round} — You won 🏆 (room {room})",
        "public_rooms_title": "🚪 **Public rooms**\nChoose a room to join:",
        "public_rooms_none": "No open rooms at the moment.",
        "public_room_row": "Room {code} — {current}/{max} players",
        "btn_join": "Join",
        "replay_again_btn": "🔄 Play again",
        "replay_again_msg": "🏁 Round over! Press «Play again» to invite the same team.",
        "btn_public_rooms": "🚪 Public rooms",
        "player_removed_5_skips": "⛔ You were removed from the game for skipping your turn 5 times.",
        "player_removed_5_skips_others": "⛔ {name} was removed from the game (skipped 5 times).",
        "bot_info_title": "ℹ️ **Bot info**",
        "bot_info_text": (
            "🎮 **Welcome to Uno Bot**\n\n"
            "Here’s what you can do 👇\n\n"
            "🎲 **1) Random play**\n"
            "• 🔍 The bot finds you an opponent and you start immediately.\n"
            "• ⏳ Each player has a limited time to play.\n"
            "• 🃏 Play the same **color** or the same **number/symbol**.\n"
            "• If no players are available, you get the option to **play vs Bot (AI)**.\n\n"
            "🤖 **2) Play with Bot (AI)**\n"
            "• From the menu: **Play vs Bot** starts a game against the bot.\n"
            "• The bot plays automatically (picks cards, chooses color for wild, accepts/challenges +4).\n"
            "• From **random play**: if no opponent is found, you can choose to play with the bot.\n\n"
            "👥 **3) Play with friends (rooms)**\n"
            "• ➕ Create a room and set players/score limit.\n"
            "• 🔑 Join by code or invite link.\n"
            "• 🚪 Public rooms (if enabled).\n\n"
            "👤 **4) My account & profiles**\n"
            "• View your points and account.\n"
            "• Follow/unfollow players, invite them to play.\n\n"
            "📊 **5) Leaderboard**\n"
            "• Tap a player name to open their profile.\n\n"
            "🧮 **6) Uno calculator**\n"
            "• Calculate points from inside the bot.\n\n"
            "📜 **7) Rules**\n"
            "• Full rules + special cards + +4 challenge.\n\n"
            "🏁 **8) After the round**\n"
            "• **Play again** and **Share your win** (with your total points) if publishing is enabled.\n\n"
            "🌍 **9) Language**\n"
            "• Arabic • English • Persian\n\n"
            "──────────────\n"
            "📩 **We welcome your suggestions and feedback via** @Branch"
        ),
    },
    "fa": {
        "welcome_new": "خوش آمدید! 👋\nبرای بازی وارد شوید یا ثبت‌نام کنید.",
        "btn_register": "📝 ثبت‌نام",
        "btn_login": "🔐 ورود",
        "ask_name": "✍️ نام خود را بفرستید (نام بازیکن):",
        "ask_password": "🔑 رمز عبور را بفرستید (حداقل ۴ کاراکتر):",
        "name_too_short": "❌ نام خیلی کوتاه است. دوباره بفرستید:",
        "name_too_long": "❌ نام خیلی بلند است. کوتاه کنید و بفرستید:",
        "name_taken": "❌ این نام قبلاً استفاده شده. یکی دیگر انتخاب کنید:",
        "password_too_short": "❌ رمز عبور ضعیف است. حداقل ۴ کاراکتر بفرستید:",
        "reg_success": "✅ ثبت‌نام شد! سلام {name}، نام کاربری: @{username}",
        "profile_complete": "✅ انجام شد! خوش آمدید {name}. رمز ذخیره شد.",
        "register_success": "✅ ثبت‌نام انجام شد! سلام {name}، رمز: {password}",
        "login_ask_name": "🔐 نام کاربری را برای ورود وارد کنید:",
        "login_ask_password": "🔑 رمز عبور را وارد کنید:",
        "login_fail": "❌ ورود ناموفق. نام کاربری و رمز را بررسی کنید.",
        "login_success": "✅ وارد شدید! سلام {name}.",
        "room_not_found": "❌ اتاق پیدا نشد یا منقضی شده.",
        "already_in_room": "⚠️ شما الان در یک اتاق هستید.",
        "room_full": "⚠️ اتاق پر است.",
        "game_starting_2p": "🎮 بازی شروع شد! آماده باشید...",
        "game_starting_multi": "🎮 بازی شروع شد! بازیکنان: {n}. آماده باشید...",
        "🎮 بدأت اللعبة! استعد...": "🎮 بازی شروع شد! آماده باشید...",
        "btn_home": "🏠 خانه",
        "player_joined": "✅ {name} به اتاق پیوست ({count}/{max}). بازیکنان: {list}",
        "waiting_players": " ⏳ در انتظار {n} بازیکن.",
        "🤌🏻اصبر شوي ": "🤌🏻 صبر کنید...",
        "➕ إنشاء غرفة": "➕ ساخت اتاق",
        "🚪 انضمام لغرفة": "🚪 پیوستن به اتاق",
        "الغرف المفتوحة": "اتاق‌های باز",
        "الرجوع": "🔙 بازگشت",
        "friends_menu": "🎮 بازی با دوستان\n\nانتخاب کنید:",
        "no_open_rooms": "⚠️ اتاق بازی وجود ندارد.",
        "open_rooms_list": "📋 اتاق‌های باز شما:",
        "room_detail": "🛏 اتاق: {code}\n👥 بازیکنان ({count}/{max}): {players}\n\n🔗 لینک ورود:\n{link}",
        "btn_close_room": "🚪 بستن اتاق",
        "btn_back": "🔙 بازگشت",
        "my_open_rooms": "اتاق‌های باز",
        "room_gone": "⚠️ اتاق دیگر وجود ندارد.",
        "room_closed_notification": "⚠️ اتاق توسط سازنده بسته شد.",
        "room_closed": "✅ اتاق بسته شد.",
        "no_open_rooms_text": "اتاق بازی ندارید. یکی بسازید یا با کد وارد شوید.",
        "send_room_code": "🔑 کد اتاق (۵ کاراکتر) را بفرستید:",
        "btn_random_play": "🎲 بازی تصادفی",
        "btn_play_vs_bot": "🤖 بازی با ربات",
        "btn_play_friends": "👥 بازی با دوستان",
        "no_players_offer_bot": "الان بازیکنی آنلاین نیست.\n\nمی‌خواهید با ربات (هوش مصنوعی) بازی کنید؟",
        "no_players_offer_bot_btn": "🤖 بله، بازی با ربات",
        "random_wait_30": "⏳ در حال جستجوی حریف... ۳۰ ثانیه فرصت دارید.\nاگر کسی نیامد، بازی با ربات پیشنهاد می‌شود.",
        "no_player_after_30": "⏳ ۳۰ ثانیه تمام شد.\n\nبازیکنی نیامد. می‌خواهید با ربات بازی کنید؟",
        "btn_yes_play_bot": "🤖 بله، بازی کن",
        "btn_random_again": "🎲 جستجوی دوباره برای بازی تصادفی",
        "btn_my_account": "👤 حساب من",
        "main_menu": "🎮 سلام {name}\n\nانتخاب کنید:",
        "lang_changed": "✅ زبان تغییر کرد.",
        "status_online": "🟢 آنلاین",
        "status_offline": "⚫ آخرین بازدید: {time}",
        "profile_title": "👤 **{name}**\n🆔 @{username}\n⭐ امتیاز: {points}\n{status}",
        "profile_followers_count": "تعداد دنبال‌کنندگان: {count}",
        "profile_following_count": "تعداد دنبال‌شده: {count}",
        "btn_follow": "➕ دنبال کردن",
        "btn_unfollow": "➖ لغو دنبال",
        "btn_invite_play": "🎮 دعوت به بازی",
        "btn_followers_list": "👥 من را دنبال می‌کنند",
        "btn_following_list": "👥 من دنبال می‌کنم",
        "btn_friends": "👥 دوستان",
        "btn_calc": "🧮 ماشین‌حساب اونو",
        "btn_rules": "📜 قوانین",
        "btn_leaderboard": "📊 آمار",
        "btn_bot_info": "ℹ️ اطلاعات ربات",
        "btn_change_lang": "🌍 تغییر زبان",
        "choose_language": "🌍 **زبان را انتخاب کنید:**",
        "menu_updated": "منو به‌روز شد 🎮",
        "invite_pending_room": "🎮 دعوت برای پیوستن به اتاق داری! وارد شو یا ثبت‌نام کن تا خودکار به اتاق بیایی.",
        "rules_text": "📜 **قوانین اونو عراق 🇮🇶 - راهنمای کامل**\n\nهدف بازی این است که قبل از همه کارت‌هایت را تمام کنی. وقتی یک کارت ماند، باید فوراً «اوونو» بزنی وگرنه کارت جریمه می‌کشی!\n\n🔹 **کارت‌های خاص:**\n1️⃣ **سحب ۲ (+۲):** بازیکن بعد ۲ کارت می‌کشد و نوبتش می‌افتد؛ مگر +۲ داشته باشد و بگذارد (۴ کارت).\n2️⃣ **برعکس (🔄):** جهت بازی عوض می‌شود.\n3️⃣ **منع (🚫):** بازیکن بعد نوبت نمی‌گیرد.\n4️⃣ **جوكر (🌈):** رنگ جدید را انتخاب کن.\n5️⃣ **جوكر +۴ (🌈+۴):** قوی‌ترین کارت! رنگ را عوض کن و بازیکن بعد ۴ کارت بکشد. در صورت داشتن رنگ همانند می‌تواند «چالش» بدهد.\n\n🔹 **چالش و جریمه:**\n- **چالش +۴:** اگر +۴ خوردی و فکر می‌کنی بازیکن رنگ همانند داشت، چالش بده. اگر تقلب کرده باشد ۴ کارت می‌کشد؛ وگرنه تو ۶ کارت می‌کشی!\n- **فراموشی اوونو:** اگر یک کارت داشتی و «اوونو» نگفتی و گیر افتادی، ۲ کارت جریمه می‌کشی.\n\n🔹 **پایان بازی:**\nوقتی یک بازیکن کارتش تمام شد دور تمام می‌شود. مجموع امتیاز کارت‌های باقی‌مانده به امتیاز برنده اضافه می‌شود.",
        "btn_back_short": "🔙 بازگشت",
        "tutorial_title": "🎓 سلام! راهنمای سریع ربات",
        "tutorial_body": "• **بازی تصادفی:** ربات حریف پیدا می‌کند و بازی شروع می‌شود.\n• **بازی با دوستان:** ساخت اتاق یا پیوستن با کد/لینک.\n• **حساب من:** تغییر نام و تنظیمات.\n• **قوانین:** قوانین کامل اونو.\n\n«الان امتحان کن» را بزن تا منو باز شود!",
        "tutorial_btn": "✅ الان امتحان کن",
        "invite_reminder": "⏰ یادآوری: هنوز دعوت بازی داری! تا ۱۵ ثانیهٔ بعد پاسخ بده.",
        "leaderboard_title": "📊 **جدول امتیازات**",
        "leaderboard_global": "🌍 همه",
        "leaderboard_friends": "👥 فقط دنبال‌شده‌ها",
        "leaderboard_empty": "هنوز بازیکنی نیست.",
        "leaderboard_row": "{rank}. {name} — {points} امتیاز",
        "leaderboard_hint": "\n\n_برای باز کردن پروفایل، روی نام بازیکن بزنید._",
        "round_summary_won": "برندهٔ دور شد",
        "bot_info_title": "ℹ️ **اطلاعات ربات**",
        "bot_info_text": (
            "🎮 **به ربات اونو خوش آمدید**\n\n"
            "امکانات اصلی 👇\n\n"
            "🎲 **1) بازی تصادفی**\n"
            "• ربات برای شما حریف پیدا می‌کند.\n"
            "• اگر بازیکنی نبود، می‌توانید **با ربات (هوش مصنوعی)** بازی کنید.\n\n"
            "🤖 **2) بازی با ربات (هوش مصنوعی)**\n"
            "• از منو: **بازی با ربات** — یک دور مقابل ربات.\n"
            "• ربات خودکار بازی می‌کند (کارت، رنگ جوكر، قبول/چالش +۴).\n"
            "• از بازی تصادفی: اگر حریفی نبود، گزینهٔ «بازی با ربات» نمایش داده می‌شود.\n\n"
            "👥 **3) بازی با دوستان (اتاق‌ها)**\n"
            "• ساخت اتاق، ورود با کد/لینک.\n\n"
            "📊 **4) جدول امتیازات**\n"
            "• با لمس نام بازیکن، پروفایلش باز می‌شود.\n\n"
            "📜 **5) قوانین**\n"
            "• قوانین کامل + کارت‌های ویژه.\n\n"
            "🏁 **6) پس از پایان دور**\n"
            "• بازی دوباره و **نشر برد** (با مجموع امتیاز) در صورت فعال بودن.\n\n"
            "🌍 **7) زبان**\n"
            "• عربی • انگلیسی • فارسی\n\n"
            "──────────────\n"
            "📩 **پیشنهادات و نظرات شما را از طریق** @Branch **می‌پذیریم**"
        ),
        "match_history_title": "📜 آخرین بازی‌های شما",
        "match_history_none": "هنوز بازی‌ای ثبت نشده.",
        "match_history_row": "دور {round} — بردی 🏆 (اتاق {room})",
        "public_rooms_title": "🚪 **اتاق‌های عمومی**\nیک اتاق برای پیوستن انتخاب کنید:",
        "public_rooms_none": "الان اتاق بازی باز نیست.",
        "public_room_row": "اتاق {code} — {current}/{max} بازیکن",
        "btn_join": "پیوستن",
        "replay_again_btn": "🔄 بازی دوباره",
        "replay_again_msg": "🏁 دور تمام شد! «بازی دوباره» را بزن تا همان تیم دعوت شوند.",
        "btn_public_rooms": "🚪 اتاق‌های عمومی",
        "player_removed_5_skips": "⛔ به‌دلیل ۵ بار رد کردن نوبت، از بازی خارج شدید.",
        "player_removed_5_skips_others": "⛔ {name} به‌دلیل ۵ بار رد کردن نوبت از بازی خارج شد.",
    },
}

