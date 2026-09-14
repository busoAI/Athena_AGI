"""
memory/store.py
ระบบความจำระยะยาวและถาวร (Persistent Long-term Memory) สำหรับ Athena Project
- บันทึกข้อเท็จจริง ความชอบของบอส ข้อมูลสำคัญ และประวัติการสั่งงาน
- ใช้ SQLite พร้อมโหมด WAL สำหรับความเสถียรและความเร็วสูงสุด
- รองรับการเรียกใช้ผ่าน Function Calling และ Context Injection เข้าสมอง AI
"""

from __future__ import annotations

import logging
from pathlib import Path
import sqlite3
import time
from typing import Any

from config import Config

logger = logging.getLogger(__name__)


class AthenaMemory:
    """
    ระบบความจำส่วนตัวสำหรับเลขาธิการเอเธน่า
    จัดการบันทึก ค้นหา ลบ และสรุปความจำของบอสอย่างเป็นระบบ
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path:
            self._db_path = Path(db_path)
        else:
            storage_dir = Config.BASE_DIR / "storage"
            storage_dir.mkdir(parents=True, exist_ok=True)
            self._db_path = storage_dir / "memory.db"

        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        """สร้างตารางและดัชนีสำหรับจัดเก็บความจำ"""
        with self._conn:
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)"
            )
        logger.info("Athena memory database initialized at %s", self._db_path)

    def remember(self, key: str, value: str, category: str = "general") -> str:
        """
        บันทึกหรืออัปเดตข้อมูลความจำ
        เช่น บอสบอก 'จำไว้ว่าไฟล์งานอยู่ที่ D:\\Work' หรือ 'จำรหัส WiFi คือ 1234'
        """
        clean_key = str(key or "").strip()
        clean_val = str(value or "").strip()
        clean_cat = str(category or "general").strip()

        if not clean_key or not clean_val:
            return "กรุณาระบุหัวข้อและข้อมูลที่ต้องการให้เอเธน่าจำค่ะ"

        now = time.time()
        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO memories (key, value, category, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        category = excluded.category,
                        updated_at = excluded.updated_at
                    """,
                    (clean_key, clean_val, clean_cat, now, now),
                )
            logger.info("Memory saved: [%s] %s = %s", clean_cat, clean_key, clean_val)
            return f"เอเธน่าบันทึกข้อมูล '{clean_key}': '{clean_val}' ลงในความจำเรียบร้อยแล้วค่ะ"
        except Exception as exc:
            logger.exception("Error saving memory: %s", exc)
            return f"เกิดข้อผิดพลาดในการบันทึกความจำ: {exc}ค่ะ"

    def recall(self, query: str = "") -> str:
        """
        ค้นหาหรือดึงข้อมูลความจำตามคำค้นหา
        เช่น 'ไฟล์งาน', 'WiFi', 'ความชอบของบอส'
        """
        needle = str(query or "").strip().lower()
        if not needle:
            return self.list_memories()

        try:
            cursor = self._conn.execute(
                """
                SELECT key, value, category, updated_at
                FROM memories
                WHERE instr(lower(key), ?) > 0
                   OR instr(lower(value), ?) > 0
                   OR instr(lower(category), ?) > 0
                ORDER BY updated_at DESC
                LIMIT 10
                """,
                (needle, needle, needle),
            )
            rows = cursor.fetchall()
            if not rows:
                return f"เอเธน่าค้นหาในความจำแล้ว ไม่พบข้อมูลเกี่ยวกับ '{query}' ค่ะ"

            results = [f"- {row['key']}: {row['value']} (หมวด: {row['category']})" for row in rows]
            return f"พบข้อมูลในความจำเกี่ยวกับ '{query}' จำนวน {len(rows)} รายการค่ะ:\n" + "\n".join(results)
        except Exception as exc:
            logger.exception("Error recalling memory: %s", exc)
            return f"เกิดข้อผิดพลาดในการค้นหาความจำ: {exc}ค่ะ"

    def forget(self, key: str) -> str:
        """
        ลบข้อมูลความจำออกจากระบบ
        เช่น บอสบอก 'ลบความจำเรื่อง WiFi' หรือ 'ไม่ต้องจำเรื่องไฟล์งานแล้ว'
        """
        clean_key = str(key or "").strip()
        if not clean_key:
            return "กรุณาระบุหัวข้อความจำที่ต้องการให้เอเธน่าลบค่ะ"

        try:
            with self._conn:
                # ลองลบแบบตรงตัวก่อน
                cursor = self._conn.execute("DELETE FROM memories WHERE key = ?", (clean_key,))
                count = cursor.rowcount

                # หากไม่พบ ลองลบแบบ partial match
                if count == 0:
                    cursor = self._conn.execute(
                        "DELETE FROM memories WHERE instr(lower(key), lower(?)) > 0",
                        (clean_key,),
                    )
                    count = cursor.rowcount

            if count > 0:
                logger.info("Memory deleted for key: %s (deleted %d rows)", clean_key, count)
                return f"เอเธน่าลบข้อมูลเกี่ยวกับ '{clean_key}' ออกจากความจำเรียบร้อยแล้วค่ะ"
            return f"ไม่พบข้อมูลเกี่ยวกับ '{clean_key}' ในความจำค่ะ"
        except Exception as exc:
            logger.exception("Error forgetting memory: %s", exc)
            return f"เกิดข้อผิดพลาดในการลบความจำ: {exc}ค่ะ"

    def list_memories(self, category: str = "") -> str:
        """แสดงรายการความจำทั้งหมดหรือตามหมวดหมู่"""
        clean_cat = str(category or "").strip().lower()
        try:
            if clean_cat:
                cursor = self._conn.execute(
                    "SELECT key, value, category FROM memories WHERE lower(category) = ? ORDER BY updated_at DESC LIMIT 20",
                    (clean_cat,),
                )
            else:
                cursor = self._conn.execute(
                    "SELECT key, value, category FROM memories ORDER BY updated_at DESC LIMIT 20"
                )
            rows = cursor.fetchall()
            if not rows:
                return "ขณะนี้ยังไม่มีข้อมูลในความจำค่ะ"

            lines = [f"- [{row['category']}] {row['key']}: {row['value']}" for row in rows]
            return f"รายการความจำที่บันทึกไว้ ({len(rows)} รายการ) ค่ะ:\n" + "\n".join(lines)
        except Exception as exc:
            logger.exception("Error listing memories: %s", exc)
            return f"เกิดข้อผิดพลาดในการดึงรายการความจำ: {exc}ค่ะ"

    def get_context_summary(self, limit: int = 8) -> str:
        """
        ดึงข้อความสรุปความจำที่สำคัญ เพื่อนำไปป้อนเข้า Context/System Prompt ของโมเดลเสียง
        """
        try:
            cursor = self._conn.execute(
                "SELECT key, value FROM memories ORDER BY updated_at DESC LIMIT ?",
                (int(limit),),
            )
            rows = cursor.fetchall()
            if not rows:
                return ""
            items = [f"{row['key']}: {row['value']}" for row in rows]
            return "ข้อมูลความจำสำคัญของบอส:\n" + "\n".join(f"- {item}" for item in items)
        except Exception:
            return ""

    def close(self) -> None:
        """ปิดการเชื่อมต่อฐานข้อมูล"""
        try:
            self._conn.close()
        except Exception:
            pass
