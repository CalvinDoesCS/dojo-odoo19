# -*- coding: utf-8 -*-

import base64
import logging
import time
from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import datetime

_logger = logging.getLogger(__name__)


class VoiceService(models.AbstractModel):
    _name = 'voice.service'
    _description = 'Voice Service Orchestrator'

    def process_voice_request(self, audio_data, conversation_id=None, context=None):
        """
        Main orchestration method: STT → AI
        
        Args:
            audio_data: Audio file bytes or base64 encoded string
            conversation_id: Optional existing conversation record ID
            context: Additional context (user, etc.)
        
        Returns:
            voice.conversation: Conversation record with results
        """
        start_time = time.time()
        
        if context is None:
            context = {}
        
        # Get or prepare conversation record (don't create yet - wait for transcription)
        if conversation_id:
            conversation = self.env['voice.conversation'].browse(conversation_id)
            if not conversation.exists():
                raise UserError('Conversation not found')
        else:
            conversation = None
        
        try:
            # Audit log: Log voice request initiation
            _logger.info(
                'Voice request initiated by user %s (ID: %s)',
                self.env.user.name,
                self.env.user.id
            )
            
            # Step 1: Speech-to-Text (do this first before creating conversation)
            transcribed_text = self._speech_to_text(audio_data, conversation)
            
            if not transcribed_text or not transcribed_text.strip():
                raise UserError('Failed to transcribe audio. Please try again.')
            
            # Now create conversation record with transcribed text
            if not conversation:
                conversation = self.env['voice.conversation'].create({
                    'user_id': self.env.user.id,
                    'user_input': transcribed_text,
                    'state': 'processing',
                })
            else:
                conversation.write({
                    'user_input': transcribed_text,
                    'state': 'processing',
                })
            
            # Audit log: Transcription completed
            _logger.info(
                'Voice transcription completed for conversation %s: %s',
                conversation.id,
                transcribed_text[:100]  # Log first 100 chars
            )
            
            # Step 2: AI Processing (send to Odoo AI)
            ai_response = self._process_with_ai(transcribed_text, context)
            conversation.write({
                'ai_response': ai_response,
                'final_response': ai_response,  # AI response is the final response
            })
            
            # Store input audio if provided
            if audio_data:
                input_attachment = self._store_input_audio(audio_data, conversation)
                conversation.write({'audio_input_id': input_attachment.id})
            
            # Update conversation state
            processing_time = time.time() - start_time
            conversation.write({
                'state': 'completed',
                'processing_time': processing_time,
            })
            
            # Audit log: Successful completion
            _logger.info(
                'Voice request completed successfully for conversation %s (user: %s, time: %.2fs)',
                conversation.id,
                self.env.user.name,
                processing_time
            )
            
            return conversation
            
        except Exception as e:
            # Log full error with traceback for admins
            _logger.error('Voice processing failed: %s', str(e), exc_info=True)
            processing_time = time.time() - start_time
            # Only update conversation if it was created
            if conversation:
                # Store full error text in DB (no user encoding constraints there)
                conversation.write({
                    'state': 'error',
                    'error_message': str(e),
                    'processing_time': processing_time,
                })
            # IMPORTANT: Raise a short ASCII-only message to avoid latin-1 issues
            raise UserError('Voice processing failed. Please try again or contact your administrator.')

    def _speech_to_text(self, audio_data, conversation=None):
        """Step 1: Convert speech to text"""
        try:
            elevenlabs_service = self.env['elevenlabs.service']
            language = self.env['ir.config_parameter'].sudo().get_param(
                'elevenlabs_connector.language', 'en'
            )
            transcribed_text = elevenlabs_service.transcribe_audio(audio_data, language)
            return transcribed_text.strip() if transcribed_text else ""
        except Exception as e:
            _logger.error('STT failed: %s', str(e))
            raise UserError(f'Speech-to-text conversion failed: {str(e)}')

    def _process_with_ai(self, transcribed_text, context):
        """Step 2: Process query with AI - uses ONLY direct API calls, never Odoo AI provider"""
        try:
            # Use our own ai.processor model (NOT Odoo's ai.provider)
            # This model ONLY makes direct HTTP calls to OpenAI/Gemini
            ai_processor = self.env['ai.processor']
            context['user'] = self.env.user
            
            # Get AI response (already sanitized to ASCII in ai_processor)
            ai_response = ai_processor.process_query(transcribed_text, context)
            
            # CRITICAL: Sanitize one more time before returning to ensure no unicode issues
            # This is a final safety check before the response enters Odoo's database
            if ai_response:
                try:
                    ai_processor = self.env['ai.processor']
                    ai_response = ai_processor._sanitize_text(ai_response)
                except Exception as sanitize_error:
                    _logger.warning('Final sanitization failed, using response as-is: %s', str(sanitize_error))
                    # Last resort: encode to ASCII
                    try:
                        ai_response = ai_response.encode('ascii', errors='ignore').decode('ascii')
                    except Exception:
                        ai_response = 'AI response received but could not be sanitized'
            
            return ai_response
        except Exception as e:
            # Log full error for debugging (with full traceback)
            _logger.error('AI processing failed: %s', str(e), exc_info=True)
            
            # Create ASCII-safe error message (NEVER use latin-1)
            # Extract error message and sanitize it
            error_str = str(e)
            error_type = type(e).__name__
            safe_error = f'AI processing error ({error_type})'
            try:
                # Try to sanitize using our processor's sanitizer
                ai_processor = self.env['ai.processor']
                sanitized = ai_processor._sanitize_text(error_str)
                if sanitized and len(sanitized) > 0:
                    safe_error = sanitized
            except Exception:
                # Last resort: strip to pure ASCII
                try:
                    safe_error = error_str.encode('ascii', errors='ignore').decode('ascii')
                    if not safe_error or len(safe_error) == 0:
                        safe_error = f'AI processing error ({error_type})'
                except Exception:
                    safe_error = f'AI processing error ({error_type})'

            # Return fallback message with ASCII-safe error
            # Also sanitize transcribed_text to be safe
            try:
                ai_processor = self.env['ai.processor']
                safe_transcribed = ai_processor._sanitize_text(transcribed_text)
            except Exception:
                safe_transcribed = transcribed_text.encode('ascii', errors='ignore').decode('ascii')
            
            fallback = (
                "Your voice was transcribed successfully, but the AI provider failed to answer. "
                "Please check your AI settings.\n\n"
                f"Transcribed text:\n{safe_transcribed}\n\n"
                f"Error: {safe_error}"
            )
            return fallback


    def _store_input_audio(self, audio_data, conversation):
        """Store input audio as attachment"""
        try:
            # Handle base64 encoded audio
            if isinstance(audio_data, str):
                try:
                    audio_data = base64.b64decode(audio_data)
                except Exception:
                    pass  # Already bytes
            
            filename = f"voice_input_{conversation.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
            attachment = self.env['ir.attachment'].create({
                'name': filename,
                'type': 'binary',
                'datas': base64.b64encode(audio_data) if isinstance(audio_data, bytes) else audio_data,
                'mimetype': 'audio/mpeg',
                'res_model': 'voice.conversation',
                'res_id': conversation.id,
            })
            return attachment
        except Exception as e:
            _logger.warning('Failed to store input audio: %s', str(e))
            return False

    def _extract_model_name(self, query_data):
        """Extract model name from query data if available"""
        if not query_data or not isinstance(query_data, list):
            return None
        # Try to infer from data structure (this is a simple heuristic)
        # In a real implementation, this would be stored during query execution
        return None

    # Future: VOIP integration hooks
    def process_voip_stream(self, stream_data, context=None):
        """
        Hook for future VOIP integration (Twilio/Asterisk)
        This method can be extended by other modules
        
        Args:
            stream_data: Audio stream data from VOIP provider
            context: Additional context (caller ID, etc.)
        
        Returns:
            voice.conversation: Conversation record with results
        
        Example extension:
        ```python
        from odoo import models
        
        class TwilioVoiceService(models.Model):
            _inherit = 'voice.service'
            
            def process_voip_stream(self, stream_data, context=None):
                # Process Twilio audio stream
                # Convert to format expected by process_voice_request
                audio_bytes = self._convert_twilio_stream(stream_data)
                return super().process_voice_request(audio_bytes, context=context)
        ```
        """
        # Placeholder for VOIP streaming support
        # This can be extended by other modules for Twilio, Asterisk, etc.
        raise UserError('VOIP streaming not yet implemented. Extend this method in a custom module.')
    
    def _convert_voip_stream(self, stream_data, provider='twilio'):
        """
        Convert VOIP stream data to audio bytes format
        Can be extended for different VOIP providers
        
        Args:
            stream_data: Raw stream data from VOIP provider
            provider: VOIP provider name ('twilio', 'asterisk', etc.)
        
        Returns:
            bytes: Audio data in format expected by process_voice_request
        """
        # Placeholder - extend in custom modules
        raise NotImplementedError('VOIP stream conversion not implemented')

