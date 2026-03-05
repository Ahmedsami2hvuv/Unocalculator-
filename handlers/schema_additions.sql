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
