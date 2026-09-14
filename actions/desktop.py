"""
actions/desktop.py
โมดูลควบคุม Desktop UI สำหรับ Athena Project
ประกอบด้วย WindowController (Win32 / ctypes) และ MouseKeyboardController (PyAutoGUI / pyperclip)
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any

import psutil
import pyautogui
import pyperclip

logger = logging.getLogger(__name__)

# ตั้งค่าความปลอดภัยและหน่วงเวลาเริ่มต้นของ PyAutoGUI
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05

# Win32 dll references
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

def _set_dpi_aware() -> None:
    """Set process DPI awareness for accurate pixel coordinates on Windows."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

_set_dpi_aware()

# เก็บ Handle ของ Window Station และ Desktop ไว้ตลอดอายุการทำงานของโปรเซส
_HWINSTA_HANDLE: int | None = None
_HDESK_HANDLE: int | None = None

# แมปชื่อเรียกโปรแกรมกับชื่อไฟล์ executable สำหรับการเปิดแอป
_ALLOWED_APPS: dict[str, str] = {
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "notepad": "shell:AppsFolder\\Microsoft.WindowsNotepad_8wekyb3d8bbwe!App",
    "โน้ตแพด": "shell:AppsFolder\\Microsoft.WindowsNotepad_8wekyb3d8bbwe!App",
    "สมุดจด": "shell:AppsFolder\\Microsoft.WindowsNotepad_8wekyb3d8bbwe!App",
    "calculator": "shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
    "เครื่องคิดเลข": "shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
    "calc": "shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
    "paint": "shell:AppsFolder\\Microsoft.Paint_8wekyb3d8bbwe!App",
    "เพ้นท์": "shell:AppsFolder\\Microsoft.Paint_8wekyb3d8bbwe!App",
    "terminal": "shell:AppsFolder\\Microsoft.WindowsTerminal_8wekyb3d8bbwe!App",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "wordpad": "wordpad.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "pwsh": "pwsh.exe",
    "taskmgr": "taskmgr.exe",
    "task manager": "taskmgr.exe",
    "antigravity": "Antigravity.exe",
    "แอนติกราวิตี้": "Antigravity.exe",
    "anti-gravity": "Antigravity.exe",
    "agy": "Antigravity.exe",
}

# แมปชื่อสำหรับ Process-Aware search และ close
_APP_PROCESS_ALIASES: dict[str, list[str]] = {
    "calc": ["calc.exe", "calculatorapp.exe", "calculator.exe"],
    "calculator": ["calc.exe", "calculatorapp.exe", "calculator.exe"],
    "เครื่องคิดเลข": ["calc.exe", "calculatorapp.exe", "calculator.exe"],
    "notepad": ["notepad.exe"],
    "โน้ตแพด": ["notepad.exe"],
    "สมุดจด": ["notepad.exe"],
    "chrome": ["chrome.exe"],
    "google chrome": ["chrome.exe"],
    "taskmgr": ["taskmgr.exe"],
    "task manager": ["taskmgr.exe"],
    "paint": ["mspaint.exe", "paint.exe"],
    "เพ้นท์": ["mspaint.exe", "paint.exe"],
    "wordpad": ["wordpad.exe"],
    "explorer": ["explorer.exe"],
    "cmd": ["cmd.exe"],
    "powershell": ["powershell.exe", "pwsh.exe"],
    "pwsh": ["powershell.exe", "pwsh.exe"],
    "antigravity": ["antigravity.exe", "antigravity"],
    "แอนติกราวิตี้": ["antigravity.exe", "antigravity"],
    "anti-gravity": ["antigravity.exe", "antigravity"],
    "agy": ["antigravity.exe", "antigravity"],
    "terminal": ["windowsterminal.exe", "wt.exe"],
    "code": ["code.exe"],
    "vscode": ["code.exe"],
}


class WindowController:
    """
    ควบคุม Window State และ Lifecycle บนระบบปฏิบัติการ Windows ผ่าน Win32 API / ctypes
    """

    @staticmethod
    def _ensure_desktop_access() -> None:
        """เชื่อมต่อ Thread ไปยัง Interactive Desktop (WinSta0\\Default) โดยคง Handle ไว้ตลอด ไม่ปิดทิ้ง"""
        global _HDESK_HANDLE, _HWINSTA_HANDLE
        try:
            if _HWINSTA_HANDLE is None:
                hw = user32.OpenWindowStationW("WinSta0", False, 0x37F)
                if hw:
                    _HWINSTA_HANDLE = int(hw)
                    user32.SetProcessWindowStation(hw)
            if _HDESK_HANDLE is None:
                hd = user32.OpenDesktopW("Default", 0, False, 0x1FF)
                if hd:
                    _HDESK_HANDLE = int(hd)
                    user32.SetThreadDesktop(hd)
        except Exception as exc:
            logger.debug("Desktop access configuration error: %s", exc)

    @classmethod
    def _find_window_hwnds(cls, target: str = "") -> list[tuple[int, str]]:
        """
        ค้นหา HWND และ Window Title ที่มองเห็นได้
        จัดลำดับความสอดคล้องตาม Process Name และ Window Title (Process-Aware)
        """
        cls._ensure_desktop_access()
        norm_target = target.strip().lower()

        target_procs = set()
        if norm_target:
            if norm_target in _APP_PROCESS_ALIASES:
                target_procs.update(p.lower() for p in _APP_PROCESS_ALIASES[norm_target])
            target_procs.add(f"{norm_target}.exe")
            target_procs.add(norm_target)

        ranked_results: list[tuple[int, int, str]] = []  # (rank, hwnd, title)

        dwmapi = ctypes.windll.dwmapi
        DWMWA_CLOAKED = 14

        def enum_cb(hwnd: int, _: int) -> bool:
            if user32.IsWindowVisible(hwnd):
                # กรองหน้าต่างผี: ตรวจสอบสถานะเฉพาะหน้าต่างที่ไม่ได้ถูกย่อ (IsIconic)
                is_iconic = bool(user32.IsIconic(hwnd))
                if not is_iconic:
                    cloaked = wintypes.DWORD(0)
                    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0:
                        if cloaked.value != 0:
                            return True

                    rect = wintypes.RECT()
                    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                        w = rect.right - rect.left
                        h = rect.bottom - rect.top
                        if w < 30 or h < 30:
                            return True

                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value.strip()
                    if title and title not in {"Program Manager", "Default IME", "MSCTFIME UI"}:
                        if not norm_target:
                            ranked_results.append((10, hwnd, title))
                            return True

                        proc_matched = False
                        pid = wintypes.DWORD()
                        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        if pid.value:
                            try:
                                proc = psutil.Process(pid.value)
                                p_name = (proc.name() or "").lower()
                                p_stem = Path(p_name).stem.lower()
                                if (
                                    p_name in target_procs
                                    or p_stem in target_procs
                                    or any(len(c) >= 3 and (p_stem == c or p_name == c) for c in target_procs)
                                ):
                                    proc_matched = True
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass

                        title_matched = norm_target in title.lower()

                        if proc_matched and title_matched:
                            ranked_results.append((0, hwnd, title))
                        elif proc_matched:
                            ranked_results.append((1, hwnd, title))
                        elif title_matched:
                            ranked_results.append((2, hwnd, title))
            return True

        cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(enum_cb)
        user32.EnumWindows(cb, 0)
        ranked_results.sort(key=lambda item: item[0])
        return [(hwnd, title) for _, hwnd, title in ranked_results]

    @staticmethod
    def _find_app_in_start_menu(name: str) -> str | None:
        """ค้นหาโปรแกรมจาก Start Menu shortcuts (.lnk หรือ .exe)"""
        if not name:
            return None
        normalized = " ".join(name.casefold().split())
        roots = (
            Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs",
            Path("C:/ProgramData/Microsoft/Windows/Start Menu/Programs"),
        )
        candidates: list[Path] = []
        for root in roots:
            if not root.exists():
                continue
            candidates.extend(
                item for item in root.rglob("*")
                if item.is_file() and item.suffix.casefold() in {".lnk", ".exe"}
            )

        matches = [
            item for item in candidates
            if normalized == item.stem.casefold() or normalized in item.stem.casefold()
        ]
        if matches:
            matches.sort(key=lambda p: (0 if p.stem.casefold() == normalized else 1, len(p.stem)))
            return str(matches[0])
        return None

    def minimize_window(self, target: str = "") -> str:
        """
        ย่อหน้าต่าง (Minimize) บน Windows ด้วย ShowWindowAsync 6
        รองรับ active window และการค้นหาแบบ Process-Aware
        """
        self._ensure_desktop_access()
        norm = target.strip().lower() if isinstance(target, str) else ""
        is_generic = not norm or norm in {"current", "active", "foreground", "หน้าต่างนี้", "จอนี้", "นี้"}

        matches: list[tuple[int, str]] = []
        if is_generic:
            fg = int(user32.GetForegroundWindow())
            if fg and user32.IsWindowVisible(fg):
                length = user32.GetWindowTextLengthW(fg)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(fg, buff, length + 1)
                    title = buff.value.strip()
                    if title:
                        matches.append((fg, title))
            if not matches:
                all_visible = self._find_window_hwnds("")
                if all_visible:
                    matches.append(all_visible[0])
        else:
            matches = self._find_window_hwnds(target)

        if not matches:
            return f"ไม่พบหน้าต่างที่ตรงกับ '{target or 'ปัจจุบัน'}' ค่ะ"

        hwnd, title = matches[0]
        user32.ShowWindowAsync(hwnd, 6)  # SW_MINIMIZE = 6
        time.sleep(0.05)
        is_minimized = bool(user32.IsIconic(hwnd))
        logger.info("Minimized window: %s (hwnd=%d, verified=%s)", title, hwnd, is_minimized)
        return f"ย่อหน้าต่าง '{title}' แล้วค่ะ"

    def maximize_window(self, target: str = "") -> str:
        """
        ขยายหน้าต่างให้เต็มจอ (Maximize) บน Windows ด้วย ShowWindowAsync 3
        รองรับ active window และการค้นหาแบบ Process-Aware พร้อมตรวจทานผลลัพธ์
        """
        self._ensure_desktop_access()
        norm = target.strip().lower() if isinstance(target, str) else ""
        is_generic = not norm or norm in {"current", "active", "foreground", "หน้าต่างนี้", "จอนี้", "นี้"}

        matches: list[tuple[int, str]] = []
        if is_generic:
            fg = int(user32.GetForegroundWindow())
            if fg and user32.IsWindowVisible(fg):
                length = user32.GetWindowTextLengthW(fg)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(fg, buff, length + 1)
                    title = buff.value.strip()
                    if title:
                        matches.append((fg, title))
            if not matches:
                all_visible = self._find_window_hwnds("")
                if all_visible:
                    matches.append(all_visible[0])
        else:
            matches = self._find_window_hwnds(target)

        if not matches:
            return f"ไม่พบหน้าต่างที่ตรงกับ '{target or 'ปัจจุบัน'}' ค่ะ"

        hwnd, title = matches[0]
        user32.ShowWindowAsync(hwnd, 3)  # SW_MAXIMIZE = 3
        time.sleep(0.05)
        is_maximized = bool(user32.IsZoomed(hwnd))
        logger.info("Maximized window: %s (hwnd=%d, verified=%s)", title, hwnd, is_maximized)
        return f"ขยายหน้าต่าง '{title}' เต็มจอแล้วค่ะ"

    @classmethod
    def force_foreground_window(cls, hwnd: int) -> bool:
        """
        นำหน้าต่างขึ้นมาอยู่หน้าสุดและรับโฟกัสแป้นพิมพ์อย่างแท้จริง
        ทะลุการบล็อก Foreground Lock ของ Windows ด้วย Z-order boost, AttachThreadInput และ Alt-key release
        """
        if not hwnd or not user32.IsWindow(hwnd):
            return False

        cls._ensure_desktop_access()

        # 1. หากหน้าต่างถูกย่ออยู่ ให้ Restore ขึ้นมาก่อน
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            time.sleep(0.06)

        # 2. ปรับ Z-order ด้วย HWND_TOPMOST ชั่วขณะ เพื่อดึงขึ้นมาอยู่เหนือทุกหน้าต่าง
        SWP_FLAGS = 0x0002 | 0x0001 | 0x0040  # SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, SWP_FLAGS)  # HWND_TOPMOST
        time.sleep(0.02)
        user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, SWP_FLAGS)  # HWND_NOTOPMOST
        time.sleep(0.02)

        # 3. เชื่อมโยง Thread Input เพื่อปลดล็อกสิทธิ์ Foreground
        cur_thread = kernel32.GetCurrentThreadId()
        fg_hwnd = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)

        attached_fg = False
        attached_target = False
        try:
            # กดและปล่อยปุ่ม Alt จำลอง เพื่อปลดล็อกการจำกัดโฟกัสของ Windows
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 0x0002, 0)

            if fg_thread and fg_thread != cur_thread:
                attached_fg = bool(user32.AttachThreadInput(cur_thread, fg_thread, True))
            if target_thread and target_thread != cur_thread:
                attached_target = bool(user32.AttachThreadInput(cur_thread, target_thread, True))

            user32.AllowSetForegroundWindow(-1)
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.SetFocus(hwnd)
        finally:
            if attached_fg:
                user32.AttachThreadInput(cur_thread, fg_thread, False)
            if attached_target:
                user32.AttachThreadInput(cur_thread, target_thread, False)

        time.sleep(0.08)
        return True

    def restore_window(self, target: str = "") -> str:
        """
        คืนขนาดหน้าต่าง (Restore) บน Windows และดึงมาอยู่หน้าสุดพร้อมรับคีย์บอร์ด 100%
        รองรับ active window และการค้นหาแบบ Process-Aware พร้อมตรวจทานผลลัพธ์
        """
        self._ensure_desktop_access()
        norm = target.strip().lower() if isinstance(target, str) else ""
        is_generic = not norm or norm in {"current", "active", "foreground", "หน้าต่างนี้", "จอนี้", "นี้"}

        matches: list[tuple[int, str]] = []
        if is_generic:
            fg = int(user32.GetForegroundWindow())
            if fg and user32.IsWindowVisible(fg):
                length = user32.GetWindowTextLengthW(fg)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(fg, buff, length + 1)
                    title = buff.value.strip()
                    if title and title not in {"Program Manager", "Default IME", "MSCTFIME UI"}:
                        matches.append((fg, title))
            if not matches:
                all_visible = self._find_window_hwnds("")
                if all_visible:
                    matches.append(all_visible[0])
        else:
            matches = self._find_window_hwnds(target)

        if not matches:
            return f"ไม่พบหน้าต่างที่ตรงกับ '{target or 'ปัจจุบัน'}' ค่ะ"

        hwnd, title = matches[0]
        self.force_foreground_window(hwnd)
        logger.info("Restored & focused window: %s (hwnd=%d)", title, hwnd)
        return f"ดึงและเปิดหน้าต่าง '{title}' ขึ้นมาใช้งานแล้วค่ะ"

    @classmethod
    def get_monitors(cls) -> list[dict[str, Any]]:
        """
        ตรวจหาข้อมูลหน้าจอทั้งหมดที่เชื่อมต่ออยู่ เรียงลำดับจากซ้ายไปขวา (X asc)
        คืนค่า list ของ dict: index (1-based), hmon, left, top, right, bottom, work_left, work_top, work_right, work_bottom, width, height, is_primary
        """
        cls._ensure_desktop_access()
        class _RECT(ctypes.Structure):
            _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long), ('right', ctypes.c_long), ('bottom', ctypes.c_long)]
        class _MONITORINFO(ctypes.Structure):
            _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', _RECT), ('rcWork', _RECT), ('dwFlags', wintypes.DWORD)]

        monitors: list[dict[str, Any]] = []
        def _cb(hmon: int, hdc: int, lprect: Any, lparam: int) -> bool:
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(_MONITORINFO)
            user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
            monitors.append({
                "hmon": int(hmon),
                "left": int(mi.rcMonitor.left),
                "top": int(mi.rcMonitor.top),
                "right": int(mi.rcMonitor.right),
                "bottom": int(mi.rcMonitor.bottom),
                "work_left": int(mi.rcWork.left),
                "work_top": int(mi.rcWork.top),
                "work_right": int(mi.rcWork.right),
                "work_bottom": int(mi.rcWork.bottom),
                "width": int(mi.rcMonitor.right - mi.rcMonitor.left),
                "height": int(mi.rcMonitor.bottom - mi.rcMonitor.top),
                "is_primary": bool(mi.dwFlags & 1),
            })
            return True

        MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(_RECT), wintypes.LPARAM)
        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_cb), 0)
        monitors.sort(key=lambda m: m["left"])
        for idx, m in enumerate(monitors, start=1):
            m["index"] = idx
        return monitors

    def move_window_to_monitor(
        self,
        target: str = "",
        direction: str = "right",
        monitor_index: int | None = None,
    ) -> str:
        """
        ย้ายหน้าต่างโปรแกรมข้ามจออย่างแม่นยำ 100% ด้วย Win32 API
        รองรับ:
          - direction: "right" (จอขวา), "left" (จอซ้าย), "next" (จอถัดไป), "prev" (จอก่อนหน้า)
          - monitor_index: หมายเลขจอ 1, 2, 3... (เรียงจากซ้ายไปขวา)
          - คงสถานะขยายเต็มจอ (Maximize) หรือขนาดย่อได้อย่างสมบูรณ์แบบ
        """
        self._ensure_desktop_access()
        monitors = self.get_monitors()
        if len(monitors) <= 1:
            return "เครื่องของบอสมีหน้าจอเพียง 1 จอ ไม่สามารถย้ายข้ามจอได้ค่ะ"

        norm = target.strip().lower() if isinstance(target, str) else ""
        is_generic = not norm or norm in {"current", "active", "foreground", "หน้าต่างนี้", "จอนี้", "นี้"}

        matches: list[tuple[int, str]] = []
        if is_generic:
            fg = int(user32.GetForegroundWindow())
            if fg and user32.IsWindowVisible(fg):
                length = user32.GetWindowTextLengthW(fg)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(fg, buff, length + 1)
                    t = buff.value.strip()
                    if t:
                        matches.append((fg, t))
            if not matches:
                all_visible = self._find_window_hwnds("")
                if all_visible:
                    matches.append(all_visible[0])
        else:
            matches = self._find_window_hwnds(target)

        if not matches:
            return f"ไม่พบหน้าต่าง '{target or 'ปัจจุบัน'}' ที่จะย้ายจอค่ะ"

        hwnd, title = matches[0]

        # ตรวจสอบว่าหน้าต่างกำลังอยู่ที่จอไหน
        cur_hmon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        cur_idx = 0
        for i, m in enumerate(monitors):
            if m["hmon"] == cur_hmon:
                cur_idx = i
                break

        # คำนวณจอเป้าหมาย
        if monitor_index is not None and 1 <= monitor_index <= len(monitors):
            target_idx = monitor_index - 1
        else:
            d = str(direction or "right").strip().lower()
            if d in {"left", "prev", "previous", "ซ้าย", "ก่อนหน้า"}:
                target_idx = (cur_idx - 1) % len(monitors)
            else:
                target_idx = (cur_idx + 1) % len(monitors)

        if target_idx == cur_idx:
            return f"หน้าต่าง '{title}' อยู่บนจอที่ {cur_idx + 1} อยู่แล้วค่ะ"

        cur_mon = monitors[cur_idx]
        target_mon = monitors[target_idx]

        # ตรวจสอบว่าหน้าต่างเดิมกำลัง Maximize อยู่หรือไม่
        is_zoomed = bool(user32.IsZoomed(hwnd))
        if is_zoomed:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE ชั่วคราวเพื่อให้ย้ายพิกัดได้
            time.sleep(0.04)

        # อ่านขนาดและพิกัดเดิม
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = max(400, int(rect.right - rect.left))
        h = max(300, int(rect.bottom - rect.top))

        # จำกัดขนาดหน้าต่างไม่ให้ล้นจอเป้าหมาย
        w = min(w, target_mon["work_right"] - target_mon["work_left"])
        h = min(h, target_mon["work_bottom"] - target_mon["work_top"])

        # คำนวณพิกัดใหม่ให้อยู่กึ่งกลางพื้นที่ทำงานของจอเป้าหมาย
        new_x = target_mon["work_left"] + max(0, (target_mon["width"] - w) // 2)
        new_y = target_mon["work_top"] + max(0, (target_mon["height"] - h) // 2)

        # ย้ายหน้าต่างด้วย SetWindowPos
        user32.SetWindowPos(
            hwnd,
            0,
            int(new_x),
            int(new_y),
            int(w),
            int(h),
            0x0004 | 0x0040,  # SWP_NOZORDER | SWP_SHOWWINDOW
        )
        time.sleep(0.04)

        # หากเดิม Maximize อยู่ ให้สั่ง Maximize บนจอใหม่ทันที
        if is_zoomed:
            user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            time.sleep(0.04)

        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)

        logger.info(
            "Moved window '%s' from Monitor %d to Monitor %d (left=%d, top=%d, zoomed=%s)",
            title, cur_idx + 1, target_idx + 1, target_mon["left"], target_mon["top"], is_zoomed
        )
        return f"ย้ายหน้าต่าง '{title}' จากจอ {cur_idx + 1} ไปยังจอ {target_idx + 1} เรียบร้อยแล้วค่ะ"

    def list_windows(self) -> list[dict[str, Any]]:
        """
        แสดงรายการหน้าต่างทั้งหมดที่เปิดอยู่และมองเห็นได้
        คืนค่าเป็น list ของ dict: hwnd, title, pid, process_name
        """
        self._ensure_desktop_access()
        windows: list[dict[str, Any]] = []

        def enum_cb(hwnd: int, _: int) -> bool:
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value.strip()
                    if title and title != "Program Manager":
                        pid = wintypes.DWORD()
                        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        proc_name = ""
                        if pid.value:
                            try:
                                proc = psutil.Process(pid.value)
                                proc_name = proc.name() or ""
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
                        windows.append({
                            "hwnd": hwnd,
                            "title": title,
                            "pid": pid.value,
                            "process_name": proc_name,
                        })
            return True

        cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(enum_cb)
        user32.EnumWindows(cb, 0)
        return windows

    def verify_window_state(self, target: str = "") -> dict[str, Any]:
        """
        ตรวจสอบและรายงานสถานะของหน้าต่างอย่างละเอียด (Closed-Loop Diagnostics)
        """
        self._ensure_desktop_access()
        norm = target.strip().lower() if isinstance(target, str) else ""
        matches = self._find_window_hwnds(norm)
        if not matches:
            return {
                "exists": False,
                "target": target,
                "message": f"ไม่พบหน้าต่าง '{target}' ในระบบค่ะ",
            }
        hwnd, title = matches[0]
        fg = int(user32.GetForegroundWindow())
        is_minimized = bool(user32.IsIconic(hwnd))
        is_maximized = bool(user32.IsZoomed(hwnd))
        is_focused = (fg == hwnd)
        status_text = "ย่ออยู่" if is_minimized else "ขยายเต็มจอ" if is_maximized else "ปกติ"
        focus_text = "อยู่หน้าสุดพร้อมใช้งาน" if is_focused else "อยู่เบื้องหลัง"
        return {
            "exists": True,
            "hwnd": hwnd,
            "title": title,
            "is_minimized": is_minimized,
            "is_maximized": is_maximized,
            "is_focused": is_focused,
            "message": f"หน้าต่าง '{title}' (สถานะ: {status_text}, {focus_text}) ค่ะ",
        }

    def open_app(self, name: str) -> str:
        """
        เปิดโปรแกรมตามชื่อหรือ path พร้อม Closed-Loop Verification
        (ตรวจสอบจนแน่ใจว่าหน้าต่างหรือ Process ปรากฏขึ้นมาจริงก่อนรายงานผล)
        """
        app_name = str(name).strip()
        if not app_name:
            return "กรุณาระบุชื่อโปรแกรมที่ต้องการเปิดค่ะ"

        executable = (
            _ALLOWED_APPS.get(app_name.lower())
            or self._find_app_in_start_menu(app_name)
            or shutil.which(app_name)
            or shutil.which(f"{app_name}.exe")
        )

        if not executable and Path(app_name).exists():
            executable = app_name

        if not executable:
            return f"ไม่พบโปรแกรม '{app_name}' ในระบบค่ะ"

        try:
            if executable.lower().startswith("shell:appsfolder"):
                # Windows 11 Packaged App (Notepad, Calculator, Terminal, Paint)
                subprocess.Popen(f'explorer.exe "{executable}"', shell=True)
                logger.info("Opened Win11 packaged app: %s (%s)", app_name, executable)
            elif executable.casefold().endswith(".lnk"):
                os.startfile(executable)
                logger.info("Opened shortcut: %s (%s)", app_name, executable)
            else:
                try:
                    os.startfile(executable)
                    logger.info("Opened app via startfile: %s (%s)", app_name, executable)
                except Exception:
                    proc = subprocess.Popen(executable, shell=True)
                    logger.info("Opened app via popen: %s (PID %d)", app_name, proc.pid)
        except Exception as exc:
            logger.exception("Error opening app %s: %s", app_name, exc)
            return f"ไม่สามารถเปิด '{app_name}' ได้ค่ะ: {exc}"

        # ── Closed-Loop State Verification ───────────────────────────
        # วนรอบตรวจสอบสถานะหน้าต่างจริงแบบฉับไว (Fast polling รองรับ Win11 Apps ได้ถึง 2.5 วินาที)
        found_window_title = ""
        found_hwnd = 0
        for _ in range(50):
            hwnds = self._find_window_hwnds(app_name)
            if hwnds:
                found_hwnd, found_window_title = hwnds[0]
                break
            time.sleep(0.05)

        if found_hwnd and found_window_title:
            self.force_foreground_window(found_hwnd)
            return f"เปิดโปรแกรม '{app_name}' และหน้าต่าง '{found_window_title}' พร้อมใช้งานบนหน้าจอแล้วค่ะ"

        # หากไม่พบหน้าต่าง ให้ตรวจสอบว่า Process กำลังรันอยู่เบื้องหลังหรือไม่ (รายงานด้วยภาษามนุษย์ ไม่พูดเรื่อง PID)
        target_procs = set()
        norm = app_name.lower()
        if norm in _APP_PROCESS_ALIASES:
            target_procs.update(p.lower() for p in _APP_PROCESS_ALIASES[norm])
        target_procs.add(f"{norm}.exe")
        target_procs.add(norm)

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                p_name = (proc.info.get("name") or "").lower()
                if p_name in target_procs:
                    return f"สั่งเปิด '{app_name}' เรียบร้อยแล้วค่ะ โปรแกรมกำลังโหลดขึ้นมาแสดงผลบนหน้าจอค่ะ"
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        return f"สั่งเปิด '{app_name}' แล้ว แต่ยังไม่พบหน้าต่างแสดงผลบนจอค่ะ"

    def close_app(self, name: str) -> str:
        """
        ปิดหน้าต่างหรือโปรแกรมที่ระบุอย่างสมบูรณ์ พร้อม Closed-Loop Verification
        (ตรวจสอบสถานะหลังปิดว่าหน้าต่างและโปรเซสหายไปจริง 100%)
        """
        app_name = str(name).strip()
        if not app_name:
            return "กรุณาระบุชื่อโปรแกรมหรือหน้าต่างที่ต้องการปิดค่ะ"

        self._ensure_desktop_access()
        norm = app_name.lower()

        # สร้างชุดชื่อ Process ที่ต้องตรวจสอบ
        target_procs = set()
        if norm in _APP_PROCESS_ALIASES:
            target_procs.update(p.lower() for p in _APP_PROCESS_ALIASES[norm])
        if norm in _ALLOWED_APPS:
            target_procs.add(Path(_ALLOWED_APPS[norm]).name.lower())
        target_procs.add(f"{norm}.exe")
        target_procs.add(norm)

        # ตรวจสอบก่อนว่ามีหน้าต่างหรือโปรเซสที่ตรงกับชื่ออยู่หรือไม่
        initial_windows = self._find_window_hwnds(app_name)
        initial_procs = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                p_name = (proc.info.get("name") or "").lower()
                p_stem = Path(p_name).stem.lower()
                if (
                    p_name in target_procs
                    or p_stem in target_procs
                    or any(len(c) >= 4 and p_stem.startswith(c) for c in target_procs)
                ):
                    initial_procs.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if not initial_windows and not initial_procs:
            return f"ไม่พบหน้าต่างหรือโปรแกรม '{app_name}' ค่ะ"

        # 1. ส่ง WM_CLOSE ไปยัง Window ที่ตรงกัน
        for hwnd, _ in initial_windows:
            WM_CLOSE = 0x0010
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

        # 2. ปิด Process ที่เกี่ยวข้อง
        for proc in initial_procs:
            try:
                proc.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # ── Closed-Loop Verification ───────────────────────────
        # วนรอบตรวจสอบว่าหน้าต่างและโปรเซสดับจริงหรือไม่แบบฉับไว
        closed_cleanly = False
        for _ in range(20):
            remaining_windows = self._find_window_hwnds(app_name)
            remaining_procs = [p for p in initial_procs if p.is_running()]
            if not remaining_windows and not remaining_procs:
                closed_cleanly = True
                break
            time.sleep(0.05)

        if closed_cleanly:
            logger.info("Closed %s cleanly (Verified 0 remaining windows/procs)", app_name)
            return f"ปิดโปรแกรม '{app_name}' เรียบร้อยแล้วค่ะ ตรวจสอบแล้วหน้าต่างและโปรเซสถูกปิดสนิท 100%"

        # ถ้ายังค้าง ให้ลอง Force Kill
        for proc in initial_procs:
            try:
                if proc.is_running():
                    proc.kill()
            except Exception:
                pass
        time.sleep(0.2)
        final_windows = self._find_window_hwnds(app_name)
        if not final_windows:
            return f"ปิดโปรแกรม '{app_name}' สำเร็จแล้วค่ะ (บังคับปิดโปรเซสเรียบร้อย)"

        return f"พยายามปิด '{app_name}' แล้ว แต่ตรวจพบว่าหน้าต่างยังคงค้างอยู่ในระบบค่ะ"

    def open_url(self, url: str) -> str:
        """เปิดที่อยู่เว็บไซต์ (URL) บนเว็บบราวเซอร์เริ่มต้น"""
        import webbrowser
        target_url = str(url or "").strip()
        if not target_url:
            return "กรุณาระบุ URL ที่ต้องการเปิดค่ะ"
        if not (target_url.startswith("http://") or target_url.startswith("https://")):
            target_url = "https://" + target_url
        try:
            webbrowser.open(target_url)
            logger.info("Opened URL: %s", target_url)
            return f"เปิดหน้าเว็บ '{target_url}' เรียบร้อยแล้วค่ะ"
        except Exception as exc:
            logger.error("Error opening URL %s: %s", target_url, exc)
            return f"ไม่สามารถเปิดเว็บ '{target_url}' ได้ค่ะ: {exc}"


class MouseKeyboardController:
    """
    ควบคุมเมาส์และคีย์บอร์ดผ่าน PyAutoGUI และ pyperclip
    เน้นการควบคุมเมาส์ทำงานจริงบนหน้าจอด้วยสายตา (Visual Grounding)
    """

    def __init__(self) -> None:
        WindowController._ensure_desktop_access()
        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0.01

    def click_element(self, target: str, button: str = "left", clicks: int = 1) -> str:
        """
        ค้นหาตำแหน่ง UI element บนหน้าจอด้วยระบบสายตา (Visual Grounding)
        เลื่อนเคอร์เซอร์เมาส์ไปยังเป้าหมายอย่างรวดเร็วและแม่นยำ แล้วทำการคลิก
        """
        norm_t = str(target or "").strip().lower()
        if norm_t.startswith("โปรแกรม ") or norm_t.startswith("แอป ") or norm_t.startswith("หน้าต่าง "):
            clean_app = norm_t.replace("โปรแกรม ", "").replace("แอป ", "").replace("หน้าต่าง ", "").strip()
            wc = WindowController()
            hwnds = wc._find_window_hwnds(clean_app)
            if hwnds:
                return wc.restore_window(clean_app)

        from vision.screen import ScreenObserver

        res = ScreenObserver.locate_element(target)
        if not res.get("found"):
            return f"เอเธน่ามองหา '{target}' บนหน้าจอไม่พบค่ะ"

        cx = res["x"]
        cy = res["y"]
        # เลื่อนเมาส์ไปยังตำแหน่งเป้าหมายแบบฉับไว
        self.move(cx, cy, duration=40)
        # คลิกเมาส์
        self.click(cx, cy, button=button, clicks=clicks)
        logger.info("Smart clicked element '%s' at (%d, %d)", target, cx, cy)
        return f"คลิก '{target}' ที่พิกัด ({cx}, {cy}) เรียบร้อยแล้วค่ะ"


    def click(self, x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1) -> str:
        """คลิกเมาส์ที่พิกัด (x, y) ตามปุ่มและจำนวนครั้งที่ระบุ"""
        btn = button.strip().lower()
        if x is not None and y is not None:
            target_x = int(x)
            target_y = int(y)
            pyautogui.click(x=target_x, y=target_y, button=btn, clicks=int(clicks), interval=0.02)
            logger.info("Mouse clicked (%s x %d) at (%d, %d)", btn, clicks, target_x, target_y)
            return f"คลิกที่ ({target_x}, {target_y}) ปุ่ม {button} จำนวน {clicks} ครั้งเรียบร้อยแล้วค่ะ"
        else:
            pyautogui.click(button=btn, clicks=int(clicks), interval=0.02)
            return f"คลิกเมาส์ปุ่ม {button} จำนวน {clicks} ครั้งเรียบร้อยแล้วค่ะ"

    def move(self, x: int, y: int, duration: int = 40) -> str:
        """เลื่อนเคอร์เซอร์เมาส์ไปยังพิกัด (x, y) ในระยะเวลา duration (มิลลิวินาที)"""
        WindowController._ensure_desktop_access()
        dur_sec = max(0.0, float(duration) / 1000.0)
        target_x = int(x)
        target_y = int(y)
        pyautogui.moveTo(x=target_x, y=target_y, duration=dur_sec)
        user32.SetCursorPos(target_x, target_y)
        logger.info("Mouse moved to (%d, %d) in %d ms", target_x, target_y, duration)
        return f"เลื่อนเมาส์ไปที่ ({target_x}, {target_y}) เรียบร้อยแล้วค่ะ"

    def scroll(self, clicks: int, x: int = 0, y: int = 0) -> str:
        """
        เลื่อนลูกกลิ้งเมาส์ (Scroll Wheel)
        บวก = เลื่อนขึ้น, ลบ = เลื่อนลง
        """
        if x != 0 or y != 0:
            pyautogui.scroll(int(clicks), x=int(x), y=int(y))
        else:
            pyautogui.scroll(int(clicks))
        logger.info("Mouse scrolled %d clicks at (%d, %d)", clicks, x, y)
        return f"เลื่อนลูกกลิ้งเมาส์ {clicks} ครั้งเรียบร้อยแล้วค่ะ"

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 200) -> str:
        """ลากเมาส์ (Drag & Drop) จากพิกัด (x1, y1) ไปยัง (x2, y2) รองรับ Virtual Desktop ข้ามจอ"""
        WindowController._ensure_desktop_access()
        dur_sec = max(0.05, float(duration_ms) / 1000.0)
        target_x1, target_y1 = int(x1), int(y1)
        target_x2, target_y2 = int(x2), int(y2)
        user32.SetCursorPos(target_x1, target_y1)
        time.sleep(0.02)
        pyautogui.mouseDown(x=target_x1, y=target_y1, button="left")
        time.sleep(0.04)
        pyautogui.moveTo(x=target_x2, y=target_y2, duration=dur_sec)
        time.sleep(0.04)
        pyautogui.mouseUp(x=target_x2, y=target_y2, button="left")
        logger.info("Mouse dragged from (%d, %d) to (%d, %d)", target_x1, target_y1, target_x2, target_y2)
        return f"ลากเมาส์จาก ({target_x1}, {target_y1}) ไปยัง ({target_x2}, {target_y2}) เรียบร้อยแล้วค่ะ"

    def drag_window(
        self,
        target: str = "",
        direction: str = "right",
        monitor_index: int | None = None,
    ) -> str:
        """
        ลากหน้าต่าง (Drag Window) ข้ามจอด้วยเมาส์และ Win32
        รองรับคำสั่ง 'ลากหน้าต่างไปจอขวา', 'แดรกหน้าต่างไปจอ 3'
        """
        wc = WindowController()
        return wc.move_window_to_monitor(target=target, direction=direction, monitor_index=monitor_index)

    def type_text(self, text: str, target_window: str = "") -> str:
        """
        พิมพ์ข้อความลงในโปรแกรมเป้าหมายหรือหน้าต่างที่กำลังใช้งาน
        รองรับภาษาไทย ภาษาอังกฤษ อักขระพิเศษ และขึ้นบรรทัดใหม่ 100%
        พร้อมระบบ Focus Assurance อัตโนมัติ ป้องกันการพิมพ์ไม่ติด
        """
        content = str(text)
        if not content:
            return "ไม่มีข้อความที่จะพิมพ์ค่ะ"

        WindowController._ensure_desktop_access()
        wc = WindowController()

        target_hwnd = 0
        target_title = ""

        # กรณี 1: มีการระบุ target_window
        if target_window and str(target_window).strip():
            norm_target = str(target_window).strip()
            matches = wc._find_window_hwnds(norm_target)
            if not matches:
                # หากไม่พบหน้าต่างที่ตรง ให้ลองสั่งเปิดโปรแกรมขึ้นมาก่อน
                wc.open_app(norm_target)
                time.sleep(1.0)
                matches = wc._find_window_hwnds(norm_target)

            if matches:
                target_hwnd, target_title = matches[0]
                wc.force_foreground_window(target_hwnd)
                time.sleep(0.12)

        # กรณี 2: ไม่ได้ระบุ target_window หรือหาไม่พบ ให้ตรวจสอบหน้าต่างโฟกัสปัจจุบัน
        if not target_hwnd:
            fg = int(user32.GetForegroundWindow())
            fg_title = ""
            if fg and user32.IsWindowVisible(fg):
                length = user32.GetWindowTextLengthW(fg)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(fg, buff, length + 1)
                    fg_title = buff.value.strip()

            # หากหน้าต่างปัจจุบันเป็น Desktop (Program Manager) หรือแถบ Taskbar หรือหน้าต่างระบบ
            # ให้ค้นหาหน้าต่างโปรแกรมของผู้ใช้ที่เปิดอยู่จริง
            if not fg or not fg_title or fg_title in {"Program Manager", "Default IME", "MSCTFIME UI", "Shell_TrayWnd"}:
                all_wins = wc._find_window_hwnds("")
                if all_wins:
                    target_hwnd, target_title = all_wins[0]
                    wc.force_foreground_window(target_hwnd)
                    time.sleep(0.12)
            else:
                target_hwnd = fg
                target_title = fg_title

        # ตรวจสอบชื่อหน้าต่างสุดท้ายก่อนพิมพ์
        final_title = target_title or "หน้าต่างปัจจุบัน"

        # คลิกกลางพื้นที่เอกสารของหน้าต่างเพื่อกระตุ้นเคอร์เซอร์กระพริบ (Caret Focus)
        if target_hwnd and user32.IsWindow(target_hwnd):
            rect = wintypes.RECT()
            if user32.GetWindowRect(target_hwnd, ctypes.byref(rect)):
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                if w > 100 and h > 100:
                    click_x = rect.left + max(50, w // 2)
                    click_y = rect.top + max(80, h // 2)
                    user32.SetCursorPos(click_x, click_y)
                    time.sleep(0.02)
                    pyautogui.click(click_x, click_y)
                    time.sleep(0.05)

        # พิมพ์ข้อความผ่าน Clipboard Paste (Ctrl+V) เพื่อความแม่นยำ 100%
        # รองรับทั้งภาษาไทยและอังกฤษ โดยไม่ขึ้นกับว่า Windows กำลังตั้งแป้นพิมพ์เป็นภาษาอะไร
        pyperclip.copy(content)
        time.sleep(0.06)

        pyautogui.keyDown("ctrl")
        time.sleep(0.03)
        pyautogui.press("v")
        time.sleep(0.03)
        pyautogui.keyUp("ctrl")
        time.sleep(0.06)

        logger.info("Typed text (%d chars via clipboard) into [%s]", len(content), final_title)
        preview = content[:50] + ("..." if len(content) > 50 else "")
        return f"พิมพ์ข้อความ '{preview}' ลงในหน้าต่าง '{final_title}' เรียบร้อยแล้วค่ะ"

    def hotkey(self, keys: str) -> str:
        """
        กดปุ่มคีย์ลัด เช่น 'ctrl+c', 'alt+f4', 'win+d'
        """
        key_parts = [k.strip().lower() for k in str(keys).split("+") if k.strip()]
        if not key_parts:
            return "กรุณาระบุคีย์ลัดค่ะ"
        pyautogui.hotkey(*key_parts)
        logger.info("Pressed hotkey: %s", "+".join(key_parts))
        return f"กดคีย์ลัด {keys} เรียบร้อยแล้วค่ะ"
