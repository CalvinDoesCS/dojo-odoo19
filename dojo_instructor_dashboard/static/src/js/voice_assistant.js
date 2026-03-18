/** @odoo-module **/
/**
 * Dojo AI Voice Assistant — floating chat panel for the instructor and admin
 * dashboards.
 *
 * Features
 * --------
 *  • Text input — type and send a message
 *  • Voice input — click the mic button to record, click again to submit
 *  • AI responses via the dojo-scoped /dojo/ai/* endpoints
 *  • Contact-parent action card — AI can propose a draft message; the user
 *    can edit subject / body, toggle email/SMS, and confirm the send
 *  • Optional text-to-speech — browser SpeechSynthesis reads AI responses aloud
 */

import { Component, useState, useRef, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

// ─── helpers ────────────────────────────────────────────────────────────────

function nowLabel() {
    return new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function htmlToPlain(html) {
    if (!html) return "";
    const tmp = document.createElement("div");
    tmp.innerHTML = html;
    return tmp.textContent || tmp.innerText || "";
}


// ─── component ──────────────────────────────────────────────────────────────

export class DojoVoiceAssistant extends Component {
    static template = "dojo_instructor_dashboard.VoiceAssistant";

    setup() {
        this.notification = useService("notification");
        this.inputRef      = useRef("msgInput");
        this.endRef        = useRef("msgEnd");

        this.state = useState({
            open: false,
            messages: [],          // [{role, text, time}]
            input: "",
            recording: false,
            processing: false,
            ttsEnabled: false,     // auto-speak AI responses
            pendingAction: null,   // contact_parent action dict from AI
            actionSubject: "",
            actionBody: "",
            actionEmail: true,
            actionSms: true,
            // Two-phase confirmation flow
            pendingConfirm: null,  // {session_key, prompt, intent_type}
        });

        this._mediaRecorder = null;
        this._audioChunks   = [];
        this._stream        = null;

        onMounted(() => {
            // Keyboard shortcut: Ctrl+Shift+A to toggle panel
            document.addEventListener("keydown", (e) => {
                if (e.ctrlKey && e.shiftKey && e.key === "A") this.toggle();
            });
        });
    }

    // ── panel open / close ───────────────────────────────────────────────────

    toggle() {
        this.state.open = !this.state.open;
        if (this.state.open && this.state.messages.length === 0) {
            this._pushMsg("assistant", "👋 Hi! I can help you look up students, check class schedules, or send messages to parents. What would you like to do?");
        }
        if (this.state.open) {
            setTimeout(() => this._scrollToBottom(), 60);
            setTimeout(() => this.inputRef.el && this.inputRef.el.focus(), 80);
        }
    }

    close() { this.state.open = false; }

    // ── messaging ────────────────────────────────────────────────────────────

    onInputKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.send();
        }
    }

    onInputChange(ev) {
        this.state.input = ev.target.value;
    }

    async send() {
        const text = (this.state.input || "").trim();
        if (!text || this.state.processing) return;
        this.state.input = "";
        await this._submitText(text);
    }

    async _submitText(text) {
        this._pushMsg("user", text);
        this.state.processing = true;
        this._scrollToBottom();

        try {
            const result = await rpc("/dojo/ai/text", { text });
            if (result.success) {
                this._handleAiResult(result);
            } else {
                this._pushMsg("assistant", "⚠️ " + (result.error || "Unknown error."));
            }
        } catch (err) {
            this._pushMsg("assistant", "⚠️ Network error — please try again.");
        } finally {
            this.state.processing = false;
            this._scrollToBottom();
        }
    }

    // ── voice recording ──────────────────────────────────────────────────────

    async toggleRecording() {
        if (this.state.recording) {
            this._stopRecording();
        } else {
            await this._startRecording();
        }
    }

    async _startRecording() {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            this.notification.add("Microphone not available in this browser.", { type: "warning" });
            return;
        }
        try {
            this._stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch (err) {
            this.notification.add("Microphone access denied. Please allow it in your browser.", { type: "warning" });
            return;
        }

        this._audioChunks = [];
        const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
            ? "audio/webm;codecs=opus"
            : "audio/webm";
        this._mediaRecorder = new MediaRecorder(this._stream, { mimeType });

        this._mediaRecorder.ondataavailable = (e) => {
            if (e.data && e.data.size > 0) this._audioChunks.push(e.data);
        };
        this._mediaRecorder.onstop = () => this._processRecording();

        this._mediaRecorder.start(250); // collect in 250 ms slices
        this.state.recording = true;

        // Auto-stop after 60 seconds
        this._recordTimeout = setTimeout(() => {
            if (this.state.recording) this._stopRecording();
        }, 60000);
    }

    _stopRecording() {
        if (this._recordTimeout) {
            clearTimeout(this._recordTimeout);
            this._recordTimeout = null;
        }
        if (this._mediaRecorder && this._mediaRecorder.state !== "inactive") {
            this._mediaRecorder.stop();
        }
        if (this._stream) {
            this._stream.getTracks().forEach((t) => t.stop());
            this._stream = null;
        }
        this.state.recording = false;
    }

    async _processRecording() {
        if (!this._audioChunks.length) return;
        const blob = new Blob(this._audioChunks, { type: "audio/webm" });
        this._audioChunks = [];

        this._pushMsg("user", "🎙️ [voice message]");
        this.state.processing = true;
        this._scrollToBottom();

        const formData = new FormData();
        formData.append("audio", blob, "recording.webm");

        try {
            const resp = await fetch("/dojo/ai/voice", {
                method: "POST",
                body: formData,
                // Odoo session cookie is sent automatically via the browser
            });
            const result = await resp.json();

            if (result.success) {
                // Replace placeholder with actual transcription
                const msgs = this.state.messages;
                const lastUser = [...msgs].reverse().find((m) => m.role === "user");
                if (lastUser && lastUser.text === "🎙️ [voice message]") {
                    lastUser.text = "🎙️ " + result.transcribed;
                }
                this._handleAiResult(result);
            } else {
                this._pushMsg("assistant", "⚠️ " + (result.error || "Voice processing failed."));
            }
        } catch (err) {
            this._pushMsg("assistant", "⚠️ Could not process voice recording.");
        } finally {
            this.state.processing = false;
            this._scrollToBottom();
        }
    }

    // ── AI result handling ────────────────────────────────────────────────────

    _handleAiResult(result) {
        const text = result.response || "";
        if (text) this._pushMsg("assistant", text);

        // Speak response if TTS is enabled
        if (this.state.ttsEnabled && text && "speechSynthesis" in window) {
            const utter = new SpeechSynthesisUtterance(text);
            utter.rate = 1.05;
            window.speechSynthesis.cancel(); // stop any in-progress speech
            window.speechSynthesis.speak(utter);
        }

        // ── Two-phase confirmation (enroll, belt, etc.) ──────────────────────
        if (result.state === "pending_confirmation" && result.session_key && result.confirmation_prompt) {
            this.state.pendingConfirm = {
                session_key: result.session_key,
                prompt: result.confirmation_prompt,
                intent_type: result.intent && result.intent.intent_type,
            };
            if (!text) {
                this._pushMsg("assistant", result.confirmation_prompt);
            }
            return;
        }

        // Handle contact_parent action (legacy)
        const action = result.action;
        if (action && action.type === "contact_parent" && !action.error) {
            this.state.pendingAction  = action;
            this.state.actionSubject  = action.suggested_subject || "Message from Dojo";
            this.state.actionBody     = action.suggested_body || "";
            this.state.actionEmail    = true;
            this.state.actionSms      = true;
        } else if (action && action.error) {
            this._pushMsg("assistant", "⚠️ " + action.error);
        }
    }

    // ── contact-parent confirmation card ─────────────────────────────────────

    onActionSubjectChange(ev)  { this.state.actionSubject = ev.target.value; }
    onActionBodyChange(ev)     { this.state.actionBody    = ev.target.value; }
    onActionEmailChange(ev)    { this.state.actionEmail   = ev.target.checked; }
    onActionSmsChange(ev)      { this.state.actionSms     = ev.target.checked; }

    cancelAction() {
        this.state.pendingAction = null;
        this._pushMsg("assistant", "Message cancelled. Let me know if you need anything else.");
    }

    // ── Two-phase confirmation (enroll / belt / etc.) ─────────────────────────

    async confirmIntent() {
        const pending = this.state.pendingConfirm;
        if (!pending) return;
        this.state.pendingConfirm = null;
        this.state.processing = true;
        try {
            const result = await rpc("/dojo/ai/confirm", {
                session_key: pending.session_key,
                confirmed: true,
            });
            if (result.success) {
                const msg = result.result && result.result.message
                    ? "✅ " + result.result.message
                    : "✅ Done!";
                this._pushMsg("assistant", msg);
                if (result.undo_available) {
                    this._pushMsg("assistant", "You can say \"undo\" to reverse this action.");
                }
            } else {
                this._pushMsg("assistant", "⚠️ " + (result.error || "Action failed."));
            }
        } catch (err) {
            this._pushMsg("assistant", "⚠️ Network error during confirmation.");
        } finally {
            this.state.processing = false;
            this._scrollToBottom();
        }
    }

    async cancelIntent() {
        const pending = this.state.pendingConfirm;
        if (!pending) return;
        this.state.pendingConfirm = null;
        try {
            await rpc("/dojo/ai/confirm", {
                session_key: pending.session_key,
                confirmed: false,
            });
        } catch (_) {}
        this._pushMsg("assistant", "Action cancelled. Let me know if you need anything else.");
    }

    async confirmAction() {
        const action = this.state.pendingAction;
        if (!action) return;

        this.state.processing = true;
        try {
            const result = await rpc("/dojo/ai/send_message", {
                member_id:  action.member_id,
                subject:    this.state.actionSubject,
                body:       this.state.actionBody,
                send_email: this.state.actionEmail,
                send_sms:   this.state.actionSms,
            });
            this.state.pendingAction = null;
            if (result.success) {
                this._pushMsg("assistant", "✅ " + (result.message || "Message sent successfully."));
                this.notification.add(result.message || "Message sent.", { type: "success" });
            } else {
                this._pushMsg("assistant", "⚠️ Failed to send: " + (result.error || "Unknown error."));
            }
        } catch (err) {
            this._pushMsg("assistant", "⚠️ Network error while sending message.");
        } finally {
            this.state.processing = false;
            this._scrollToBottom();
        }
    }

    // ── TTS toggle ────────────────────────────────────────────────────────────

    toggleTts() {
        this.state.ttsEnabled = !this.state.ttsEnabled;
        if (!this.state.ttsEnabled) window.speechSynthesis && window.speechSynthesis.cancel();
    }

    // ── utils ─────────────────────────────────────────────────────────────────

    _pushMsg(role, text) {
        this.state.messages.push({ role, text, time: nowLabel() });
    }

    _scrollToBottom() {
        if (this.endRef.el) {
            this.endRef.el.scrollIntoView({ behavior: "smooth" });
        }
    }
}
