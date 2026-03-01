-- إضافات قاعدة البيانات للتطويرات الجديدة
-- شغّل ما تحتاجه حسب ما هو متوفر لديك
--
-- 📍 مكان الملف: ضعه مع الملفات الرئيسية للمشروع (مثلاً داخل مجلد uno/ أو جذر المشروع)
--    وليس داخل مجلد handlers. هذا ملف SQL يُنفَّذ مرة واحدة على قاعدة البيانات
--    ولا يُستورد من بايثون.

-- يوزر تليجرام (@) للاعب (يُحدَّث من البوت عند التفاعل)
ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(100) DEFAULT NULL;

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
