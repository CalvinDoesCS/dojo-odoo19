/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";

export class VoicePage extends Component {
    setup() {
        this.state = useState({
            isRecording: false,
            isProcessing: false,
            mediaRecorder: null,
            audioChunks: [],
            transcribedText: '',
            responseText: '',
            audioUrl: null,
            error: null,
            conversations: [],
        });

        onWillStart(async () => {
            await this.loadConversations();
        });
    }

    async loadConversations() {
        try {
            const result = await rpc('/elevenlabs/voice/conversations', {
                limit: 10,
            });
            if (result.success) {
                this.state.conversations = result.conversations;
            }
        } catch (error) {
            console.error('Failed to load conversations:', error);
        }
    }

    async startRecording() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const mediaRecorder = new MediaRecorder(stream);
            const audioChunks = [];

            mediaRecorder.ondataavailable = (event) => {
                audioChunks.push(event.data);
            };

            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                await this.processAudio(audioBlob);
                stream.getTracks().forEach(track => track.stop());
            };

            this.state.mediaRecorder = mediaRecorder;
            this.state.audioChunks = audioChunks;
            this.state.isRecording = true;
            this.state.error = null;

            mediaRecorder.start();
            this.updateStatus('Recording... Click again to stop');
        } catch (error) {
            console.error('Error starting recording:', error);
            this.state.error = 'Failed to access microphone. Please check permissions.';
            this.updateStatus('Error: Microphone access denied');
        }
    }

    stopRecording() {
        if (this.state.mediaRecorder && this.state.isRecording) {
            this.state.mediaRecorder.stop();
            this.state.isRecording = false;
            this.updateStatus('Processing...');
        }
    }

    async processAudio(audioBlob) {
        this.state.isProcessing = true;
        this.state.error = null;

        try {
            // Convert blob to base64
            const reader = new FileReader();
            reader.onloadend = async () => {
                const base64Audio = reader.result.split(',')[1];
                
                try {
                    const result = await rpc('/elevenlabs/voice/process', {
                        audio_data: base64Audio,
                    });

                    if (result.success) {
                        this.state.transcribedText = result.transcribed_text;
                        this.state.responseText = result.response_text;
                        this.state.audioUrl = result.audio_url;
                        
                        // Show audio player
                        const audioPlayer = document.getElementById('response-audio');
                        if (audioPlayer && result.audio_url) {
                            audioPlayer.controls = true;
                            audioPlayer.src = result.audio_url;
                            document.getElementById('audio-player').style.display = 'block';
                        }

                        // Show conversation
                        document.getElementById('user-input-display').style.display = 'block';
                        document.getElementById('user-input-text').textContent = result.transcribed_text;
                        document.getElementById('response-display').style.display = 'block';
                        document.getElementById('response-text').textContent = result.response_text;

                        // Reload conversations
                        await this.loadConversations();
                        this.updateStatus('Completed! Click to record again');
                    } else {
                        this.state.error = result.error || 'Processing failed';
                        this.updateStatus('Error occurred');
                    }
                } catch (error) {
                    console.error('Processing error:', error);
                    this.state.error = error.message || 'Failed to process audio';
                    this.updateStatus('Error occurred');
                } finally {
                    this.state.isProcessing = false;
                }
            };
            reader.readAsDataURL(audioBlob);
        } catch (error) {
            console.error('Audio processing error:', error);
            this.state.error = error.message || 'Failed to process audio';
            this.state.isProcessing = false;
            this.updateStatus('Error occurred');
        }
    }

    async handleFileUpload(event) {
        const file = event.target.files[0];
        if (!file) return;

        this.state.isProcessing = true;
        this.state.error = null;
        this.updateStatus('Processing uploaded file...');

        try {
            const formData = new FormData();
            formData.append('audio', file);

            const response = await fetch('/elevenlabs/voice/upload', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                },
            });

            const result = await response.json();

            if (result.success) {
                this.state.transcribedText = result.transcribed_text;
                this.state.responseText = result.response_text;
                this.state.audioUrl = result.audio_url;

                // Show audio player
                const audioPlayer = document.getElementById('response-audio');
                if (audioPlayer && result.audio_url) {
                    audioPlayer.src = result.audio_url;
                    document.getElementById('audio-player').style.display = 'block';
                }

                // Show conversation
                document.getElementById('user-input-display').style.display = 'block';
                document.getElementById('user-input-text').textContent = result.transcribed_text;
                document.getElementById('response-display').style.display = 'block';
                document.getElementById('response-text').textContent = result.response_text;

                await this.loadConversations();
                this.updateStatus('Completed!');
            } else {
                this.state.error = result.error || 'Processing failed';
                this.updateStatus('Error occurred');
            }
        } catch (error) {
            console.error('Upload error:', error);
            this.state.error = error.message || 'Failed to upload file';
            this.updateStatus('Error occurred');
        } finally {
            this.state.isProcessing = false;
        }
    }

    updateStatus(text) {
        const statusElement = document.getElementById('status-text');
        if (statusElement) {
            statusElement.textContent = text;
        }
    }

    toggleRecording() {
        if (this.state.isRecording) {
            this.stopRecording();
        } else {
            this.startRecording();
        }
    }
}

VoicePage.template = "elevenlabs_connector.VoicePage";

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    const recordBtn = document.getElementById('record-btn');
    const uploadBtn = document.getElementById('upload-btn');
    const fileInput = document.getElementById('audio-file-input');
    const errorDisplay = document.getElementById('error-display');
    const errorText = document.getElementById('error-text');

    if (recordBtn) {
        let isRecording = false;
        let mediaRecorder = null;
        let audioChunks = [];

        recordBtn.addEventListener('click', async () => {
            if (!isRecording) {
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    mediaRecorder = new MediaRecorder(stream);
                    audioChunks = [];

                    mediaRecorder.ondataavailable = (event) => {
                        audioChunks.push(event.data);
                    };

                    mediaRecorder.onstop = async () => {
                        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                        await processAudio(audioBlob);
                        stream.getTracks().forEach(track => track.stop());
                    };

                    mediaRecorder.start();
                    isRecording = true;
                    recordBtn.classList.add('btn-danger');
                    recordBtn.classList.remove('btn-primary');
                    recordBtn.innerHTML = '<i class="fa fa-stop fa-2x"></i>';
                    document.getElementById('status-text').textContent = 'Recording... Click to stop';
                } catch (error) {
                    console.error('Error accessing microphone:', error);
                    showError('Failed to access microphone. Please check permissions.');
                }
            } else {
                if (mediaRecorder) {
                    mediaRecorder.stop();
                    isRecording = false;
                    recordBtn.classList.remove('btn-danger');
                    recordBtn.classList.add('btn-primary');
                    recordBtn.innerHTML = '<i class="fa fa-microphone fa-2x"></i>';
                    document.getElementById('status-text').textContent = 'Processing...';
                }
            }
        });
    }

    if (uploadBtn && fileInput) {
        uploadBtn.addEventListener('click', () => {
            fileInput.click();
        });

        fileInput.addEventListener('change', async (event) => {
            const file = event.target.files[0];
            if (!file) return;

            document.getElementById('status-text').textContent = 'Processing uploaded file...';
            uploadBtn.disabled = true;

            try {
                const formData = new FormData();
                formData.append('audio', file);

                const response = await fetch('/elevenlabs/voice/upload', {
                    method: 'POST',
                    body: formData,
                });

                const result = await response.json();

                if (result.success) {
                    document.getElementById('user-input-display').style.display = 'block';
                    document.getElementById('user-input-text').textContent = result.transcribed_text;
                    document.getElementById('response-display').style.display = 'block';
                    document.getElementById('response-text').textContent = result.response_text;

                    const audioPlayer = document.getElementById('response-audio');
                    if (audioPlayer && result.audio_url) {
                        audioPlayer.src = result.audio_url;
                        document.getElementById('audio-player').style.display = 'block';
                    }

                    document.getElementById('status-text').textContent = 'Completed!';
                    loadConversations();
                } else {
                    showError(result.error || 'Processing failed');
                }
            } catch (error) {
                console.error('Upload error:', error);
                showError('Failed to upload file');
            } finally {
                uploadBtn.disabled = false;
            }
        });
    }

    async function processAudio(audioBlob) {
        try {
            const reader = new FileReader();
            reader.onloadend = async () => {
                const base64Audio = reader.result.split(',')[1];
                
                try {
                    const response = await fetch('/elevenlabs/voice/process', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            audio_data: base64Audio,
                        }),
                    });

                    const result = await response.json();

                    if (result.success) {
                        document.getElementById('user-input-display').style.display = 'block';
                        document.getElementById('user-input-text').textContent = result.transcribed_text;
                        document.getElementById('response-display').style.display = 'block';
                        document.getElementById('response-text').textContent = result.response_text;

                        const audioPlayer = document.getElementById('response-audio');
                        if (audioPlayer && result.audio_url) {
                            audioPlayer.controls = true;
                            audioPlayer.src = result.audio_url;
                            document.getElementById('audio-player').style.display = 'block';
                        }

                        document.getElementById('status-text').textContent = 'Completed! Click to record again';
                        loadConversations();
                    } else {
                        showError(result.error || 'Processing failed');
                    }
                } catch (error) {
                    console.error('Processing error:', error);
                    showError('Failed to process audio');
                }
            };
            reader.readAsDataURL(audioBlob);
        } catch (error) {
            console.error('Audio processing error:', error);
            showError('Failed to process audio');
        }
    }

    async function loadConversations() {
        try {
            const response = await fetch('/elevenlabs/voice/conversations?limit=10');
            const result = await response.json();

            if (result.success) {
                const historyDiv = document.getElementById('conversation-history');
                if (result.conversations.length === 0) {
                    historyDiv.innerHTML = '<p class="text-muted">No conversations yet. Start by recording a question!</p>';
                } else {
                    let html = '<div class="list-group">';
                    result.conversations.forEach(conv => {
                        html += `
                            <div class="list-group-item">
                                <div class="d-flex justify-content-between">
                                    <div>
                                        <strong>You:</strong> ${conv.user_input.substring(0, 100)}${conv.user_input.length > 100 ? '...' : ''}<br>
                                        <small class="text-muted">${new Date(conv.conversation_date).toLocaleString()}</small>
                                    </div>
                                    ${conv.audio_url ? `<audio controls src="${conv.audio_url}" style="max-width: 200px;"></audio>` : ''}
                                </div>
                            </div>
                        `;
                    });
                    html += '</div>';
                    historyDiv.innerHTML = html;
                }
            }
        } catch (error) {
            console.error('Failed to load conversations:', error);
        }
    }

    function showError(message) {
        if (errorDisplay && errorText) {
            errorText.textContent = message;
            errorDisplay.style.display = 'block';
            setTimeout(() => {
                errorDisplay.style.display = 'none';
            }, 5000);
        }
    }

    // Load conversations on page load
    loadConversations();
});

