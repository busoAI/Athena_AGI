"""
main.py
Athena Project — Main Entry Point
รันระบบควบคุมเครื่อง สื่อสารผ่านเสียงสองทาง (Gemini Live) หรือพิมพ์สั่งงาน
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from athena_core import AthenaCore


async def run_voice_loop(core: AthenaCore) -> None:
    """รันระบบเสียงสดสองทาง เชื่อมต่อ Antigravity Live Voice (Gemini Live เป็นเพียง Mouthpiece เปล่งเสียง)"""
    try:
        from voice.antigravity_voice import AntigravityLiveVoice
        live = AntigravityLiveVoice(core=core)
        await live.start()
    except Exception as exc:
        print(f"[Athena Voice Error] ระบบเสียงขัดข้อง: {exc}")


async def run_console_loop(core: AthenaCore) -> None:
    """รันระบบสั่งงานผ่านคอนโซล (พิมพ์สั่งงาน) ด้วย Gemini Brain + Native Function Calling"""
    from google import genai
    from google.genai import types
    from config import Config

    loop = asyncio.get_running_loop()
    print("\n" + "=" * 60)
    print("  ATHENA OS AGENT (Autonomous Terminal Mode)")
    print("  สมอง Gemini คิดและตัดสินใจเลือก Tool เอง 100% (ไร้ if-else)")
    print("  พิมพ์คำสั่งภาษาธรรมชาติได้ทุกอย่าง เช่น: 'ย่อหน้าต่าง', 'ดูหน้าจอให้หน่อย'")
    print("  พิมพ์ 'exit' หรือ 'quit' เพื่อปิดระบบ")
    print("=" * 60 + "\n")

    from voice.live_stream import ATHENA_SYSTEM_PROMPT

    client = genai.Client(api_key=Config.GEMINI_API_KEY)
    tools = [{"function_declarations": core.get_tool_declarations()}]

    chat = client.chats.create(
        model=Config.CHAT_MODEL,
        config=types.GenerateContentConfig(
            system_instruction=ATHENA_SYSTEM_PROMPT,
            tools=tools,
            temperature=0.2,
        ),
    )

    while True:
        try:
            line = await loop.run_in_executor(None, input, "athena> ")
            cmd = line.strip()
            if not cmd:
                continue
            if cmd.lower() in {"exit", "quit", "q", "ออก"}:
                break

            response = await asyncio.to_thread(chat.send_message, cmd)

            # จัดการ Tool Calls หากโมเดลต้องการรันเครื่องมือ
            while response.function_calls:
                function_responses = []
                for fc in response.function_calls:
                    print(f"[Athena Thinking] กำลังเรียกใช้เครื่องมือ: {fc.name} (args: {fc.args})")
                    result = core.execute_tool(fc.name, fc.args or {})
                    print(f"[Athena Execution]: {result}")
                    function_responses.append(
                        types.Part.from_function_response(
                            name=fc.name,
                            response={"result": result}
                        )
                    )
                # ส่งผลลัพธ์ของ Tool กลับให้โมเดลสรุปคำตอบ
                response = await asyncio.to_thread(chat.send_message, function_responses)

            if response.text:
                print(f"[Athena]: {response.text.strip()}\n")

        except (KeyboardInterrupt, EOFError):
            break
        except Exception as exc:
            print(f"[Athena Error]: {exc}")


async def async_main(args: argparse.Namespace) -> None:
    core = AthenaCore()
    core.initialize_subsystems()

    if args.mode in {"voice", "both"}:
        print("[Athena] เริ่มต้นระบบเสียงสดสองทาง...")
        voice_task = asyncio.create_task(run_voice_loop(core))
        if args.mode == "voice":
            try:
                await voice_task
            except (asyncio.CancelledError, KeyboardInterrupt):
                pass
            return

    if args.mode in {"console", "both"}:
        await run_console_loop(core)


def main() -> None:
    parser = argparse.ArgumentParser(description="Athena Project — Autonomous Desktop Agent")
    parser.add_argument("--mode", choices=["voice", "console", "both"], default="both", help="โหมดการทำงาน (voice, console, both)")
    args = parser.parse_args()

    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("\n[Athena] ปิดระบบเรียบร้อยค่ะ")


if __name__ == "__main__":
    main()
