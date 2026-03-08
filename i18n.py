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
        "btn_rules": "📜 قوانين اللعب",
        "btn_leaderboard": "📊 الإحصائيات",
        "btn_bot_info": "ℹ️ معلومات البوت",
        "btn_change_lang": "🌍 تغيير اللغة",
        "badge_publish_btn": "🏅 انشر شارتك",
        "badge_color_settings": "🏅 لون الشارة",
        "badge_profile_label": "🏅 الشارة: {badge}",
        "choose_language": "🌍 **اختر اللغة:**",
        "menu_updated": "تم تحديث القائمة 🎮",
        "invite_pending_room": "🎮 لديك دعوة للانضمام إلى غرفة! سجّل الدخول أو أنشئ حساباً ثم سيتم إدخالك للغرفة تلقائياً.",
        "rules_text": (
        "📜 **قوانين اللعب - أونو العراق 🇮🇶**\n\n"
        "👉 _للشرح المختصر اضغط زر **التدريب** أدناه._\n\n"
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
        "tutorial_body": "• **لعب عشوائي:** البوت يلاقي لك خصم وتبدأون.\n• **لعب مع الأصدقاء:** تنشئ غرفة أو تنضم بكود أو رابط.\n• **حسابي:** تعديل الاسم والإعدادات.\n• **قوانين اللعب:** قوانين أونو كاملة.\n\nاضغط «جرب الآن» لفتح القائمة والبدء!",
        "tutorial_btn": "✅ جرب الآن",
        "training_offer_question": "🎓 **أهلاً بك!**\n\nهل تريد **التدريب** على اللعبة أم أنت تعرف أونو مسبقاً؟",
        "training_btn_yes": "📚 نعم، أريد التدريب",
        "training_btn_no": "✅ أعرف اللعبة",
        "training_title": "📚 **التدريب — أونو باختصار**",
        "training_content": (
            "🎯 **الهدف:** أن تخلص كل أوراقك قبل الخصم.\n\n"
            "🃏 **اللعب:** ورقتك يجب أن تطابق إما **نفس اللون** أو **نفس الرقم/الرمز** للورقة النازلة.\n\n"
            "📌 **أوراق خاصة:**\n"
            "• **+2** → الخصم يسحب ورقتين.\n"
            "• **🚫 منع** → الخصم يفوّت دوره.\n"
            "• **🔄 تدوير** → اتجاه اللعب ينعكس.\n"
            "• **🌈 جوكر** → تختار اللون الجديد.\n"
            "• **🔥 +4** → تختار لون والخصم يسحب ٤ (وله حق التحدي).\n\n"
            "🚨 **أونو!** إذا بقي عندك ورقة واحدة يجب أن تضغط **أونو** قبل ما يلعب غيرك.\n\n"
            "📜 للتفاصيل الكاملة: **قوانين اللعب** من القائمة."
        ),
        "btn_training": "📚 التدريب",
        "btn_start_training_game": "🎮 بدء جولة تدريبية",
        "training_hint_intro": "📚 **التدريب:** الورقة النازلة: {top_card}\n\nأوراقك: {hand}\n\n{valid_line}\n\n👉 العب إحداها.",
        "training_hint_valid_reason_color": "• {card} — نفس اللون",
        "training_hint_valid_reason_value": "• {card} — نفس الرقم/الرمز",
        "training_hint_valid_reason_wild": "• {card} — جوكر (تقدر تلعبها أي وقت)",
        "training_hint_no_valid": "ما عندك ورقة تشتغل حاليًا. اضغط «مرر الدور» أو اسحب ورقة.",
        "training_win_congrats": "🎉 مبروك! كملت التدريب بنجاح وربحت الجولة!",
        "training_plan_intro": "📚 **خطة لعب:**\n{plan}\n\n**الورقة النازلة:** {top_card}\n**أوراقك:** {hand}\n\n**تقدر تلعب:**\n{valid_line}\n\n👉 العب إحداها.",
        "training_plan_skip": "يلا مادام عندك ورقة منع (🚫) العبها؛ بعدها الدور يرجع لك — بعدين لاقِ ورقة من نفس اللون واكمل.",
        "training_plan_reverse": "ورقة التحويل (🔄) نفس فكرة المنع — العبها عشان يرجع لك الدور ثم العب نفس اللون.",
        "training_plan_plus2": "ورقة +٢ حلوة تصير الخصم يسحب — العبها إذا تبي تضغط على البوت.",
        "training_plan_joker_draw": "جوكر +1 (💧) أو +2 (🌊): تقدر تلعبها أي وقت، الخصم يسحب والدور يرجع لك — استغلهم!",
        "training_plan_same_color": "حاول تلعب ورقة من نفس لون الورقة النازلة عشان تتحكم باللون اللي يلعب عليه البوت.",
        "training_plan_wild": "تقدر تلعب الجوكر وتختار اللون اللي عندك أكثره عشان تكمل.",
        "training_plan_wild4_has_other": "جوكر +4 (🔥) تقدر تلعبها **فقط** إذا ما عندك أي ورقة تشتغل! عندك ورقة مناسبة — العبها. إذا لعبتها بدون ما تحتاج، الخصم يقدر يتحداك.",
        "training_plan_wild4_ok": "ما عندك ورقة تشتغل — تقدر تلعب جوكر +4 (🔥). بعد ما تلعبها لازم تنتظر رد التحدي من الخصم (يقبل السحب أو يتحداك).",
        "training_plan_default": "اختر أي ورقة من اللي تحت واعمل خطوتك.",
        "wild4_only_when_no_valid": "⛔ جوكر +4 تقدر تلعبها فقط إذا ما عندك ورقة تشتغل! عندك ورقة مناسبة — العبها.",
        "training_plan_no_valid": "ما عندك ورقة تلعبها حاليًا — مرّر الدور أو اسحب ورقة.",
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
            "📚 **التدريب:** من زر **قوانين اللعب** يمكنك فتح **التدريب** لشرح سريع للعبة.\n\n"
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
            "📜 **8) قوانين اللعب**\n"
            "• شرح كامل لقوانين اللعب + شرح أوراق الأكشن والجوكر.\n"
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
        "channel_subscribe_required": "⛔ يجب الاشتراك في القناة أولاً لاستخدام البوت.\n\nاشترك ثم اضغط «تحقق».",
        "banned_from_bot": "🚫 تم حظرك من البوت. لا يمكنك استخدام البوت.",
        "thanks": "✅ شكراً!",
        "player_not_found": "👤 اللاعب غير موجود أو حذف حسابه.",
        "invalid_join_link": "⚠️ رابط الانضمام غير صالح أو انتهت صلاحية الغرفة. أرسل /start للقائمة.",
        "username_3_chars": "❌ اليوزر نيم يجب أن يكون 3 أحرف أو أكثر (إنجليزي وأرقام فقط):",
        "username_taken": "❌ هذا اليوزر نيم محجوز لشخص آخر، اختر غيره:",
        "username_ok_send_password": "✅ يوزر رائع! الآن أرسل كلمة السر التي تريدها (4 أحرف أو أكثر):",
        "password_4_chars": "❌ كلمة السر ضعيفة، أرسل 4 أحرف أو أكثر:",
        "enter_username_prompt": "✍️ يرجى إدخال اسم مستخدم (يوزر نيم) خاص بك (حروف إنجليزية وأرقام فقط، 3 أحرف على الأقل):",
        "username_in_use": "❌ هذا اليوزر نيم مستخدم من قبل، اختر غيره.",
        "banned_no_rooms": "🚫 تم حظرك من البوت. لا يمكنك الانضمام للغرف.",
        "game_started_vs_bot": "🎮 بدأت اللعبة ضد البوت! استعد...",
        "choose_player_count": "👥 اختر عدد اللاعبين:",
        "account_not_registered": "⚠️ حسابك غير مسجل.",
        "cancelled": "تم الإلغاء.",
        "help_request_sent": "✅ تم إرسال طلب المساعدة للإدارة. المدير يمكنه أيضاً مراجعة جميع الطلبات من: لوحة الإدارة ← طلبات المساعدة.",
        "help_request_error": "⚠️ حدث خطأ أثناء إرسال طلبك. تم حفظه. جرّب لاحقاً أو راجع لوحة الإدارة ← طلبات المساعدة.",
        "chat_opened": "💬 تم فتح المحادثة مع الإدارة.\n\nاكتب رسالتك أو اضغط «إنهاء المحادثة» عند الانتهاء.",
        "chat_rejected": "تم رفض المحادثة.",
        "chat_ended": "تم إنهاء المحادثة.",
        "message_sent": "✅ تم إرسال رسالتك.",
        "room_expired": "⚠️ الغرفة لم تعد موجودة.",
        "already_confirmed": "✅ سبق وأكدت! بانتظار البقية...",
        "error_generic": "⚠️ خطأ.",
        "not_allowed": "⚠️ غير مسموح.",
        "request_expired": "⏱ انتهت صلاحية الطلب.",
        "cannot_follow_self": "🧐 لا يمكنك متابعة نفسك!",
        "screen_expired": "⚠️ انتهت صلاحية هذه الشاشة.",
        "unfollow_done": "❌ تم إلغاء المتابعة.",
        "follow_done": "✅ تمت متابعة هذا اللاعب. القائمة تبقى لعرض الباقين.",
        "already_following": "⚠️ أنت تتابع هذا اللاعب بالفعل.",
        "no_player_selected": "⚠️ لم تختر أي لاعب! أو استخدم رابط الدعوة لأي شخص.",
        "only_host_settings": "⚠️ فقط صاحب الغرفة يقدر يدخل الإعدادات!",
        "returning_to_game": "🔄 جاري العودة للعبة...",
        "only_host_kick": "⚠️ فقط صاحب الغرفة يقدر يطرد!",
        "no_other_players": "⚠️ ما في لاعبين ثانيين في الغرفة!",
        "select_players_to_kick": "🚫 حدد اللاعبين اللي تبي تطردهم:",
        "no_one_selected": "⚠️ ما حددت أحد!",
        "kicked_from_room": "🚫 تم طردك من الغرفة بواسطة صاحب الغرفة.",
        "only_host_change_cap": "⚠️ فقط صاحب الغرفة يقدر يغير السقف!",
        "logged_out_msg": "تم تسجيل الخروج. استخدم دخول أو تسجيل للعودة.",
        "setting_save_failed": "⚠️ تعذر حفظ الإعداد. (قد تحتاج إضافة عمود invite_from لجدول users)",
        "saved": "✅ تم الحفظ.",
        "what_to_edit": "✏️ ماذا تريد تعديله؟",
        "send_new_name": "📛 أرسل الاسم الجديد:",
        "name_length_1_30": "❌ الاسم لازم يكون بين 1 و 30 حرف. حاول مرة ثانية:",
        "send_new_username": "🆔 أرسل اليوزر نيم الجديد (حروف إنجليزية وأرقام فقط، 3 أحرف على الأقل):",
        "username_3_plus": "❌ اليوزر نيم لازم 3 أحرف أو أكثر (إنجليزي وأرقام فقط). حاول مرة ثانية:",
        "username_taken_other": "❌ هذا اليوزر نيم محجوز لشخص آخر. اختر غيره:",
        "send_new_password": "🔑 أرسل الرمز السري الجديد:",
        "password_length_1_30": "❌ الرمز لازم يكون بين 1 و 30 حرف. حاول مرة ثانية:",
        "password_changed": "✅ تم تغيير الرمز السري بنجاح!",
        "confirm_logout": "🚪 هل أنت متأكد من تسجيل الخروج؟",
        "logout_success": "👋 تم تسجيل الخروج بنجاح!\nأرسل /start للتسجيل مرة أخرى.",
        "choose_play_mode": "🔄 اختر طريقة اللعب:",
        "invite_expired": "⚠️ انتهت صلاحية الدعوة.",
        "invite_not_yours": "⚠️ هذه الدعوة ليست لك.",
        "already_responded": "⚠️ سبق ورديت على الدعوة.",
        "accepted_invite": "✅ قبلت الدعوة! بانتظار بقية اللاعبين...",
        "rejected_invite": "❌ رفضت الدعوة.",
        "send_username_to_search": "✍️ أرسل الآن اسم المستخدم (اليوزر نيم) للشخص الذي تبحث عنه:",
        "no_player_with_username": "❌ لا يوجد لاعب بهذا اليوزر. تأكد من الحروف وأرسله مرة ثانية:",
        "follow_success": "✅ تمت المتابعة بنجاح!",
        "not_following_anyone": "📉 أنت لا تتابع أحداً حالياً.",
        "no_followers": "📈 لا يوجد متابعون لحسابك حالياً.",
        "must_follow_for_alerts": "⚠️ يجب أن تتابع اللاعب أولاً لتفعيل التنبيهات!",
        "alert_updated": "✅ تم تحديث إعدادات التنبيه",
        "alert_disabled": "❌ تم إيقاف التنبيه",
        "own_settings_only": "🧐 يمكنك تعديل إعداداتك فقط من 'حسابي'.",
        "requests_allowed": "✅ تم السماح بالطلبات",
        "requests_locked": "❌ تم قفل الطلبات",
        "data_error": "⚠️ خطأ في البيانات.",
        "cannot_invite_self": "🚫 لا يمكنك دعوة نفسك!",
        "player_blocked_you": "⛔ هذا اللاعب حظرك. لا يمكنك إرسال دعوة له.",
        "invites_following_only": "⛔ هذا اللاعب يستقبل الدعوات فقط من الذين يتابعهم. أنت لست من قائمة متابعاته.",
        "follow_first_then_invite": "⛔ هذا اللاعب يستقبل الدعوات فقط من الذين يتابعونه. تابعَه أولاً ثم جرّب الدعوة.",
        "invite_sent": "✅ تم إرسال طلب اللعب بنجاح!",
        "invite_failed": "⚠️ تعذر إرسال الطلب (ربما قام اللاعب بحظر البوت).",
        "mute_cancelled": "✅ تم إلغاء الكتم. يمكن لهذا اللاعب إرسال دعوات لك مجدداً.",
        "cannot_block_self": "لا يمكنك حظر نفسك.",
        "blocked_success": "✅ تم حظره. لن يستطيع إرسال دعوات لك ولن يظهر في قوائمك.",
        "already_blocked": "⚠️ أنت حاظره مسبقاً.",
        "unblocked": "✅ تم إلغاء الحظر. يمكنه إرسال دعوات لك مجدداً.",
        "choose_mute_duration": "🔇 اختر مدة الكتم أو ألغِ الكتم:",
        "updated": "✅ تم التحديث",
        "invite_accepted_starting": "✅ تم قبول الدعوة! جاري بدء اللعبة...",
        "game_start_error": "⚠️ حدث خطأ في بدء اللعبة.",
        "request_rejected": "تم رفض الطلب بنجاح.",
        "request_rejected_msg": "❌ تم رفض الطلب.",
        "still_not_subscribed": "⛔ ما زلت غير مشترك. اشترك في القناة ثم اضغط «تحقق» مرة أخرى.",
        "verified": "✅ تم التحقق، مرحباً!",
        "verified_register": "✅ تم التحقق، سجّل أو ادخل لحسابك.",
        "verified_join_room": "✅ تم التحقق، تم انضمامك للغرفة!",
        "hello_send_start": "مرحباً! أرسل /start مرة أخرى للتسجيل.",
        "enter_username_please": "⚠️ يرجى إدخال اسم مستخدم (يوزر نيم) خاص بك (حروف إنجليزية وأرقام فقط):",
        "post_published": "✅ تم نشر منشورك في القناة.",
        "publish_unavailable": "⚠️ نشر المنشورات غير متاح حالياً.",
        "share_unavailable": "⚠️ نشر النتائج غير متاح حالياً. سيتم تفعيله من الإدارة لاحقاً.",
        "share_expired": "⚠️ انتهت صلاحية النشر. جرّب النشر مباشرة بعد انتهاء الجولة.",
        "not_authorized": "⚠️ غير مصرح.",
        "channel_unavailable": "📜 القناة غير متاحة حالياً. سيتم تفعيلها من الإدارة لاحقاً.",
        "send_message_again": "أرسل رسالتك من جديد.",
        "cannot_delete_post": "⚠️ لا يمكنك حذف هذا المنشور.",
        "post_deleted": "✅ تم حذف المنشور.",
        "option_expired": "⚠️ انتهت صلاحية هذا الخيار.",
        "player_not_found_short": "❌ اللاعب غير موجود.",
        "profile_open_failed": "⚠️ فشل فتح بروفايل اللاعب.",
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
        "badge_publish_btn": "🏅 Publish badge",
        "badge_color_settings": "🏅 Badge color",
        "badge_profile_label": "🏅 Badge: {badge}",
        "choose_language": "🌍 **Choose language:**",
        "menu_updated": "Menu updated 🎮",
        "invite_pending_room": "🎮 You have an invite to join a room! Log in or register and you will join automatically.",
        "rules_text": "📜 **Uno Iraq 🇮🇶 - Full Rules**\n\nThe goal is to get rid of all your cards first. When you have one card left, you must press \"Uno\" immediately, or you draw penalty cards!\n\n🔹 **Special cards:**\n1️⃣ **Draw 2 (+2):** The next player draws 2 and skips their turn, unless they have +2 and stack it (draw 4).\n2️⃣ **Reverse (🔄):** Reverses play direction.\n3️⃣ **Skip (🚫):** The next player is skipped.\n4️⃣ **Wild (🌈):** Choose the new color.\n5️⃣ **Wild Draw 4 (🌈+4):** Strongest card! Choose color and the next player draws 4. They can challenge if they think you had a matching color.\n\n🔹 **Challenge & penalties:**\n- **+4 challenge:** If you get +4 and suspect the player had a matching color, you can challenge. If they cheated, they draw 4. If not, you draw 6!\n- **Forgot Uno:** If you had one card and didn't say \"Uno\" and get caught, you draw 2.\n\n🔹 **End of game:**\nThe round ends when one player runs out of cards. Remaining cards in others' hands are counted as points and added to the winner's score.",
        "btn_back_short": "🔙 Back",
        "tutorial_title": "🎓 Hi! Quick tour of the bot",
        "tutorial_body": "• **Random play:** The bot finds you an opponent and you start.\n• **Play with friends:** Create a room or join with a code/link.\n• **My account:** Edit name and settings.\n• **Rules:** Full Uno rules.\n\nPress «Try now» to open the menu and start!",
        "tutorial_btn": "✅ Try now",
        "training_offer_question": "🎓 **Welcome!**\n\nDo you want **training** or do you already know Uno?",
        "training_btn_yes": "📚 Yes, I want training",
        "training_btn_no": "✅ I know the game",
        "training_title": "📚 **Training — Uno in short**",
        "training_content": "🎯 **Goal:** Get rid of all your cards first.\n\n🃏 **Play:** Your card must match either **color** or **number/symbol** of the top card.\n\n📌 **Special cards:** +2, Skip, Reverse, Wild, Wild +4.\n\n🚨 **Uno!** With one card left, press **Uno** before others play.\n\n📜 Full details: **Rules** from the menu.",
        "btn_training": "📚 Training",
        "btn_start_training_game": "🎮 Start training round",
        "training_hint_intro": "📚 **Training:** Top card: {top_card}\n\nYour cards: {hand}\n\n{valid_line}\n\n👉 Play one of them.",
        "training_hint_valid_reason_color": "• {card} — same color",
        "training_hint_valid_reason_value": "• {card} — same number/symbol",
        "training_hint_valid_reason_wild": "• {card} — wild (you can play it anytime)",
        "training_hint_no_valid": "You have no valid card right now. Tap «Pass» or draw a card.",
        "training_win_congrats": "🎉 Congrats! You completed training and won the round!",
        "training_plan_intro": "📚 **Play plan:**\n{plan}\n\n**Top card:** {top_card}\n**Your cards:** {hand}\n\n**You can play:**\n{valid_line}\n\n👉 Play one of them.",
        "training_plan_skip": "Since you have a Skip (🚫), play it so the turn comes back to you — then play a card of the same color.",
        "training_plan_reverse": "Reverse (🔄) works like Skip — play it to get the turn back, then play same color.",
        "training_plan_plus2": "A +2 card makes the opponent draw — play it to pressure the bot.",
        "training_plan_joker_draw": "Joker +1 (💧) or +2 (🌊): you can play them anytime, opponent draws and the turn stays yours — use them!",
        "training_plan_same_color": "Try playing a card of the same color as the top card so you control what color the bot plays.",
        "training_plan_wild": "You can play the wild and choose the color you have most of to continue.",
        "training_plan_wild4_has_other": "Wild +4 (🔥) can only be played when you have **no** matching card! You have a valid card — play it. If you play +4 anyway, the opponent can challenge.",
        "training_plan_wild4_ok": "You have no valid card — you can play Wild +4 (🔥). After playing it you must wait for the opponent's challenge response (accept draw or challenge).",
        "training_plan_default": "Pick any of the cards below and make your move.",
        "wild4_only_when_no_valid": "⛔ You can only play Wild +4 when you have no valid card! You have a matching card — play it instead.",
        "training_plan_no_valid": "You have no valid card right now — pass or draw.",
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
        "channel_subscribe_required": "⛔ You must subscribe to the channel first to use the bot.\n\nSubscribe then tap «Verify».",
        "banned_from_bot": "🚫 You have been banned from the bot. You cannot use the bot.",
        "thanks": "✅ Thanks!",
        "player_not_found": "👤 Player not found or account deleted.",
        "invalid_join_link": "⚠️ Invalid join link or room expired. Send /start for the menu.",
        "username_3_chars": "❌ Username must be 3+ characters (letters and numbers only):",
        "username_taken": "❌ This username is taken by someone else. Choose another:",
        "username_ok_send_password": "✅ Great username! Now send the password you want (4+ characters):",
        "password_4_chars": "❌ Password too weak. Send 4+ characters:",
        "enter_username_prompt": "✍️ Please enter a username (letters and numbers only, at least 3 characters):",
        "username_in_use": "❌ This username is already in use. Choose another.",
        "banned_no_rooms": "🚫 You have been banned from the bot. You cannot join rooms.",
        "game_started_vs_bot": "🎮 Game started vs Bot! Get ready...",
        "choose_player_count": "👥 Choose number of players:",
        "account_not_registered": "⚠️ Your account is not registered.",
        "cancelled": "Cancelled.",
        "help_request_sent": "✅ Your help request was sent to the admins. They can also review all requests from: Admin panel → Help requests.",
        "help_request_error": "⚠️ An error occurred while sending your request. It was saved. Try again later or check Admin panel → Help requests.",
        "chat_opened": "💬 Chat with admin is open.\n\nType your message or tap «End chat» when done.",
        "chat_rejected": "Chat was rejected.",
        "chat_ended": "Chat ended.",
        "message_sent": "✅ Your message was sent.",
        "room_expired": "⚠️ The room no longer exists.",
        "already_confirmed": "✅ You already confirmed! Waiting for others...",
        "error_generic": "⚠️ Error.",
        "not_allowed": "⚠️ Not allowed.",
        "request_expired": "⏱ Request expired.",
        "cannot_follow_self": "🧐 You cannot follow yourself!",
        "screen_expired": "⚠️ This screen has expired.",
        "unfollow_done": "❌ Unfollowed.",
        "follow_done": "✅ You are now following this player. The list stays to show the rest.",
        "already_following": "⚠️ You are already following this player.",
        "no_player_selected": "⚠️ You didn't select any player! Or use the invite link for anyone.",
        "only_host_settings": "⚠️ Only the room host can open settings!",
        "returning_to_game": "🔄 Returning to game...",
        "only_host_kick": "⚠️ Only the room host can kick!",
        "no_other_players": "⚠️ There are no other players in the room!",
        "select_players_to_kick": "🚫 Select the players you want to kick:",
        "no_one_selected": "⚠️ You didn't select anyone!",
        "kicked_from_room": "🚫 You were kicked from the room by the host.",
        "only_host_change_cap": "⚠️ Only the room host can change the cap!",
        "logged_out_msg": "Logged out. Use login or register to return.",
        "setting_save_failed": "⚠️ Failed to save setting. (You may need to add invite_from column to users table)",
        "saved": "✅ Saved.",
        "what_to_edit": "✏️ What do you want to edit?",
        "send_new_name": "📛 Send the new name:",
        "name_length_1_30": "❌ Name must be 1–30 characters. Try again:",
        "send_new_username": "🆔 Send the new username (letters and numbers only, 3+ characters):",
        "username_3_plus": "❌ Username must be 3+ characters (letters and numbers only). Try again:",
        "username_taken_other": "❌ This username is taken by someone else. Choose another:",
        "send_new_password": "🔑 Send the new password:",
        "password_length_1_30": "❌ Password must be 1–30 characters. Try again:",
        "password_changed": "✅ Password changed successfully!",
        "confirm_logout": "🚪 Are you sure you want to log out?",
        "logout_success": "👋 Logged out successfully!\nSend /start to register again.",
        "choose_play_mode": "🔄 Choose how to play:",
        "invite_expired": "⚠️ Invite expired.",
        "invite_not_yours": "⚠️ This invite is not for you.",
        "already_responded": "⚠️ You already responded to this invite.",
        "accepted_invite": "✅ Invite accepted! Waiting for other players...",
        "rejected_invite": "❌ Invite rejected.",
        "send_username_to_search": "✍️ Send the username of the person you're looking for:",
        "no_player_with_username": "❌ No player with this username. Check the spelling and try again:",
        "follow_success": "✅ Followed successfully!",
        "not_following_anyone": "📉 You are not following anyone at the moment.",
        "no_followers": "📈 You have no followers at the moment.",
        "must_follow_for_alerts": "⚠️ You must follow the player first to enable alerts!",
        "alert_updated": "✅ Alert settings updated",
        "alert_disabled": "❌ Alert disabled",
        "own_settings_only": "🧐 You can only edit your settings from 'My account'.",
        "requests_allowed": "✅ Requests allowed",
        "requests_locked": "❌ Requests locked",
        "data_error": "⚠️ Data error.",
        "cannot_invite_self": "🚫 You cannot invite yourself!",
        "player_blocked_you": "⛔ This player has blocked you. You cannot send them an invite.",
        "invites_following_only": "⛔ This player only accepts invites from people they follow. You are not in their list.",
        "follow_first_then_invite": "⛔ This player only accepts invites from followers. Follow them first then try the invite.",
        "invite_sent": "✅ Play request sent successfully!",
        "invite_failed": "⚠️ Failed to send request (player may have blocked the bot).",
        "mute_cancelled": "✅ Mute removed. This player can send you invites again.",
        "cannot_block_self": "You cannot block yourself.",
        "blocked_success": "✅ Blocked. They cannot send you invites or appear in your lists.",
        "already_blocked": "⚠️ You have already blocked them.",
        "unblocked": "✅ Unblocked. They can send you invites again.",
        "choose_mute_duration": "🔇 Choose mute duration or remove mute:",
        "updated": "✅ Updated",
        "invite_accepted_starting": "✅ Invite accepted! Starting game...",
        "game_start_error": "⚠️ An error occurred starting the game.",
        "request_rejected": "Request rejected successfully.",
        "request_rejected_msg": "❌ Request rejected.",
        "still_not_subscribed": "⛔ You are still not subscribed. Subscribe to the channel then tap «Verify» again.",
        "verified": "✅ Verified, welcome!",
        "verified_register": "✅ Verified. Register or log in to your account.",
        "verified_join_room": "✅ Verified, you have joined the room!",
        "hello_send_start": "Hello! Send /start again to register.",
        "enter_username_please": "⚠️ Please enter a username (letters and numbers only):",
        "post_published": "✅ Your post was published on the channel.",
        "publish_unavailable": "⚠️ Publishing is not available at the moment.",
        "share_unavailable": "⚠️ Sharing results is not available yet. It will be enabled by admins later.",
        "share_expired": "⚠️ Share expired. Try sharing right after the round ends.",
        "not_authorized": "⚠️ Not authorized.",
        "channel_unavailable": "📜 Channel is not available at the moment. It will be enabled by admins later.",
        "send_message_again": "Send your message again.",
        "cannot_delete_post": "⚠️ You cannot delete this post.",
        "post_deleted": "✅ Post deleted.",
        "option_expired": "⚠️ This option has expired.",
        "player_not_found_short": "❌ Player not found.",
        "profile_open_failed": "⚠️ Failed to open player profile.",
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
        "badge_publish_btn": "🏅 انتشار نشان",
        "badge_color_settings": "🏅 رنگ نشان",
        "badge_profile_label": "🏅 نشان: {badge}",
        "choose_language": "🌍 **زبان را انتخاب کنید:**",
        "menu_updated": "منو به‌روز شد 🎮",
        "invite_pending_room": "🎮 دعوت برای پیوستن به اتاق داری! وارد شو یا ثبت‌نام کن تا خودکار به اتاق بیایی.",
        "rules_text": "📜 **قوانین اونو عراق 🇮🇶 - راهنمای کامل**\n\nهدف بازی این است که قبل از همه کارت‌هایت را تمام کنی. وقتی یک کارت ماند، باید فوراً «اوونو» بزنی وگرنه کارت جریمه می‌کشی!\n\n🔹 **کارت‌های خاص:**\n1️⃣ **سحب ۲ (+۲):** بازیکن بعد ۲ کارت می‌کشد و نوبتش می‌افتد؛ مگر +۲ داشته باشد و بگذارد (۴ کارت).\n2️⃣ **برعکس (🔄):** جهت بازی عوض می‌شود.\n3️⃣ **منع (🚫):** بازیکن بعد نوبت نمی‌گیرد.\n4️⃣ **جوكر (🌈):** رنگ جدید را انتخاب کن.\n5️⃣ **جوكر +۴ (🌈+۴):** قوی‌ترین کارت! رنگ را عوض کن و بازیکن بعد ۴ کارت بکشد. در صورت داشتن رنگ همانند می‌تواند «چالش» بدهد.\n\n🔹 **چالش و جریمه:**\n- **چالش +۴:** اگر +۴ خوردی و فکر می‌کنی بازیکن رنگ همانند داشت، چالش بده. اگر تقلب کرده باشد ۴ کارت می‌کشد؛ وگرنه تو ۶ کارت می‌کشی!\n- **فراموشی اوونو:** اگر یک کارت داشتی و «اوونو» نگفتی و گیر افتادی، ۲ کارت جریمه می‌کشی.\n\n🔹 **پایان بازی:**\nوقتی یک بازیکن کارتش تمام شد دور تمام می‌شود. مجموع امتیاز کارت‌های باقی‌مانده به امتیاز برنده اضافه می‌شود.",
        "btn_back_short": "🔙 بازگشت",
        "tutorial_title": "🎓 سلام! راهنمای سریع ربات",
        "tutorial_body": "• **بازی تصادفی:** ربات حریف پیدا می‌کند و بازی شروع می‌شود.\n• **بازی با دوستان:** ساخت اتاق یا پیوستن با کد/لینک.\n• **حساب من:** تغییر نام و تنظیمات.\n• **قوانین:** قوانین کامل اونو.\n\n«الان امتحان کن» را بزن تا منو باز شود!",
        "tutorial_btn": "✅ الان امتحان کن",
        "training_offer_question": "🎓 **خوش اومدی!**\n\nمی‌خوای **تمرین** ببینی یا از قبل اونو بلدی؟",
        "training_btn_yes": "📚 بله، تمرین می‌خوام",
        "training_btn_no": "✅ بلدم",
        "training_title": "📚 **تمرین — اونو خلاصه**",
        "training_content": "🎯 **هدف:** زودتر از همه کارت‌هات رو تموم کن.\n\n🃏 **بازی:** کارت باید هم‌رنگ یا هم‌عدد با کارت روی میز باشه.\n\n📌 **کارت‌های خاص:** +۲، منع، برعکس، جوكر، جوكر +۴.\n\n🚨 **اوونو!** با یه کارت باید «اوونو» بزنی.\n\n📜 جزئیات: **قوانین** از منو.",
        "btn_training": "📚 تمرین",
        "btn_start_training_game": "🎮 شروع دور تمرین",
        "training_hint_intro": "📚 **تمرین:** کارت روی میز: {top_card}\n\nکارت‌های تو: {hand}\n\n{valid_line}\n\n👉 یکی رو بازی کن.",
        "training_hint_valid_reason_color": "• {card} — هم‌رنگ",
        "training_hint_valid_reason_value": "• {card} — هم‌عدد/هم‌نماد",
        "training_hint_valid_reason_wild": "• {card} — جوكر (هر وقت می‌تونی بازی کن)",
        "training_hint_no_valid": "الان کارت قابل بازی نداری. «رد کردن» بزن یا کارت بکش.",
        "training_win_congrats": "🎉 آفرین! تمرین رو تموم کردی و دور رو بردی!",
        "training_plan_intro": "📚 **برنامه بازی:**\n{plan}\n\n**کارت روی میز:** {top_card}\n**کارت‌های تو:** {hand}\n\n**می‌تونی بازی کنی:**\n{valid_line}\n\n👉 یکی رو انتخاب کن.",
        "training_plan_skip": "چون کارت منع (🚫) داری، بزنش تا نوبت برگرده به تو — بعد هم‌رنگ بازی کن.",
        "training_plan_reverse": "کارت برعکس (🔄) مثل منعه — بزنش نوبت برگرده، بعد هم‌رنگ بزن.",
        "training_plan_plus2": "کارت +۲ حریف رو وادار به کشیدن می‌کنه — بزنش به ربات فشار بیاری.",
        "training_plan_joker_draw": "جوكر +1 (💧) یا +2 (🌊): هر وقت می‌تونی بزنی، حریف می‌کشه و نوبت پیش تو می‌مونه — استفاده کن!",
        "training_plan_same_color": "سعی کن هم‌رنگ با کارت روی میز بزنی تا تو رنگ بعدی رو تعیین کنی.",
        "training_plan_wild": "می‌تونی جوكر بزنی و رنگی که بیشتر داری رو انتخاب کنی.",
        "training_plan_wild4_has_other": "جوكر +۴ (🔥) فقط وقتی می‌تونی بزنی که **هیچ** کارت مطابق نداری! الان کارت مطابق داری — اونو بزن. اگه بی‌دلیل +۴ بزنی، حریف می‌تونه بهت اعتراض کنه.",
        "training_plan_wild4_ok": "کارت مطابق نداری — می‌تونی جوكر +۴ (🔥) بزنی. بعدش باید جواب اعتراض حریف رو صبر کنی (بپذیره یا اعتراض کنه).",
        "training_plan_default": "یکی از کارت‌های زیر رو انتخاب کن و بازی کن.",
        "wild4_only_when_no_valid": "⛔ جوكر +۴ فقط وقتی مجازی که کارت مطابق نداری! کارت مطابق داری — اونو بزن.",
        "training_plan_no_valid": "الان کارت قابل بازی نداری — رد کن یا بکش.",
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
        "channel_subscribe_required": "⛔ برای استفاده از ربات ابتدا در کانال عضو شوید.\n\nعضو شوید سپس «تأیید» را بزنید.",
        "banned_from_bot": "🚫 شما از ربات مسدود شده‌اید.",
        "thanks": "✅ ممنون!",
        "player_not_found": "👤 بازیکن پیدا نشد یا حساب حذف شده.",
        "invalid_join_link": "⚠️ لینک نامعتبر یا اتاق منقضی شده. /start بفرستید.",
        "username_3_chars": "❌ نام کاربری حداقل ۳ کاراکتر (فقط حروف و اعداد):",
        "username_taken": "❌ این نام کاربری گرفته شده. دیگری انتخاب کنید:",
        "username_ok_send_password": "✅ نام کاربری ثبت شد. حالا رمز (۴+ کاراکتر) بفرستید:",
        "password_4_chars": "❌ رمز ضعیف. حداقل ۴ کاراکتر بفرستید:",
        "enter_username_prompt": "✍️ نام کاربری وارد کنید (حداقل ۳ کاراکتر، حروف و اعداد):",
        "username_in_use": "❌ این نام کاربری قبلاً استفاده شده.",
        "banned_no_rooms": "🚫 شما از ربات مسدود هستید. نمی‌توانید به اتاق بپیوندید.",
        "game_started_vs_bot": "🎮 بازی با ربات شروع شد! آماده باشید...",
        "choose_player_count": "👥 تعداد بازیکنان را انتخاب کنید:",
        "account_not_registered": "⚠️ حساب شما ثبت‌نام نشده.",
        "cancelled": "لغو شد.",
        "help_request_sent": "✅ درخواست کمک به ادمین ارسال شد.",
        "help_request_error": "⚠️ خطا در ارسال. بعداً دوباره امتحان کنید.",
        "chat_opened": "💬 چت با ادمین باز است.\n\nپیام بفرستید یا «پایان چت» بزنید.",
        "chat_rejected": "چت رد شد.",
        "chat_ended": "چت تمام شد.",
        "message_sent": "✅ پیام ارسال شد.",
        "room_expired": "⚠️ اتاق دیگر وجود ندارد.",
        "already_confirmed": "✅ قبلاً تأیید کردید. در انتظار بقیه...",
        "error_generic": "⚠️ خطا.",
        "not_allowed": "⚠️ مجاز نیست.",
        "request_expired": "⏱ درخواست منقضی شد.",
        "cannot_follow_self": "🧐 نمی‌توانید خودتان را دنبال کنید!",
        "screen_expired": "⚠️ این صفحه منقضی شده.",
        "unfollow_done": "❌ دنبال‌کردن لغو شد.",
        "follow_done": "✅ این بازیکن را دنبال می‌کنید.",
        "already_following": "⚠️ قبلاً این بازیکن را دنبال می‌کنید.",
        "no_player_selected": "⚠️ بازیکنی انتخاب نکردید! یا از لینک دعوت استفاده کنید.",
        "only_host_settings": "⚠️ فقط سازندهٔ اتاق می‌تواند تنظیمات را باز کند!",
        "returning_to_game": "🔄 در حال بازگشت به بازی...",
        "only_host_kick": "⚠️ فقط سازندهٔ اتاق می‌تواند اخراج کند!",
        "no_other_players": "⚠️ بازیکن دیگری در اتاق نیست!",
        "select_players_to_kick": "🚫 بازیکنانی را که می‌خواهید اخراج کنید انتخاب کنید:",
        "no_one_selected": "⚠️ کسی انتخاب نشد!",
        "kicked_from_room": "🚫 سازندهٔ اتاق شما را اخراج کرد.",
        "only_host_change_cap": "⚠️ فقط سازندهٔ اتاق می‌تواند سقف را عوض کند!",
        "logged_out_msg": "خروج انجام شد. برای بازگشت وارد شوید یا ثبت‌نام کنید.",
        "setting_save_failed": "⚠️ ذخیرهٔ تنظیم ناموفق بود.",
        "saved": "✅ ذخیره شد.",
        "what_to_edit": "✏️ چه چیزی را می‌خواهید ویرایش کنید؟",
        "send_new_name": "📛 نام جدید بفرستید:",
        "name_length_1_30": "❌ نام باید ۱ تا ۳۰ کاراکتر باشد.",
        "send_new_username": "🆔 نام کاربری جدید (۳+ کاراکتر) بفرستید:",
        "username_3_plus": "❌ نام کاربری حداقل ۳ کاراکتر. دوباره بفرستید:",
        "username_taken_other": "❌ این نام کاربری گرفته شده.",
        "send_new_password": "🔑 رمز جدید بفرستید:",
        "password_length_1_30": "❌ رمز باید ۱ تا ۳۰ کاراکتر باشد.",
        "password_changed": "✅ رمز با موفقیت عوض شد!",
        "confirm_logout": "🚪 مطمئنید که می‌خواهید خارج شوید؟",
        "logout_success": "👋 با موفقیت خارج شدید!\nبرای ثبت‌نام دوباره /start بفرستید.",
        "choose_play_mode": "🔄 نحوهٔ بازی را انتخاب کنید:",
        "invite_expired": "⚠️ دعوت منقضی شده.",
        "invite_not_yours": "⚠️ این دعوت برای شما نیست.",
        "already_responded": "⚠️ قبلاً به این دعوت پاسخ داده‌اید.",
        "accepted_invite": "✅ دعوت قبول شد! در انتظار بقیه...",
        "rejected_invite": "❌ دعوت رد شد.",
        "send_username_to_search": "✍️ نام کاربری شخصی را که می‌خواهید پیدا کنید بفرستید:",
        "no_player_with_username": "❌ بازیکنی با این نام کاربری نیست. دوباره امتحان کنید:",
        "follow_success": "✅ با موفقیت دنبال شد!",
        "not_following_anyone": "📉 الان کسی را دنبال نمی‌کنید.",
        "no_followers": "📈 الان دنبال‌کننده‌ای ندارید.",
        "must_follow_for_alerts": "⚠️ اول بازیکن را دنبال کنید تا هشدار فعال شود!",
        "alert_updated": "✅ تنظیمات هشدار به‌روز شد",
        "alert_disabled": "❌ هشدار غیرفعال شد",
        "own_settings_only": "🧐 فقط از «حساب من» می‌توانید تنظیمات خود را ویرایش کنید.",
        "requests_allowed": "✅ درخواست‌ها مجاز شد",
        "requests_locked": "❌ درخواست‌ها قفل شد",
        "data_error": "⚠️ خطای داده.",
        "cannot_invite_self": "🚫 نمی‌توانید خودتان را دعوت کنید!",
        "player_blocked_you": "⛔ این بازیکن شما را مسدود کرده. نمی‌توانید دعوت بفرستید.",
        "invites_following_only": "⛔ این بازیکن فقط از کسانی که دنبال می‌کند دعوت می‌پذیرد.",
        "follow_first_then_invite": "⛔ اول این بازیکن را دنبال کنید بعد دعوت بفرستید.",
        "invite_sent": "✅ درخواست بازی با موفقیت ارسال شد!",
        "invite_failed": "⚠️ ارسال ناموفق (شاید ربات را مسدود کرده).",
        "mute_cancelled": "✅ بی‌صدا برداشته شد. این بازیکن دوباره می‌تواند دعوت بفرستد.",
        "cannot_block_self": "نمی‌توانید خودتان را مسدود کنید.",
        "blocked_success": "✅ مسدود شد. نمی‌تواند دعوت بفرستد.",
        "already_blocked": "⚠️ قبلاً مسدود کرده‌اید.",
        "unblocked": "✅ رفع مسدودیت شد.",
        "choose_mute_duration": "🔇 مدت بی‌صدا یا لغو بی‌صدا را انتخاب کنید:",
        "updated": "✅ به‌روز شد",
        "invite_accepted_starting": "✅ دعوت قبول شد! در حال شروع بازی...",
        "game_start_error": "⚠️ خطا در شروع بازی.",
        "request_rejected": "درخواست با موفقیت رد شد.",
        "request_rejected_msg": "❌ درخواست رد شد.",
        "still_not_subscribed": "⛔ هنوز عضو کانال نیستید. عضو شوید و دوباره «تأیید» بزنید.",
        "verified": "✅ تأیید شد، خوش آمدید!",
        "verified_register": "✅ تأیید شد. ثبت‌نام یا ورود کنید.",
        "verified_join_room": "✅ تأیید شد، به اتاق پیوستید!",
        "hello_send_start": "سلام! برای ثبت‌نام دوباره /start بفرستید.",
        "enter_username_please": "⚠️ لطفاً نام کاربری (حروف و اعداد) وارد کنید:",
        "post_published": "✅ پست شما در کانال منتشر شد.",
        "publish_unavailable": "⚠️ الان انتشار در دسترس نیست.",
        "share_unavailable": "⚠️ اشتراک نتایج هنوز فعال نیست.",
        "share_expired": "⚠️ زمان اشتراک تمام شده. بعد از پایان دور دوباره امتحان کنید.",
        "not_authorized": "⚠️ مجاز نیست.",
        "channel_unavailable": "📜 کانال الان در دسترس نیست.",
        "send_message_again": "پیام را دوباره بفرستید.",
        "cannot_delete_post": "⚠️ نمی‌توانید این پست را حذف کنید.",
        "post_deleted": "✅ پست حذف شد.",
        "option_expired": "⚠️ این گزینه منقضی شده.",
        "player_not_found_short": "❌ بازیکن پیدا نشد.",
        "profile_open_failed": "⚠️ باز کردن پروفایل ناموفق بود.",
    },
}

