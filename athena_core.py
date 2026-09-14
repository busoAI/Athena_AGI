"""
athena_core.py
Athena Project — Central Core & Orchestrator
รวมศูนย์การทำงานระหว่าง สายตา (Vision), มือ (Actions), และ เสียง (Voice Live) เข้าด้วยกัน
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# เพิ่ม path ให้สามารถเรียกโมดูลภายในได้
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Config


class AthenaCore:
    """แกนหลักของ Athena ทำหน้าที่เป็นสมองสั่งการและประสานงานทุกระบบ"""

    def __init__(self) -> None:
        self.config = Config()
        self._running = False

        # โมดูลระบบ (Lazy initialize)
        self.win_controller = None
        self.mouse_controller = None
        self.screen_observer = None
        self.voice_stream = None
        self.supervisor = None
        self.memory = None

    def initialize_subsystems(self) -> None:
        """โหลดโมดูล OS, Vision, Action, Memory และ Supervisor เข้าสู่ระบบ"""
        try:
            from actions.desktop import WindowController, MouseKeyboardController
            self.win_controller = WindowController()
            self.mouse_controller = MouseKeyboardController()
        except ImportError as exc:
            print(f"[Core] คำเตือน: ยังไม่พบ actions.desktop ({exc})")

        try:
            from vision.screen import ScreenObserver
            self.screen_observer = ScreenObserver()
        except ImportError as exc:
            print(f"[Core] คำเตือน: ยังไม่พบ vision.screen ({exc})")

        try:
            from memory.store import AthenaMemory
            self.memory = AthenaMemory()
        except Exception as exc:
            print(f"[Core] คำเตือน: โหลด memory.store ({exc})")

        try:
            from brain.supervisor import AntigravitySupervisor
            self.supervisor = AntigravitySupervisor(core=self)
        except Exception as exc:
            print(f"[Core] คำเตือน: โหลด brain.supervisor ({exc})")

    def execute_tool(self, name: str, args: dict[str, Any]) -> str:
        """รันคำสั่งควบคุมคอมพิวเตอร์และคืนค่าผลลัพธ์ที่เป็นธรรมชาติ"""
        print(f"\n[Athena Action] เรียกใช้: {name} {args}")

        try:
            # 1. จัดการหน้าต่าง Windows
            if name in {"win_minimize", "minimize_window", "minimize"}:
                target = args.get("target", "") or args.get("title", "")
                if self.win_controller:
                    return self.win_controller.minimize_window(target)
                return "ย่อหน้าต่างสำเร็จค่ะ"

            elif name in {"win_maximize", "maximize_window", "maximize"}:
                target = args.get("target", "") or args.get("title", "")
                if self.win_controller:
                    return self.win_controller.maximize_window(target)
                return "ขยายหน้าต่างเต็มจอสำเร็จค่ะ"

            elif name in {"win_restore", "restore_window", "restore", "focus", "focus_window"}:
                target = args.get("target", "") or args.get("title", "")
                if self.win_controller:
                    return self.win_controller.restore_window(target)
                return "คืนขนาดหน้าต่างสำเร็จค่ะ"

            elif name in {"open_app", "launch_app"}:
                app_name = args.get("name", "") or args.get("app_name", "")
                if self.win_controller:
                    return self.win_controller.open_app(app_name)
                return f"กำลังเปิด {app_name} ค่ะ"

            elif name in {"close_app", "kill_app"}:
                app_name = args.get("name", "") or args.get("app_name", "")
                if self.win_controller:
                    return self.win_controller.close_app(app_name)
                return f"ปิด {app_name} เรียบร้อยค่ะ"

            elif name in {"list_windows", "get_windows"}:
                query = args.get("query", "") or args.get("target", "")
                if self.win_controller:
                    wins = self.win_controller.list_windows()
                    q = query.strip().lower()
                    if q:
                        wins = [w for w in wins if q in w["title"].lower() or q in w.get("process_name", "").lower()]
                    if not wins:
                        return f"ไม่พบหน้าต่างที่ตรงกับ '{query}' ค่ะ" if q else "ขณะนี้ไม่พบหน้าต่างเปิดใช้งานอยู่ค่ะ"
                    summary_lines = [f"- {w['title']}" for w in wins[:10]]
                    return f"พบหน้าต่างเปิดอยู่บนหน้าจอ {len(wins)} รายการค่ะ:\n" + "\n".join(summary_lines)
                return "ไม่สามารถดึงรายการหน้าต่างได้ค่ะ"

            elif name in {"verify_window_state", "check_window"}:
                target = args.get("target", "") or args.get("title", "") or args.get("name", "")
                if self.win_controller:
                    res = self.win_controller.verify_window_state(target)
                    return res.get("message", f"ตรวจสอบสถานะหน้าต่าง '{target}' เรียบร้อยค่ะ")
                return f"ตรวจสอบสถานะหน้าต่าง '{target}' เรียบร้อยค่ะ"

            elif name in {"move_window_to_monitor", "move_window", "drag_window"}:
                target = args.get("target", "") or args.get("title", "") or args.get("name", "")
                direction = args.get("direction", "right")
                monitor_index = int(args["monitor_index"]) if args.get("monitor_index") is not None else None
                if self.win_controller:
                    return self.win_controller.move_window_to_monitor(target=target, direction=direction, monitor_index=monitor_index)
                return "ย้ายหน้าต่างเรียบร้อยแล้วค่ะ"

            # 2. ควบคุมเมาส์และคีย์บอร์ด
            elif name in {"click_element", "smart_click"}:
                target = args.get("target", "") or args.get("element", "")
                button = args.get("button", "left")
                clicks = int(args.get("clicks", 1))
                if self.mouse_controller:
                    return self.mouse_controller.click_element(target, button=button, clicks=clicks)
                return f"คลิก {target} เรียบร้อยแล้วค่ะ"

            elif name in {"mouse_click", "click"}:
                x = int(args.get("x", 0)) if args.get("x") is not None else None
                y = int(args.get("y", 0)) if args.get("y") is not None else None
                button = args.get("button", "left")
                clicks = int(args.get("clicks", 1))
                if self.mouse_controller:
                    if x is not None and y is not None:
                        return self.mouse_controller.click(x, y, button=button, clicks=clicks)
                    return self.mouse_controller.click(button=button, clicks=clicks)
                return f"คลิกเมาส์เรียบร้อยแล้วค่ะ"

            elif name in {"mouse_move", "move"}:
                x = int(args.get("x", 0))
                y = int(args.get("y", 0))
                duration = int(args.get("duration", args.get("duration_ms", 100)))
                if self.mouse_controller:
                    return self.mouse_controller.move(x, y, duration=duration)
                return f"เลื่อนเมาส์ไปที่ ({x}, {y}) แล้วค่ะ"

            elif name in {"mouse_scroll", "scroll"}:
                clicks = int(args.get("clicks", -3))
                if self.mouse_controller:
                    return self.mouse_controller.scroll(clicks)
                return f"เลื่อนหน้าจอ {clicks} ระดับแล้วค่ะ"

            elif name in {"mouse_drag", "drag"}:
                x1 = int(args.get("x1", 0))
                y1 = int(args.get("y1", 0))
                x2 = int(args.get("x2", 0))
                y2 = int(args.get("y2", 0))
                if self.mouse_controller:
                    return self.mouse_controller.drag(x1, y1, x2, y2)
                return f"ลากเมาส์เรียบร้อยค่ะ"

            elif name in {"keyboard_type", "type"}:
                text = args.get("text", "")
                target_window = args.get("target_window", "") or args.get("title", "") or args.get("target", "")
                if self.mouse_controller:
                    return self.mouse_controller.type_text(text, target_window=target_window)
                return f"พิมพ์ข้อความเรียบร้อยค่ะ"

            elif name in {"open_url", "browse_url"}:
                url = args.get("url", "")
                if self.win_controller:
                    return self.win_controller.open_url(url)
                return f"เปิดหน้าเว็บ {url} เรียบร้อยแล้วค่ะ"

            # 3. จับภาพหน้าจอและการรับรู้ (Perception & Vision)
            elif name in {"see_screen", "describe_screen"}:
                query = args.get("query", "")
                if self.screen_observer:
                    return self.screen_observer.describe_screen(query)
                return "มองเห็นหน้าจอเรียบร้อยค่ะ"

            elif name == "capture_screen":
                if self.screen_observer:
                    res = self.screen_observer.capture()
                    return f"แคปภาพหน้าจอเรียบร้อยค่ะ ขนาด {res.get('width')}x{res.get('height')}"
                return "แคปภาพหน้าจอเรียบร้อยค่ะ"

            elif name == "get_active_window":
                if self.screen_observer:
                    win = self.screen_observer.get_active_window()
                    return f"หน้าต่างปัจจุบันคือ '{win.get('title')}' (PID {win.get('pid')})"
                return "ตรวจสอบหน้าต่างปัจจุบันเรียบร้อยค่ะ"

            # 4. แขนกลภายนอก (Autonomous Harnesses)
            elif name in {"delegate_to_antigravity", "run_terminal", "run_code", "ask_antigravity"}:
                prompt = args.get("prompt", "") or args.get("command", "") or args.get("task", "")
                confirmed = bool(args.get("confirmed", False))
                return self.delegate_to_antigravity(prompt, confirmed=confirmed)

            elif name in {"delegate_to_ufo", "ufo_task", "deep_gui_task"}:
                task = args.get("task", "") or args.get("request", "")
                return self.delegate_to_ufo(task)

            elif name in {"executive_action", "solve_task", "complex_task", "supervise"}:
                command = args.get("command", "") or args.get("prompt", "") or args.get("task", "")
                if self.supervisor:
                    return self.supervisor.execute_task(command)
                return f"ดำเนินการ '{command}' เรียบร้อยค่ะ"

            elif name in {"confirm_action", "approve_action"}:
                action = args.get("action", "") or args.get("command", "")
                return f"บอสได้อนุมัติการดำเนินการ '{action}' เรียบร้อยแล้วค่ะ เอเธน่ากำลังลงมือปฏิบัติการค่ะ"

            # 5. ระบบความจำ (Memory System)
            elif name in {"remember", "store_memory", "save_memory"}:
                key = str(args.get("key", "") or args.get("topic", "")).strip()
                value = str(args.get("value", "") or args.get("content", "") or args.get("note", "")).strip()
                category = str(args.get("category", "general")).strip()
                if self.memory:
                    return self.memory.remember(key=key, value=value, category=category)
                return f"เอเธน่าบันทึกข้อมูล '{key}': '{value}' เรียบร้อยแล้วค่ะ"

            elif name in {"recall", "search_memory", "get_memory"}:
                query = str(args.get("query", "") or args.get("key", "") or args.get("topic", "")).strip()
                if self.memory:
                    return self.memory.recall(query=query)
                return "ไม่พบข้อมูลในความจำค่ะ"

            elif name in {"forget", "delete_memory", "remove_memory"}:
                key = str(args.get("key", "") or args.get("query", "")).strip()
                if self.memory:
                    return self.memory.forget(key=key)
                return f"เอเธน่าลบข้อมูลเกี่ยวกับ '{key}' ออกจากความจำเรียบร้อยแล้วค่ะ"

            elif name in {"list_memories", "all_memories"}:
                category = str(args.get("category", "")).strip()
                if self.memory:
                    return self.memory.list_memories(category=category)
                return "ขณะนี้ยังไม่มีข้อมูลในความจำค่ะ"

            return f"ดำเนินการคำสั่ง {name} สำเร็จค่ะ"

        except Exception as exc:
            err_msg = f"เกิดข้อผิดพลาดในการทำ {name}: {exc}"
            print(f"[Athena Error] {err_msg}")
            return err_msg

    @staticmethod
    def _is_consequential_action(command: str) -> tuple[bool, str]:
        """ตรวจสอบว่าคำสั่งเป็นงานที่มีผลกระทบย้อนกลับไม่ได้หรือความเสี่ยงสูง (Human-in-the-Loop)"""
        if not command:
            return False, ""
        lower = command.lower()
        danger_patterns = [
            ("rmdir", "ลบโฟลเดอร์แบบถาวร"),
            ("del /", "ลบไฟล์จำนวนมาก"),
            ("rm -rf", "ลบโฟลเดอร์แบบถาวร (Force recursive)"),
            ("format ", "ฟอร์แมตดิสก์"),
            ("drop table", "ลบตารางฐานข้อมูล"),
            ("drop database", "ลบฐานข้อมูล"),
            ("delete from", "ลบข้อมูลในฐานข้อมูล"),
            ("shutdown", "ปิดหรือรีสตาร์ตเครื่องคอมพิวเตอร์"),
            ("taskkill /f /im explorer", "บังคับปิด Windows Explorer"),
            ("git reset --hard", "รีเซ็ตโค้ดทิ้งทั้งหมด"),
            ("git clean -fd", "ลบไฟล์ที่ไม่ได้ track ทิ้ง"),
        ]
        for pattern, desc in danger_patterns:
            if pattern in lower:
                return True, desc
        return False, ""

    def delegate_to_antigravity(self, prompt: str, confirmed: bool = False) -> str:
        """ส่งคำสั่งให้ Antigravity CLI (agy) ดำเนินการด้านโค้ด เทอร์มินัล หรืองานระบบอัตโนมัติ พร้อม Consequential Gate"""
        import subprocess
        agy_path = r"C:\Users\BUSOLOVE\AppData\Local\agy\bin\agy.exe"
        if not os.path.exists(agy_path):
            return "ไม่พบโปรแกรม Antigravity CLI (agy.exe) ในระบบค่ะ"

        # Consequential Action Gate (Human-in-the-Loop)
        is_danger, reason = self._is_consequential_action(prompt)
        if is_danger and not confirmed:
            return (
                f"[Consequential Action Gate]: คำสั่งนี้มีความเสี่ยงสูงต่อระบบ (ตรวจพบ: {reason}) "
                f"เพื่อความปลอดภัย กรุณายืนยันคำสั่งโดยระบุ confirmed=True ก่อนที่เอเธน่าจะดำเนินการค่ะ"
            )

        print(f"[Athena Core] สั่งงาน Antigravity CLI: {prompt}")
        try:
            cmd = [agy_path, "-p", prompt, "--dangerously-skip-permissions"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                encoding="utf-8",
                errors="replace",
                cwd=str(self.config.BASE_DIR),
            )
            out = result.stdout.strip()
            if result.returncode != 0 and not out:
                err = result.stderr.strip()
                return f"Antigravity CLI ทำงานขัดข้อง (code {result.returncode}): {err}"
            if len(out) > 2500:
                out = out[:2500] + "\n... [ผลลัพธ์ถูกตัดทอนเพื่อประหยัด Token ค่ะ]"
            return out or "Antigravity CLI ดำเนินการเรียบร้อยแล้วค่ะ"
        except subprocess.TimeoutExpired:
            return "Antigravity CLI ใช้เวลาประมวลผลนานเกินกำหนดค่ะ (Timeout)"
        except Exception as exc:
            return f"เกิดข้อผิดพลาดในการเรียก Antigravity CLI: {exc}"

    def delegate_to_ufo(self, task: str) -> str:
        """ส่งคำสั่งให้ Microsoft UFO ดำเนินการควบคุม GUI เชิงลึก หรือจัดการเอกสาร Office"""
        import subprocess
        ufo_python = r"E:\ufo\.venv\Scripts\python.exe"
        ufo_dir = r"E:\ufo"
        if not os.path.exists(ufo_python):
            return "ไม่พบสภาพแวดล้อมเสมือนของ Microsoft UFO (E:\\ufo\\.venv) ค่ะ"

        print(f"[Athena Core] สั่งงาน Microsoft UFO: {task}")
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
            if len(out) > 2500:
                out = out[:2500] + "\n... [ผลลัพธ์ถูกตัดทอนเพื่อประหยัด Token ค่ะ]"
            return out or f"Microsoft UFO ดำเนินการงาน '{task}' สำเร็จค่ะ"
        except subprocess.TimeoutExpired:
            return "Microsoft UFO ใช้เวลาทำงานนานเกินกำหนดค่ะ (Timeout)"
        except Exception as exc:
            return f"เกิดข้อผิดพลาดในการเรียก Microsoft UFO: {exc}"


    def get_tool_declarations(self) -> list[dict[str, Any]]:
        """สร้าง Tool Schema สำหรับส่งให้ Gemini Function Calling โดยดึงจาก DesktopTools"""
        from voice.live_stream import DesktopTools
        return DesktopTools.DESKTOP_TOOL_DECLARATIONS

    def get_desktop_summary(self) -> str:
        """ดึงข้อมูลสรุปหน้าต่างและสถานะหน้าจอผ่าน Supervisor"""
        if self.supervisor:
            return self.supervisor.get_desktop_summary()
        return ""

    def get_memory_summary(self, limit: int = 8) -> str:
        """ดึงข้อมูลสรุปความจำสำคัญของบอสเพื่อป้อนเป็น Context"""
        if self.memory:
            return self.memory.get_context_summary(limit=limit)
        return ""


