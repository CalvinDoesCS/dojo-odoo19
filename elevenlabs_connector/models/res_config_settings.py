# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    """Add ElevenLabs configuration to main Settings page."""
    _inherit = 'res.config.settings'

    # ElevenLabs Configuration
    elevenlabs_api_key = fields.Char(
        string='ElevenLabs API Key',
        config_parameter='elevenlabs_connector.api_key',
        help='Your ElevenLabs API key. Get it from https://elevenlabs.io/app/settings/api-keys',
    )
    
    elevenlabs_voice_id = fields.Char(
        string='Default Voice ID',
        config_parameter='elevenlabs_connector.voice_id',
        default='21m00Tcm4TlvDq8ikWAM',  # Default ElevenLabs voice
        help='ElevenLabs voice model ID. Default: Rachel (21m00Tcm4TlvDq8ikWAM)',
    )
    
    elevenlabs_language = fields.Selection(
        [
            ('en', 'English'),
            ('es', 'Spanish'),
            ('fr', 'French'),
            ('de', 'German'),
            ('it', 'Italian'),
            ('pt', 'Portuguese'),
            ('pl', 'Polish'),
            ('tr', 'Turkish'),
            ('ru', 'Russian'),
            ('nl', 'Dutch'),
            ('cs', 'Czech'),
            ('ar', 'Arabic'),
            ('zh', 'Chinese'),
            ('ja', 'Japanese'),
            ('hu', 'Hungarian'),
            ('ko', 'Korean'),
        ],
        string='Language',
        config_parameter='elevenlabs_connector.language',
        default='en',
        help='Language for voice output',
    )
    
    # AI Provider Configuration
    ai_provider = fields.Selection(
        [
            ('openai', 'OpenAI'),
            ('gemini', 'Google Gemini'),
            ('odoo_native', 'Odoo Native AI'),
            ('custom', 'Custom Provider'),
        ],
        string='AI Provider',
        config_parameter='elevenlabs_connector.ai_provider',
        default='openai',
        help='Select the AI provider for processing voice queries',
    )
    
    openai_api_key = fields.Char(
        string='OpenAI API Key',
        config_parameter='elevenlabs_connector.openai_api_key',
        help='Your OpenAI API key. Get it from https://platform.openai.com/api-keys',
    )
    
    gemini_api_key = fields.Char(
        string='Gemini API Key',
        config_parameter='elevenlabs_connector.gemini_api_key',
        help='Your Google Gemini API key. Get it from https://makersuite.google.com/app/apikey',
    )
    
    # Test Connection
    elevenlabs_connection_status = fields.Char(
        string='Connection Status',
        readonly=True,
        help='Status of the last connection test to ElevenLabs API',
    )

    def action_test_elevenlabs_connection(self):
        """Test connection to ElevenLabs API"""
        self.ensure_one()
        if not self.elevenlabs_api_key:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'Please enter an API key first',
                    'type': 'danger',
                    'sticky': True,
                }
            }
        
        try:
            service = self.env['elevenlabs.service']
            result = service.test_connection(self.elevenlabs_api_key)
            if result:
                self.elevenlabs_connection_status = 'Connected successfully'
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Success',
                        'message': 'ElevenLabs API connection successful',
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                raise ValidationError('Connection test failed - Invalid API key or network error')
        except UserError as e:
            _logger.error('ElevenLabs connection test failed: %s', str(e))
            self.elevenlabs_connection_status = f'Error: {str(e)}'
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Failed',
                    'message': f'Failed to connect to ElevenLabs: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }
        except Exception as e:
            _logger.error('ElevenLabs connection test failed: %s', str(e), exc_info=True)
            self.elevenlabs_connection_status = f'Error: {str(e)}'
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Failed',
                    'message': f'Failed to connect to ElevenLabs: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

