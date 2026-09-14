"""
scratch/test_supervisor_intelligence.py
Athena Project — Verification Suite for Antigravity Cognitive Supervisor
ทดสอบ:
1. การตั้งค่า CHAT_MODEL ('gemini-3.1-pro-preview') และ FALLBACK_CHAT_MODEL ('gemini-3.6-flash')
2. คำสั่งสนทนาทั่วไป (General Conversation / Executive Advisory):
   - คมคาย ฉลาด ไม่ตอบแบบหุ่นยนต์
   - สุภาพ ลงท้ายด้วย 'ค่ะ' เสมอ (ห้ามใช้ 'ครับ')
   - กฎเหล็ก: ปราศจากคำถามหรือประโยคเซ้าซี้ปิดท้าย 100%
3. คำสั่งปฏิบัติการคอมพิวเตอร์ (Desktop Action & Closed-Loop Verification):
   - เปิด notepad, พิมพ์ข้อความ, ตรวจสอบสถานะกายภาพจริง
   - ปิด notepad และยืนยันความเรียบร้อย
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Config
from athena_core import AthenaCore
from brain.supervisor import AntigravitySupervisor, _format_athena_response


def test_configuration() -> None:
    print("\n" + "=" * 65)
    print("  [TEST 1] ตรวจสอบการกำหนดค่าโมเดลและ Fallback ใน Config")
    print("=" * 65)

    print(f">> CHAT_MODEL: {Config.CHAT_MODEL}")
    print(f">> FALLBACK_CHAT_MODEL: {Config.FALLBACK_CHAT_MODEL}")

    assert Config.CHAT_MODEL == "gemini-3.1-pro-preview", (
        f"CHAT_MODEL ต้องเป็น 'gemini-3.1-pro-preview' แต่พบ '{Config.CHAT_MODEL}'"
    )
    assert Config.FALLBACK_CHAT_MODEL == "gemini-3.6-flash", (
        f"FALLBACK_CHAT_MODEL ต้องเป็น 'gemini-3.6-flash' แต่พบ '{Config.FALLBACK_CHAT_MODEL}'"
    )
    print(">> PASS: ตั้งค่าโมเดล Pro และโมเดล Fallback ถูกต้อง 100%")


def test_general_conversation_intelligence() -> None:
    print("\n" + "=" * 65)
    print("  [TEST 2] ทดสอบคำถามสนทนาทั่วไปและการให้คำปรึกษาเชิงบริหาร")
    print("=" * 65)

    core = AthenaCore()
    core.initialize_subsystems()
    supervisor = AntigravitySupervisor(core=core)

    prompt = "เอเธน่า ในฐานะเลขานุการบริหารส่วนตัว มีคำแนะนำเชิงกลยุทธ์อย่างไรในการจัดลำดับความสำคัญของงานระดับ High-Impact ให้บอสในวันนี้"
    print(f"บอส: '{prompt}'\n")

    response = supervisor.execute_task(prompt)
    print(f"[Athena Response]:\n{response}\n")

    assert isinstance(response, str) and len(response) > 20, "คำตอบต้องมีความยาวและเนื้อหาที่สมบูรณ์"

    # กฎเหล็ก 1: ต้องลงท้ายด้วย 'ค่ะ' หรือ 'นะคะ' ห้ามมี 'ครับ' เด็ดขาด
    assert "ครับ" not in response, "ต้องไม่มีคำลงท้าย 'ครับ' ในคำตอบของเอเธน่า"
    assert response.strip().endswith("ค่ะ") or response.strip().endswith("นะคะ"), (
        f"คำตอบต้องลงท้ายด้วย 'ค่ะ' หรือ 'นะคะ' เสมอ (ลงท้ายด้วย: '{response[-10:]}')"
    )

    # กฎเหล็ก 2: ห้ามมีคำถามหรือประโยคเซ้าซี้ปิดท้ายเด็ดขาด
    forbidden_closing_patterns = [
        r"มีอะไรให้(ช่วย|ดิฉัน|เอเธน่า).{0,25}(ไหม|แจ้ง|บอก)",
        r"ต้องการให้(ช่วย|ดิฉัน|เอเธน่า).{0,25}(ไหม|แจ้ง|บอก)",
        r"หากมี(อะไร|ข้อสงสัย|งาน).{0,25}(แจ้ง|บอก|สอบถาม)",
        r"แจ้ง(มา|ได้|เอเธน่าได้).{0,15}(นะคะ|ค่ะ)",
        r"มีอะไรเพิ่มเติม.{0,15}(ไหม|แจ้ง|บอก)",
        r"มีข้อสงสัย.{0,15}(สอบถาม|ถาม)",
        r"ยินดี(ช่วยเหลือ|รับใช้)",
    ]
    for pat in forbidden_closing_patterns:
        match = re.search(pat, response)
        assert not match, f"พบประโยคเซ้าซี้ที่ต้องห้ามในคำตอบ: '{match.group(0)}'"

    print(">> PASS: การสนทนาทั่วไปฉลาด คมคาย สุภาพ และปฏิบัติตามกฎเหล็กของเอเธน่า 100%")


def test_desktop_action_and_closed_loop_verification() -> None:
    print("\n" + "=" * 65)
    print("  [TEST 3] ทดสอบคำสั่งคอมพิวเตอร์: เปิด Notepad พิมพ์ข้อความ และตรวจงานจริง")
    print("=" * 65)

    core = AthenaCore()
    core.initialize_subsystems()
    supervisor = AntigravitySupervisor(core=core)

    test_text = "Athena Cognitive Brain Active 100%"
    prompt = f"เปิด notepad พิมพ์ข้อความว่า '{test_text}' แล้วตรวจสอบสถานะหน้าต่าง notepad ให้บอสด้วยค่ะ"
    print(f"คำสั่งทดสอบ: '{prompt}'\n")

    response = supervisor.execute_task(prompt)
    print(f"[Athena Execution & Verification Report]:\n{response}\n")

    assert isinstance(response, str) and len(response) > 0
    assert "ครับ" not in response, "ต้องไม่มี 'ครับ' ในคำตอบ"
    assert response.strip().endswith("ค่ะ") or response.strip().endswith("นะคะ")

    # ตรวจสอบทางกายภาพจริงว่า Notepad เปิดอยู่จริง
    verify_res = core.win_controller.verify_window_state("notepad")
    print(f">> การตรวจสอบสถานะทางกายภาพหลังคำสั่ง: {verify_res}")
    assert verify_res.get("exists") is True, "หน้าต่าง Notepad ต้องมีอยู่จริงบนระบบหลังสั่งเปิดและพิมพ์"

    # เก็บกวาดหน้าต่าง Notepad เพื่อคืนสถานะเดิมของหน้าจอ
    print(">> กำลังเก็บกวาด: ปิด Notepad หลังการทดสอบเสร็จสมบูรณ์...")
    close_res = core.win_controller.close_app("notepad")
    print(f">> ผลการปิด: {close_res}")

    # ตรวจสอบซ้ำว่าปิดสนิทแล้ว
    post_close = core.win_controller.verify_window_state("notepad")
    assert post_close.get("exists") is False, "หน้าต่าง Notepad ต้องถูกปิดสนิท 100%"
    print(">> PASS: Closed-Loop Verification และการจัดการหน้าต่างสำเร็จ 100%")


def test_response_formatter_strictness() -> None:
    print("\n" + "=" * 65)
    print("  [TEST 4] ทดสอบฟังก์ชันขัดเกลาคำตอบ _format_athena_response")
    print("=" * 65)

    raw_input_1 = "ผมได้เปิดโปรแกรมให้แล้วครับ มีอะไรให้ผมช่วยเพิ่มเติมไหมครับ"
    formatted_1 = _format_athena_response(raw_input_1)
    print(f"Raw 1: '{raw_input_1}'\nCleaned 1: '{formatted_1}'")
    assert "ครับ" not in formatted_1
    assert "มีอะไรให้" not in formatted_1
    assert formatted_1.endswith("ค่ะ")

    raw_input_3 = "การบริหารเวลาคือการบริหารความสำคัญค่ะ หากบอสต้องการให้ช่วยอะไรเพิ่มเติมแจ้งได้เลยนะคะ"
    formatted_3 = _format_athena_response(raw_input_3)
    print(f"\nRaw 3: '{raw_input_3}'\nCleaned 3: '{formatted_3}'")
    assert not formatted_3.endswith("หากบอส ค่ะ")
    assert formatted_3 == "การบริหารเวลาคือการบริหารความสำคัญค่ะ"

    print("\n>> PASS: ตัวกรองและจัดรูปแบบบุคลิกภาพทำงานได้อย่างสมบูรณ์แบบ 100%")


if __name__ == "__main__":
    print("*" * 65)
    print("   ATHENA COGNITIVE SUPERVISOR INTELLIGENCE & ACTION TEST")
    print("*" * 65)

    test_configuration()
    test_response_formatter_strictness()
    test_general_conversation_intelligence()
    test_desktop_action_and_closed_loop_verification()

    print("\n" + "=" * 65)
    print("  สรุปผล: การทดสอบสมองและระบบสั่งการของเอเธน่า ผ่านครบทุกเงื่อนไข 100% ค่ะ!")
    print("=" * 65)
