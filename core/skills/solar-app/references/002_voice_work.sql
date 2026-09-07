ALTER TABLE threads ADD COLUMN state TEXT NOT NULL DEFAULT 'talking';
ALTER TABLE threads ADD COLUMN active_run_id TEXT;
ALTER TABLE runs ADD COLUMN task_id TEXT;
ALTER TABLE runs ADD COLUMN cancellation_requested INTEGER NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS voice_requests (
    request_id TEXT PRIMARY KEY,
    source_text TEXT NOT NULL,
    response_json TEXT,
    created_at TEXT NOT NULL
);
