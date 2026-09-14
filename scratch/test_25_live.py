import asyncio
import os
import time
from google import genai
from google.genai import types

async def test_full_loop():
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    model = "gemini-2.5-flash-native-audio-preview-12-2025"
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
            )
        ),
        system_instruction=types.Content(
            parts=[types.Part.from_text(text="คุณคือท่อเสียงสด เมื่อได้ยินคำสั่งบอสให้เรียก ask_antigravity ทันที เมื่อได้รับผลลัพธ์ให้อ่านออกเสียงตามนั้น")]
        ),
        tools=[{
            "function_declarations": [{
                "name": "ask_antigravity",
                "description": "ส่งคำสั่งไป Antigravity",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"user_speech": {"type": "STRING"}},
                    "required": ["user_speech"]
                }
            }]
        }],
        output_audio_transcription=types.AudioTranscriptionConfig()
    )
    
    print("1. CONNECTING...")
    async with client.aio.live.connect(model=model, config=config) as session:
        print("1. CONNECTED SUCCESSFULLY")
        await session.send_realtime_input(text="เปิด notepad ให้หน่อยค่ะ")
        
        tool_done = False
        audio_bytes = 0
        spoke_text = ""
        
        start = time.time()
        async for resp in session.receive():
            if time.time() - start > 20:
                print("TIMEOUT")
                break
            if resp.tool_call and not tool_done:
                fc = resp.tool_call.function_calls[0]
                print(f"2. TOOL CALL: {fc.name} with args: {fc.args}")
                tool_done = True
                
                # Send fake Antigravity supervisor response
                f_resp = types.FunctionResponse(
                    name=fc.name,
                    response={"result": "เปิดโปรแกรม Notepad ให้เรียบร้อยแล้วค่ะ"},
                    id=fc.id
                )
                print("3. SENDING FUNCTION RESPONSE...")
                await session.send_tool_response(function_responses=[f_resp])
            
            if resp.server_content:
                if resp.server_content.model_turn:
                    for p in resp.server_content.model_turn.parts:
                        if p.inline_data and p.inline_data.data:
                            audio_bytes += len(p.inline_data.data)
                if resp.server_content.output_transcription and resp.server_content.output_transcription.text:
                    spoke_text += resp.server_content.output_transcription.text
                if resp.server_content.turn_complete:
                    print(f"4. TURN COMPLETE! Spoke: '{spoke_text.strip()}', Audio: {audio_bytes} bytes")
                    break
        
        print(f"5. RESULT: ToolCalled={tool_done}, AudioBytes={audio_bytes}, Text='{spoke_text.strip()}'")

if __name__ == "__main__":
    asyncio.run(test_full_loop())
