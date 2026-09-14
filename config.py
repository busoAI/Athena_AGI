"""
config.py
Athena Project — Central Configuration
โหลดค่า Environment Variables สำหรับเชื่อมต่อ AI และตั้งค่าระบบ
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# โหลด .env จากโฟลเดอร์โปรเจกต์
PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")


class Config:
    """การตั้งค่าระบบ Athena"""

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    LIVE_VOICE_MODEL: str = os.getenv("LIVE_VOICE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
    CHAT_MODEL: str = os.getenv("CHAT_MODEL", "gemini-3.1-pro-preview")
    FALLBACK_CHAT_MODEL: str = os.getenv("FALLBACK_CHAT_MODEL", "gemini-3.6-flash")
    VOICE_NAME: str = os.getenv("VOICE_NAME", "Kore")  # เสียงผู้หญิงสไตล์เลขาบริหาร (Firm & Professional)
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # พาร์ทพื้นที่ทำงาน
    BASE_DIR: Path = PROJECT_ROOT
    TEMP_DIR: Path = PROJECT_ROOT / "temp"

    @classmethod
    def ensure_dirs(cls) -> None:
        cls.TEMP_DIR.mkdir(parents=True, exist_ok=True)


Config.ensure_dirs()
