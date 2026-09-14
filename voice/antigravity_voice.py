"""
voice/antigravity_voice.py
Athena Project — Antigravity Live Voice & Audio Mouthpiece Bridge
- เชื่อมต่อ Gemini Live API (Config.LIVE_VOICE_MODEL) ผ่าน Google GenAI SDK (client.aio.live.connect)
- ทำหน้าที่เป็น "ช่องทางรับและถ่ายทอดเสียงสด (Live Audio Mouthpiece / Puppet)" เพียงอย่างเดียว
- ไม่คิดคำตอบเองเด็ดขาด แต่ส่งคำพูดบอสทั้งหมดผ่าน ask_antigravity เข้าสู่ AntigravitySupervisor ใน brain/supervisor.py
- เมื่อได้รับคำตอบจาก AntigravitySupervisor จะส่ง ToolResponse ให้ Gemini Live อ่านออกเสียงสด 100%
- รองรับ Audio I/O ผ่าน sounddevice (Mic PCM 16kHz, Speaker PCM 24kHz) พร้อมระบบตัดเสียงพูดแทรก (Barge-in / Interruption)
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from typing import Any, Callable

import numpy as np
from google import genai
from google.genai import types
import sounddevice as sd

from config import Config
from brain.supervisor import AntigravitySupervisor

logger = logging.getLogger("AntigravityLiveVoice")

# System Instruction บังคับบทบาท Live Audio Mouthpiece / Puppet 100%
ANTIGRAVITY_MOUTHPIECE_SYSTEM_INSTRUCTION = """คุณคือช่องทางรับและถ่ายทอดเสียงสด (Live Audio Mouthpiece) ของระบบเลขานุการบริหาร 'เอเธน่า'
หน้าที่ของคุณมีเพียงอย่างเดียว:
1. เมื่อได้ยินเสียงจากบอส ให้เรียกใช้เครื่องมือ ask_antigravity(user_speech=...) ทันที โดยส่งคำพูดทั้งหมดของบอสไปยัง Antigravity สมองหลัก ห้ามตอบเองหรือตัดสินใจเองเด็ดขาด
2. เมื่อได้รับข้อความผลลัพธ์จาก Antigravity ให้อ้าปากอ่านออกเสียงสดตามข้อความนั้นทุกประการด้วยน้ำเสียงธรรมชาติ สุภาพ ฉลาด ชัดเจน และห้ามต่อเติมหรือถามคำถามใดๆ เพิ่มเติมเด็ดขาด
"""

# ประกาศ Tool ตัวเดียวสำหรับ Gemini Live: ask_antigravity
ASK_ANTIGRAVITY_TOOL_DECLARATION = [
    {
        "function_declarations": [
            {
                "name": "ask_antigravity",
                "description": (
                    "ส่งคำพูดและคำสั่งทั้งหมดของบอสไปยัง Antigravity สมองหลัก "
                    "เพื่อคิด วิเคราะห์ วางแผน สั่งการระบบ และตัดสินใจคำตอบ ห้ามตอบเองหรือตัดสินใจเองเด็ดขาด"
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "user_speech": {
                            "type": "STRING",
                            "description": "คำพูดทั้งหมดของบอสที่ได้ยินจากเสียงสด",
                        }
                    },
                    "required": ["user_speech"],
                },
            }
        ]
    }
]


def generate_earcon_tone(duration_sec: float = 0.12, sample_rate: int = 24000) -> bytes:
    """
    สร้างสัญญาณเสียงตอบรับสั้นๆ ทันที (Instant Processing Chime/Earcon) PCM 24kHz
    เพื่อตัดช่วงเงียบ (Dead Air) ยืนยันว่ารับคำสั่งแล้วขณะ Antigravity กำลังประมวลผล
    """
    import math
    import struct

    total_samples = int(sample_rate * duration_sec)
    audio_bytes = bytearray()
    f1 = 800.0   # โน้ตแรก
    f2 = 1200.0  # โน้ตสอง
    mid = total_samples // 2

    for i in range(total_samples):
        freq = f1 if i < mid else f2
        fade = math.sin(math.pi * i / total_samples)
        sample_val = int(fade * 0.22 * 32767.0 * math.sin(2.0 * math.pi * freq * i / sample_rate))
        audio_bytes.extend(struct.pack("<h", max(-32768, min(32767, sample_val))))

    return bytes(audio_bytes)


_EARCON_CHIME_BYTES = generate_earcon_tone()


class AudioStreamManager:
    """
    จัดการ Audio Streams สำหรับ Mic PCM 16kHz และ Speaker PCM 24kHz ผ่าน sounddevice
    พร้อมระบบตัดเสียงทันทีเมื่อบอสพูดแทรก (Barge-in / Interruption) และป้องกัน Echo Loopback
    """

    def __init__(self, input_sample_rate: int = 16_000, output_sample_rate: int = 24_000) -> None:
        self.input_sample_rate = input_sample_rate
        self.output_sample_rate = output_sample_rate
        self.input_stream: sd.RawInputStream | None = None
        self.output_stream: sd.RawOutputStream | None = None
        self.mic_queue: queue.Queue[bytes] = queue.Queue(maxsize=64)
        self.speaker_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=120)
        self._is_active = False
        self.is_speaker_playing = False
        self.last_speaker_time = 0.0
        self._output_lock = threading.Lock()

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
            logger.info(
                "Audio streams opened (Mic: %dHz, Speaker: %dHz)",
                self.input_sample_rate,
                self.output_sample_rate,
            )
        except Exception as exc:
            self.stop()
            raise RuntimeError(f"ไม่สามารถเปิด audio streams ได้: {exc}") from exc

    def stop(self) -> None:
        """ปิด audio streams ทั้งหมด"""
        self._is_active = False
        for stream in (self.input_stream, self.output_stream):
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception as exc:
                    logger.debug("Closing stream notice: %s", exc)
        self.input_stream = None
        self.output_stream = None
        self.clear_speaker_queue()
        logger.info("Audio streams closed.")

    def clear_speaker_queue(self) -> None:
        """ล้างคิวเสียงลำโพงทันที (ใช้เมื่อบอสพูดแทรก / Interruption) พร้อมตัดเสียงฮาร์ดแวร์ทันที"""
        while not self.speaker_queue.empty():
            try:
                self.speaker_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.is_speaker_playing = False
        if self.output_stream is not None:
            try:
                with self._output_lock:
                    self.output_stream.abort()
                    self.output_stream.start()
            except Exception as exc:
                logger.debug("Output stream abort notice: %s", exc)

    def play_instant_sound(self, sound_bytes: bytes) -> None:
        """เล่นเสียงตอบรับสั้นๆ ทันทีแบบ Non-blocking เพื่อตัด Dead Air"""
        if self.output_stream is not None and sound_bytes and self._is_active:
            try:
                with self._output_lock:
                    self.output_stream.write(sound_bytes)
            except Exception as exc:
                logger.debug("play_instant_sound notice: %s", exc)


class AntigravityLiveVoice:
    """
    AntigravityLiveVoice — Live Audio Mouthpiece / Puppet Controller
    - เชื่อมต่อ WebSocket สดกับ Gemini Live API (gemini-3.1-flash-live-preview)
    - กำหนดให้ Gemini Live ทำหน้าที่เป็นท่อเสียงสด (Mouthpiece) อย่างเดียว
    - เมื่อได้ยินเสียงสด จะยิง ask_antigravity ไปให้ AntigravitySupervisor คิดและสั่งการ
    - รับคำตอบจาก AntigravitySupervisor ส่งกลับเป็น ToolResponse ให้อ่านออกเสียงสด
    - มีระบบตัดเสียงเมื่อผู้ใช้พูดแทรก (Barge-in) และตัด Echo ทันที
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        voice_name: str | None = None,
        supervisor: AntigravitySupervisor | None = None,
        core: Any | None = None,
    ) -> None:
        self.api_key = api_key or Config.GEMINI_API_KEY
        self.model = model or Config.LIVE_VOICE_MODEL
        self.voice_name = voice_name or Config.VOICE_NAME
        self.core = core
        self.supervisor = supervisor or AntigravitySupervisor(core=core)
        self.audio_manager = AudioStreamManager()
        self._client: genai.Client | None = None
        self._is_running = False
        self._is_tool_running = False
        self._is_mouthpiece_authorized = False
        self._reconnect_requested = False
        self._tasks: list[asyncio.Task[Any]] = []

        # Hooks สำหรับตรวจสอบหรือติดตามการทำงาน
        self.on_tool_call: Callable[[str, dict[str, Any]], None] | None = None
        self.on_supervisor_reply: Callable[[str], None] | None = None

    def get_live_config(self) -> types.LiveConnectConfig:
        """คืนค่าการตั้งค่า Live Session สำหรับ Mouthpiece Mode"""
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
                parts=[types.Part.from_text(text=ANTIGRAVITY_MOUTHPIECE_SYSTEM_INSTRUCTION)]
            ),
            tools=ASK_ANTIGRAVITY_TOOL_DECLARATION,
            input_audio_transcription=types.AudioTranscriptionConfig(
                language_codes=["th-TH", "th"]
            ),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

    async def execute_ask_antigravity(self, user_speech: str) -> str:
        """
        ส่งคำพูดของบอสเข้าสู่ AntigravitySupervisor เพื่อคิด วางแผน และสั่งการระบบ
        """
        logger.info("[Mouthpiece -> Supervisor] ส่งคำพูดบอส: %s", user_speech)
        reply = await self.supervisor.aexecute_task(user_speech)
        logger.info("[Supervisor -> Mouthpiece] คำตอบของ Antigravity: %s", reply)
        if self.on_supervisor_reply:
            try:
                self.on_supervisor_reply(reply)
            except Exception as exc:
                logger.debug("on_supervisor_reply hook error: %s", exc)
        return reply

    async def _send_audio_loop(self, session: Any) -> None:
        """อ่านข้อมูลเสียงไมโครโฟน PCM 16kHz จากคิวส่งเข้า Gemini Live API"""
        logger.info("Mouthpiece microphone sender loop started.")
        try:
            while self._is_running:
                data = await asyncio.to_thread(self.audio_manager.mic_queue.get)
                if not data or not self._is_running:
                    continue

                # Echo & Interruption Guard (รองรับ Barge-in พูดแทรกสดได้จริง):
                # 1. ขณะลำโพงกำลังพูด: ตรวจสอบความดัง (Peak Amplitude)
                #    - ถ้าต่ำกว่า 3000 ถือเป็นเสียงสะท้อนจากลำโพง (Echo) -> ข้าม
                #    - ถ้าเกิน 3000 แสดงว่าบอสกำลังเอ่ยปากพูดแทรก (Barge-in) -> ส่งเสียงขึ้นเซิร์ฟเวอร์ทันที
                # 2. ป้องกันเสียงสะท้อนตกค้างหลังลำโพงหยุดพูด 0.20 วินาที
                now = time.time()
                if self.audio_manager.is_speaker_playing:
                    try:
                        samples = np.frombuffer(data, dtype=np.int16)
                        peak = int(np.max(np.abs(samples))) if len(samples) > 0 else 0
                        if peak < 3000:
                            continue
                    except Exception:
                        continue
                elif (now - self.audio_manager.last_speaker_time < 0.20):
                    continue

                try:
                    blob = types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                    await session.send_realtime_input(audio=blob)
                except Exception as exc:
                    if not self._is_running:
                        break
                    logger.warning("Transient error sending mic chunk: %s", exc)
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Error in mic sender loop: %s", exc)

    async def _playback_loop(self) -> None:
        """ดึงข้อมูลเสียง PCM 24kHz ที่โมเดลอ่านออกเสียงสดส่งออกลำโพง"""
        logger.info("Mouthpiece speaker playback loop started.")
        try:
            while self._is_running:
                chunk = await self.audio_manager.speaker_queue.get()
                if chunk and self._is_running and self.audio_manager.output_stream:
                    try:
                        self.audio_manager.is_speaker_playing = True
                        self.audio_manager.last_speaker_time = time.time()
                        def _write_chunk(stream: Any, chunk_bytes: bytes, lock: Any) -> None:
                            with lock:
                                stream.write(chunk_bytes)
                        await asyncio.to_thread(
                            _write_chunk,
                            self.audio_manager.output_stream,
                            chunk,
                            self.audio_manager._output_lock,
                        )
                        self.audio_manager.last_speaker_time = time.time()
                    except Exception as exc:
                        if not self._is_running:
                            break
                        logger.warning("Playback warning: %s", exc)
                    finally:
                        self.audio_manager.is_speaker_playing = False
                        self.audio_manager.last_speaker_time = time.time()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Error in speaker playback loop: %s", exc)

    async def _receive_loop(self, session: Any) -> None:
        """รับเหตุการณ์จาก Gemini Live API ตลอดเวลา (เสียงตอบกลับ, Tool Calls, Interruption)"""
        logger.info("Mouthpiece receiver loop started.")
        try:
            while self._is_running:
                async for response in session.receive():
                    if not self._is_running:
                        break

                    # 1. จัดการ Server Content (เสียงสด, Interruption, Transcriptions)
                    server_content = response.server_content
                    if server_content:
                        # บอสพูดแทรก (Barge-in / Interruption): ล้างคิวเสียงลำโพงทันที และล็อกตะกร้อ
                        if getattr(server_content, "interrupted", False):
                            logger.info("[Barge-in Detected] บอสพูดแทรก ล้างคิวเสียงลำโพงทันที")
                            self._is_mouthpiece_authorized = False
                            self.audio_manager.clear_speaker_queue()

                        # รับข้อมูลเสียงสด PCM 24kHz (Muzzle Gate: เล่นเฉพาะเสียงที่ Antigravity อนุมัติเท่านั้น)
                        if server_content.model_turn and server_content.model_turn.parts:
                            if self._is_mouthpiece_authorized:
                                for part in server_content.model_turn.parts:
                                    if part.inline_data and part.inline_data.data:
                                        try:
                                            self.audio_manager.speaker_queue.put_nowait(part.inline_data.data)
                                        except asyncio.QueueFull:
                                            try:
                                                self.audio_manager.speaker_queue.get_nowait()
                                                self.audio_manager.speaker_queue.put_nowait(part.inline_data.data)
                                            except (asyncio.QueueEmpty, asyncio.QueueFull):
                                                pass
                            else:
                                logger.warning("[Muzzle Gate] บล็อกสัญญาณเสียงที่ Gemini Live แอบตอบเองโดยไม่ผ่าน Antigravity!")

                        # สิ้นสุดรอบการพูด (Turn Complete) -> รีเซ็ตล็อกตะกร้อครอบปากกลับคืน
                        if getattr(server_content, "turn_complete", False):
                            self._is_mouthpiece_authorized = False

                        # ติดตามคำพูดของบอสที่ถอดความได้
                        in_trans = getattr(server_content, "input_transcription", None)
                        if in_trans and getattr(in_trans, "text", None):
                            logger.info("[Boss Heard]: %s", in_trans.text.strip())

                        # ติดตามคำพูดที่เอเธน่าอ่านออกเสียง
                        out_trans = getattr(server_content, "output_transcription", None)
                        if out_trans and getattr(out_trans, "text", None):
                            logger.info("[Athena Spoke]: %s", out_trans.text.strip())

                    # 2. จัดการ Tool Call จาก Gemini Live
                    tool_call = response.tool_call
                    if tool_call and tool_call.function_calls:
                        self._is_tool_running = True
                        try:
                            function_responses: list[types.FunctionResponse] = []
                            for fc in tool_call.function_calls:
                                logger.info(
                                    "[Tool Call Detected]: name=%s (id=%s, args=%s)",
                                    fc.name,
                                    fc.id,
                                    fc.args,
                                )
                                if self.on_tool_call:
                                    try:
                                        self.on_tool_call(fc.name, dict(fc.args or {}))
                                    except Exception as exc:
                                        logger.debug("on_tool_call hook error: %s", exc)

                                if fc.name == "ask_antigravity":
                                    # ยิงเสียง Chime สั้นๆ ทันที (Earcon) เพื่อตัด Dead Air ให้บอสรู้ว่ารับคำสั่งแล้วและกำลังจัดการ
                                    asyncio.create_task(
                                        asyncio.to_thread(self.audio_manager.play_instant_sound, _EARCON_CHIME_BYTES)
                                    )
                                    args = fc.args or {}
                                    speech = (
                                        args.get("user_speech")
                                        or args.get("prompt")
                                        or args.get("text")
                                        or ""
                                    )
                                    # ส่งคำสั่งให้ AntigravitySupervisor คิดและสั่งการ
                                    result_text = await self.execute_ask_antigravity(speech)
                                else:
                                    result_text = f"ไม่รองรับฟังก์ชัน '{fc.name}' ค่ะ"

                                function_responses.append(
                                    types.FunctionResponse(
                                        name=fc.name,
                                        response={"result": result_text},
                                        id=fc.id,
                                    )
                                )

                            # ส่ง FunctionResponse กลับเข้า Live Session ทันทีเพื่อให้ Gemini Live อ่านออกเสียงสด
                            if function_responses:
                                logger.info(
                                    "[Sending Tool Response] ส่งผลลัพธ์ %d รายการกลับเข้า Live Session",
                                    len(function_responses),
                                )
                                self._is_mouthpiece_authorized = True
                                await session.send_tool_response(function_responses=function_responses)
                        finally:
                            await asyncio.sleep(0.15)
                            self._is_tool_running = False

                    # 3. จัดการ GoAway Warning สัญญาณเตือนใกล้ครบกำหนดเวลาเซสชัน
                    go_away = getattr(response, "go_away", None)
                    if go_away:
                        time_left = getattr(go_away, "time_left", None)
                        logger.warning("เซิร์ฟเวอร์ส่งสัญญาณ GoAway (เหลือเวลา %s) กำลังเตรียม Reconnect อัตโนมัติ", time_left)
                        self._reconnect_requested = True
                        break

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Error in live receiver loop: %s", exc)

    async def start(self) -> None:
        """เปิดการเชื่อมต่อและเริ่มทำงาน Antigravity Live Voice Session"""
        if self._is_running:
            return

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY ไม่ได้กำหนดใน Environment หรือ Config")

        self._client = genai.Client(api_key=self.api_key)
        self.audio_manager.start()
        self._is_running = True
        reconnect_attempts = 0

        try:
            while self._is_running:
                config = self.get_live_config()
                logger.info("กำลังเชื่อมต่อไปยัง Gemini Live API (%s, Voice: %s)...", self.model, self.voice_name)
                self._reconnect_requested = False

                try:
                    async with self._client.aio.live.connect(model=self.model, config=config) as session:
                        logger.info("เชื่อมต่อ Live Voice Session สำเร็จ (Mouthpiece Mode)!")
                        reconnect_attempts = 0

                        sender_task = asyncio.create_task(self._send_audio_loop(session))
                        receiver_task = asyncio.create_task(self._receive_loop(session))
                        playback_task = asyncio.create_task(self._playback_loop())
                        self._tasks = [sender_task, receiver_task, playback_task]

                        # ทำงานจนกว่าจะมี Task สิ้นสุด
                        done, pending = await asyncio.wait(
                            [sender_task, receiver_task, playback_task],
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        for task in pending:
                            task.cancel()
                        if pending:
                            await asyncio.gather(*pending, return_exceptions=True)
                        self.audio_manager.clear_speaker_queue()
                        for task in done:
                            if not task.cancelled() and task.exception():
                                raise task.exception()

                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    reconnect_attempts += 1
                    logger.warning(
                        "Live session หลุดการเชื่อมต่อ (%s) กำลังพยายาม Reconnect รอบที่ %d...",
                        exc,
                        reconnect_attempts,
                    )
                    if not self._is_running:
                        break
                    delay = min(1.0 * (1.5 ** (reconnect_attempts - 1)), 10.0)
                    await asyncio.sleep(delay)
                else:
                    if self._reconnect_requested and self._is_running:
                        logger.info("กำลังทำการ Reconnect เซสชันใหม่แบบ Graceful...")
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
        logger.info("Antigravity Live Voice stopped.")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    print("=" * 60)
    print("  Athena Antigravity Live Voice (Mouthpiece Mode)")
    print("  Model :", Config.LIVE_VOICE_MODEL)
    print("  Voice :", Config.VOICE_NAME)
    print("=" * 60)
    print("กด Ctrl+C เพื่อหยุดการทำงาน\n")

    mouthpiece = AntigravityLiveVoice()
    try:
        await mouthpiece.start()
    except KeyboardInterrupt:
        print("\nหยุดการทำงานโดยผู้ใช้")
    except Exception as err:
        print(f"\nเกิดข้อผิดพลาด: {err}")
    finally:
        await mouthpiece.stop()


if __name__ == "__main__":
    asyncio.run(main())
