# -*- coding: utf-8 -*-
from odoo import models, fields

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    tax_decision_log = fields.Text(string='Historial de Decisión Fiscal')
    
