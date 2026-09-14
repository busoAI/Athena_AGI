"""High-speed, lightweight screen capture and active window observer for Athena."""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import io
from pathlib import Path
import tempfile
import time
from typing import Any


_HWINSTA_HANDLE: int | None = None
_HDESK_HANDLE: int | None = None

def _ensure_desktop_access() -> None:
    """Ensure current thread can access the interactive user desktop WinSta0\\Default."""
    global _HWINSTA_HANDLE, _HDESK_HANDLE
    try:
        user32 = ctypes.windll.user32
        if _HWINSTA_HANDLE is None:
            hwinsta = user32.OpenWindowStationW("WinSta0", False, 0x37F)
            if hwinsta:
                _HWINSTA_HANDLE = int(hwinsta)
                user32.SetProcessWindowStation(hwinsta)
        if _HDESK_HANDLE is None:
            hdesk = user32.OpenDesktopW("Default", 0, False, 0x1FF)
            if hdesk:
                _HDESK_HANDLE = int(hdesk)
                user32.SetThreadDesktop(hdesk)
    except Exception:
        pass


def _set_dpi_aware() -> None:
    """Set process DPI awareness for accurate pixel coordinates on Windows."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _cleanup_old_temp_files(prefix: str = "athena_screen_", max_age_seconds: int = 120) -> None:
    """Safely purge stale screenshot temp files to avoid disk clutter."""
    try:
        tmp_dir = Path(tempfile.gettempdir())
        now = time.time()
        for old in tmp_dir.glob(f"{prefix}*.png"):
            try:
                if now - old.stat().st_mtime > max_age_seconds:
                    old.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass


# Initialize desktop access and DPI awareness once at module load
_ensure_desktop_access()
_set_dpi_aware()


class ScreenObserver:
    """Screen observation and high-speed capture engine for Athena."""

    def __init__(self) -> None:
        _ensure_desktop_access()

    @classmethod
    def get_screen_resolution(cls, all_screens: bool = False) -> tuple[int, int]:
        """Return the screen resolution as (width, height).

        Args:
            all_screens: If True, returns the combined virtual resolution of all monitors.
                         If False (default), returns primary monitor resolution.

        Returns:
            tuple[int, int]: (width, height) in pixels.
        """
        _ensure_desktop_access()

        try:
            import mss

            with mss.MSS() as sct:
                if all_screens and sct.monitors:
                    return (int(sct.monitors[0]["width"]), int(sct.monitors[0]["height"]))

                cur_mon = cls.get_cursor_monitor()
                if cur_mon and cur_mon.get("width") and cur_mon.get("height"):
                    return (int(cur_mon["width"]), int(cur_mon["height"]))

                if len(sct.monitors) > 1:
                    primary = next((m for m in sct.monitors[1:] if m.get("is_primary")), sct.monitors[1])
                    return (int(primary["width"]), int(primary["height"]))
                if sct.monitors:
                    return (int(sct.monitors[0]["width"]), int(sct.monitors[0]["height"]))
        except Exception:
            pass

        try:
            user32 = ctypes.windll.user32
            if all_screens:
                w = int(user32.GetSystemMetrics(78))  # SM_CXVIRTUALSCREEN
                h = int(user32.GetSystemMetrics(79))  # SM_CYVIRTUALSCREEN
            else:
                w = int(user32.GetSystemMetrics(0))  # SM_CXSCREEN
                h = int(user32.GetSystemMetrics(1))  # SM_CYSCREEN
            if w > 0 and h > 0:
                return (w, h)
        except Exception:
            pass

        return (1920, 1080)

    @classmethod
    def get_active_window(cls) -> dict[str, Any]:
        """Retrieve details of the current active foreground window.

        Returns:
            dict with keys:
                - hwnd (int): Window handle (0 if none)
                - title (str): Window title bar text
                - pid (int): Process ID
                - bbox (tuple[int, int, int, int]): (x, y, width, height)
                - x (int): Left coordinate
                - y (int): Top coordinate
                - width (int): Window width
                - height (int): Window height
        """
        _ensure_desktop_access()
        user32 = ctypes.windll.user32

        hwnd = int(user32.GetForegroundWindow())
        if not hwnd:
            return {
                "hwnd": 0,
                "title": "",
                "pid": 0,
                "bbox": (0, 0, 0, 0),
                "x": 0,
                "y": 0,
                "width": 0,
                "height": 0,
            }

        # Window title
        title_buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title_buf, 512)
        title = title_buf.value.strip()

        # Process ID
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        pid = int(process_id.value)

        # Window bounding box (Prefer DwmGetWindowAttribute to exclude invisible shadow borders)
        rect = wintypes.RECT()
        rect_retrieved = False
        try:
            dwmapi = ctypes.windll.dwmapi
            DWMWA_EXTENDED_FRAME_BOUNDS = 9
            res = dwmapi.DwmGetWindowAttribute(
                hwnd,
                DWMWA_EXTENDED_FRAME_BOUNDS,
                ctypes.byref(rect),
                ctypes.sizeof(rect),
            )
            if res == 0:
                rect_retrieved = True
        except Exception:
            rect_retrieved = False

        if not rect_retrieved:
            try:
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
            except Exception:
                pass

        x = int(rect.left)
        y = int(rect.top)
        w = max(0, int(rect.right - rect.left))
        h = max(0, int(rect.bottom - rect.top))

        # Check for minimized window (-32000 coordinates)
        if x <= -10000 or y <= -10000:
            w = 0
            h = 0

        return {
            "hwnd": hwnd,
            "title": title,
            "pid": pid,
            "bbox": (x, y, w, h),
            "x": x,
            "y": y,
            "width": w,
            "height": h,
        }

    @classmethod
    def get_cursor_monitor(cls) -> dict[str, int]:
        """ตรวจหาหน้าจอ (Monitor) ที่เคอร์เซอร์เมาส์ของบอสอยู่จริงในปัจจุบัน (รองรับจอซ้อน / Multi-Monitor)"""
        user32 = ctypes.windll.user32
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        cx, cy = pt.x, pt.y

        try:
            import mss
            with mss.MSS() as sct:
                for m in sct.monitors[1:]:
                    left = m["left"]
                    top = m["top"]
                    right = left + m["width"]
                    bottom = top + m["height"]
                    if left <= cx < right and top <= cy < bottom:
                        return m
                if len(sct.monitors) > 1:
                    return sct.monitors[1]
                return sct.monitors[0]
        except Exception:
            return {"left": 0, "top": 0, "width": 1920, "height": 1080}

    @classmethod
    def capture(
        cls,
        save_path: str | Path | None = None,
        only_active: bool = False,
        all_screens: bool = False,
    ) -> dict[str, Any]:
        """Capture the screen or active window at ultra-fast speeds using mss.
        รองรับ Multi-Monitor และวาดตำแหน่งเคอร์เซอร์เมาส์จริงลงบนภาพ
        """
        _ensure_desktop_access()
        _cleanup_old_temp_files()

        target_region: dict[str, int] | None = None
        target_left = 0
        target_top = 0

        if only_active:
            active_win = cls.get_active_window()
            x, y, w, h = active_win.get("bbox", (0, 0, 0, 0))
            if w > 0 and h > 0:
                target_region = {"left": x, "top": y, "width": w, "height": h}
                target_left = x
                target_top = y

        if target_region is None:
            if all_screens:
                import mss
                with mss.MSS() as sct:
                    target_region = sct.monitors[0]
                    target_left = target_region["left"]
                    target_top = target_region["top"]
            else:
                target_region = cls.get_cursor_monitor()
                target_left = target_region["left"]
                target_top = target_region["top"]

        raw_bytes: bytes | None = None
        width = 0
        height = 0

        # 1. High-speed capture with MSS (~15-30ms)
        try:
            import io
            import mss
            from PIL import Image, ImageDraw

            with mss.MSS() as sct:
                sct_img = sct.grab(target_region)
                width = int(sct_img.width)
                height = int(sct_img.height)

                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

                # วาดตำแหน่งเคอร์เซอร์เมาส์ของจริงลงบนภาพ เพื่อให้ AI มองเห็นตรงกับสายตาบอส
                try:
                    user32 = ctypes.windll.user32
                    pt = wintypes.POINT()
                    user32.GetCursorPos(ctypes.byref(pt))
                    cur_x = pt.x - target_left
                    cur_y = pt.y - target_top
                    if 0 <= cur_x < width and 0 <= cur_y < height:
                        draw = ImageDraw.Draw(img)
                        r = 9
                        draw.ellipse((cur_x - r, cur_y - r, cur_x + r, cur_y + r), outline="red", width=2)
                        draw.line((cur_x - r - 4, cur_y, cur_x + r + 4, cur_y), fill="red", width=2)
                        draw.line((cur_x, cur_y - r - 4, cur_x, cur_y + r + 4), fill="red", width=2)
                        draw.ellipse((cur_x - 2, cur_y - 2, cur_x + 2, cur_y + 2), fill="red")
                except Exception:
                    pass

                buf = io.BytesIO()
                img.save(buf, format="PNG", compress_level=1)
                raw_bytes = buf.getvalue()
        except Exception:
            raw_bytes = None

        # 2. Resilient fallback using PIL ImageGrab
        if raw_bytes is None:
            try:
                import io
                from PIL import ImageGrab

                if target_region:
                    bbox = (
                        target_region["left"],
                        target_region["top"],
                        target_region["left"] + target_region["width"],
                        target_region["top"] + target_region["height"],
                    )
                    img = ImageGrab.grab(bbox=bbox, all_screens=True)
                else:
                    img = ImageGrab.grab(all_screens=all_screens)

                width, height = img.size
                buf = io.BytesIO()
                img.save(buf, format="PNG", compress_level=1)
                raw_bytes = buf.getvalue()
            except Exception as exc:
                raise RuntimeError(f"Athena ScreenObserver failed to capture screen: {exc}") from exc

        # 3. Save to destination file if requested
        if save_path:
            out_file = Path(save_path).resolve()
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(raw_bytes)
            final_path = str(out_file)
        else:
            tmp_dir = Path(tempfile.gettempdir())
            tmp_file = tmp_dir / f"athena_screen_{int(time.time() * 1000)}.png"
            tmp_file.write_bytes(raw_bytes)
            final_path = str(tmp_file)

        # 4. Generate Base64
        base64_str = base64.b64encode(raw_bytes).decode("ascii")

        return {
            "base64": base64_str,
            "bytes": raw_bytes,
            "width": width,
            "height": height,
            "path": final_path,
            "left": target_left,
            "top": target_top,
        }

    _client_instance: Any = None

    @classmethod
    def _get_client(cls) -> Any:
        if cls._client_instance is None:
            from config import Config
            from google import genai
            cls._client_instance = genai.Client(api_key=Config.GEMINI_API_KEY)
        return cls._client_instance

    @classmethod
    def locate_element(
        cls,
        target: str,
        model: str = "gemini-3.1-flash-lite",
        fallback_model: str = "gemini-2.0-flash",
    ) -> dict[str, Any]:
        """Locate a target UI element on screen using Gemini Visual Grounding.

        Args:
            target: Description, name, or text of the target (e.g. 'close button', 'ปุ่มค้นหา', 'ไอคอน Chrome')
            model: Primary fast vision model for grounding
            fallback_model: Secondary fallback model if primary fails

        Returns:
            dict containing:
                - found (bool): True if located
                - x (int): Center X coordinate in screen pixels
                - y (int): Center Y coordinate in screen pixels
                - bbox (tuple[int, int, int, int]): (x1, y1, x2, y2) in screen pixels
                - label (str): Name or description of found target
                - error (str | None): Error message if any
        """
        import io
        import json
        from PIL import Image
        from google.genai import types

        clean_target = str(target or "").strip()
        if not clean_target:
            return {"found": False, "x": 0, "y": 0, "bbox": (0, 0, 0, 0), "label": "", "error": "Target is empty"}

        cap = cls.capture()
        img_bytes = cap["bytes"]
        w = cap["width"]
        h = cap["height"]
        target_left = cap.get("left", 0)
        target_top = cap.get("top", 0)

        # บีบอัดภาพเป็น JPEG ขนาดกะทัดรัด (~150KB แทนที่จะเป็น 5MB PNG) เพื่อลดเวลาส่งขึ้น API
        try:
            pil_img = Image.open(io.BytesIO(img_bytes))
            upload_img = pil_img.copy()
            if max(w, h) > 1600:
                upload_img.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            upload_img.save(buf, format="JPEG", quality=80, optimize=True)
            upload_bytes = buf.getvalue()
            upload_mime = "image/jpeg"
        except Exception:
            upload_bytes = img_bytes
            upload_mime = "image/png"

        prompt = f"""You are Athena's precision visual grounding engine.
The desktop image has resolution {w}x{h}.
Your task is to locate this specific UI element: "{clean_target}".
Find the exact bounding box of "{clean_target}" on this screen.
Coordinates must be normalized to 0-1000 scale: [ymin, xmin, ymax, xmax].
Respond ONLY with a valid JSON object:
{{"found": true, "name": "{clean_target}", "box_2d": [ymin, xmin, ymax, xmax]}}
If the element is not found on the screen, respond with:
{{"found": false, "name": "{clean_target}", "box_2d": []}}
"""

        client = cls._get_client()
        selected_models = [model, fallback_model]

        for m in selected_models:
            try:
                resp = client.models.generate_content(
                    model=m,
                    contents=[
                        types.Part.from_bytes(data=upload_bytes, mime_type=upload_mime),
                        prompt,
                    ],
                    config=types.GenerateContentConfig(response_mime_type="application/json"),
                )
                text = (resp.text or "").strip()
                data = json.loads(text)
                # If wrapped in a list, extract the first item
                if isinstance(data, list) and data:
                    data = data[0]

                if isinstance(data, dict) and data.get("found") and data.get("box_2d"):
                    ymin, xmin, ymax, xmax = data["box_2d"]
                    x1 = int(xmin * w / 1000.0)
                    x2 = int(xmax * w / 1000.0)
                    y1 = int(ymin * h / 1000.0)
                    y2 = int(ymax * h / 1000.0)
                    cx = target_left + (x1 + x2) // 2
                    cy = target_top + (y1 + y2) // 2
                    return {
                        "found": True,
                        "x": cx,
                        "y": cy,
                        "bbox": (target_left + x1, target_top + y1, target_left + x2, target_top + y2),
                        "label": data.get("name", clean_target),
                        "error": None,
                    }
                elif isinstance(data, dict) and not data.get("found"):
                    return {
                        "found": False,
                        "x": 0,
                        "y": 0,
                        "bbox": (0, 0, 0, 0),
                        "label": clean_target,
                        "error": f"Element '{clean_target}' not found on screen",
                    }
            except Exception as exc:
                continue

        return {
            "found": False,
            "x": 0,
            "y": 0,
            "bbox": (0, 0, 0, 0),
            "label": clean_target,
            "error": f"Failed to locate '{clean_target}' on screen",
        }

    @classmethod
    def describe_screen(
        cls,
        query: str = "",
        model: str = "gemini-3.1-flash-lite",
        fallback_model: str = "gemini-2.0-flash",
    ) -> str:
        """Capture screen and describe what is visible or answer a specific query concisely in Thai."""
        import io
        from PIL import Image
        from google.genai import types

        cap = cls.capture()
        img_bytes = cap["bytes"]
        mime = "image/png"
        try:
            img = Image.open(io.BytesIO(img_bytes))
            img.thumbnail((1280, 720))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75)
            img_bytes = buf.getvalue()
            mime = "image/jpeg"
        except Exception:
            pass

        q = (query or "").strip()
        if q:
            prompt = (
                "คุณคือระบบสายตาของเอเธน่า (Human-Eye Perception) มองภาพหน้าจอนี้เสมือนเลขาธิการส่วนตัวที่ยืนมองมอนิเตอร์อยู่ข้างบอส "
                "รายงานสิ่งที่สายตามนุษย์มองเห็นจริงบนจอภาพอย่างตรงไปตรงมา (เช่น หน้าต่างที่เปิดอยู่, กล่องข้อความ error, ปุ่มกด, สิ่งที่กำลังแสดงผล) "
                "ห้ามใช้ศัพท์เทคนิคหุ่นยนต์ เช่น PID, HWND, Process ID เด็ดขาด "
                f"ตอบคำถามของบอสอย่างกระชับ ตรงประเด็น เป็นภาษาไทย ลงท้ายด้วย 'ค่ะ' รายงานเฉพาะข้อเท็จจริง ห้ามถามคำถามปิดท้ายเด็ดขาด: {q}"
            )
        else:
            prompt = (
                "คุณคือระบบสายตาของเอเธน่า (Human-Eye Perception) มองภาพหน้าจอนี้เสมือนเลขาธิการส่วนตัวที่ยืนมองมอนิเตอร์อยู่ข้างบอส "
                "สรุปสั้นๆ 1-2 บรรทัดเป็นภาษาไทยว่าสายตามนุษย์มองเห็นอะไรแสดงอยู่บนจอปัจจุบันบ้าง เช่น หน้าต่างโปรแกรมที่เปิดอยู่ เนื้อหาหลัก หรือข้อความสำคัญ "
                "ห้ามใช้ศัพท์เทคนิคหุ่นยนต์ เช่น PID, HWND, Process ตอบกระชับ ลงท้ายด้วย 'ค่ะ' รายงานเฉพาะข้อเท็จจริง ห้ามถามคำถามปิดท้ายเด็ดขาด"
            )

        client = cls._get_client()
        for m in [model, fallback_model]:
            try:
                resp = client.models.generate_content(
                    model=m,
                    contents=[
                        types.Part.from_bytes(data=img_bytes, mime_type=mime),
                        prompt,
                    ],
                )
                txt = (resp.text or "").strip()
                if txt:
                    return txt
            except Exception:
                continue

        return "เอเธน่ามองดูหน้าจอแล้ว แต่ระบบประมวลผลภาพขัดข้องชั่วคราวค่ะ"

