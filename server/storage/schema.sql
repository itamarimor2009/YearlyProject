-- schema.sql - The tables of the filter database (SQLite).
-- A drawing of these tables is in docs/ARCHITECTURE.md, section 8.
-- "IF NOT EXISTS" means it is safe to run this file every time the server starts.

-- Where blocked sites come from (for now only the file blacklist.txt).
CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,      -- e.g. "file:blacklist.txt"
    kind          TEXT NOT NULL,             -- e.g. "file" (later: "url", "manual")
    last_imported TEXT                       -- date and time of the last import
);

-- The blocklist itself. Blocking "facebook.com" also blocks its subdomains.
CREATE TABLE IF NOT EXISTS blocked_sites (
    id        INTEGER PRIMARY KEY,
    domain    TEXT NOT NULL,                 -- e.g. "facebook.com"
    source_id INTEGER NOT NULL REFERENCES sources(id),
    category  TEXT,                          -- optional, e.g. "social"
    enabled   INTEGER NOT NULL DEFAULT 1,    -- 1 = active, 0 = switched off
    added_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (domain, source_id)
);
CREATE INDEX IF NOT EXISTS idx_blocked_sites_domain ON blocked_sites(domain);

-- The computers that are allowed to use the server.
-- We never store the token itself, only its SHA-256 hash.
CREATE TABLE IF NOT EXISTS clients (
    id         INTEGER PRIMARY KEY,
    client_id  TEXT NOT NULL UNIQUE,         -- e.g. "pc-12"
    token_hash TEXT NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- One row for every "check" (allowed and blocked). The future dashboard reads this.
CREATE TABLE IF NOT EXISTS access_log (
    id        INTEGER PRIMARY KEY,
    ts        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,   -- time of the check (UTC)
    client_id TEXT NOT NULL,
    client_ip TEXT NOT NULL,
    host      TEXT NOT NULL,
    decision  TEXT NOT NULL,                 -- "allow" or "block"
    rule      TEXT                           -- the blocked domain that matched, or NULL
);
CREATE INDEX IF NOT EXISTS idx_access_log_ts ON access_log(ts);
CREATE INDEX IF NOT EXISTS idx_access_log_host ON access_log(host);

-- Remember which version of this schema the database has (for future upgrades).
PRAGMA user_version = 1;
