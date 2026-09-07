DROP TABLE IF EXISTS app_conversation_settings;
ALTER TABLE app_messages ADD COLUMN dispatch_pending INTEGER NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS app_run_content (
 run_id TEXT PRIMARY KEY, input TEXT NOT NULL DEFAULT '', output TEXT NOT NULL DEFAULT '', log TEXT NOT NULL DEFAULT ''
);
ALTER TABLE runs DROP COLUMN task_root;
