# 🏛️ ATHENA BLUEPRINT (พิมพ์เขียวสถาปัตยกรรมระบบ Athena Project ฉบับสมบูรณ์)

---

## 🎯 วิสัยทัศน์และเป้าหมายสูงสุดของระบบ (Vision Statement)

> ### **"บอส ต้องการDesktop AGI Agent เต็มรูปแบบ ที่มีสมองคิดเอง คุยเสียงสดได้ และมีแขนกลทำงานแทนมนุษย์ได้ทุกอย่างบนคอมพิวเตอร์จริง ๆ"**

---

## 🏛️ 1. การแปลงวงจร Astra สู่สถาปัตยกรรม Athena_Project

| ขั้นตอนของ Astra | กลไกในระบบ Athena_Project ของเรา | ตัวอย่างการทำงานจริง |
| :--- | :--- | :--- |
| **1. ตีความเป้าหมายและข้อจำกัด** | **Antigravity Supervisor + Gemini Live Mouthpiece** | Gemini Live รับฟังเสียงบอสแล้วส่งต่อให้ Antigravity Supervisor ตีความเป้าหมายหลักและดักจับเงื่อนไขความปลอดภัย |
| **2. วางแผนงานหลายขั้นตอน** | **Antigravity Supervisor + UFO + agy** | แตกงานใหญ่ออกเป็น sub-tasks ทีละขั้น (เช่น 1. ดึงข้อมูล ➔ 2. ใส่ Excel ➔ 3. ร่างอีเมล) |
| **3. รับรู้สถานะบนหน้าจอ** | **ScreenObserver ( mss ) + UIA Inspector + DevTools** | มองจอแบบผสมผสาน (Hybrid): แคปภาพดูภาพรวม + อ่าน UIA Tree/DOM หาตำแหน่งปุ่มและฟิลด์จริง |
| **4. ลงมือควบคุมอินเทอร์เฟซ** | **Fast Action (Win32) + UFO Action + DevTools** | คลิก, พิมพ์ข้อความภาษาไทย/อังกฤษ, เลื่อนหน้าจอ, สลับแท็บ, แนบไฟล์ ผ่านคำสั่งระดับระบบ |
| **5. ประเมินผลทุกก้าว (Act ➔ Observe)** | **UFO EvaluationAgent + State Verification** | ตรวจทันทีหลังคลิกหรือพิมพ์ว่าหน้าจอเปลี่ยนตามที่ต้องการไหม ถ้าพิมพ์ไม่ติดจะลองสลับวิธีทันที |
| **6. จัดการงานระยะยาว** | **Cross-Context Notes & State Store** | บันทึกสถานะงานข้าม Session ไม่ลืมเป้าหมายหลัก แม้บอสจะสั่งงานอื่นแทรกระหว่างทาง |
| **7. การกำกับดูแลในจุดสำคัญ (Human-in-the-Loop)** | **Consequential Action Gate (ขออนุมัติด้วยเสียงสด)** | งานที่มีผลกระทบย้อนกลับไม่ได้ (เช่น กดส่งอีเมล, ลบไฟล์สำคัญ) เอเธน่าจะเอ่ยปากถามบอสออกลำโพงเพื่อขออนุมัติก่อนกดเสมอค่ะ |

---

## 💡 เปรียบเทียบให้เห็นภาพง่ายที่สุด:

* **AI (เช่น Astra หรือ Gemini):** คือ **"คนขับรถ"** ที่มองทาง คิดว่าจะเลี้ยวซ้ายหรือขวา
* **Harness (เช่น UFO, agy , Win32):** คือ **"พวงมาลัย คันเร่ง และชุดเกียร์"** ที่ถ่ายทอดแรงจากการตัดสินใจของคนขับ ไปหมุนล้อรถบนถนนจริงค่ะ

---

## 🔍 ชิ้นส่วน Harness ที่เรามีอยู่ในเครื่องจริง ๆ:

| ชิ้นส่วนที่มีในเครื่อง | ทำหน้าที่เป็น Harness อะไร | อยู่ที่ไหนในเครื่องบอส |
| :--- | :--- | :--- |
| **1. Fast Desktop Harness** | แขนกลคลิกเมาส์, พิมพ์คีย์บอร์ด, ย่อ/ขยาย/เปิดแอป (Win32 + UIA) จบในระดับมิลลิวินาที | `E:\Athena_Project\actions\desktop.py` |
| **2. Deep GUI Harness** | แขนกลแกะโครงสร้างหน้าต่างซับซ้อน (Control Tree) และตรวจงานด้วยสายตา (UFO Automator) | `E:\ufo\ufo\automator\ui_control\` |
| **3. Terminal & Code Harness** | แขนกลสั่ง Terminal, เขียนโค้ด, รันระบบเบื้องหลัง (เทียบเท่า Codex Harness ของ Astra) | `C:\Users\BUSOLOVE\AppData\Local\agy\bin\agy.exe` |
| **4. Browser Harness** | แขนกลควบคุมเบราว์เซอร์ กรอกฟอร์ม ท่องเว็บ ผ่าน CDP Protocol | `chrome-devtools-mcp` |
| **5. 3D & Office Harness** | แขนกลสั่ง Blender ขึ้นรูป 3D และสั่ง Excel/Word ใส่สูตรสร้างตารางผ่าน Windows COM | `blender-mcp` และ UFO Office Server |

---

## 🏛️ 2. ผังสถาปัตยกรรมระบบ (Athena Project Architecture)

```mermaid
graph TB
    subgraph USER ["👤 ผู้ใช้งาน (BOSS)"]
        direction LR
        BossVoice["🗣️ สั่งด้วยเสียงสด (Microphone)"]
        BossEyes["👀 ดูผลลัพธ์บนจอ (Display)"]
        BossEars["👂 ฟังเสียงตอบกลับ (Speaker)"]
    end

    subgraph VOICE_GATE ["🎙️ INTERFACE: ท่อเสียงสดสองทาง (Live Audio Mouthpiece)"]
        direction TB
        GeminiLive["Google Gemini Live API (gemini-3.1-flash-live-preview)<br/>- รับเสียงไมค์สด PCM 16kHz<br/>- พูดเสียงสด PCM 24kHz (Kore) ทันทีแบบ Zero-Latency<br/>- ตัดเสียงทันทีเมื่อบอสพูดแทรก (Barge-in / Interruption)<br/>- ❌ ไม่คิดเอง / ❌ ไม่แชตคุยเอง (100% Puppet)"]
        MouthpieceTool["ask_antigravity(user_speech)<br/>(ท่อส่งคำพูดบอสเข้าสมองหลักทันที)"]
        GeminiLive --> MouthpieceTool
    end

    subgraph BRAIN ["🧠 LAYER 1: สมองบริหารสูงสุด (Antigravity Supervisor)"]
        direction TB
        AntigravityBrain["AntigravitySupervisor (gemini-3.1-pro-preview / 3.6-flash)<br/>- วิเคราะห์เจตนา วางแผนหลายขั้นตอน (Multi-step Reasoning)<br/>- รักษาบุคลิกภาพเลขาบริหารเอเธน่า 100% (ฉลาด คมคาย สุภาพ)<br/>- ควบคุมคุณภาพคำตอบ (ตัดคำถามเซ้าซี้, ลงท้าย 'ค่ะ' เสมอ)<br/>- Cascade Fallback อัตโนมัติเมื่อชน Rate Limit"]
        ClosedLoop["Closed-Loop Verifier<br/>(ตรวจสอบผลลัพธ์จริงบนจอ/ระบบก่อนสรุป)"]
        AntigravityBrain --- ClosedLoop
    end

    subgraph CORE ["🏛️ LAYER 2: ศูนย์สั่งการ (Athena Core)"]
        AthenaCore["AthenaCore Router<br/>(athena_core.py)"]
        SafetyGate["Safety Guard & Consequential Check<br/>(ถามขออนุมัติด้วยเสียงก่อนกดส่ง/ลบ)"]
        AthenaCore --- SafetyGate
    end

    subgraph ENGINES ["🦾 LAYER 3: 3 แขนกลปฏิบัติการจริงในเครื่อง"]
        FastAction["⚡ Fast Action (Win32 / UIA)<br/>- ย่อ / ขยาย / สลับหน้าต่าง<br/>- คลิกพิกัด / พิมพ์ด่วน (~0.05s)"]
        UFOEngine["🛸 Microsoft UFO<br/>- แกะโครงสร้าง Control Tree<br/>- กรอกฟอร์มข้ามหลายแอป<br/>- Office COM (Excel, Word, PPT)"]
        AGYEngine["💻 Antigravity CLI (agy)<br/>- รัน Terminal / Shell commands<br/>- เขียนและแก้โค้ดอัตโนมัติ<br/>- จัดการไฟล์และ Background Tasks"]
    end

    subgraph OS ["💻 LAYER 4: สภาพแวดล้อมจริง (Windows 11)"]
        WinOS["Windows 11 Desktop & Applications<br/>(Chrome, Notepad, Office, Terminal, etc.)"]
    end

    %% Flow lines
    BossVoice -->|สตรีมเสียงสด PCM 16kHz| GeminiLive
    MouthpieceTool -->|ส่งคำสั่งดิบเข้าสมอง| AntigravityBrain
    AntigravityBrain -->|สั่งการปฏิบัติการ| AthenaCore
    
    AthenaCore -->|คำสั่งหน้าต่าง/เมาส์ด่วน| FastAction
    AthenaCore -->|งาน UI ลึก / กรอกข้อมูล / Office| UFOEngine
    AthenaCore -->|งานโค้ด / จัดการระบบ / Terminal| AGYEngine

    FastAction --> WinOS
    UFOEngine --> WinOS
    AGYEngine --> WinOS

    WinOS -.->|สถานะและผลลัพธ์ส่งกลับ| ClosedLoop
    ClosedLoop -.->|ยืนยันผลสำเร็จ| AntigravityBrain
    AntigravityBrain -->|ส่งข้อความคำตอบระดับบริหาร| MouthpieceTool
    MouthpieceTool -->|อ้าปากอ่านคำตอบสดทันที (FunctionResponse)| GeminiLive
    GeminiLive -->|สตรีมเสียงสด PCM 24kHz (<1s)| BossEars
    BossEyes -.->|ดูผลงานจริงบนจอ| WinOS
```

### 🔍 สรุปการแบ่งเลเยอร์ตามสถาปัตยกรรมใหม่:

1. **Voice Interface (ท่อเสียงสดสองทาง): Gemini Live (`AntigravityLiveVoice`)** 
   - ทำหน้าที่เป็น "ปากและหูสด" (Live Audio Mouthpiece) รับเสียงไมค์สด PCM 16kHz และสตรีมเสียงสด 24kHz ตอบกลับทันที พร้อมระบบ Barge-in ตัดเสียงเมื่อบอสพูดแทรก
   - **ไม่มีหน้าที่คิดเองหรือสนทนาเองเด็ดขาด** เมื่อได้ยินเสียงบอส จะส่งคำพูดผ่าน `ask_antigravity` เข้าสู่สมองหลักทันที และเมื่อสมองตอบกลับมา จะอ้าปากอ่านคำตอบนั้นออกมาเป็นเสียงสด 100%
2. **Layer 1 (สมองหลักระดับบริหาร): Antigravity Supervisor**
   - ใช้โมเดลระดับคิดวิเคราะห์ลึกซึ้งสูงสุด (`gemini-3.1-pro-preview` พร้อม Fallback สู่ `gemini-3.6-flash`)
   - คิด วางแผน ตัดสินใจ และควบคุมพฤติกรรมเลขาบริหารเอเธน่า (พูดจาฉลาด คมคาย ไม่เซ้าซี้ ลงท้าย 'ค่ะ' เสมอ)
   - มีระบบ Closed-Loop Verification ตรวจสอบว่าแอปเปิดจริงไหม พิมพ์ติดจริงไหม ก่อนสรุปคำตอบ
3. **Layer 2 (ศูนย์กลางควบคุม): Athena Core** 
   - รับคำสั่งจากสมอง ตรวจสอบความปลอดภัย (Safety Guard) และแยกงานส่งไปยังแขนกลที่ตรงจุด
4. **Layer 3 (3 แขนกลปฏิบัติการจริง):**
   * **Fast Action (Win32/UIA):** สำหรับงานสลับจอ ย่อ ขยาย คลิก พิมพ์ ที่ต้องการความเร็วระดับ 0.05 วินาที
   * **Microsoft UFO:** สำหรับงานควบคุมโปรแกรมซับซ้อน แกะปุ่มลึก ๆ กรอกฟอร์ม และสั่งสร้างไฟล์ Office (Excel, Word, PPT)
   * **Antigravity CLI ( agy ):** สำหรับงานสาย Terminal เขียนโค้ด จัดการไฟล์ และงานวิศวกรรมระบบ
5. **Layer 4 (เครื่องคอมพิวเตอร์จริง):** หน้าจอโปรแกรมและระบบปฏิบัติการ **Windows 11** ของบอสค่ะ

---

## 🥊 3. ตารางเปรียบเทียบ: บอทตอนนี้ VS แนวทางใหม่

| มิติการทำงาน | ❌ บอทที่บอสไม่ต้องการ | 🟢 แนวทางใหม่ระดับ Astra (New Architecture) |
| :--- | :--- | :--- |
| **1. การตัดสินใจ (Decision Making)** | **ดักคำด้วย if-else ตายตัว** เช่น `if "ย่อ" in cmd:` พูดคำไม่ตรงคีย์เวิร์ดจะไม่เข้าใจ เหมือนแชตบอทโบราณ | **Antigravity Supervisor คิดและตัดสินใจเอง 100%** (Pro/Flash Cascade) มีเหตุผลลึกซึ้ง บุคลิกเลขาบริหาร คมคาย ไม่เซ้าซี้ และมี Closed-Loop ตรวจผลจริง |
| **2. ความเร็วในการตอบสนอง (Speed)** | **ช้ามาก (77 วินาที)** เพราะรัน UFO โดด ๆ ต้องแคปภาพและวิเคราะห์ซ้ำซ้อนทุกสเต็ป | **ระดับเสี้ยววินาที (<1 วินาที)** สมองโต้ตอบทันที และส่งคำสั่งด่วนผ่าน Win32/UIA จบงานใน 0.05–1.5 วินาที |
| **3. การคุยด้วยเสียง (Voice Interaction)** | **ยังไม่ได้เชื่อมเป็นระบบเดียว** หรือใช้ TTS แข็งทื่อ | **ระบบเสียงสดสองทาง (Gemini Live Mouthpiece):** อ้าปากอ่านคำตอบ Antigravity ออกมาเป็นเสียงสดทันที ไม่ใช้ TTS ดั้งเดิม และ **พูดแทรก (Barge-in) ได้ทันที** |
| **4. การควบคุมโปรแกรม (Computer Use)** | **พยายามรันคำสั่ง Shell แล้วติดลูป Windows 11** (เช่น Notepad ค้างใน background) | **เรียกใช้ Harness ตรงจุด:** ใช้ Fast Action คุมหน้าต่างด่วน + ใช้ UFO/COM สั่ง Excel, Word, PPT โดยตรง |
| **5. งานเขียนโค้ดและระบบ (Code & OS)** | **ไม่มีตัวขับเคลื่อนงานโค้ด** สั่งงาน Terminal อัตโนมัติไม่ได้ | **มี Antigravity CLI ( agy ) เป็นแขนกล:** สั่งแก้บั๊ก เขียนโค้ด และรันสคริปต์เบื้องหลังแบบ Autonomous |
| **6. ความปลอดภัยและการยืนยัน (Safety)** | **ทำงานแบบเดาสุ่ม** หรือหลอนว่าทำเสร็จทั้งที่หน้าต่างว่างเปล่า | **ถามขออนุมัติด้วยเสียงสด (Human-in-the-loop):** งานเสี่ยงสูง (ส่งเมล, ลบไฟล์) จะเอ่ยปากถามบอสก่อนกดเสมอ |

---

## ⚙️ ข้อมูลเชิงลึก: การทำงานแทนมนุษย์ได้ทุกอย่างบนคอมพิวเตอร์จริง ๆ

เพื่อให้บรรลุวิสัยทัศน์ของบอส เอเธน่าจัดสรรเครื่องมือและ Harness รองรับงานทุกประเภทดังนี้:

1. **งานเอกสารและสเปรดชีต (Spreadsheets & Office):**
   * ใช้ **Microsoft UFO (Office COM Server)** สั่งเปิด Excel, ใส่สูตรคำนวณ, สร้าง Pivot Table, จัดฟอร์แมตเซลล์, และสร้างสไลด์ PowerPoint โดยไม่ต้องพึ่งการคลิกแบบสุ่มสี่สุ่มห้า
2. **งานอีเมลและการสื่อสาร (Email & Web Messaging):**
   * ใช้ **Browser Harness (`chrome-devtools-mcp`)** ล็อกอินและเข้าถึง DOM โดยตรงเพื่อค้นหาช่องผู้รับ กรอกหัวข้อ ร่างเนื้อหา และแนบไฟล์ พร้อมใช้ระบบ Consequential Gate ขออนุมัติจากบอสด้วยเสียงก่อนกด "ส่ง"
3. **งานกราฟิกและโมเดล 3 มิติ (3D Modeling & Graphics):**
   * ใช้ **`blender-mcp`** สั่งรัน Python script บน Blender เพื่อสร้างวัตถุ 3D, จัดแสง, ปรับ Texture และ Render ภาพอัตโนมัติ
4. **งานวิศวกรรมซอฟต์แวร์และการจัดการระบบ (Coding & DevOps):**
   * ใช้ **Antigravity CLI (`agy.exe`)** เป็นแขนกลระดับโปรเกรสซีฟในการสร้างโปรเจกต์ ตรวจสอบโค้ด รันการทดสอบ ยิง Git commit และจัดการ Service เบื้องหลัง
5. **งานทั่วไปบนหน้าจอ Windows (General OS Navigation):**
   * สลับหน้าต่างด้วย **`actions/desktop.py` (Win32)** ใน 0.05 วินาที ควบคุมเมาส์/คีย์บอร์ดระดับพิกเซลที่แม่นยำ พร้อมสายตา **`vision/screen.py` (ScreenObserver)** ที่ตรวจทานผลลัพธ์ทันทีค่ะ
