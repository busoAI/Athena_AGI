"""
voice/live_stream.py
โมดูล Real-time Voice & Live Stream สำหรับ Athena Project
- เชื่อมต่อ Gemini Live API แบบ Bidirectional ผ่าน Google GenAI SDK (gemini-3.1-flash-live-preview)
- บันทึกเสียงไมโครโฟน PCM 16kHz และเล่นเสียงตอบกลับ PCM 24kHz ผ่าน sounddevice
- รองรับ Function Calling / Tool Declarations สำหรับคำสั่ง Desktop:
  (minimize, maximize, restore, click, move, type, open_app, close_app)
- เมื่อโมเดลสั่ง ToolCall -> รันฟังก์ชัน -> ส่ง ToolResponse กลับเข้าห้อง -> โมเดลพูดรายงานผลออกลำโพงสดทันที
- ปราศจาก regex หรือ if-else ดักคำศัพท์ โดยให้โมเดลเป็นผู้ตัดสินใจเรียก Tool อย่างอิสระ
"""

from __future__ import annotations

import asyncio
import ctypes
from ctypes import wintypes
import logging
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import time
from typing import Any

from google import genai
from google.genai import types
import psutil
import sounddevice as sd

from config import Config

# กำหนดค่า Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("AthenaLiveStream")


# ─────────────────────────────────────────────────────────────────────────────
# Desktop Control Tools
# ─────────────────────────────────────────────────────────────────────────────

# รายการแอปพลิเคชันยอดนิยมสำหรับคำสั่งเปิดแอปแบบย่อ
COMMON_APP_ALIASES: dict[str, str] = {
    "notepad": "notepad.exe",
    "โน้ตแพด": "notepad.exe",
    "สมุดจด": "notepad.exe",
    "calc": "calc.exe",
    "calculator": "calc.exe",
    "เครื่องคิดเลข": "calc.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "โครม": "chrome.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "paint": "mspaint.exe",
    "เพ้นท์": "mspaint.exe",
    "cmd": "cmd.exe",
    "terminal": "powershell.exe",
    "powershell": "powershell.exe",
    "taskmgr": "taskmgr.exe",
    "task manager": "taskmgr.exe",
    "ทาสก์เมเนเจอร์": "taskmgr.exe",
    "edge": "msedge.exe",
}


class DesktopTools:
    """
    ชุดเครื่องมือควบคุม Desktop (Windows, Mouse, Keyboard, Apps)
    พร้อม Tool Declarations สำหรับ Gemini Function Calling
    """

    DESKTOP_TOOL_DECLARATIONS: list[dict[str, Any]] = [
        {
            "name": "minimize",
            "description": "ย่อหน้าต่าง หรือพับหน้าต่าง (Minimize) บน Windows เช่น 'ย่อหน้าต่าง', 'พับจอ', 'ย่อลงมา', 'เอาหน้าต่างลงมา', 'ย่อ Chrome' หากไม่ระบุชื่อจะย่อหน้าต่างปัจจุบันที่กำลังใช้งาน",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "title": {
                        "type": "STRING",
                        "description": "ชื่อหน้าต่างหรือโปรแกรมที่ต้องการย่อ (เว้นว่างได้หากต้องการย่อหน้าต่างปัจจุบัน)",
                    }
                },
            },
        },
        {
            "name": "maximize",
            "description": "ขยายหน้าต่างให้เต็มจอ (Maximize) บน Windows หากไม่ระบุชื่อจะขยายหน้าต่างปัจจุบันที่กำลังใช้งาน",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "title": {
                        "type": "STRING",
                        "description": "ชื่อหน้าต่างหรือโปรแกรมที่ต้องการขยาย (เว้นว่างได้หากต้องการขยายหน้าต่างปัจจุบัน)",
                    }
                },
            },
        },
        {
            "name": "restore",
            "description": "สลับไปยังโปรแกรม หรือดึงหน้าต่างขึ้นมาแสดงบนหน้าจอ (Restore/Focus Window) เช่น 'ไปที่ Anti-Gravity', 'สลับไป Chrome', 'ดึงหน้าต่างขึ้นมา' ทำงานรวดเร็วระดับเสี้ยววินาที",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "title": {
                        "type": "STRING",
                        "description": "ชื่อหน้าต่างหรือโปรแกรมที่ต้องการสลับหรือคืนขนาด เช่น 'antigravity', 'chrome', 'notepad'",
                    }
                },
            },
        },
        {
            "name": "click_element",
            "description": "คลิกปุ่ม ลิงก์ ไอคอน หรือช่องข้อความบนหน้าจอด้วยระบบสายตาอัจฉริยะ (เช่น 'ปุ่มส่ง', 'ปุ่มปิด', 'ช่องค้นหา', 'ไอคอน Chrome')",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "target": {
                        "type": "STRING",
                        "description": "ชื่อหรือคำอธิบายของสิ่งที่ต้องการคลิก เช่น 'ปุ่มส่ง', 'ปุ่มปิด', 'ช่องค้นหา', 'ไอคอน YouTube'",
                    },
                    "button": {
                        "type": "STRING",
                        "description": "ปุ่มเมาส์: left, right (ค่าเริ่มต้น left)",
                    },
                    "clicks": {
                        "type": "INTEGER",
                        "description": "จำนวนครั้งที่คลิก เช่น 1 หรือ 2 สำหรับดับเบิ้ลคลิก (ค่าเริ่มต้น 1)",
                    },
                },
                "required": ["target"],
            },
        },
        {
            "name": "see_screen",
            "description": "มองดูภาพหน้าจอคอมพิวเตอร์ปัจจุบันด้วยสายตามนุษย์ (Human-Eye Vision) เรียกใช้ทันทีเมื่อบอสพูดถึงสิ่งที่ปรากฏบนหน้าจอ เช่น 'ตรงนี้', 'หน้านี้', 'ปุ่มนี้', 'ทำไมเออเร่อ', 'ทำไมขึ้นแบบนี้', 'ดูนี่สิ', 'เกิดอะไรขึ้น', 'อ่านให้ฟังหน่อย', 'ทำไมค้าง' โดยตัดสินใจเรียกเองทันที ไม่ต้องรอให้บอสพูดคำว่าดูจอ และห้ามถามขออนุญาต",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": "สิ่งที่ต้องการสังเกตหรือคำถามเกี่ยวกับสิ่งที่อยู่บนหน้าจอ เช่น 'ตรวจดูข้อความ error บนจอ', 'สรุปหน้าจอ', 'ตรวจดูตรงนี้'",
                    }
                },
            },
        },
        {
            "name": "open_url",
            "description": "เปิดหน้าเว็บหรือเว็บไซต์ในเบราว์เซอร์ เช่น 'https://youtube.com', 'google.com'",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "url": {
                        "type": "STRING",
                        "description": "URL หรือที่อยู่เว็บไซต์ที่ต้องการเปิด",
                    }
                },
                "required": ["url"],
            },
        },
        {
            "name": "scroll",
            "description": "เลื่อนลูกกลิ้งเมาส์เพื่อดูเนื้อหาหน้าเว็บหรือเอกสารขึ้นหรือลง (Scroll wheel) เช่น 'เลื่อนลง', 'เลื่อนขึ้น' ห้ามใช้กับการย่อหน้าต่างหรือพับจอเด็ดขาด",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "clicks": {
                        "type": "INTEGER",
                        "description": "จำนวนการหมุนลูกกลิ้ง เช่น -5 หรือ 5",
                    }
                },
            },
        },
        {
            "name": "click",
            "description": "คลิกเมาส์ที่พิกัด x, y หรือตำแหน่งปัจจุบัน",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "x": {"type": "INTEGER", "description": "พิกัดแกน X บนหน้าจอ (optional)"},
                    "y": {"type": "INTEGER", "description": "พิกัดแกน Y บนหน้าจอ (optional)"},
                    "button": {
                        "type": "STRING",
                        "description": "ปุ่มเมาส์: left, right, middle (ค่าเริ่มต้น left)",
                    },
                    "clicks": {
                        "type": "INTEGER",
                        "description": "จำนวนครั้งที่คลิก (ค่าเริ่มต้น 1)",
                    },
                },
            },
        },
        {
            "name": "move",
            "description": "เลื่อนตำแหน่งเมาส์ไปยังพิกัด x, y บนหน้าจอ",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "x": {"type": "INTEGER", "description": "พิกัดแกน X บนหน้าจอ"},
                    "y": {"type": "INTEGER", "description": "พิกัดแกน Y บนหน้าจอ"},
                    "duration_ms": {
                        "type": "INTEGER",
                        "description": "ระยะเวลาเลื่อนเมาส์ในหน่วยมิลลิวินาที (ค่าเริ่มต้น 200)",
                    },
                },
                "required": ["x", "y"],
            },
        },
        {
            "name": "type",
            "description": "พิมพ์ข้อความผ่านแป้นพิมพ์ รองรับทั้งภาษาไทย ภาษาอังกฤษ และอักขระพิเศษ",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "text": {"type": "STRING", "description": "ข้อความที่ต้องการพิมพ์"},
                    "target_window": {
                        "type": "STRING",
                        "description": "ชื่อหน้าต่างหรือโปรแกรมที่ต้องการพิมพ์ลงไป (เช่น 'notepad', 'antigravity') หากระบุจะดึงหน้าต่างขึ้นมาโฟกัสก่อนพิมพ์ทันที",
                    },
                },
                "required": ["text"],
            },
        },
        {
            "name": "open_app",
            "description": "เปิดโปรแกรมหรือแอปพลิเคชันบน Windows เช่น notepad, calculator, chrome",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "name": {
                        "type": "STRING",
                        "description": "ชื่อโปรแกรมหรือชื่อแอป เช่น notepad, calc, chrome",
                    }
                },
                "required": ["name"],
            },
        },
        {
            "name": "close_app",
            "description": "ปิดหน้าต่างหรือปิดโปรแกรมบน Windows ตามชื่อหน้าต่างหรือชื่อโปรแกรม",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "name": {
                        "type": "STRING",
                        "description": "ชื่อหน้าต่างหรือโปรแกรมที่ต้องการปิด เช่น notepad, chrome",
                    }
                },
                "required": ["name"],
            },
        },
        {
            "name": "list_windows",
            "description": "ตรวจสอบและแสดงรายชื่อหน้าต่างโปรแกรมทั้งหมดที่เปิดอยู่บนหน้าจอ Windows เพื่อตรวจดูว่ามีโปรแกรมใดทำงานอยู่บ้าง",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": "คำค้นหาชื่อหน้าต่าง เช่น 'notepad', 'chrome' (เว้นว่างได้เพื่อดูทั้งหมด)",
                    }
                },
            },
        },
        {
            "name": "verify_window_state",
            "description": "ตรวจสอบสถานะจริงของหน้าต่างโปรแกรมอย่างละเอียด เช่น กำลังย่ออยู่, ขยายเต็มจอ, หรืออยู่ด้านหน้าสุดพร้อมใช้งาน",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "target": {
                        "type": "STRING",
                        "description": "ชื่อโปรแกรมหรือหน้าต่างที่ต้องการตรวจสถานะ เช่น 'notepad', 'chrome', 'antigravity'",
                    }
                },
                "required": ["target"],
            },
        },
        {
            "name": "delegate_to_antigravity",
            "description": "ส่งคำสั่งให้ Antigravity CLI (agy) ดำเนินการด้านการเขียนโค้ด ตรวจสอบไฟล์ รันคำสั่ง Terminal และงานระบบแบบ Autonomous",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "prompt": {
                        "type": "STRING",
                        "description": "คำสั่งหรือคำอธิบายงานที่ต้องการให้ Antigravity CLI ทำ เช่น 'วิเคราะห์โค้ดในไฟล์ main.py', 'รัน pytest', 'สร้างไฟล์...'",
                    },
                    "confirmed": {
                        "type": "BOOLEAN",
                        "description": "บอสยืนยันอนุมัติคำสั่ง (สำหรับคำสั่งที่มีความเสี่ยงสูง)",
                    },
                },
                "required": ["prompt"],
            },
        },
        {
            "name": "delegate_to_ufo",
            "description": "ส่งงานให้ Microsoft UFO ดำเนินการควบคุม GUI ซับซ้อนหลายขั้นตอน หรือจัดการเอกสาร Office (Excel, Word, PowerPoint)",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "task": {
                        "type": "STRING",
                        "description": "คำอธิบายงาน GUI หรือ Office ที่ต้องการให้ Microsoft UFO ลงมือทำบนหน้าจอ",
                    }
                },
                "required": ["task"],
            },
        },
        {
            "name": "executive_action",
            "description": "ส่งคำสั่งงานซับซ้อน คำสั่งหลายขั้นตอน หรืองานที่ต้องคิดวางแผนและตรวจงานจริง ให้สมอง Antigravity Supervisor บริหารจัดการและควบคุมเครื่องอย่างแม่นยำ เช่น 'เปิด notepad พิมพ์รายงาน แล้วตรวจดูว่าเปิดอยู่ไหม'",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "command": {
                        "type": "STRING",
                        "description": "คำสั่งหรือคำอธิบายงานที่ต้องการให้สมองบริหารจัดการลงมือทำ",
                    }
                },
                "required": ["command"],
            },
        },
        {
            "name": "remember",
            "description": "บันทึกข้อมูลสำคัญ ความชอบของบอส ที่อยู่ไฟล์ รหัส หรือข้อเท็จจริงที่บอสสั่งให้จำลงในฐานความจำถาวร เช่น 'จำไว้ว่าไฟล์งานอยู่ที่ D:\\Work'",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "key": {
                        "type": "STRING",
                        "description": "หัวข้อหรือชื่อเรื่องของความจำ เช่น 'ที่อยู่ไฟล์งาน', 'ความชอบของบอส', 'รหัสผ่าน'",
                    },
                    "value": {
                        "type": "STRING",
                        "description": "เนื้อหาหรือรายละเอียดที่ต้องการให้จำ เช่น 'D:\\Work\\Report.xlsx'",
                    },
                    "category": {
                        "type": "STRING",
                        "description": "หมวดหมู่ของความจำ เช่น 'work', 'preference', 'personal', 'credential', 'general'",
                    },
                },
                "required": ["key", "value"],
            },
        },
        {
            "name": "recall",
            "description": "ค้นหาและดึงข้อมูลความจำที่เคยบันทึกไว้เมื่อบอสสอบถาม เช่น 'จำได้ไหมว่าไฟล์งานอยู่ที่ไหน', 'ความจำเรื่องรหัสผ่าน'",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": "คำค้นหาหรือหัวข้อความจำที่ต้องการดึง เช่น 'ไฟล์งาน', 'รหัสผ่าน'",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "forget",
            "description": "ลบข้อมูลความจำที่ไม่ต้องการแล้วออกจากระบบ เช่น 'ลบความจำเรื่องรหัสผ่าน'",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "key": {
                        "type": "STRING",
                        "description": "หัวข้อหรือคีย์ของความจำที่ต้องการลบ",
                    },
                },
                "required": ["key"],
            },
        },
        {
            "name": "move_window_to_monitor",
            "description": "ย้ายหน้าต่างโปรแกรมข้ามหน้าจอ (Multi-Monitor) เช่น 'ย้ายหน้าต่างไปจอขวา', 'ย้าย Chrome ไปจอซ้าย', 'สลับหน้าต่างไปจอ 3', 'ย้ายไปอีกจอ' ทำงานระดับเสี้ยววินาทีและคงสถานะเต็มจอไว้ได้อย่างสมบูรณ์",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "title": {
                        "type": "STRING",
                        "description": "ชื่อหน้าต่างหรือโปรแกรมที่ต้องการย้าย (เว้นว่างได้หากต้องการย้ายหน้าต่างปัจจุบัน)",
                    },
                    "direction": {
                        "type": "STRING",
                        "description": "ทิศทางการย้าย: 'right' (จอขวา/จอถัดไป), 'left' (จอซ้าย/จอก่อนหน้า)",
                    },
                    "monitor_index": {
                        "type": "INTEGER",
                        "description": "หมายเลขจอเป้าหมายโดยตรง เช่น 1, 2, 3 (เว้นว่างได้หากระบุ direction)",
                    },
                },
            },
        },
        {
            "name": "drag_window",
            "description": "แดรกเมาส์หรือลากหน้าต่างข้ามจอ เช่น 'แดรกหน้าต่างนี้ไปจอขวา', 'ลากหน้าต่างไปจอข้างๆ'",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "title": {
                        "type": "STRING",
                        "description": "ชื่อหน้าต่างหรือโปรแกรมที่ต้องการลาก (เว้นว่างได้หากต้องการลากหน้าต่างปัจจุบัน)",
                    },
                    "direction": {
                        "type": "STRING",
                        "description": "ทิศทางที่ต้องการลาก: 'right' (จอขวา), 'left' (จอซ้าย)",
                    },
                    "monitor_index": {
                        "type": "INTEGER",
                        "description": "หมายเลขจอเป้าหมาย เช่น 1, 2, 3",
                    },
                },
            },
        },
        {
            "name": "drag",
            "description": "ลากเมาส์ (Drag & Drop) จากพิกัดเริ่มต้น (x1, y1) ไปยังพิกัดเป้าหมาย (x2, y2) บนหน้าจอ",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "x1": {"type": "INTEGER", "description": "พิกัดแกน X เริ่มต้น"},
                    "y1": {"type": "INTEGER", "description": "พิกัดแกน Y เริ่มต้น"},
                    "x2": {"type": "INTEGER", "description": "พิกัดแกน X สิ้นสุด"},
                    "y2": {"type": "INTEGER", "description": "พิกัดแกน Y สิ้นสุด"},
                    "duration_ms": {
                        "type": "INTEGER",
                        "description": "ระยะเวลาในการลากหน่วยมิลลิวินาที (ค่าเริ่มต้น 200)",
                    },
                },
                "required": ["x1", "y1", "x2", "y2"],
            },
        },
    ]

    @classmethod
    def get_tool_definitions(cls) -> list[dict[str, Any]]:
        """คืนค่า Function Declarations สำหรับกำหนดใน LiveConnectConfig"""
        return [{"function_declarations": cls.DESKTOP_TOOL_DECLARATIONS}]

    def __init__(self, core: Any | None = None) -> None:
        self.core = core
        from actions.desktop import WindowController, MouseKeyboardController
        self.win_controller = WindowController()
        self.mk_controller = MouseKeyboardController()
        self.memory = None
        if self.core and hasattr(self.core, "memory") and self.core.memory:
            self.memory = self.core.memory
        else:
            try:
                from memory.store import AthenaMemory
                self.memory = AthenaMemory()
            except Exception:
                pass

    def minimize(self, title: str = "") -> str:
        return self.win_controller.minimize_window(title)

    def maximize(self, title: str = "") -> str:
        return self.win_controller.maximize_window(title)

    def restore(self, title: str = "") -> str:
        return self.win_controller.restore_window(title)

    def list_windows(self, query: str = "") -> str:
        wins = self.win_controller.list_windows()
        q = (query or "").strip().lower()
        if q:
            wins = [w for w in wins if q in w["title"].lower() or q in w.get("process_name", "").lower()]
        if not wins:
            return f"ไม่พบหน้าต่างที่ตรงกับ '{query}' ค่ะ" if q else "ขณะนี้ไม่พบหน้าต่างเปิดใช้งานอยู่ค่ะ"
        summary_lines = [f"- '{w['title']}' (PID {w['pid']}, {w.get('process_name', '')})" for w in wins[:10]]
        return f"พบหน้าต่างเปิดอยู่ {len(wins)} รายการค่ะ:\n" + "\n".join(summary_lines)

    def verify_window_state(self, target: str = "") -> str:
        res = self.win_controller.verify_window_state(target)
        return res.get("message", f"ตรวจสถานะ '{target}' เรียบร้อยค่ะ")

    def open_app(self, name: str) -> str:
        return self.win_controller.open_app(name)

    def close_app(self, name: str) -> str:
        return self.win_controller.close_app(name)

    def open_url(self, url: str) -> str:
        return self.win_controller.open_url(url)

    def click_element(self, target: str, button: str = "left", clicks: int = 1) -> str:
        return self.mk_controller.click_element(target, button=button, clicks=clicks)

    def click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        clicks: int = 1,
    ) -> str:
        return self.mk_controller.click(x=x, y=y, button=button, clicks=clicks)

    def move(self, x: int, y: int, duration_ms: int = 200) -> str:
        return self.mk_controller.move(x=x, y=y, duration=duration_ms)

    def scroll(self, clicks: int = -3) -> str:
        return self.mk_controller.scroll(clicks=clicks)

    def type_text(self, text: str, target_window: str = "") -> str:
        return self.mk_controller.type_text(text=text, target_window=target_window)

    def move_window_to_monitor(self, title: str = "", direction: str = "right", monitor_index: int | None = None) -> str:
        return self.win_controller.move_window_to_monitor(target=title, direction=direction, monitor_index=monitor_index)

    def drag_window(self, title: str = "", direction: str = "right", monitor_index: int | None = None) -> str:
        return self.mk_controller.drag_window(target=title, direction=direction, monitor_index=monitor_index)

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 200) -> str:
        return self.mk_controller.drag(x1=x1, y1=y1, x2=x2, y2=y2, duration_ms=duration_ms)

    def see_screen(self, query: str = "") -> str:
        from vision.screen import ScreenObserver
        return ScreenObserver.describe_screen(query)

    def _run_antigravity(self, prompt: str, confirmed: bool = False) -> str:
        if self.core:
            return self.core.delegate_to_antigravity(prompt, confirmed=confirmed)
        agy_path = r"C:\Users\BUSOLOVE\AppData\Local\agy\bin\agy.exe"
        if not os.path.exists(agy_path):
            return "ไม่พบโปรแกรม Antigravity CLI (agy.exe) ในระบบค่ะ"
        try:
            cmd = [agy_path, "-p", prompt, "--dangerously-skip-permissions"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                encoding="utf-8",
                errors="replace",
            )
            out = result.stdout.strip()
            if result.returncode != 0 and not out:
                err = result.stderr.strip()
                return f"Antigravity CLI ทำงานขัดข้อง (code {result.returncode}): {err}"
            return out or "Antigravity CLI ดำเนินการเรียบร้อยแล้วค่ะ"
        except subprocess.TimeoutExpired:
            return "Antigravity CLI ใช้เวลาประมวลผลนานเกินกำหนดค่ะ (Timeout)"
        except Exception as exc:
            return f"เกิดข้อผิดพลาดในการเรียก Antigravity CLI: {exc}"

    def _run_ufo(self, task: str) -> str:
        if self.core:
            return self.core.delegate_to_ufo(task)
        ufo_python = r"E:\ufo\.venv\Scripts\python.exe"
        ufo_dir = r"E:\ufo"
        if not os.path.exists(ufo_python):
            return "ไม่พบสภาพแวดล้อมเสมือนของ Microsoft UFO (E:\\ufo\\.venv) ค่ะ"
        try:
            cmd = [ufo_python, "-m", "ufo", "--task", "athena_ufo_task", "--request", task]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                encoding="utf-8",
                errors="replace",
                cwd=ufo_dir,
            )
            out = result.stdout.strip()
            if result.returncode != 0 and not out:
                err = result.stderr.strip()
                return f"Microsoft UFO ทำงานขัดข้อง (code {result.returncode}): {err}"
            return out or f"Microsoft UFO ดำเนินการงาน '{task}' สำเร็จค่ะ"
        except subprocess.TimeoutExpired:
            return "Microsoft UFO ใช้เวลาทำงานนานเกินกำหนดค่ะ (Timeout)"
        except Exception as exc:
            return f"เกิดข้อผิดพลาดในการเรียก Microsoft UFO: {exc}"

    def _run_executive_action(self, command: str) -> str:
        """ส่งคำสั่งซับซ้อนหลายขั้นตอนให้ Antigravity Supervisor วางแผนและตรวจงานจริง"""
        if self.core and getattr(self.core, "supervisor", None):
            return self.core.supervisor.execute_task(command)
        from brain.supervisor import AntigravitySupervisor
        supervisor = AntigravitySupervisor(core=self.core)
        return supervisor.execute_task(command)

    def remember(self, key: str, value: str, category: str = "general") -> str:
        """บันทึกข้อมูลความจำ"""
        if self.core:
            return self.core.execute_tool("remember", {"key": key, "value": value, "category": category})
        if self.memory:
            return self.memory.remember(key, value, category)
        return f"เอเธน่าบันทึกข้อมูล '{key}': '{value}' เรียบร้อยแล้วค่ะ"

    def recall(self, query: str = "") -> str:
        """ค้นหาข้อมูลในความจำ"""
        if self.core:
            return self.core.execute_tool("recall", {"query": query})
        if self.memory:
            return self.memory.recall(query)
        return "ไม่พบข้อมูลในความจำค่ะ"

    def forget(self, key: str) -> str:
        """ลบข้อมูลความจำ"""
        if self.core:
            return self.core.execute_tool("forget", {"key": key})
        if self.memory:
            return self.memory.forget(key)
        return f"เอเธน่าลบข้อมูลเกี่ยวกับ '{key}' ออกจากความจำเรียบร้อยแล้วค่ะ"

    # ── Tool Dispatcher ──────────────────────────────────────────────────

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """รันฟังก์ชัน Desktop ใน worker thread เพื่อไม่บล็อก async event loop"""
        handler_map = {
            "minimize": lambda: self.minimize(title=str(arguments.get("title", ""))),
            "maximize": lambda: self.maximize(title=str(arguments.get("title", ""))),
            "restore": lambda: self.restore(title=str(arguments.get("title", ""))),
            "list_windows": lambda: self.list_windows(query=str(arguments.get("query", ""))),
            "verify_window_state": lambda: self.verify_window_state(target=str(arguments.get("target", ""))),
            "click_element": lambda: self.click_element(
                target=str(arguments.get("target", "")),
                button=str(arguments.get("button", "left")),
                clicks=int(arguments.get("clicks", 1)),
            ),
            "see_screen": lambda: self.see_screen(query=str(arguments.get("query", ""))),
            "open_url": lambda: self.open_url(url=str(arguments.get("url", ""))),
            "scroll": lambda: self.scroll(clicks=int(arguments.get("clicks", -3))),
            "click": lambda: self.click(
                x=arguments.get("x"),
                y=arguments.get("y"),
                button=str(arguments.get("button", "left")),
                clicks=int(arguments.get("clicks", 1)),
            ),
            "move": lambda: self.move(
                x=int(arguments.get("x", 0)),
                y=int(arguments.get("y", 0)),
                duration_ms=int(arguments.get("duration_ms", 200)),
            ),
            "drag": lambda: self.drag(
                x1=int(arguments.get("x1", 0)),
                y1=int(arguments.get("y1", 0)),
                x2=int(arguments.get("x2", 0)),
                y2=int(arguments.get("y2", 0)),
                duration_ms=int(arguments.get("duration_ms", 200)),
            ),
            "move_window_to_monitor": lambda: self.move_window_to_monitor(
                title=str(arguments.get("title", "")),
                direction=str(arguments.get("direction", "right")),
                monitor_index=int(arguments["monitor_index"]) if arguments.get("monitor_index") is not None else None,
            ),
            "drag_window": lambda: self.drag_window(
                title=str(arguments.get("title", "")),
                direction=str(arguments.get("direction", "right")),
                monitor_index=int(arguments["monitor_index"]) if arguments.get("monitor_index") is not None else None,
            ),
            "type": lambda: self.type_text(
                text=str(arguments.get("text", "")),
                target_window=str(arguments.get("target_window", "")),
            ),
            "open_app": lambda: self.open_app(name=str(arguments.get("name", ""))),
            "close_app": lambda: self.close_app(name=str(arguments.get("name", ""))),
            "delegate_to_antigravity": lambda: self._run_antigravity(
                prompt=str(arguments.get("prompt", "")),
                confirmed=bool(arguments.get("confirmed", False)),
            ),
            "delegate_to_ufo": lambda: self._run_ufo(task=str(arguments.get("task", ""))),
            "executive_action": lambda: self._run_executive_action(command=str(arguments.get("command", ""))),
            "remember": lambda: self.remember(
                key=str(arguments.get("key", "")),
                value=str(arguments.get("value", "")),
                category=str(arguments.get("category", "general")),
            ),
            "recall": lambda: self.recall(query=str(arguments.get("query", ""))),
            "forget": lambda: self.forget(key=str(arguments.get("key", ""))),
        }

        func = handler_map.get(tool_name)
        if not func:
            return f"ไม่พบฟังก์ชัน '{tool_name}' ในระบบ Desktop ค่ะ"

        try:
            return await asyncio.to_thread(func)
        except Exception as exc:
            logger.exception("Error executing tool %s: %s", tool_name, exc)
            return f"เกิดข้อผิดพลาดในการทำงานของ {tool_name}: {exc}"


# ─────────────────────────────────────────────────────────────────────────────
# Audio Stream Manager
# ─────────────────────────────────────────────────────────────────────────────

class AudioStreamManager:
    """
    จัดการ Audio Streams (Microphone PCM 16kHz และ Speaker PCM 24kHz)
    ผ่าน sounddevice พร้อมคิวส่งเสียงและระบบตัดเสียงพูดทันทีเมื่อผู้ใช้พูดแทรก
    """

    def __init__(self, input_sample_rate: int = 16_000, output_sample_rate: int = 24_000) -> None:
        self.input_sample_rate = input_sample_rate
        self.output_sample_rate = output_sample_rate
        self.input_stream: sd.RawInputStream | None = None
        self.output_stream: sd.RawOutputStream | None = None
        self.mic_queue: queue.Queue[bytes] = queue.Queue(maxsize=64)
        self.speaker_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._is_active = False
        self.is_speaker_playing = False
        self.last_speaker_time = 0.0

    def start(self) -> None:
        """เปิดและเริ่มสตรีมเสียงไมค์และลำโพง"""
        if self._is_active:
            return

        def _mic_callback(indata: bytes, frames: int, time_info: Any, status: sd.CallbackFlags) -> None:
            if not self._is_active or not indata:
                return
            try:
                self.mic_queue.put_nowait(bytes(indata))
            except queue.Full:
                try:
                    self.mic_queue.get_nowait()
                    self.mic_queue.put_nowait(bytes(indata))
                except queue.Empty:
                    pass

        try:
            self.input_stream = sd.RawInputStream(
                samplerate=self.input_sample_rate,
                channels=1,
                dtype="int16",
                blocksize=1024,
                callback=_mic_callback,
            )
            self.output_stream = sd.RawOutputStream(
                samplerate=self.output_sample_rate,
                channels=1,
                dtype="int16",
                blocksize=2048,
            )
            self.input_stream.start()
            self.output_stream.start()
            self._is_active = True
            logger.info("Audio streams opened successfully (Mic: %dHz, Spk: %dHz)", self.input_sample_rate, self.output_sample_rate)
        except Exception as exc:
            self.stop()
            raise RuntimeError(f"ไม่สามารถเปิด audio stream ได้: {exc}") from exc

    def stop(self) -> None:
        """ปิด audio streams ทั้งหมด"""
        self._is_active = False
        for stream in (self.input_stream, self.output_stream):
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception as exc:
                    logger.debug("Closing stream warning: %s", exc)
        self.input_stream = None
        self.output_stream = None
        self.clear_speaker_queue()
        logger.info("Audio streams closed.")

    def clear_speaker_queue(self) -> None:
        """ล้างคิวเสียงที่ค้างอยู่ (ใช้เมื่อตรวจจับการพูดแทรก / Interruption)"""
        while not self.speaker_queue.empty():
            try:
                self.speaker_queue.get_nowait()
            except asyncio.QueueEmpty:
                break


# ─────────────────────────────────────────────────────────────────────────────
# Athena Live Stream Session
# ─────────────────────────────────────────────────────────────────────────────

ATHENA_SYSTEM_PROMPT = """คุณคือ 'เอเธน่า' (Athena) เลขานุการและผู้ช่วยส่วนตัวระดับบริหารประจำโต๊ะทำงานของบอส (Boss)
บุคลิกและน้ำเสียง: หญิงสาวฉลาด คล่องแคล่ว มีไหวพริบ มั่นใจ ชัดเจน และสุภาพแบบเลขาธิการบริหาร (Executive Personal Secretary) พูดจาฉะฉาน เป็นมิตร มั่นใจ เด็ดขาด ไม่ใช้น้ำเสียงหวานเลี่ยนหรือหุ่นยนต์
กฎการสื่อสารและการปฏิบัติงานที่ต้องปฏิบัติตามอย่างเคร่งครัด:
1. ลงท้ายประโยคด้วยคำว่า "ค่ะ" เสมอ (ห้ามใช้ "ครับ" หรือสำเนียงผู้ชายเด็ดขาด)
2. พูดภาษาไทยอย่างเป็นธรรมชาติ กระชับ ตรงประเด็น ไม่พูดเยิ่นเย้อ และไม่ขอโทษ (No apologies)
3. Action-First: ควบคุมคอมพิวเตอร์และตอบสนองตามคำสั่งบอสทันที:
   - สั่งให้จำข้อมูล จดบันทึก หรือบันทึกความจำ (เช่น 'จำไว้ว่า...', 'จดไว้ว่า...', 'บันทึกว่า...') ให้เรียก remember(key="...", value="...") ทันที
   - สั่งให้ค้นหาความจำ ถามถึงข้อมูลที่เคยบันทึก หรือถามความจำ (เช่น 'จำได้ไหมว่า...', 'ไฟล์งานอยู่ที่ไหนนะ...', 'เคยบอกว่าอะไร...') ให้เรียก recall(query="...") ทันที
   - สั่งให้ลบความจำ (เช่น 'ลบความจำเรื่อง...', 'ไม่ต้องจำเรื่อง...แล้ว') ให้เรียก forget(key="...") ทันที
   - สลับไปโปรแกรม หรือดึงหน้าต่างขึ้นมา (เช่น 'ไปที่ Anti-Gravity', 'สลับไป Chrome', 'เปิดหน้าต่าง...') ให้เรียก restore(title="...") ทันที ห้ามใช้ click_element กับชื่อหน้าต่างเพราะช้าและผิดตำแหน่ง
   - สั่งพิมพ์ข้อความในโปรแกรม (เช่น 'ที่โปรแกรม Notepad พิมพ์ข้อความว่า...') ให้เรียก type(text="...", target_window="notepad") ทันที เพื่อดึงหน้าต่างขึ้นมาโฟกัสก่อนพิมพ์
   - สั่งพิมพ์ข้อความทั่วไป (เช่น 'พิมพ์ว่า...') ให้เรียก type(text="...") ทันที
   - สั่งย่อหน้าต่าง หรือพับจอ (เช่น 'ย่อหน้าต่าง', 'พับจอลงมา', 'ย่อ Chrome', 'เอาหน้าต่างลงมา') ให้เรียก minimize(title="...") ห้ามเรียก scroll เด็ดขาด
   - สั่งเลื่อนลูกกลิ้งเมาส์ดูเนื้อหา (เช่น 'เลื่อนจอลง', 'เลื่อนขึ้น') ให้เรียก scroll(clicks=...)
   - สั่งคลิกปุ่ม ลิงก์ ไอคอน หรือช่องพิมพ์บนหน้าจอ (เช่น 'ปุ่มค้นหา', 'ไอคอน Chrome', 'ช่องพิมพ์') ให้เรียก click_element(target="...")
   - สั่งตรวจสอบว่ามีโปรแกรมอะไรเปิดอยู่ หรือถามว่าหน้าต่างเปิดอยู่ไหม ให้เรียก list_windows(query="...") หรือ verify_window_state(target="...") เพื่อตรวจสถานะจริง
   - สั่งมองดู ตรวจสอบ หรือถามเกี่ยวกับสิ่งที่ปรากฏบนหน้าจอ ให้เรียก see_screen(query="...")
   - สั่งเปิดหน้าเว็บ เช่น YouTube หรือเว็บไซต์ต่างๆ ให้เรียก open_url(url="...")
   - สั่งเปิดหรือปิดโปรแกรม ให้เรียก open_app(name="...") หรือ close_app(name="...")
   - สั่งย้ายหน้าต่างข้ามจอ สลับจอ หรือแดรกหน้าต่างไปอีกจอ (เช่น 'ย้ายหน้าต่างนี้ไปจอขวา', 'ย้ายไปจอซ้าย', 'ย้าย Chrome ไปจอ 3', 'แดรกหน้าต่างไปจอข้างๆ', 'ลากไปอีกจอ') ให้เรียก move_window_to_monitor(direction="right"/"left" หรือ monitor_index=...) หรือ drag_window(...) ทันที
   - สั่งลากเมาส์ ลากไฟล์ หรือลากสิ่งของบนจอ (Drag & Drop) ให้เรียก drag(x1=..., y1=..., x2=..., y2=...) ทันที
   - คำสั่งที่มีหลายขั้นตอน ซับซ้อน หรืองานที่ต้องคิดวางแผนและตรวจงานจริง (เช่น เปิดแอปแล้วพิมพ์ข้อความและตรวจสอบสถานะ) ให้เรียก executive_action(command="...") ทันที เพื่อให้สมอง Antigravity Supervisor วางแผนและสั่งการแขนกลอย่างแม่นยำ
   - งานเขียนโค้ด งานรันคำสั่ง Terminal ตรวจสอบโปรเจกต์ หรือสร้าง/แก้โค้ดอัตโนมัติ ให้เรียก delegate_to_antigravity(prompt="...") ทันที
   - งานควบคุม GUI ซับซ้อนหลายขั้นตอน หรือจัดการเอกสาร Office (Excel, Word, PowerPoint) เช่น ใส่สูตรคำนวณ ทำตาราง ให้เรียก delegate_to_ufo(task="...") ทันที
   คุณต้องเรียกใช้ Function Calling / Tools ที่เกี่ยวข้องทันทีโดยไม่ต้องถามยืนยันซ้ำ
4. ไหวพริบสายตาอัตโนมัติ (Autonomous Visual Reflex) - สื่อสารลื่นไหล ไร้คำถามซ้ำซาก:
   - ระบบของเราไม่ดึงภาพหน้าจอต่อเนื่องตลอดเวลาเพื่อรักษาความเสถียรและประหยัดแบนด์วิดท์ แต่เอเธน่าต้องมี 'ไหวพริบสายตาอัตโนมัติ'
   - เมื่อใดก็ตามที่บอสพูดถึงบริบทที่ต้องใช้สายตามอง หรือมีการอ้างอิงตำแหน่ง/สิ่งของบนจอ เช่น:
     * คำระบุตำแหน่ง: 'ตรงนี้', 'ตรงนั้น', 'ปุ่มนี้', 'ข้อความนี้', 'หน้านี้', 'รูปนี้', 'หน้าต่างนี้'
     * คำถามสถานการณ์หน้าจอ: 'ทำไมมันเออเร่อ', 'ทำไมขึ้นแบบนี้', 'เกิดอะไรขึ้น', 'ดูนี่สิ', 'อ่านให้ฟังหน่อย', 'สรุปหน้านี้ให้ที', 'ทำไมมันค้าง', 'เห็นไหม'
     * คำสั่งกระทำบนจอ: 'คลิกให้หน่อย', 'กดตรงนี้', 'ปิดหน้านี้ให้ที'
   - เอเธน่าต้องตัดสินใจแอบเรียก see_screen(query="...") หรือ click_element(target="...") ทันทีในเบื้องหลังด้วยตัวเอง
   - ห้ามรอให้บอสพูดคำว่า 'เอเธน่าดูหน้าจอหน่อย' เด็ดขาด
   - ห้ามถามคำถามขออนุญาต เช่น 'ให้เอเธน่าดูหน้าจอไหมคะ' หรือ 'ต้องการให้ตรวจดูหน้าจอไหมคะ' เด็ดขาด ให้ใช้สายตาดูหน้าจอทันที!
5. มองแบบสายตามนุษย์ (Human-Eye Perception) - ไม่พูดแบบหุ่นยนต์/Process:
   - มองและอธิบายหน้าจอเสมือนเป็นเลขานุการส่วนตัวที่ยืนอยู่ข้างบอสและมองไปยังจอมอนิเตอร์
   - รายงานเฉพาะสิ่งที่สายตามนุษย์มองเห็นจริงบนจอภาพ เช่น:
     * "หน้าต่างโปรแกรมเปิดขึ้นมาเต็มจอด้านขวาแล้วค่ะ"
     * "มีกล่องข้อความเตือนสีแดงว่าเชื่อมต่อล้มเหลวขึ้นมากลางจอค่ะ"
     * "มีปุ่มสีฟ้าเขียนว่ายืนยันอยู่ด้านล่างขวาค่ะ"
     * "โปรแกรมกำลังโหลดขึ้นมาแสดงผลบนหน้าจอค่ะ"
   - ห้ามรายงานแบบหุ่นยนต์หรือช่างเทคนิคหลังบ้านเด็ดขาด: ห้ามพูดถึง PID (เช่น PID 1234), HWND, Process ID, Process Name, Window Handle หรือสถานะโค้ดรัน
6. กฎการตรวจสอบผลลัพธ์จริง (Closed-Loop Real-World Verification) - สำคัญสูงสุด:
   - ห้ามเดา หรือสรุปว่างานสำเร็จล่วงหน้าเด็ดขาด
   - อ่านและสรุปรายงานตามข้อเท็จจริงที่เครื่องมือ (Tool) ส่งกลับมาเสมอ
   - หากผลลัพธ์แจ้งว่าตรวจพบหน้าต่างจริงหรือทำสำเร็จ ให้รายงานตามนั้น เช่น "เปิดโปรแกรม Notepad และตรวจสอบพบหน้าต่างพร้อมใช้งานแล้วค่ะบอส"
   - หากผลลัพธ์แจ้งว่าไม่พบหน้าต่าง หรือเกิดปัญหา ห้ามบอกว่าเรียบร้อยเด็ดขาด ให้รายงานปัญหาตามตรง เช่น "สั่งเปิดแล้ว แต่ยังไม่พบหน้าต่างขึ้นบนจอค่ะบอส"
   - ห้ามจินตนาการผลลัพธ์ล่วงหน้าเด็ดขาด รายงานเฉพาะความจริงที่ตรวจพบเท่านั้น
7. กฎห้ามถามคำถามปิดท้ายเด็ดขาด (Strict Zero-Trailing-Questions Rule):
   - รายงานเฉพาะข้อเท็จจริงที่ทำเสร็จแล้วจบประโยคทันที ห้ามมีประโยคคำถามหรือคำถามเซ้าซี้ปิดท้ายเด็ดขาด เช่น 'ต้องการให้ช่วยอะไรเพิ่มไหมคะ', 'มีอะไรให้ทำต่อไหมคะ', 'แจ้งได้เลยนะคะ', 'ต้องการให้เปิดให้อีกรอบไหมคะ', 'ให้ดูหน้าจอไหมคะ'
"""


class AthenaLiveStream:
    """
    Real-time Live Stream Voice Controller สำหรับ Athena
    จัดการการสื่อสารเสียงสองทางกับ Gemini Live API พร้อมการเรียกใช้งาน Desktop Tools
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        voice_name: str | None = None,
        core: Any | None = None,
    ) -> None:
        self.api_key = api_key or Config.GEMINI_API_KEY
        self.model = model or Config.LIVE_VOICE_MODEL
        self.voice_name = voice_name or Config.VOICE_NAME
        self.core = core
        self.desktop_tools = DesktopTools(core=core)
        self.audio_manager = AudioStreamManager()
        self._client: genai.Client | None = None
        self._is_running = False
        self._is_tool_running = False
        self._reconnect_requested = False
        self._tasks: list[asyncio.Task[Any]] = []

    def _get_live_config(self) -> types.LiveConnectConfig:
        """สร้างการตั้งค่า Live Session พร้อม Tools และ System Instruction"""
        instruction_text = ATHENA_SYSTEM_PROMPT
        if self.core and hasattr(self.core, "get_memory_summary"):
            mem_summary = self.core.get_memory_summary()
            if mem_summary:
                instruction_text += f"\n\n[ฐานความจำสำคัญของบอส]:\n{mem_summary}"

        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.voice_name
                    )
                )
            ),
            system_instruction=types.Content(
                parts=[types.Part.from_text(text=instruction_text)]
            ),
            tools=self.desktop_tools.get_tool_definitions(),
            input_audio_transcription=types.AudioTranscriptionConfig(
                language_codes=["th-TH", "th"]
            ),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

    async def _send_audio_loop(self, session: Any) -> None:
        """อ่านข้อมูลเสียงไมค์จากคิวแล้วส่งไปยัง Gemini Live API"""
        logger.info("Microphone audio sender loop started.")
        try:
            while self._is_running:
                data = await asyncio.to_thread(self.audio_manager.mic_queue.get)
                if not data or not self._is_running:
                    continue

                # Echo & Tool Feedback Prevention: ระงับการส่งเสียงไมค์หาก:
                # 1. ลำโพงกำลังเล่นเสียงอยู่
                # 2. ลำโพงเพิ่งเล่นจบไปไม่ถึง 0.35 วินาที (ป้องกันเสียงสะท้อนตกค้างในห้อง)
                # 3. กำลังอยู่ระหว่างรัน Tool Call (ป้องกันเสียงรบกวนเข้าไปตัดรอบ ToolResponse)
                now = time.time()
                if (
                    self.audio_manager.is_speaker_playing
                    or (now - self.audio_manager.last_speaker_time < 0.35)
                    or self._is_tool_running
                ):
                    continue

                try:
                    blob = types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                    await session.send_realtime_input(audio=blob)
                except Exception as exc:
                    if not self._is_running:
                        break
                    logger.warning("Transient error sending mic audio: %s", exc)
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Fatal error in mic sender loop: %s", exc)

    async def _playback_loop(self) -> None:
        """ดึงข้อมูลเสียงจากคิวส่งออกไปเล่นที่ลำโพง"""
        logger.info("Speaker audio playback loop started.")
        try:
            while self._is_running:
                chunk = await self.audio_manager.speaker_queue.get()
                if chunk and self._is_running and self.audio_manager.output_stream:
                    try:
                        self.audio_manager.is_speaker_playing = True
                        self.audio_manager.last_speaker_time = time.time()
                        await asyncio.to_thread(self.audio_manager.output_stream.write, chunk)
                        self.audio_manager.last_speaker_time = time.time()
                    except Exception as exc:
                        if not self._is_running:
                            break
                        logger.warning("Warning during speaker playback: %s", exc)
                    finally:
                        self.audio_manager.is_speaker_playing = False
                        self.audio_manager.last_speaker_time = time.time()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Error in speaker playback loop: %s", exc)

    async def _send_screen_loop(self, session: Any) -> None:
        """จับภาพหน้าจอส่งเข้า Gemini Live API เป็นระยะ (Periodic Vision Ingestion) เพื่อให้สมองมองเห็นสถานการณ์ตลอดเวลา"""
        import io
        from PIL import Image
        import mss

        logger.info("Periodic screen stream loop started.")
        try:
            with mss.mss() as sct:
                while self._is_running:
                    await asyncio.sleep(3.5)
                    if not self._is_running:
                        break

                    # ถ้าลำโพงกำลังเล่นเสียง หรือกำลังรัน Tool ให้ข้ามรอบนี้
                    if self.audio_manager.is_speaker_playing or self._is_tool_running:
                        continue

                    try:
                        monitor = sct.monitors[1]  # หน้าจอหลัก
                        sct_img = sct.grab(monitor)
                        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

                        # ปรับขนาดย่อลงเพื่อประหยัด bandwidth (ความกว้างสูงสุด 1024px)
                        max_w = 1024
                        if img.width > max_w:
                            scale = max_w / img.width
                            new_h = int(img.height * scale)
                            img = img.resize((max_w, new_h), Image.Resampling.LANCZOS)

                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=65)
                        jpeg_bytes = buf.getvalue()

                        video_blob = types.Blob(data=jpeg_bytes, mime_type="image/jpeg")
                        await session.send_realtime_input(video=video_blob)
                        logger.debug("Sent periodic screen frame (%d bytes) to Gemini Live", len(jpeg_bytes))
                    except Exception as exc:
                        logger.debug("Transient error in screen loop: %s", exc)
                        await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Fatal error in screen stream loop: %s", exc)

    async def _receive_loop(self, session: Any) -> None:
        """รับการตอบกลับจาก Gemini Live ตลอดอายุเซสชัน (รองรับบทสนทนาหลายรอบ / Multi-turn)"""
        logger.info("Live receiver loop started.")
        try:
            while self._is_running:
                async for response in session.receive():
                    if not self._is_running:
                        break

                    # 1. จัดการ Server Content (เสียงสังเคราะห์, คำถอดความ, Interruption)
                    server_content = response.server_content
                    if server_content:
                        # ถ้าผู้ใช้พูดแทรกขณะที่ลำโพงกำลังเล่นเสียงออกจริงๆ ให้ล้างคิวเสียงลำโพงทันที
                        if getattr(server_content, "interrupted", False):
                            if self.audio_manager.is_speaker_playing:
                                logger.info("User interrupted speech. Flushing speaker queue.")
                                self.audio_manager.clear_speaker_queue()

                        # รับข้อมูลเสียง PCM 24kHz
                        if server_content.model_turn and server_content.model_turn.parts:
                            for part in server_content.model_turn.parts:
                                if part.inline_data and part.inline_data.data:
                                    await self.audio_manager.speaker_queue.put(part.inline_data.data)

                        # แสดง Transcription สำหรับดีบักหรือติดตามการสนทนา
                        if server_content.input_transcription and server_content.input_transcription.text:
                            logger.info("Boss said: %s", server_content.input_transcription.text.strip())

                        if server_content.output_transcription and server_content.output_transcription.text:
                            logger.info("Athena replied: %s", server_content.output_transcription.text.strip())

                    # 2. จัดการ Tool Call จากโมเดล
                    tool_call = response.tool_call
                    if tool_call and tool_call.function_calls:
                        self._is_tool_running = True
                        try:
                            function_responses: list[types.FunctionResponse] = []
                            for fc in tool_call.function_calls:
                                logger.info("Gemini Live requested tool: %s (args=%s, id=%s)", fc.name, fc.args, fc.id)
                                # รันฟังก์ชัน Desktop
                                if self.core:
                                    args = dict(fc.args or {})
                                    if "title" in args and "target" not in args:
                                        args["target"] = args["title"]
                                    result = await asyncio.to_thread(self.core.execute_tool, fc.name, args)
                                else:
                                    result = await self.desktop_tools.execute(fc.name, fc.args or {})
                                logger.info("Tool %s executed: %s", fc.name, result)
                                function_responses.append(
                                    types.FunctionResponse(
                                        name=fc.name,
                                        response={"result": result},
                                        id=fc.id,
                                    )
                                )

                            # ส่ง ToolResponse กลับเข้าห้อง Live Session ทันที
                            if function_responses:
                                logger.info("Sending %d ToolResponse(s) back to Gemini Live.", len(function_responses))
                                await session.send_tool_response(function_responses=function_responses)
                        finally:
                            # รอสั้นๆ ให้โมเดลรับผลลัพธ์และเริ่มส่งเสียงตอบกลับ
                            await asyncio.sleep(0.15)
                            self._is_tool_running = False

                    # 3. ตรวจจับสัญญาณเตือน GoAway จากเซิร์ฟเวอร์ (แจ้งหมดเวลาล่วงหน้า)
                    go_away = getattr(response, "go_away", None)
                    if go_away:
                        time_left = getattr(go_away, "time_left", None)
                        logger.warning("Google sent GoAway signal (time_left=%s). Preparing graceful reconnection.", time_left)
                        self._reconnect_requested = True
                        break

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Error in live receiver loop: %s", exc)

    async def start(self) -> None:
        """เชื่อมต่อและเริ่มทำงาน Real-time Live Session (Pure Audio 15 นาที + Auto-Reconnect)"""
        if self._is_running:
            return

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY ไม่ได้กำหนดใน Environment หรือ Config")

        self._client = genai.Client(api_key=self.api_key)
        self.audio_manager.start()
        self._is_running = True
        reconnect_attempts = 0
        is_first_connection = True

        try:
            while self._is_running:
                config = self._get_live_config()
                logger.info("Connecting to Gemini Live API (%s)...", self.model)
                self._reconnect_requested = False

                try:
                    async with self._client.aio.live.connect(model=self.model, config=config) as session:
                        logger.info("Connected to Gemini Live Session successfully (Pure Audio Mode)!")
                        reconnect_attempts = 0

                        # สตรีมไมค์, ลำโพง, และการรับข้อมูลคู่ขนาน
                        # ตัด Background Screen Loop ออกเพื่อให้เป็น Pure Audio รองรับ 15 นาทีเต็ม (ดูจอแบบ On-Demand ผ่าน see_screen)
                        sender_task = asyncio.create_task(self._send_audio_loop(session))
                        receiver_task = asyncio.create_task(self._receive_loop(session))
                        playback_task = asyncio.create_task(self._playback_loop())
                        self._tasks = [sender_task, receiver_task, playback_task]

                        # ส่งคำทักทายเฉพาะการเปิดใช้งานครั้งแรกเท่านั้น (Reconnect จะไม่ทักทายซ้ำ)
                        if is_first_connection:
                            greeting_prompt = "[คำสั่งระบบ]: ทักทายบอสสั้นๆ เป็นภาษาไทย เช่น 'สวัสดีค่ะบอส เอเธน่าพร้อมแล้วค่ะ' แล้วรอฟังคำสั่ง"
                            await session.send_realtime_input(text=greeting_prompt)
                            is_first_connection = False

                        # ทำงานจนกว่าจะมี Task สิ้นสุด
                        done, pending = await asyncio.wait(
                            [sender_task, receiver_task],
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        for task in pending:
                            task.cancel()
                        for task in done:
                            if not task.cancelled() and task.exception():
                                raise task.exception()

                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    reconnect_attempts += 1
                    logger.warning("Gemini Live session ended (%s). Reconnect attempt %d...", exc, reconnect_attempts)
                    if not self._is_running:
                        break
                    delay = min(1.0 * (1.5 ** (reconnect_attempts - 1)), 10.0)
                    await asyncio.sleep(delay)
                else:
                    if self._reconnect_requested and self._is_running:
                        logger.info("Graceful reconnecting to fresh session...")
                        await asyncio.sleep(0.3)
        finally:
            await self.stop()

    async def stop(self) -> None:
        """หยุดการทำงานและคืนทรัพยากรทั้งหมด"""
        self._is_running = False
        for task in self._tasks:
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
        self.audio_manager.stop()
        logger.info("Athena Live Stream stopped.")


# ─────────────────────────────────────────────────────────────────────────────
# CLI Entry Point
# ─────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    print("=" * 60)
    print("  Athena Real-time Voice & Live Stream Assistant")
    print("  Model :", Config.LIVE_VOICE_MODEL)
    print("  Voice :", Config.VOICE_NAME)
    print("=" * 60)
    print("กด Ctrl+C เพื่อหยุดการทำงาน\n")

    assistant = AthenaLiveStream()
    try:
        await assistant.start()
    except KeyboardInterrupt:
        print("\nหยุดการทำงานโดยผู้ใช้")
    except Exception as err:
        print(f"\nเกิดข้อผิดพลาด: {err}")
    finally:
        await assistant.stop()


# Alias สำหรับการเรียกใช้แบบย่อ
AthenaLiveVoice = AthenaLiveStream


if __name__ == "__main__":
    asyncio.run(main())
