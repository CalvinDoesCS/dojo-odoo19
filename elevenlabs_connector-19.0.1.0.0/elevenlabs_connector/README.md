# AI Voice Assistant for Odoo 19

Hands‑free voice assistant for Odoo 19 using **ElevenLabs Speech‑to‑Text** and direct AI calls
to **OpenAI** or **Google Gemini** – no external proxy, no Odoo AI stack, and no TTS complexity.

> Built and tested for Odoo 19 / Odoo.sh. Perfect for users who want to talk to their AI
> assistant directly from the Odoo backend (CRM, Sales, HR, etc.).

---

## Overview

This module adds a Voice Assistant to the Odoo backend. Users press a microphone button,
speak their question, and receive an instant AI‑generated answer displayed directly in Odoo.
All voice processing happens as:

1. Browser microphone → audio stream.
2. ElevenLabs **Speech‑to‑Text** (STT) → transcribed text.
3. Direct HTTP call from Odoo to **OpenAI** or **Gemini** → AI answer.
4. Answer shown under the microphone and stored in **Conversation History**.

There is **no Text‑to‑Speech (TTS)** – answers are text‑only, which keeps the flow fast,
robust on Odoo.sh and avoids audio output complexity.

---

## Key Features

- **Voice input in the Odoo backend**
  - Microphone button inside a modern OWL widget.
  - Works in any modern browser (HTTPS required for microphone API).

- **High‑quality Speech‑to‑Text with ElevenLabs**
  - Uses ElevenLabs STT API with configurable language and voice model ID.
  - Audio is converted to text; the text is what is stored in Odoo.

- **Direct AI calls (no Odoo AI provider layer)**
  - **OpenAI**: Chat Completions endpoint via HTTPS.
  - **Google Gemini**: Generative Language API via HTTPS.
  - No dependence on `ai.provider` or Odoo’s internal AI stack, avoiding latin‑1 encoding issues.

- **UTF‑8 safe & Odoo.sh friendly**
  - All HTTP requests/responses are forced to UTF‑8.
  - AI outputs are sanitized to ASCII where needed to avoid server crashes.

- **Conversation history**
  - Model `voice.conversation` stores:
    - User (res.users)
    - Transcribed text
    - AI response
    - Processing time and error details (if any)
  - Viewable from **Voice Assistant → Conversation History**.

- **Central configuration under AI**
  - Menu: **AI → Configuration → ElevenLabs Voice Connector**.
  - Configure:
    - ElevenLabs API key, language and optional voice ID.
    - OpenAI API key.
    - Google Gemini API key.
    - Which provider to use for answers (OpenAI vs Gemini).
  - Direct links to the relevant provider “API keys” pages for convenience.

---

## Installation

### Requirements

- **Odoo 19.0** (including Odoo.sh)
- Python library `requests` (usually already installed)

If for some reason `requests` is missing, install it in your environment:

```bash
pip install requests
```

No additional Python SDKs (OpenAI, Google, ElevenLabs) are required – all APIs are called
via raw HTTPS requests from Odoo using `requests`.

### Module Installation

1. Add the `elevenlabs_connector` directory to your Odoo addons path.
2. Update the Apps list.
3. Install **“ElevenLabs Voice Connector”**.
4. Ensure the official **AI app** (`ai_app`) is installed (required for the AI menu).

---

## Configuration

Open **AI → Configuration → ElevenLabs Voice Connector**.

### ElevenLabs

1. Paste your **ElevenLabs API key**  
   (Get it from: <https://elevenlabs.io/app/settings/api-keys>).
2. Optionally set a **Default Voice ID** (e.g. `21m00Tcm4TlvDq8ikWAM`).
3. Choose the **Language** for transcription.
4. Click **Test Connection** to verify the ElevenLabs API key.

### OpenAI

1. Paste your **OpenAI API key**  
   (Get it from: <https://platform.openai.com/api-keys>).
2. No model field is exposed in Odoo – the module handles model choice internally.

### Google Gemini

1. Paste your **Gemini API key**  
   (Get it from: <https://aistudio.google.com/app/apikey>).
2. The module automatically chooses a supported model based on the available options.

### Provider Selection

1. Choose **AI Provider**:
   - `OpenAI` or `Gemini`.
2. The Voice Assistant will send all transcribed questions to the selected provider.

---

## Usage

### Voice Assistant (backend widget)

1. Open the **Voice Assistant** entry in the Odoo backend (menu added by the module).
2. Click the large **microphone button** to start recording.
3. Ask your question out loud (e.g. “How many opportunities do I have in my CRM?”).
4. Click again to stop recording.
5. When processing finishes, you will see:
   - **“You said”** – the transcribed text.
   - **“AI Response”** – the textual answer from OpenAI or Gemini.
6. The conversation is saved in **Conversation History**.

### Conversation History

1. Go to **Voice Assistant → Conversation History**.
2. Browse past voice interactions per user:
   - Date & time.
   - Transcribed question.
   - AI answer.
   - Any technical error message (for admin debugging).

---

## Technical Architecture

- **Models**
  - `voice.conversation`: persists each interaction.
  - `res.config.settings` (inherited): stores API keys and provider selection.
  - `elevenlabs.service` (abstract): encapsulates ElevenLabs STT HTTP calls.
  - `ai.processor` (abstract): centralizes OpenAI/Gemini HTTP logic and sanitization.
  - `voice.service`: orchestrates STT → AI → response + history.

- **Flow**
  1. Browser records audio (MediaRecorder API).
  2. Audio is base64‑encoded and sent to `/elevenlabs/voice/process`.
  3. Backend calls `elevenlabs.service.transcribe_audio()` → text.
  4. `voice.service` calls `ai.processor.process_query()` → AI answer.
  5. Result is saved in `voice.conversation` and returned to the widget.

- **Encoding & Safety**
  - All HTTP responses are forced to UTF‑8, avoiding latin‑1 crashes.
  - AI responses are sanitized to ASCII where needed to stay safe in logs/UI.

---

## Security & Data Handling

- API keys are stored in **Odoo config parameters** (`ir.config_parameter`) and are not
  visible to normal users.
- Each conversation is linked to the **current Odoo user**.
- No raw audio is sent to third‑party services other than ElevenLabs STT.
- No direct SQL is executed; all access is through the ORM with standard record rules.

---

## Extensibility

- You can extend `ai.processor` to plug in additional AI providers by overriding
  `_process_custom()` in your own module.
- You can extend `voice.service` to support other audio sources (e.g. VOIP streams)
  by implementing `process_voip_stream()` and adapting the audio format before
  passing it to `process_voice_request()`.

---

## Support & Issues

If you encounter problems on Odoo.sh or on‑premise installations (especially around
encoding, API errors, or browser microphone access), check the **Conversation History**
for the error details and review the Odoo logs.  
For commercial support and customization, please contact **Dow Group** via the website
listed in the module manifest.
│   ├── elevenlabs_service.py
│   ├── ai_processor.py
│   ├── voice_query_processor.py
│   ├── voice_conversation.py
│   └── voice_service.py
├── controllers/
│   ├── __init__.py
│   └── voice_controller.py
├── views/
│   ├── res_config_settings_views.xml
│   ├── voice_conversation_views.xml
│   └── voice_page_templates.xml
├── static/
│   └── src/
│       ├── css/
│       ├── js/
│       └── xml/
└── security/
    └── ir.model.access.csv
```

## License

LGPL-3

## Author

Dow Group

## Support

For issues and feature requests, please contact support or create an issue in the repository.

## Changelog

### Version 19.0.1.0.0

- Initial release
- ElevenLabs TTS/STT integration
- AI provider abstraction
- Database query processor
- Voice widget and dedicated page
- Conversation history
- Security and audit logging


