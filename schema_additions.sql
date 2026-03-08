-- إضافات قاعدة البيانات للتطويرات الجديدة
-- شغّل ما تحتاجه حسب ما هو متوفر لديك
--
-- 📍 مكان الملف: ضعه مع الملفات الرئيسية للمشروع (مثلاً داخل مجلد uno/ أو جذر المشروع)
--    وليس داخل مجلد handlers. هذا ملف SQL يُنفَّذ مرة واحدة على قاعدة البيانات
--    ولا يُستورد من بايثون.

-- يوزر تليجرام (@) للاعب (يُحدَّث من البوت عند التفاعل)
ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(100) DEFAULT NULL;

-- تسجيل خروج: عندما يكون TRUE يُعرض للمستخدم شاشة الدخول/التسجيل
ALTER TABLE users ADD COLUMN IF NOT EXISTS logged_out BOOLEAN DEFAULT FALSE;

-- تعليم تفاعلي: عرض الدليل لأول مرة فقط
ALTER TABLE users ADD COLUMN IF NOT EXISTS seen_tutorial BOOLEAN DEFAULT FALSE;

-- إنجازات اللاعبين
CREATE TABLE IF NOT EXISTS user_achievements (
    user_id BIGINT NOT NULL,
    achievement_id VARCHAR(32) NOT NULL,
    unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, achievement_id)
);

-- سجل نتائج الجولات (للمباريات والإحصائيات وعرض نهاية الجولة)
CREATE TABLE IF NOT EXISTS match_results (
    id SERIAL PRIMARY KEY,
    room_id VARCHAR(16) NOT NULL,
    round_num INT DEFAULT 1,
    winner_id BIGINT,
    scores_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- غرف عامة (اختياري: عرض الغرفة في قائمة الغرف العامة)
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS is_public BOOLEAN DEFAULT FALSE;

-- بطولات مصغرة
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS is_tournament BOOLEAN DEFAULT FALSE;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS tournament_rounds INT DEFAULT 3;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS tournament_current_round INT DEFAULT 1;

-- وقت إنشاء الغرفة (لإدارة البوت: إغلاق الغرف المتروكة أكثر من 24 ساعة)
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- كود الغرفة المعلقة (عند فتح رابط انضمام قبل تسجيل الدخول، لانضمامه بعد الدخول)
ALTER TABLE users ADD COLUMN IF NOT EXISTS pending_room_code VARCHAR(20) DEFAULT NULL;

-- منشورات القناة (لإحصائيات: لايكات، نقرات حساب، ومشاهدات لاحقاً)
CREATE TABLE IF NOT EXISTS channel_posts (
    id SERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL,
    message_id BIGINT NOT NULL,
    publisher_uid BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    likes_count INT DEFAULT 0,
    profile_clicks_count INT DEFAULT 0,
    add_profile BOOLEAN DEFAULT TRUE,
    join_code VARCHAR(20) DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_channel_posts_publisher ON channel_posts(publisher_uid);
ALTER TABLE channel_posts ADD COLUMN IF NOT EXISTS add_profile BOOLEAN DEFAULT TRUE;
ALTER TABLE channel_posts ADD COLUMN IF NOT EXISTS join_code VARCHAR(20) DEFAULT NULL;

-- انتظار نشر منشور (بعد ضغط «تم أرسل رسالتك» حتى يرسل المستخدم النص/الميديا) — يعمل مع أكثر من worker
ALTER TABLE users ADD COLUMN IF NOT EXISTS pending_post_options TEXT DEFAULT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS pending_post_at TIMESTAMP DEFAULT NULL;

-- جلسات نشر الفوز (حتى يعمل «نشر فوزك» من أي حساب/worker بعد انتهاء الجولة)
CREATE TABLE IF NOT EXISTS replay_sessions (
    replay_id VARCHAR(16) PRIMARY KEY,
    summary TEXT,
    winner_id BIGINT,
    players_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- طلبات المساعدة (لعرضها في لوحة الأدمن وإرسالها للمدير)
CREATE TABLE IF NOT EXISTS help_requests (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    body_text TEXT NOT NULL,
    has_media BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ========== نظام الشارات (Badges) ==========
-- لون الشارة (🔴🟡🟢🔵)، المستوى الحالي، العداد، وآخر خصم (لمنع الاحتيال)
ALTER TABLE users ADD COLUMN IF NOT EXISTS badge_color VARCHAR(10) DEFAULT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS badge_level INT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS badge_streak INT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS badge_streak_started_at TIMESTAMP DEFAULT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS badge_last_opponent_id BIGINT DEFAULT NULL;
-- عمود اختياري في replay_sessions لعرض زر «انشر شارتك» بعد الحصول على شارة
ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS badge_earned TEXT DEFAULT NULL;

-- عرض سؤال «هل تريد التدريب» مرة واحدة بعد إكمال التسجيل
ALTER TABLE users ADD COLUMN IF NOT EXISTS asked_training_offer BOOLEAN DEFAULT FALSE;

-- وضع التدريب: لعب حقيقي مع البوت مع توجيه خطوة بخطوة حتى يفوز اللاعب
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS is_training BOOLEAN DEFAULT FALSE;
