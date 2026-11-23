"""Configuration for the invites.example.com invite-page app."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORAGE = Path(os.environ.get("JA_STORAGE", ROOT / "storage")).resolve()
DB_PATH = Path(os.environ.get("JA_DB_PATH", STORAGE / "ja.db")).resolve()
UPLOAD_DIR = Path(os.environ.get("JA_UPLOAD_DIR", STORAGE / "uploads")).resolve()
BACKGROUND_DIR = Path(os.environ.get("JA_BACKGROUND_DIR", STORAGE / "backgrounds")).resolve()
MEDIA_DIR = Path(os.environ.get("JA_MEDIA_DIR", STORAGE / "media")).resolve()

GRADIENTS = {
    "aurora": "linear-gradient(135deg, #05060d 0%, #0b1a3a 45%, #2b1055 100%)",
    "sunset": "linear-gradient(135deg, #ff7e5f 0%, #feb47b 45%, #6a3093 100%)",
    "ocean": "linear-gradient(135deg, #0a192f 0%, #0f4c75 55%, #1b998b 100%)",
    "violet": "linear-gradient(135deg, #1a0b2e 0%, #6a3093 55%, #a044ff 100%)",
    "forest": "linear-gradient(135deg, #0b2017 0%, #1d6b4f 55%, #8fd19e 100%)",
}

BASE_URL = os.environ.get("JA_BASE_URL", "https://invites.example.com").rstrip("/")
SITE_NAME = os.environ.get("JA_SITE_NAME", "invites.example.com")

HOST = os.environ.get("JA_HOST", "127.0.0.1")
PORT = int(os.environ.get("JA_PORT", "8080"))

SESSION_COOKIE = "ja_session"
SESSION_TTL = 60 * 60 * 24 * 30
MAX_UPLOAD = 10 * 1024 * 1024  # 10 MB per image
MAX_VIDEO_UPLOAD = 100 * 1024 * 1024  # 100 MB per video

LOGIN_WINDOW = 15 * 60
LOGIN_MAX = 10


def ensure_dirs():
    STORAGE.mkdir(parents=True, exist_ok=True, mode=0o700)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    BACKGROUND_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(STORAGE, 0o700)
        os.chmod(UPLOAD_DIR, 0o700)
        os.chmod(BACKGROUND_DIR, 0o700)
        os.chmod(MEDIA_DIR, 0o700)
    except OSError:
        pass
