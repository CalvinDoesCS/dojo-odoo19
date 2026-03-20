# Dojo AI Assistant

A reusable, centralized AI assistant service for Dojo modules. It processes natural language
commands (typed or spoken) from instructors, admins, and kiosk users, turning them into
structured database actions with a confirmation step before any write is made.

---

## How It Works

### High-Level Flow

```
User input (text or voice)
        │
        ▼
[ai_processor_ext.py]
  Conversational query → OpenAI / Gemini
  → free-form response text + optional inline intent block
        │
        ▼  (if no confident intent found, falls back to:)
  Structured intent query → OpenAI JSON mode / Gemini
  → JSON: { intent_type, parameters, confidence, resolved_entities }
        │
        ▼
[ai_assistant_service.py]  parse_and_confirm()
  • Validate intent type against _KNOWN_INTENT_TYPES
  • Apply keyword override rules (e.g. "roster" → course_enroll)
  • Recover missing parameters from raw text when the AI drops them
  • Resolve entity names → database IDs  (_resolve_entities)
  • Check role permission (dojo.ai.intent.schema)
  • Log the parse in dojo.ai.action.log
        │
        ├─── Read-only intent? ──► auto-execute → return result immediately
        │
        └─── Mutating intent? ──► return confirmation_prompt + session_key
                                          │
                                    User confirms
                                          │
                                          ▼
                              execute_confirmed(session_key)
                                → _execute_intent() → handler method
                                → log result + create undo snapshot
```

### Two-Phase Confirmation Flow

| Phase | Entry point | What happens |
|-------|-------------|--------------|
| **Phase 1 – Parse** | `handle_command()` / `parse_and_confirm()` | AI parses natural language into an intent. Read-only intents auto-execute. Mutating intents return `state: "pending_confirmation"` with a human-readable `confirmation_prompt` and a `session_key`. |
| **Phase 2 – Execute** | `execute_confirmed(session_key)` | The frontend calls this after the user says "Yes". The intent is run and the result (plus undo info) is returned. |

---

## Are Commands Manually Created?

**Yes.** Every command (called an *intent*) is manually wired up in three places:

### 1. Intent Schema Record (`data/ai_intent_schema_data.xml`)

Each intent is a database record in `dojo.ai.intent.schema` that tells the LLM what the
command does, what parameters it expects, and who is allowed to run it:

```xml
<record id="intent_belt_promote" model="dojo.ai.intent.schema">
    <field name="intent_type">belt_promote</field>
    <field name="name">Promote Belt Rank</field>
    <field name="description">Promote a member to a new belt rank</field>
    <field name="category">belt</field>
    <field name="parameters_schema">{
"type": "object",
"properties": {
    "member_name": {"type": "string"},
    "new_belt":    {"type": "string"}
}}</field>
    <field name="example_phrases">Promote John to blue belt
Give Sarah her orange belt</field>
    <field name="allowed_roles">instructor,admin</field>
    <field name="requires_confirmation">True</field>
    <field name="is_undoable">True</field>
</record>
```

These records are injected into the LLM system prompt at runtime so the model knows exactly
which intent types exist and what parameters they carry.

### 2. Intent Type Registry (`models/ai_assistant_service.py`)

The Python service keeps two hardcoded sets that must include every intent:

```python
# Auto-execute without user confirmation (read-only intents)
_AUTO_EXECUTE_INTENTS = {
    "member_lookup", "class_list", "belt_lookup", ...
}

# Every recognised intent type (must match handler keys)
_KNOWN_INTENT_TYPES = {
    "member_lookup", "belt_promote", "member_enroll", ...
}
```

Any intent type not in `_KNOWN_INTENT_TYPES` is silently downgraded to `"unknown"`.

### 3. Handler Method (`models/ai_assistant_service.py`)

Each intent type maps to a Python method via the dispatch dict in `_execute_intent()`:

```python
handlers = {
    "member_lookup":  self._handle_member_lookup,
    "belt_promote":   self._handle_belt_promote,
    "member_enroll":  self._handle_member_enroll,
    ...
}
```

Each `_handle_*` method receives `(intent_data, resolved_data, action_log)` and returns
a standard result dict `{ "success": bool, "message": str, "data": dict }`.

---

## All Available Intents

| Intent Type | Category | Auto-execute | Undoable | Roles |
|-------------|----------|:---:|:---:|-------|
| `member_lookup` | Read | ✅ | ❌ | kiosk, instructor, admin |
| `class_list` | Read | ✅ | ❌ | kiosk, instructor, admin |
| `schedule_today` | Read | ✅ | ❌ | kiosk, instructor, admin |
| `belt_lookup` | Read | ✅ | ❌ | kiosk, instructor, admin |
| `subscription_lookup` | Read | ✅ | ❌ | instructor, admin |
| `attendance_history` | Read | ✅ | ❌ | instructor, admin |
| `at_risk_members` | Read | ✅ | ❌ | instructor, admin |
| `campaign_lookup` | Read | ✅ | ❌ | instructor, admin |
| `marketing_card_lookup` | Read | ✅ | ❌ | instructor, admin |
| `attendance_checkin` | Attendance | ❌ | ✅ | kiosk, instructor, admin |
| `attendance_checkout` | Attendance | ❌ | ✅ | kiosk, instructor, admin |
| `member_enroll` | Enrollment | ❌ | ✅ | instructor, admin |
| `member_unenroll` | Enrollment | ❌ | ✅ | instructor, admin |
| `course_enroll` | Enrollment | ❌ | ✅ | instructor, admin |
| `belt_promote` | Belt | ❌ | ✅ | instructor, admin |
| `belt_test_register` | Belt | ❌ | ❌ | instructor, admin |
| `subscription_create` | Subscription | ❌ | ❌ | instructor, admin |
| `subscription_cancel` | Subscription | ❌ | ❌ | instructor, admin |
| `subscription_pause` | Subscription | ❌ | ❌ | instructor, admin |
| `subscription_resume` | Subscription | ❌ | ❌ | instructor, admin |
| `contact_parent` | Communication | ❌ | ❌ | instructor, admin |
| `member_create` | Member | ❌ | ❌ | instructor, admin |
| `member_update` | Member | ❌ | ❌ | instructor, admin |
| `class_create` | Class | ❌ | ❌ | instructor, admin |
| `class_cancel` | Class | ❌ | ❌ | instructor, admin |
| `campaign_create` | Marketing | ❌ | ❌ | admin |
| `campaign_activate` | Marketing | ❌ | ❌ | admin |
| `social_post_create` | Social | ❌ | ❌ | admin |
| `social_post_schedule` | Social | ❌ | ❌ | admin |
| `undo_action` | System | ❌ | ❌ | kiosk, instructor, admin |
| `unknown` | System | ✅ | ❌ | all |

---

## Adding a New Command

To add a new intent you must make changes in three places:

### Step 1 — Add the intent schema record

Add a `<record>` to `data/ai_intent_schema_data.xml`:

```xml
<record id="intent_my_new_command" model="dojo.ai.intent.schema">
    <field name="intent_type">my_new_command</field>
    <field name="name">My New Command</field>
    <field name="description">What this command does (shown to the LLM)</field>
    <field name="category">member</field>  <!-- see category choices in model -->
    <field name="parameters_schema">{
"type": "object",
"properties": {
    "member_name": {"type": "string", "description": "Name of the member"}
}}</field>
    <field name="example_phrases">Example phrase one
Another example phrase</field>
    <field name="allowed_roles">instructor,admin</field>
    <field name="requires_confirmation">True</field>  <!-- False = auto-execute -->
    <field name="is_undoable">False</field>
    <field name="supports_bulk">False</field>
    <field name="active">True</field>
</record>
```

### Step 2 — Register the intent type in `ai_assistant_service.py`

Add the new string to both sets at the top of the file:

```python
_AUTO_EXECUTE_INTENTS = {
    ...,
    "my_new_command",   # only if requires_confirmation=False
}

_KNOWN_INTENT_TYPES = {
    ...,
    "my_new_command",
}
```

And add it to the `handlers` dict inside `_execute_intent()`:

```python
handlers = {
    ...,
    "my_new_command": self._handle_my_new_command,
}
```

### Step 3 — Implement the handler method

Add a method to `AiAssistantService` (or a mixin/extension model):

```python
@api.model
def _handle_my_new_command(self, intent_data, resolved_data, action_log):
    """Handle my_new_command intent."""
    member_id = resolved_data.get("member_id")
    if not member_id:
        return {"success": False, "error": "Member not found."}

    member = self.env["dojo.member"].browse(member_id)
    # ... do the work ...
    return {
        "success": True,
        "message": f"Done for {member.name}.",
        "data": {"member_id": member.id},
    }
```

---

## Architecture Overview

```
dojo_assistant/
├── models/
│   ├── ai_intent_schema.py       # dojo.ai.intent.schema — intent definitions
│   ├── ai_processor_ext.py       # ai.processor extension — LLM calling logic
│   ├── ai_assistant_service.py   # ai.assistant.service — orchestration + handlers
│   ├── ai_action_log.py          # dojo.ai.action.log — audit trail
│   └── ai_undo_snapshot.py       # dojo.ai.undo.snapshot — undo state
├── controllers/
│   └── main.py                   # HTTP endpoints (/dojo/ai/*)
├── data/
│   ├── ai_intent_schema_data.xml # Seed data: all intent definitions
│   └── ir_cron.xml               # Scheduled jobs (e.g. log cleanup)
└── views/                        # Odoo backend views for intent management
```

### Key Models

| Model | Purpose |
|-------|---------|
| `dojo.ai.intent.schema` | Defines available intents: parameters, roles, confirmation requirement, undo support |
| `ai.processor` (from `elevenlabs_connector`) | Base LLM caller (OpenAI / Gemini) |
| `ai.assistant.service` | Main orchestrator: parses input, resolves entities, routes to handlers |
| `dojo.ai.action.log` | Audit log for every AI parse + execution |
| `dojo.ai.undo.snapshot` | Before-state snapshots for undoable actions |

### HTTP Endpoints

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/dojo/ai/text` | Submit a text query |
| POST | `/dojo/ai/voice` | Submit an audio file (ElevenLabs STT → query) |
| POST | `/dojo/ai/confirm` | Confirm or reject a pending action |
| POST | `/dojo/ai/undo` | Request undo of last undoable action |
| GET  | `/dojo/ai/history` | Retrieve recent action history |
| GET  | `/dojo/ai/intents` | List available intents for the current user's role |

### AI Provider Support

The assistant supports two LLM providers, configured in Odoo settings:

- **OpenAI** (`gpt-4o-mini`) — uses JSON response mode for structured intent parsing
- **Google Gemini** (`gemini-1.5-flash`) — uses firm JSON-only prompting

For intent parsing the system uses a two-step strategy:
1. **Conversational mode** — free-form response with an optional inline `##INTENT##` block
2. **Structured mode** (fallback) — JSON-only response when the conversational result has
   low confidence or an unrecognised intent type

---

## Configuration

Settings live under **AI → Configuration → ElevenLabs Voice Connector**:

| Setting | Key | Notes |
|---------|-----|-------|
| OpenAI API key | `openai.api_key` | Required for OpenAI provider |
| Gemini API key | `gemini.api_key` | Required for Gemini provider |
| Active provider | `elevenlabs_connector.ai_provider` | `openai` or `gemini` |
| Undo expiry (minutes) | `dojo_assistant.undo_expiry_minutes` | Default 60 |

---

## Security

- All endpoints require `auth="user"` — users must be logged in.
- Role (`kiosk` / `instructor` / `admin`) is derived from the user's Odoo groups and
  checked against `dojo.ai.intent.schema.allowed_roles` before any execution.
- API keys are stored in `ir.config_parameter` and are not exposed to normal users.
- Every AI action is logged in `dojo.ai.action.log` for auditing.
