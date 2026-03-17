/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

class VoiceAssistantWidget extends Component {
    setup() {
        this.state = useState({
            isRecording: false,
            isProcessing: false,
            transcribedText: "",
            aiResponse: "",
            error: null,
            mediaRecorder: null,
            audioChunks: [],
            conversations: [],
        });
        
        onWillStart(async () => {
            await this.loadConversations();
        });
    }

    async loadConversations() {
        try {
            const result = await rpc("/elevenlabs/voice/conversations", {
                limit: 10,
            });
            if (result.success) {
                const conversations = result.conversations || [];
                this.state.conversations = conversations;

                // ALWAYS populate the current view with the latest conversation
                // This ensures the response appears under the microphone
                if (conversations.length > 0) {
                    const latest = conversations[0];
                    this.state.transcribedText = latest.user_input || "";
                    this.state.aiResponse = latest.final_response || "";
                    console.log('Updated main view with latest conversation:', {
                        transcribed: this.state.transcribedText,
                        response: this.state.aiResponse
                    });
                } else {
                    // Clear if no conversations
                    this.state.transcribedText = "";
                    this.state.aiResponse = "";
                }
            }
        } catch (error) {
            console.error("Failed to load conversations:", error);
        }
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

    toggleRecording() {
        if (this.state.isRecording) {
            this.stopRecording();
        } else {
            this.startRecording();
        }
    }

    async processAudio(audioBlob) {
        this.state.isProcessing = true;
        this.state.error = null;
        // Clear previous response when starting new recording
        this.state.transcribedText = "";
        this.state.aiResponse = "";

        try {
            const reader = new FileReader();
            reader.onloadend = async () => {
                const base64Audio = reader.result.split(',')[1];

                try {
                    const result = await rpc("/elevenlabs/voice/process", {
                        audio_data: base64Audio,
                    });

                    if (result.success) {
                        console.log('Voice processing successful:', {
                            transcribed: result.transcribed_text,
                            response: result.response_text
                        });
                        
                        // IMMEDIATELY update state with response - this should trigger UI update
                        this.state.transcribedText = result.transcribed_text || "";
                        this.state.aiResponse = result.response_text || "";
                        this.state.isProcessing = false;
                        
                        console.log('State updated immediately:', {
                            transcribedText: this.state.transcribedText,
                            aiResponse: this.state.aiResponse
                        });
                        
                        // Refresh conversation list (this will also update the main view)
                        await this.loadConversations();
                        
                        // Force a small delay then scroll to response
                        setTimeout(() => {
                            const responseElement = document.getElementById('current-conversation-result');
                            if (responseElement) {
                                responseElement.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                            }
                        }, 300);
                    } else {
                        this.state.error = result.error || 'Processing failed';
                        this.state.isProcessing = false;
                    }
                } catch (error) {
                    console.error('Processing error:', error);
                    this.state.error = 'Failed to process audio. Please try again.';
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

VoiceAssistantWidget.template = "elevenlabs_connector.VoiceAssistantWidget";

// Register as client action - opens directly in Odoo UI
registry.category("actions").add("elevenlabs_connector.voice_assistant_action", VoiceAssistantWidget);

