/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class VoiceAssistantButton extends Component {
    setup() {
        this.dialog = useService("dialog");
        this.rpc = useService("rpc");
    }

    openVoiceAssistant() {
        this.dialog.add(VoiceAssistantDialog, {
            title: "Voice Assistant",
            size: "lg",
        });
    }
}

VoiceAssistantButton.template = "elevenlabs_connector.VoiceAssistantButton";

class VoiceAssistantDialog extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.state = useState({
            isRecording: false,
            isProcessing: false,
            transcribedText: "",
            aiResponse: "",
            error: null,
            mediaRecorder: null,
            audioChunks: [],
        });
    }

    async startRecording() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            this.state.mediaRecorder = new MediaRecorder(stream);
            this.state.audioChunks = [];

            this.state.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    this.state.audioChunks.push(event.data);
                }
            };

            this.state.mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(this.state.audioChunks, { type: 'audio/webm' });
                await this.processAudio(audioBlob);
                stream.getTracks().forEach(track => track.stop());
            };

            this.state.mediaRecorder.start();
            this.state.isRecording = true;
            this.state.error = null;
        } catch (error) {
            console.error('Error accessing microphone:', error);
            this.state.error = 'Could not access microphone. Please check permissions.';
        }
    }

    stopRecording() {
        if (this.state.mediaRecorder && this.state.isRecording) {
            this.state.mediaRecorder.stop();
            this.state.isRecording = false;
        }
    }

    async processAudio(audioBlob) {
        this.state.isProcessing = true;
        this.state.error = null;

        try {
            const reader = new FileReader();
            reader.onloadend = async () => {
                const base64Audio = reader.result.split(',')[1];

                try {
                    const result = await this.rpc("/elevenlabs/voice/process", {
                        audio_data: base64Audio,
                    });

                    if (result.success) {
                        this.state.transcribedText = result.transcribed_text || "";
                        this.state.aiResponse = result.response_text || "";
                    } else {
                        this.state.error = result.error || 'Processing failed';
                    }
                } catch (error) {
                    console.error('Processing error:', error);
                    this.state.error = 'Failed to process audio. Please try again.';
                } finally {
                    this.state.isProcessing = false;
                }
            };

            reader.readAsDataURL(audioBlob);
        } catch (error) {
            console.error('Audio processing error:', error);
            this.state.error = 'Failed to process audio';
            this.state.isProcessing = false;
        }
    }

    clearConversation() {
        this.state.transcribedText = "";
        this.state.aiResponse = "";
        this.state.error = null;
    }
}

VoiceAssistantDialog.template = "elevenlabs_connector.VoiceAssistantDialog";

// Register as a systray item (appears in top bar)
registry.category("systray").add("elevenlabs_connector.voice_button", {
    Component: VoiceAssistantButton,
});

