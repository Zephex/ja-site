"""Passwords, sessions, CSRF, invite tokens and login throttling."""

import hashlib
import hmac
import json
import secrets
import time

from . import config, db

PBKDF2_ROUNDS = 210_000


def new_token():
    return secrets.token_urlsafe(24)


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def equal(a, b):
    return hmac.compare_digest(str(a), str(b))


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return "pbkdf2_sha256$%d$%s$%s" % (PBKDF2_ROUNDS, salt.hex(), digest.hex())


def verify_password(password, stored):
    try:
        scheme, rounds, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        )
        return equal(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


class Session:
    def __init__(self, data=None, token=None, old_hash=None):
        self.data = data or {}
        self.token = token or new_token()
        self.old_hash = old_hash
        self.dirty = False

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.dirty = True

    def pop(self, key, default=None):
        value = self.data.pop(key, default)
        self.dirty = True
        return value

    def clear(self):
        self.data = {}
        self.dirty = True

    def regenerate(self):
        previous = token_hash(self.token)
        if self.old_hash is None:
            self.old_hash = previous
        self.token = new_token()
        self.dirty = True


def load_session(conn, cookie_token):
    old_hash = token_hash(cookie_token) if cookie_token else None
    if old_hash:
        row = db.one(conn, "SELECT data, expires_at FROM sessions WHERE token_hash = ?", (old_hash,))
        if row and row["expires_at"] > int(time.time()):
            try:
                return Session(json.loads(row["data"]), cookie_token, old_hash)
            except (ValueError, TypeError):
                pass
    return Session()


def save_session(conn, session):
    if not session.dirty:
        return
    if session.old_hash:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (session.old_hash,))
    conn.execute(
        "INSERT OR REPLACE INTO sessions (token_hash, data, expires_at) VALUES (?, ?, ?)",
        (
            token_hash(session.token),
            json.dumps(session.data),
            int(time.time()) + config.SESSION_TTL,
        ),
    )
    conn.commit()


def csrf_token(session):
    token = session.get("csrf")
    if not token:
        token = new_token()
        session.set("csrf", token)
    return token


def csrf_ok(session, req):
    supplied = req.form.get("csrf") or req.headers.get("x-csrf-token", "")
    expected = session.get("csrf", "")
    return bool(expected) and equal(supplied, expected)


def client_ip(req):
    forwarded = req.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return req.remote_addr or "unknown"


def login_blocked(conn, req):
    cutoff = int(time.time()) - config.LOGIN_WINDOW
    conn.execute("DELETE FROM login_attempts WHERE created_at < ?", (cutoff,))
    ip_hash = token_hash(client_ip(req))
    row = db.one(
        conn, "SELECT COUNT(*) AS n FROM login_attempts WHERE ip_hash = ?", (ip_hash,)
    )
    return row["n"] >= config.LOGIN_MAX


def login_failed(conn, req):
    conn.execute(
        "INSERT INTO login_attempts (ip_hash, created_at) VALUES (?, ?)",
        (token_hash(client_ip(req)), int(time.time())),
    )
    conn.commit()


def login_succeeded(conn, req):
    conn.execute("DELETE FROM login_attempts WHERE ip_hash = ?", (token_hash(client_ip(req)),))
    conn.commit()
