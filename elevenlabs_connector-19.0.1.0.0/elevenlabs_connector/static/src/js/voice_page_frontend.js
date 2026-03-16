// Voice Assistant Frontend JavaScript
(function() {
    'use strict';

    let mediaRecorder = null;
    let audioChunks = [];
    let isRecording = false;
    let isProcessing = false;

    // Initialize when DOM is ready
    document.addEventListener('DOMContentLoaded', function() {
        initializeVoiceAssistant();
    });

    function initializeVoiceAssistant() {
        const recordBtn = document.getElementById('record-btn');
        const uploadBtn = document.getElementById('upload-btn');
        const audioFileInput = document.getElementById('audio-file-input');
        const statusText = document.getElementById('status-text');

        if (recordBtn) {
            recordBtn.addEventListener('click', toggleRecording);
        }

        if (uploadBtn && audioFileInput) {
            uploadBtn.addEventListener('click', () => audioFileInput.click());
            audioFileInput.addEventListener('change', handleFileUpload);
        }

        loadConversations();
    }

    async function toggleRecording() {
        if (isRecording) {
            stopRecording();
        } else {
            await startRecording();
        }
    }

    async function startRecording() {
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

            isRecording = true;
            updateStatus('Recording... Click again to stop');
            mediaRecorder.start();
        } catch (error) {
            console.error('Error starting recording:', error);
            showError('Failed to access microphone. Please check permissions.');
            updateStatus('Error: Microphone access denied');
        }
    }

    function stopRecording() {
        if (mediaRecorder && isRecording) {
            mediaRecorder.stop();
            isRecording = false;
            updateStatus('Processing...');
        }
    }

    async function processAudio(audioBlob) {
        isProcessing = true;
        hideError();

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
                        // Show transcribed text
                        const userInputDisplay = document.getElementById('user-input-display');
                        const userInputText = document.getElementById('user-input-text');
                        if (userInputDisplay && userInputText) {
                            userInputText.textContent = result.transcribed_text || 'Your question';
                            userInputDisplay.style.display = 'block';
                        }

                        // Show response
                        const responseDisplay = document.getElementById('response-display');
                        const responseText = document.getElementById('response-text');
                        if (responseDisplay && responseText) {
                            responseText.textContent = result.response_text || 'Response received';
                            responseDisplay.style.display = 'block';
                        }

                        // Play audio response
                        if (result.audio_url) {
                            const audioPlayer = document.getElementById('response-audio');
                            const audioPlayerContainer = document.getElementById('audio-player');
                            if (audioPlayer) {
                                audioPlayer.src = result.audio_url;
                                audioPlayer.controls = true;
                                if (audioPlayerContainer) {
                                    audioPlayerContainer.style.display = 'block';
                                }
                                // Auto-play the response
                                audioPlayer.play().catch(e => console.log('Auto-play prevented:', e));
                            }
                        }

                        // Reload conversations
                        await loadConversations();
                        updateStatus('Completed! Click to record again');
                    } else {
                        showError(result.error || 'Processing failed');
                        updateStatus('Error occurred');
                    }
                } catch (error) {
                    console.error('Processing error:', error);
                    showError(error.message || 'Failed to process audio');
                    updateStatus('Error occurred');
                } finally {
                    isProcessing = false;
                }
            };
            reader.readAsDataURL(audioBlob);
        } catch (error) {
            console.error('Audio processing error:', error);
            showError(error.message || 'Failed to process audio');
            isProcessing = false;
            updateStatus('Error occurred');
        }
    }

    async function handleFileUpload(event) {
        const file = event.target.files[0];
        if (!file) return;

        isProcessing = true;
        hideError();
        updateStatus('Processing uploaded file...');

        try {
            const formData = new FormData();
            formData.append('audio', file);

            const response = await fetch('/elevenlabs/voice/upload', {
                method: 'POST',
                body: formData,
            });

            const result = await response.json();

            if (result.success) {
                // Show transcribed text
                const userInputDisplay = document.getElementById('user-input-display');
                const userInputText = document.getElementById('user-input-text');
                if (userInputDisplay && userInputText) {
                    userInputText.textContent = result.transcribed_text || 'Your question';
                    userInputDisplay.style.display = 'block';
                }

                // Show response
                const responseDisplay = document.getElementById('response-display');
                const responseText = document.getElementById('response-text');
                if (responseDisplay && responseText) {
                    responseText.textContent = result.response_text || 'Response received';
                    responseDisplay.style.display = 'block';
                }

                // Play audio response
                if (result.audio_url) {
                    const audioPlayer = document.getElementById('response-audio');
                    const audioPlayerContainer = document.getElementById('audio-player');
                    if (audioPlayer) {
                        audioPlayer.src = result.audio_url;
                        audioPlayer.controls = true;
                        if (audioPlayerContainer) {
                            audioPlayerContainer.style.display = 'block';
                        }
                        audioPlayer.play().catch(e => console.log('Auto-play prevented:', e));
                    }
                }

                await loadConversations();
                updateStatus('Completed!');
            } else {
                showError(result.error || 'Upload failed');
                updateStatus('Error occurred');
            }
        } catch (error) {
            console.error('Upload error:', error);
            showError(error.message || 'Failed to upload audio');
            updateStatus('Error occurred');
        } finally {
            isProcessing = false;
            // Reset file input
            event.target.value = '';
        }
    }

    async function loadConversations() {
        try {
            const response = await fetch('/elevenlabs/voice/conversations?limit=10');
            const result = await response.json();

            if (result.success && result.conversations) {
                displayConversations(result.conversations);
            }
        } catch (error) {
            console.error('Failed to load conversations:', error);
        }
    }

    function displayConversations(conversations) {
        const historyContainer = document.getElementById('conversation-history');
        if (!historyContainer) return;

        if (conversations.length === 0) {
            historyContainer.innerHTML = '<p class="text-muted">No conversations yet. Start by recording a question!</p>';
            return;
        }

        let html = '<div class="list-group">';
        conversations.forEach(conv => {
            html += `
                <div class="list-group-item">
                    <div class="d-flex justify-content-between align-items-start">
                        <div class="flex-grow-1">
                            <h6 class="mb-1">${conv.user_input || 'Voice query'}</h6>
                            <p class="mb-1">${conv.final_response || 'No response'}</p>
                            <small class="text-muted">${conv.conversation_date ? new Date(conv.conversation_date).toLocaleString() : ''}</small>
                        </div>
                        ${conv.audio_url ? `<audio controls src="${conv.audio_url}" style="max-width: 200px;"></audio>` : ''}
                    </div>
                </div>
            `;
        });
        html += '</div>';
        historyContainer.innerHTML = html;
    }

    function updateStatus(message) {
        const statusText = document.getElementById('status-text');
        if (statusText) {
            statusText.textContent = message;
        }
    }

    function showError(message) {
        const errorDisplay = document.getElementById('error-display');
        const errorText = document.getElementById('error-text');
        if (errorDisplay && errorText) {
            errorText.textContent = message;
            errorDisplay.style.display = 'block';
        }
    }

    function hideError() {
        const errorDisplay = document.getElementById('error-display');
        if (errorDisplay) {
            errorDisplay.style.display = 'none';
        }
    }
})();

