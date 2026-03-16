# -*- coding: utf-8 -*-

import base64
import json
import logging
from odoo import http
from odoo.http import request
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class VoiceController(http.Controller):

    @http.route('/elevenlabs/voice', type='http', auth='user', website=True)
    def voice_page(self, **kwargs):
        """Dedicated voice assistant page"""
        # Get recent conversations for this user
        conversations = request.env['voice.conversation'].search([
            ('user_id', '=', request.env.user.id)
        ], limit=10, order='create_date desc')
        
        return request.render('elevenlabs_connector.voice_page_template', {
            'conversations': conversations,
        })

    @http.route('/elevenlabs/voice/process', type='json', auth='user', methods=['POST'], csrf=False)
    def process_voice(self, audio_data=None, conversation_id=None, **kwargs):
        """
        Process voice input: STT → AI → Database → TTS
        
        Args:
            audio_data: Base64 encoded audio data
            conversation_id: Optional existing conversation ID
        
        Returns:
            dict: {
                'success': bool,
                'conversation_id': int,
                'transcribed_text': str,
                'response_text': str,
                'audio_url': str,
                'error': str (if failed)
            }
        """
        try:
            if not audio_data:
                return {
                    'success': False,
                    'error': 'No audio data provided'
                }
            
            # Decode base64 audio if needed
            if isinstance(audio_data, str):
                try:
                    audio_bytes = base64.b64decode(audio_data)
                except Exception:
                    audio_bytes = audio_data.encode() if isinstance(audio_data, str) else audio_data
            else:
                audio_bytes = audio_data
            
            # Process voice request
            voice_service = request.env['voice.service']
            conversation = voice_service.process_voice_request(
                audio_bytes,
                conversation_id=conversation_id,
                context={'user': request.env.user}
            )
            
            return {
                'success': True,
                'conversation_id': conversation.id,
                'transcribed_text': conversation.user_input,
                'response_text': conversation.final_response,
                'state': conversation.state,
            }
            
        except Exception as e:
            _logger.error('Voice processing failed: %s', str(e), exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    # Use POST here because Odoo's JSON-RPC (used by the JS `rpc` service) always sends POST requests.
    # Using GET causes 405 errors in the frontend.
    @http.route('/elevenlabs/voice/conversations', type='json', auth='user', methods=['POST'])
    def get_conversations(self, limit=10, **kwargs):
        """Get recent conversations for the current user"""
        try:
            conversations = request.env['voice.conversation'].search([
                ('user_id', '=', request.env.user.id)
            ], limit=limit, order='create_date desc')
            
            return {
                'success': True,
                'conversations': [{
                    'id': conv.id,
                    'user_input': conv.user_input,
                    'final_response': conv.final_response,
                    'conversation_date': conv.conversation_date.isoformat() if conv.conversation_date else None,
                    'state': conv.state,
                } for conv in conversations]
            }
        except Exception as e:
            _logger.error('Failed to get conversations: %s', str(e))
            return {
                'success': False,
                'error': str(e)
            }

    @http.route('/elevenlabs/voice/upload', type='http', auth='user', methods=['POST'], csrf=False)
    def upload_audio(self, **kwargs):
        """Handle audio file upload"""
        try:
            audio_file = request.httprequest.files.get('audio')
            if not audio_file:
                return request.make_response(
                    json.dumps({'success': False, 'error': 'No audio file provided'}, ensure_ascii=False).encode('utf-8'),
                    headers=[('Content-Type', 'application/json; charset=utf-8')],
                    status=400
                )
            
            # Read audio file
            audio_data = audio_file.read()
            
            # Process voice request
            voice_service = request.env['voice.service']
            conversation = voice_service.process_voice_request(
                audio_data,
                context={'user': request.env.user}
            )
            
            return request.make_response(
                json.dumps({
                    'success': True,
                    'conversation_id': conversation.id,
                    'transcribed_text': conversation.user_input,
                    'response_text': conversation.final_response,
                }, ensure_ascii=False).encode('utf-8'),
                headers=[('Content-Type', 'application/json; charset=utf-8')]
            )
            
        except Exception as e:
            _logger.error('Audio upload failed: %s', str(e))
            return request.make_response(
                json.dumps({'success': False, 'error': str(e)}, ensure_ascii=False).encode('utf-8'),
                headers=[('Content-Type', 'application/json; charset=utf-8')],
                status=500
            )

