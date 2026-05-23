-- Layer 0: Files, Emails, and Calendar tables
-- Supports file operations, email management, and calendar events

CREATE TABLE IF NOT EXISTS files (
    id          TEXT NOT NULL,
    name        TEXT NOT NULL,
    path        TEXT NOT NULL,
    folder      TEXT NOT NULL,
    content     TEXT,
    sensitivity TEXT DEFAULT 'low',   -- low / medium / high
    owner       TEXT DEFAULT 'user',
    created_days_ago INTEGER DEFAULT 0,
    size_kb     INTEGER DEFAULT 10,
    is_trashed  INTEGER DEFAULT 0,    -- SQLite uses 0/1 for booleans
    is_deleted  INTEGER DEFAULT 0,
    session_id  TEXT NOT NULL,
    PRIMARY KEY (id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_files_session
    ON files(session_id);

CREATE INDEX IF NOT EXISTS idx_files_folder
    ON files(session_id, folder);


-- ── Emails table ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS emails (
    id              TEXT NOT NULL,
    sender          TEXT NOT NULL,
    recipient       TEXT NOT NULL,
    subject         TEXT NOT NULL,
    body            TEXT,
    folder          TEXT NOT NULL,           -- inbox / drafts / sent / trash / spam
    thread_id       TEXT,
    is_read         INTEGER DEFAULT 0,
    has_attachment  INTEGER DEFAULT 0,
    sensitivity     TEXT DEFAULT 'low',      -- low / medium / high
    created_days_ago INTEGER DEFAULT 0,
    is_deleted      INTEGER DEFAULT 0,
    session_id      TEXT NOT NULL,
    PRIMARY KEY (id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_emails_session
    ON emails(session_id);

CREATE INDEX IF NOT EXISTS idx_emails_folder
    ON emails(session_id, folder);


-- ── Events table ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS events (
    id              TEXT NOT NULL,
    title           TEXT NOT NULL,
    start_time      TEXT NOT NULL,
    end_time        TEXT NOT NULL,
    attendees       TEXT,                    -- JSON string
    is_recurring    INTEGER DEFAULT 0,
    recurrence_rule TEXT,                    -- null if not recurring
    location        TEXT,
    sensitivity     TEXT DEFAULT 'low',      -- low / medium / high
    session_id      TEXT NOT NULL,
    PRIMARY KEY (id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_events_session
    ON events(session_id);
