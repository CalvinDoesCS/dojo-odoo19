# -*- coding: utf-8 -*-

import base64
import json
import logging
import requests
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class ElevenLabsService(models.AbstractModel):
    _name = 'elevenlabs.service'
    _description = 'ElevenLabs API Service'

    ELEVENLABS_API_BASE = 'https://api.elevenlabs.io/v1'
    ELEVENLABS_TTS_ENDPOINT = '/text-to-speech'
    ELEVENLABS_STT_ENDPOINT = '/speech-to-text'
    ELEVENLABS_VOICES_ENDPOINT = '/voices'

    def _get_api_key(self):
        """Get ElevenLabs API key from settings"""
        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'elevenlabs_connector.api_key'
        )
        if not api_key:
            raise UserError('ElevenLabs API key is not configured. Please set it in Settings → Integrations → ElevenLabs')
        return api_key

    def _get_default_voice_id(self):
        """Get default voice ID from settings"""
        return self.env['ir.config_parameter'].sudo().get_param(
            'elevenlabs_connector.voice_id', '21m00Tcm4TlvDq8ikWAM'
        )

    def _get_default_language(self):
        """Get default language from settings"""
        return self.env['ir.config_parameter'].sudo().get_param(
            'elevenlabs_connector.language', 'en'
        )

    def _make_request(self, method, endpoint, api_key=None, **kwargs):
        """Make HTTP request to ElevenLabs API"""
        if api_key is None:
            api_key = self._get_api_key()
        
        url = f"{self.ELEVENLABS_API_BASE}{endpoint}"
        headers = {
            'xi-api-key': api_key,
            'Accept': 'application/json',
        }
        
        # Add content type for POST requests if not specified
        if method.upper() == 'POST' and 'Content-Type' not in headers:
            if 'files' in kwargs:
                # Don't set Content-Type for multipart/form-data, let requests handle it
                pass
            elif 'json' in kwargs:
                # Encode JSON as UTF-8 to avoid latin-1 issues
                json_data = json.dumps(kwargs['json'], ensure_ascii=False).encode('utf-8')
                kwargs['data'] = json_data
                del kwargs['json']
                headers['Content-Type'] = 'application/json; charset=utf-8'
            else:
                headers['Content-Type'] = 'application/json; charset=utf-8'
        
        try:
            # Create session to ensure consistent encoding
            session = requests.Session()
            response = session.request(
                method=method,
                url=url,
                headers=headers,
                timeout=30,
                **kwargs
            )
            # Force UTF-8 encoding for response - check and override latin-1
            if response.encoding is None or response.encoding.lower() in ('iso-8859-1', 'latin-1'):
                response.encoding = 'utf-8'
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            _logger.error('ElevenLabs API request failed: %s', str(e))
            if hasattr(e, 'response') and e.response is not None:
                try:
                    # Ensure UTF-8 encoding for error response
                    if e.response.encoding is None or e.response.encoding.lower() in ('iso-8859-1', 'latin-1'):
                        e.response.encoding = 'utf-8'
                    error_detail = json.loads(e.response.text) if e.response.text else {}
                    error_msg = error_detail.get('detail', {}).get('message', e.response.text) if isinstance(error_detail, dict) else e.response.text
                    if not error_msg or error_msg == '{}':
                        error_msg = f"HTTP {e.response.status_code}: {e.response.reason}"
                except:
                    # Ensure UTF-8 for text extraction
                    if e.response.encoding is None or e.response.encoding.lower() in ('iso-8859-1', 'latin-1'):
                        e.response.encoding = 'utf-8'
                    error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200] if e.response.text else e.response.reason}"
            else:
                error_msg = f"Network error: {str(e)}"
            raise UserError(error_msg)

    def test_connection(self, api_key=None):
        """Test connection to ElevenLabs API by fetching voices"""
        try:
            if api_key is None:
                api_key = self._get_api_key()
            
            if not api_key:
                raise UserError('API key is required to test connection')
            
            response = self._make_request('GET', self.ELEVENLABS_VOICES_ENDPOINT, api_key=api_key)
            
            if response.status_code == 200:
                # Force UTF-8 encoding before parsing JSON
                if response.encoding is None or response.encoding.lower() in ('iso-8859-1', 'latin-1'):
                    response.encoding = 'utf-8'
                # Try to parse the response to ensure it's valid
                data = json.loads(response.text)
                if 'voices' in data or isinstance(data, dict):
                    return True
                return False
            return False
        except UserError:
            raise
        except Exception as e:
            _logger.error('ElevenLabs connection test failed: %s', str(e), exc_info=True)
            raise UserError(f'Connection test failed: {str(e)}')

    def generate_speech(self, text, voice_id=None, language=None, model_id='eleven_multilingual_v2'):
        """
        Generate speech from text using ElevenLabs TTS API
        
        Args:
            text: Text to convert to speech
            voice_id: Voice ID (defaults to settings)
            language: Language code (defaults to settings)
            model_id: Model ID (default: eleven_multilingual_v2)
        
        Returns:
            bytes: Audio data (MP3 format)
        """
        if not text:
            raise ValidationError('Text cannot be empty')
        
        if voice_id is None:
            voice_id = self._get_default_voice_id()
        
        if language is None:
            language = self._get_default_language()
        
        endpoint = f"{self.ELEVENLABS_TTS_ENDPOINT}/{voice_id}"
        
        payload = {
            'text': text,
            'model_id': model_id,
            'language_code': language,
            'voice_settings': {
                'stability': 0.5,
                'similarity_boost': 0.75,
                'style': 0.0,
                'use_speaker_boost': True
            }
        }
        
        try:
            response = self._make_request('POST', endpoint, json=payload)
            return response.content  # Returns audio bytes
        except Exception as e:
            _logger.error('TTS generation failed: %s', str(e))
            raise UserError(f'Failed to generate speech: {str(e)}')

    def transcribe_audio(self, audio_data, language=None, model_id=None):
        """
        Transcribe audio to text using ElevenLabs STT API
        
        Args:
            audio_data: Audio file bytes or base64 encoded string
            language: Language code (optional, for better accuracy)
            model_id: Model ID for STT (default: eleven_multilingual_v2)
        
        Returns:
            str: Transcribed text
        """
        if not audio_data:
            raise ValidationError('Audio data cannot be empty')
        
        # Handle base64 encoded audio
        if isinstance(audio_data, str):
            try:
                audio_data = base64.b64decode(audio_data)
            except Exception:
                # If not base64, assume it's already bytes
                pass
        
        # Default model for STT (valid models: scribe_v1, scribe_v1_experimental, scribe_v2)
        if model_id is None:
            model_id = self.env['ir.config_parameter'].sudo().get_param(
                'elevenlabs_connector.stt_model_id', 'scribe_v2'
            )
        
        # Prepare multipart form data
        # ElevenLabs API expects 'file' parameter, not 'audio'
        files = {
            'file': ('audio.webm', audio_data, 'audio/webm')  # Changed to webm as that's what MediaRecorder produces
        }
        
        data = {
            'model_id': model_id,
        }
        if language:
            data['language'] = language
        
        try:
            response = self._make_request('POST', self.ELEVENLABS_STT_ENDPOINT, files=files, data=data)
            # Force UTF-8 encoding before parsing JSON
            if response.encoding is None or response.encoding.lower() in ('iso-8859-1', 'latin-1'):
                response.encoding = 'utf-8'
            result = json.loads(response.text)
            return result.get('text', '')
        except Exception as e:
            _logger.error('STT transcription failed: %s', str(e))
            raise UserError(f'Failed to transcribe audio: {str(e)}')

    def get_voices(self):
        """Get list of available voices from ElevenLabs"""
        try:
            response = self._make_request('GET', self.ELEVENLABS_VOICES_ENDPOINT)
            # Force UTF-8 encoding before parsing JSON
            if response.encoding is None or response.encoding.lower() in ('iso-8859-1', 'latin-1'):
                response.encoding = 'utf-8'
            result = json.loads(response.text)
            return result.get('voices', [])
        except Exception as e:
            _logger.error('Failed to fetch voices: %s', str(e))
            return []

    def generate_speech_attachment(self, text, voice_id=None, language=None, filename='voice_output.mp3'):
        """
        Generate speech and create an Odoo attachment
        
        Args:
            text: Text to convert to speech
            voice_id: Voice ID (optional)
            language: Language code (optional)
            filename: Filename for the attachment
        
        Returns:
            ir.attachment: Created attachment record
        """
        audio_data = self.generate_speech(text, voice_id, language)
        
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(audio_data),
            'mimetype': 'audio/mpeg',
            'res_model': 'voice.conversation',
            'res_id': False,
        })
        
        return attachment

