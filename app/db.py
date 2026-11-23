"""SQLite storage. A fresh connection is used per request (thread-safe)."""

import shutil
import sqlite3
import time

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    greeting TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    token TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL DEFAULT '',
    require_name INTEGER NOT NULL DEFAULT 0,
    expires_at INTEGER,
    max_uses INTEGER,
    uses INTEGER NOT NULL DEFAULT 0,
    revoked INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS redemptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invite_id INTEGER NOT NULL REFERENCES invites(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    visitor_name TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    original_name TEXT NOT NULL,
    mime TEXT NOT NULL,
    size INTEGER NOT NULL,
    caption TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL UNIQUE,
    original_name TEXT NOT NULL,
    mime TEXT NOT NULL,
    kind TEXT NOT NULL,
    size INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS login_attempts (
    ip_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_invites_account ON invites(account_id);
CREATE INDEX IF NOT EXISTS idx_images_account ON images(account_id);
CREATE INDEX IF NOT EXISTS idx_links_account ON links(account_id);
CREATE INDEX IF NOT EXISTS idx_attempts_ip ON login_attempts(ip_hash, created_at);
"""

Initialized = False


def connect():
    global Initialized
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if not Initialized:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        Initialized = True
        # Older installs stored one background image outside the library.
        # Bring it into the library so it stays selectable after this upgrade.
        legacy = get_setting(conn, "bg_image", "")
        if legacy and "/" not in legacy and "\\" not in legacy and ".." not in legacy:
            source = config.BACKGROUND_DIR / legacy
            target = config.MEDIA_DIR / legacy
            if source.is_file() and not target.exists():
                try:
                    shutil.copyfile(source, target)
                except OSError:
                    pass
            if target.is_file() and not one(conn, "SELECT id FROM media WHERE filename = ?", (legacy,)):
                cursor = conn.execute(
                    """INSERT INTO media (filename, original_name, mime, kind, size, created_at)
                       VALUES (?, ?, ?, 'image', 0, ?)""",
                    (
                        legacy,
                        legacy,
                        get_setting(conn, "bg_image_mime", "image/jpeg"),
                        int(time.time()),
                    ),
                )
                if not get_setting(conn, "bg_media_id", ""):
                    set_setting(conn, "bg_media_id", str(cursor.lastrowid))
    return conn


def one(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()


def all_rows(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def run(conn, sql, params=()):
    return conn.execute(sql, params)


def commit(conn):
    conn.commit()


def get_setting(conn, key, default=""):
    row = one(conn, "SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
