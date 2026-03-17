# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models
from datetime import timedelta

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    signed_by = fields.Char(string="Signed By", copy=False)
    signed_on = fields.Datetime( string="Signed On", copy=False)
    signature = fields.Image(
        string="Signature",
        copy=False, attachment=True, max_width=1024, max_height=1024)