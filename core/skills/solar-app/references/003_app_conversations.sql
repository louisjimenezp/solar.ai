CREATE TABLE IF NOT EXISTS app_conversations (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_messages (
 id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL,
 text TEXT NOT NULL, created_at TEXT NOT NULL, request_id TEXT UNIQUE, work_thread_id TEXT
);
CREATE INDEX IF NOT EXISTS app_messages_conversation ON app_messages(conversation_id, created_at);
CREATE TABLE IF NOT EXISTS app_work_links (
 run_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, thread_id TEXT NOT NULL,
 delivered INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS app_file_snapshot (
 path TEXT PRIMARY KEY, size INTEGER NOT NULL, modified INTEGER NOT NULL, present INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS app_file_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL
);

ALTER TABLE runs ADD COLUMN task_root TEXT;
