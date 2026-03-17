# -*- coding: utf-8 -*-

import json
import logging
import re
from odoo import models, fields, api
from odoo.exceptions import UserError, AccessError

_logger = logging.getLogger(__name__)


class VoiceQueryProcessor(models.AbstractModel):
    _name = 'voice.query.processor'
    _description = 'Voice Query Database Processor'

    MAX_RESULTS = 50  # Limit results for safety

    def _get_queryable_models(self):
        """Get list of queryable model names from settings"""
        queryable_models = self.env['ir.config_parameter'].sudo().get_param(
            'elevenlabs_connector.queryable_models', ''
        )
        
        if queryable_models:
            model_ids = [int(x) for x in queryable_models.split(',') if x.isdigit()]
            models = self.env['ir.model'].browse(model_ids)
            return [m.model for m in models]
        else:
            # Default allowed models if none specified
            return [
                'calendar.event',
                'account.move',
                'crm.lead',
                'res.partner',
                'sale.order',
                'purchase.order',
                'project.task',
                'hr.employee',
            ]

    def _is_model_allowed(self, model_name):
        """Check if a model is in the allowed queryable models list"""
        queryable_models = self._get_queryable_models()
        return model_name in queryable_models

    def _check_model_access(self, model_name, operation='read'):
        """Check if user has access to the model"""
        try:
            model = self.env[model_name]
            # Check if model exists and user has access
            if not self.env.user.has_group('base.group_user'):
                return False
            
            # Check access rights
            access = self.env['ir.model.access'].check(
                model_name, operation, raise_exception=False
            )
            return access
        except Exception as e:
            _logger.warning('Access check failed for model %s: %s', model_name, str(e))
            return False

    def _validate_domain(self, domain):
        """Validate domain to prevent SQL injection and unsafe queries"""
        if not isinstance(domain, list):
            return False
        
        # Only allow safe operators
        allowed_operators = ['=', '!=', '<', '>', '<=', '>=', 'like', 'ilike', 'in', 'not in', 'child_of', 'parent_of']
        
        for condition in domain:
            if not isinstance(condition, (list, tuple)) or len(condition) != 3:
                return False
            
            field, operator, value = condition
            
            # Validate operator
            if operator not in allowed_operators:
                return False
            
            # Validate field name (should be a valid field, no SQL injection)
            if not isinstance(field, str) or not re.match(r'^[a-z_][a-z0-9_.]*$', field):
                return False
        
        return True

    def _parse_ai_response(self, ai_response):
        """Parse AI response to extract query instructions"""
        try:
            # Try to find JSON in the response
            json_match = re.search(r'\{[^{}]*"action"[^{}]*\}', ai_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                try:
                    query_data = json.loads(json_str)
                    if query_data.get('action') == 'query':
                        return query_data
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            _logger.warning('Failed to parse AI response: %s', str(e))
        
        return None

    def process_ai_response(self, ai_response, context=None):
        """
        Process AI response and execute database queries if needed
        
        Args:
            ai_response: Text response from AI processor
            context: Additional context
        
        Returns:
            dict: {
                'text': Final response text,
                'data': Query results if any,
                'has_query': Boolean indicating if query was executed
            }
        """
        if context is None:
            context = {}
        
        # Try to parse query instructions from AI response
        query_data = self._parse_ai_response(ai_response)
        
        if query_data and query_data.get('action') == 'query':
            # Execute database query
            model_name = query_data.get('model')
            domain = query_data.get('domain', [])
            fields_to_read = query_data.get('fields', [])
            
            if not model_name:
                return {
                    'text': ai_response,
                    'data': None,
                    'has_query': False
                }
            
            # Security checks
            if not self._is_model_allowed(model_name):
                _logger.warning('Model %s is not in queryable models list', model_name)
                return {
                    'text': f"I don't have permission to query {model_name}. Please configure it in Settings → Integrations → ElevenLabs.",
                    'data': None,
                    'has_query': False
                }
            
            if not self._check_model_access(model_name, 'read'):
                _logger.warning('User %s does not have read access to model %s', self.env.user.name, model_name)
                return {
                    'text': f"I don't have permission to access {model_name}.",
                    'data': None,
                    'has_query': False
                }
            
            if not self._validate_domain(domain):
                _logger.warning('Invalid domain provided: %s', domain)
                return {
                    'text': 'Invalid query parameters. Please try rephrasing your question.',
                    'data': None,
                    'has_query': False
                }
            
            # Audit log: Database query execution
            _logger.info(
                'Database query executed by user %s: model=%s, domain=%s',
                self.env.user.name,
                model_name,
                str(domain)[:200]  # Log first 200 chars of domain
            )
            
            # Execute query
            try:
                results = self._execute_query(model_name, domain, fields_to_read)
                
                # Format results into readable text
                formatted_results = self._format_results(model_name, results, fields_to_read)
                
                # Combine AI response with query results
                final_text = f"{ai_response}\n\n{formatted_results}"
                
                return {
                    'text': final_text,
                    'data': results,
                    'has_query': True
                }
            except Exception as e:
                _logger.error('Query execution failed: %s', str(e))
                return {
                    'text': f"I encountered an error while querying the database: {str(e)}",
                    'data': None,
                    'has_query': False
                }
        
        # No query to execute, return AI response as-is
        return {
            'text': ai_response,
            'data': None,
            'has_query': False
        }

    def _execute_query(self, model_name, domain, fields_to_read):
        """Execute a safe database query"""
        try:
            model = self.env[model_name]
            
            # Apply domain with user's record rules
            records = model.search(domain, limit=self.MAX_RESULTS)
            
            if not records:
                return []
            
            # Read specified fields or default fields
            if fields_to_read:
                # Validate fields exist
                valid_fields = []
                for field_name in fields_to_read:
                    if field_name in model._fields:
                        valid_fields.append(field_name)
                if not valid_fields:
                    # Use default display fields
                    valid_fields = ['name', 'id']
            else:
                # Use default display fields
                if 'name' in model._fields:
                    valid_fields = ['name', 'id']
                else:
                    # Get first few fields
                    valid_fields = list(model._fields.keys())[:5]
            
            # Read data
            result_data = records.read(valid_fields)
            
            return result_data
        except AccessError:
            raise UserError('You do not have permission to access these records')
        except Exception as e:
            _logger.error('Query execution error: %s', str(e))
            raise UserError(f'Query execution failed: {str(e)}')

    def _format_results(self, model_name, results, fields_to_read):
        """Format query results into human-readable text"""
        if not results:
            return "No records found."
        
        model_info = self.env['ir.model']._get(model_name)
        model_label = model_info.name if model_info else model_name
        
        if len(results) == 1:
            result_text = f"Found 1 {model_label}:\n"
        else:
            result_text = f"Found {len(results)} {model_label}s:\n"
        
        for i, record in enumerate(results[:10], 1):  # Limit to 10 for readability
            result_text += f"\n{i}. "
            # Format record fields
            field_values = []
            for field_name, field_value in record.items():
                if field_name == 'id':
                    continue
                if isinstance(field_value, (list, tuple)):
                    field_value = ', '.join(str(v) for v in field_value[:3])
                field_values.append(f"{field_name}: {field_value}")
            result_text += ' | '.join(field_values)
        
        if len(results) > 10:
            result_text += f"\n\n... and {len(results) - 10} more results."
        
        return result_text

