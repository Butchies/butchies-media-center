CREATE TABLE IF NOT EXISTS playback_sessions (
 id TEXT PRIMARY KEY,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 media_id TEXT NOT NULL REFERENCES media(id) ON DELETE CASCADE,
 media_file_id TEXT REFERENCES media_files(id),
 device_id TEXT,
 started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 last_progress_at TEXT,
 position_ms INTEGER NOT NULL DEFAULT 0,
 paused INTEGER NOT NULL DEFAULT 0,
 stopped_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_playback_user ON playback_sessions(user_id,stopped_at);
CREATE TABLE IF NOT EXISTS playback_preferences (
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 default_audio_language TEXT,
 default_subtitle_language TEXT,
 autoplay_next INTEGER NOT NULL DEFAULT 1,
 preferred_quality TEXT NOT NULL DEFAULT 'auto',
 subtitle_size TEXT NOT NULL DEFAULT 'medium',
 subtitle_offset_ms INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS playback_queue (
 session_id TEXT NOT NULL REFERENCES playback_sessions(id) ON DELETE CASCADE,
 position INTEGER NOT NULL,
 media_id TEXT NOT NULL REFERENCES media(id),
 PRIMARY KEY(session_id,position)
);