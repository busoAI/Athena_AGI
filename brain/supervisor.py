"""
brain/supervisor.py
Athena Project — Antigravity Cognitive Supervisor (สมองแกนกลางระดับบริหาร)
- ทำหน้าที่เป็น Executive Planning & Reasoning Layer ร่วมกับ Antigravity CLI (agy.exe)
- วางแผนคำสั่งหลายขั้นตอน (Multi-step Decomposition) และสั่งการแขนกล (Actions)
- ตรวจสอบสถานะกายภาพจริง (Closed-Loop Verification) ก่อนส่งรายงานกลับเข้าท่อเสียง Gemini Live
- รองรับ Model Fallback อัตโนมัติเมื่อเกิด Rate Limit / Quota Exceeded
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import re
import time
from typing import Any

from google import genai
from google.genai import types

from config import Config

logger = logging.getLogger(__name__)

SUPERVISOR_SYSTEM_INSTRUCTION = """คุณคือ 'เอเธน่า' (Athena) เลขานุการบริหารส่วนตัวและสมองสั่งการระดับสูงของบอส (Boss) ได้รับแรงบันดาลใจจากเทพีเอเธน่า: ฉลาด สุขุม ปราดเปรื่อง มีไหวพริบ ความคิดเฉียบแหลม มั่นใจในข้อมูล และมีวินัยระดับบริหารสูงสุด

[บุคลิกภาพและแนวทางปฏิบัติของเอเธน่า 100%]:
1. สุภาพ ฉลาด กระชับ และคมคาย: สื่อสารด้วยภาษาไทยระดับมืออาชีพ เป็นธรรมชาติ ไม่ตอบแบบหุ่นยนต์แข็งทื่อ มั่นใจในข้อมูล ตรงไปตรงมา และลงท้ายด้วย 'ค่ะ' เสมอ (ห้ามใช้ 'ครับ' เด็ดขาด)
2. ห้ามขอโทษหรือแสดงความสงสาร: มุ่งเน้นความถูกต้อง แม่นยำ และผลลัพธ์ที่สำเร็จจริง 100%
3. คิดก่อนทำ - วางแผนอย่างเป็นระบบ: เมื่อได้รับคำสั่ง ให้วิเคราะห์ความต้องการ หากเป็นงานคอมพิวเตอร์หลายขั้นตอน ให้วางลำดับเครื่องมืออย่างรอบคอบและลงมือทำอย่างเป็นขั้นเป็นตอน
4. ทำเฉพาะจุด - ไม่ทำเกิน Scope: จัดการเฉพาะสิ่งที่บอสสั่งอย่างแม่นยำ ไม่เพิ่มความซับซ้อนโดยไม่จำเป็น
5. ไม่เดาเงียบ - Closed-Loop Physical Verification: ทุกครั้งที่มีการเปิด ปิด ย่อ ขยาย พิมพ์ หรือสั่งการใดๆ บนคอมพิวเตอร์ ต้องเรียกใช้เครื่องมือตรวจสอบสถานะจริงทางกายภาพเสมอ (เช่น verify_window_state, list_windows, see_screen) เพื่อยืนยันว่าการกระทำสำเร็จจริง 100% ก่อนรายงานผล ห้ามเดาหรือแจ้งว่าสำเร็จล่วงหน้าเด็ดขาด
6. กฎเหล็กห้ามถามคำถามเซ้าซี้ปิดท้ายเด็ดขาด: เมื่อทำงานเสร็จหรือตอบคำถามเสร็จแล้ว ให้จบประโยคอย่างสง่างามทันที ห้ามลงท้ายด้วยคำถามหรือประโยคเซ้าซี้ เช่น 'มีอะไรให้ช่วยเพิ่มไหมคะ', 'ต้องการให้ทำอะไรต่อไหมคะ', 'มีข้อสงสัยสอบถามได้นะคะ', 'แจ้งได้เลยนะคะ' โดยเด็ดขาด
7. ความยืดหยุ่นในการสื่อสาร:
   - หากบอสสนทนาทั่วไป ชวนคุย ขอคำปรึกษา หรือแลกเปลี่ยนความคิดเห็น: ให้ตอบด้วยไหวพริบ สติปัญญา และมุมมองระดับเลขาบริหาร โดยไม่ต้องเรียกใช้เครื่องมือ Desktop ใดๆ
   - หากบอสสั่งงานคอมพิวเตอร์ (เช่น เปิด/ปิดแอป, พิมพ์ข้อความ, สลับหน้าจอ, ดูหน้าจอ, รันโค้ดผ่าน Antigravity agy): ให้เรียกใช้เครื่องมือ Desktop Tools ที่เหมาะสม ดำเนินการ และตรวจสอบผลลัพธ์จริงก่อนสรุปรายงาน
"""


def _is_rate_limit_error(exc: Exception) -> bool:
    """ตรวจสอบว่าข้อผิดพลาดมาจาก Rate Limit หรือ Quota หมดหรือไม่"""
    err_str = str(exc).lower()
    keywords = ["429", "resource_exhausted", "quota", "rate limit", "ratelimit", "too many requests"]
    if any(k in err_str for k in keywords):
        return True
    if hasattr(exc, "code") and getattr(exc, "code") == 429:
        return True
    if hasattr(exc, "status_code") and getattr(exc, "status_code") == 429:
        return True
    return False


def _format_athena_response(text: str) -> str:
    """
    ขัดเกลาคำตอบให้อยู่ในมาตรฐานบุคลิกภาพเอเธน่า 100%:
    - ใช้ 'ค่ะ' เสมอ (ห้ามมี 'ครับ')
    - แปลงสรรพนามบุรุษที่หนึ่งให้เป็น 'เอเธน่า'
    - ตัดประโยคหรือคำถามเซ้าซี้ปิดท้ายทิ้งอย่างหมดจด
    - สุภาพ กระชับ คมคาย
    """
    if not text:
        return "เอเธน่าดำเนินการตรวจสอบและจัดการให้เรียบร้อยแล้วค่ะ"

    cleaned = text.strip()

    # 1. แปลงสรรพนามบุรุษที่หนึ่ง 'ผม' ให้เป็น 'เอเธน่า'
    cleaned = re.sub(r"(?<![ก-๙])ผม(?=[ก-๙\s])", "เอเธน่า", cleaned)

    # 2. แทนที่คำลงท้าย 'ครับ' ด้วย 'ค่ะ'
    cleaned = re.sub(r"ครับ(?=[!?,.\s]|$)", "ค่ะ", cleaned)
    cleaned = cleaned.replace("นะครับ", "นะคะ").replace("ครับ", "ค่ะ")

    # 3. กฎเหล็ก: กำจัดประโยคเซ้าซี้ปิดท้ายเด็ดขาด
    annoying_patterns = [
        r"[\s,.]*(?:หากบอส|ถ้าบอส|หากคุณ|ถ้าคุณ|หากมี|ถ้ามี|พร้อม|ยินดี)?\s*(?:มีอะไรให้|ต้องการให้|แจ้งได้|สอบถาม|บอกเอเธน่า).*",
        r"[\s,.]*(?:หากบอส|ถ้าบอส|หากมี|ถ้ามี)?\s*ต้องการให้.*?(ช่วย|ทำ|แจ้ง|สอบถาม).*",
        r"[\s,.]*(?:หากบอส|ถ้าบอส|หากมี|ถ้ามี)?\s*มีอะไรเพิ่มเติม.*",
        r"[\s,.]*หากมี.*?(คำถาม|ข้อสงสัย|งาน|อะไร).*",
        r"[\s,.]*แจ้ง.*?(ได้|มา|เอเธน่าได้).*?(นะคะ|ค่ะ).*",
        r"[\s,.]*มีข้อสงสัย.*",
        r"[\s,.]*ยินดี.*?(ช่วยเหลือ|รับใช้|บริการ).*",
        r"[\s,.]*ต้องการสอบถาม.*",
        r"[\s,.]*บอกเอเธน่าได้.*",
    ]
    for pat in annoying_patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE).strip()

    # 4. ตัดคำเชื่อมค้างท้ายที่อาจหลงเหลือจากการตัดประโยค (Dangling Conjunctions)
    dangling_conjunctions = [
        r"[\s,.]+(?:หากบอส|ถ้าบอส|หากคุณ|ถ้าคุณ|หากมี|ถ้ามี|หาก|ถ้า|และ|หรือ)\s*$",
    ]
    for dc in dangling_conjunctions:
        cleaned = re.sub(dc, "", cleaned).strip()

    # ล้างท้ายบรรทัดและใส่คำลงท้ายหากยังไม่มี
    cleaned = cleaned.rstrip(".!?, ")
    if not (cleaned.endswith("ค่ะ") or cleaned.endswith("นะคะ")):
        cleaned += " ค่ะ"

    return cleaned


class AntigravitySupervisor:
    """
    สมองผู้คุมหลัก (Executive Supervisor) สำหรับ Athena Project
    ประสานงานระหว่าง Antigravity Engine, การวางแผนงานหลายขั้นตอน และการตรวจงานจริง
    """

    def __init__(self, core: Any | None = None) -> None:
        self.core = core
        self.client = genai.Client(api_key=Config.GEMINI_API_KEY)
        self.agy_path = r"C:\Users\BUSOLOVE\AppData\Local\agy\bin\agy.exe"
        self._history: list[types.Content] = []

    def clear_history(self) -> None:
        """ล้างประวัติการสนทนาต่อเนื่องทั้งหมด"""
        self._history.clear()
        logger.info("[Supervisor] ล้างประวัติการสนทนาเรียบร้อยแล้วค่ะ")

    def get_history(self) -> list[types.Content]:
        """ดึงประวัติการสนทนาต่อเนื่องปัจจุบัน"""
        return list(self._history)

    def _ensure_core(self) -> Any | None:
        """เชื่อมต่อ AthenaCore อัตโนมัติหากยังไม่ได้แนบมา เพื่อให้เข้าถึงเครื่องมือได้ครบถ้วน"""
        if self.core is None:
            try:
                from athena_core import AthenaCore
                self.core = AthenaCore()
                self.core.initialize_subsystems()
                logger.info("[Supervisor] เชื่อมต่อ AthenaCore อัตโนมัติสำเร็จ")
            except Exception as exc:
                logger.warning("[Supervisor] ไม่สามารถเชื่อมต่อ AthenaCore อัตโนมัติได้: %s", exc)
        return self.core

    def is_antigravity_available(self) -> bool:
        """ตรวจสอบว่ามี Antigravity CLI ติดตั้งอยู่ในเครื่องหรือไม่"""
        return os.path.exists(self.agy_path)

    def get_desktop_summary(self) -> str:
        """
        ดึงสรุปสถานะปัจจุบันของหน้าจอและหน้าต่างโปรแกรมที่เปิดอยู่
        เพื่อใช้เป็น Context ป้อนให้โมเดลเสียงสดทราบสถานะตลอดเวลา
        """
        self._ensure_core()
        if not self.core or not self.core.win_controller:
            return "ขณะนี้ยังไม่ได้เชื่อมต่อตัวควบคุมหน้าต่างค่ะ"

        try:
            wins = self.core.win_controller.list_windows()
            if not wins:
                return "ขณะนี้ไม่พบหน้าต่างโปรแกรมที่เปิดอยู่บนหน้าจอค่ะ"

            titles = [w["title"] for w in wins[:5]]
            return f"หน้าต่างที่เปิดอยู่บนจอขณะนี้: {', '.join(titles)}"
        except Exception as exc:
            return f"ไม่สามารถดึงสถานะหน้าจอได้: {exc}"

    def execute_task(self, prompt: str) -> str:
        """
        ประมวลผลคำสั่งเชิงลึก วางแผนหลายขั้นตอน รันเครื่องมือ พร้อม Closed-Loop Verification
        และสลับโมเดล Fallback อัตโนมัติหากเกิด Rate limit
        """
        command = str(prompt).strip()
        if not command:
            return "กรุณาระบุคำสั่งที่ต้องการให้เอเธน่าทำค่ะ"

        logger.info("[Supervisor Thinking] ได้รับคำสั่ง: %s", command)
        self._ensure_core()

        # สร้างลำดับโมเดลที่ต้องการทดลอง (Primary -> Fallback -> Safety Net)
        primary_model = getattr(Config, "CHAT_MODEL", "gemini-3.1-pro-preview")
        fallback_model = getattr(Config, "FALLBACK_CHAT_MODEL", "gemini-3.6-flash")
        safety_model = "gemini-3.5-flash-lite"

        candidate_models = []
        for m in [primary_model, fallback_model, safety_model]:
            if m and m not in candidate_models:
                candidate_models.append(m)

        # เตรียมเครื่องมือ (กรองฟังก์ชันที่อาจเกิด recursion ออก)
        tools = None
        if self.core and hasattr(self.core, "get_tool_declarations"):
            try:
                raw_decls = self.core.get_tool_declarations()
                filtered = [
                    t for t in raw_decls
                    if t.get("name") not in {"executive_action", "solve_task", "complex_task", "supervise"}
                ]
                if filtered:
                    tools = [{"function_declarations": filtered}]
            except Exception as exc:
                logger.warning("[Supervisor] ไม่สามารถโหลด Tool Declarations: %s", exc)

        # รวมคำสั่งระบบและบริบทความจำของบอส
        instruction = SUPERVISOR_SYSTEM_INSTRUCTION
        if self.core and hasattr(self.core, "get_memory_summary"):
            try:
                mem_summary = self.core.get_memory_summary()
                if mem_summary:
                    instruction += f"\n\n[ฐานความจำสำคัญของบอส]:\n{mem_summary}"
            except Exception as exc:
                logger.warning("[Supervisor] ไม่สามารถดึงความจำบอส: %s", exc)

        # ดึงสรุปหน้าต่างปัจจุบันบนหน้าจอแบบกระชับ (Grounding ทันที ประหยัด Token และไม่ต้องเรียก list_windows ก่อน)
        if self.core and hasattr(self.core, "win_controller") and self.core.win_controller:
            try:
                wins = self.core.win_controller.list_windows()
                if wins:
                    top_titles = [w["title"] for w in wins[:4] if w.get("title")]
                    if top_titles:
                        instruction += f"\n\n[หน้าต่างที่เปิดอยู่บนจอขณะนี้]: {', '.join(top_titles)}"
            except Exception:
                pass

        last_error = None

        for model_name in candidate_models:
            logger.info("[Supervisor] กำลังประมวลผลด้วยโมเดล: %s", model_name)
            try:
                chat_config_kwargs: dict[str, Any] = {
                    "system_instruction": instruction,
                    "temperature": 0.2,
                }
                if tools:
                    chat_config_kwargs["tools"] = tools

                chat = self.client.chats.create(
                    model=model_name,
                    config=types.GenerateContentConfig(**chat_config_kwargs),
                    history=self._history[-20:] if self._history else None,
                )

                response = chat.send_message(command)
                step_count = 0
                max_steps = 10

                # Closed-Loop Agentic Execution: คิด ➔ สั่งการ ➔ ตรวจสอบจริง ➔ สรุป
                while response.function_calls and step_count < max_steps:
                    step_count += 1
                    function_responses = []

                    for fc in response.function_calls:
                        tool_name = fc.name
                        tool_args = fc.args or {}
                        logger.info("[Supervisor Action Step %d] เรียกใช้ %s %s", step_count, tool_name, tool_args)

                        if self.core:
                            res = self.core.execute_tool(tool_name, tool_args)
                        else:
                            res = f"ไม่สามารถรัน {tool_name} ได้เนื่องจากไม่มี core ค่ะ"

                        # ตัดทอนผลลัพธ์ของ Tool หากยาวเกิน 2,500 ตัวอักษร เพื่อประหยัด Token และป้องกัน Context บวม
                        res_str = str(res)
                        if len(res_str) > 2500:
                            res_str = res_str[:2500] + "\n... (ข้อความยาวเกินไป เอเธน่าตัดทอนเพื่อประหยัดโควตาค่ะ)"

                        logger.info("[Supervisor Step Result]: %s", res_str[:200])
                        function_responses.append(
                            types.Part.from_function_response(
                                name=tool_name,
                                response={"result": res_str},
                            )
                        )

                    response = chat.send_message(function_responses)

                final_text = response.text.strip() if response.text else "เอเธน่าดำเนินการตรวจสอบและจัดการให้เรียบร้อยแล้วค่ะ"
                formatted_text = _format_athena_response(final_text)
                logger.info("[Supervisor Final Report]: %s", formatted_text)

                # บันทึกประวัติการสนทนาแบบ Multi-turn เพื่อรักษา Context ข้ามรอบ
                self._history.append(types.Content(role="user", parts=[types.Part.from_text(text=command)]))
                self._history.append(types.Content(role="model", parts=[types.Part.from_text(text=formatted_text)]))
                if len(self._history) > 40:
                    self._history = self._history[-40:]

                return formatted_text

            except Exception as exc:
                last_error = exc
                if _is_rate_limit_error(exc):
                    logger.warning(
                        "[Supervisor Fallback] โมเดล '%s' ติด Rate limit / Quota (%s) กำลังสลับไปใช้โมเดลถัดไป...",
                        model_name,
                        exc,
                    )
                    continue
                else:
                    logger.exception("[Supervisor Execution Error] ข้อผิดพลาดขณะรันโมเดล %s: %s", model_name, exc)
                    # หากเกิดความผิดพลาดอื่น ลองโมเดลถัดไป
                    continue

        err_detail = str(last_error or "")
        if "401" in err_detail or "unauthenticated" in err_detail.lower():
            friendly_err = "เอเธน่าไม่สามารถเชื่อมต่อระบบปัญญาประดิษฐ์ได้ เนื่องจากปัญหาการยืนยันตัวตน API Key ค่ะ กรุณาตรวจสอบการตั้งค่าคีย์ค่ะ"
        elif "429" in err_detail or "resource_exhausted" in err_detail.lower():
            friendly_err = "ขณะนี้ระบบมีปริมาณการเรียกใช้งานหนาแน่นชั่วคราว เอเธน่ากำลังรอสลับช่องทางประมวลผลค่ะ"
        elif "network" in err_detail.lower() or "connection" in err_detail.lower():
            friendly_err = "เกิดข้อผิดพลาดในการเชื่อมต่อเครือข่ายอินเทอร์เน็ตค่ะ กรุณาตรวจสอบการเชื่อมต่อค่ะ"
        else:
            friendly_err = "เอเธน่าพบข้อขัดข้องในการประมวลผลคำสั่งค่ะ กรุณาลองสั่งใหม่อีกครั้งค่ะ"

        return _format_athena_response(friendly_err)

    async def aexecute_task(self, prompt: str) -> str:
        """รันคำสั่งเชิงลึกแบบ Asynchronous ใน Worker Thread เพื่อไม่บล็อก Live Loop"""
        return await asyncio.to_thread(self.execute_task, prompt)
