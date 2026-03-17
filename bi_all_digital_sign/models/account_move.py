# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from datetime import timedelta

class AccountMove(models.Model):
	_inherit = "account.move"

	signed_person = fields.Char(string="Signed By", copy=False)
	signed_time = fields.Datetime(string="Signed On", copy=False)
	signature_in = fields.Image(
		string="Signature ",
		copy=False, attachment=True, max_width=800, max_height=800,readonly=False)