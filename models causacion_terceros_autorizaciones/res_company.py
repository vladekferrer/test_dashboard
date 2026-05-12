# -*- coding: utf-8 -*-
from odoo import fields, models

class ResCompany(models.Model):
    _inherit = 'res.company'

    porcentaje_iva_mayor_valor = fields.Float(
        string='Porcentaje IVA Mayor Valor Gasto (%)',
        help="Porcentaje del IVA que se asignará a la cuenta de Mayor Valor Gasto (Ej. 90 para 90%)"
    )
    diario_defecto_pdf_id = fields.Many2one(
        'account.journal', 
        string='Diario para OCR/PDF', 
        domain="[('type', '=', 'purchase')]"
    )
    diario_defecto_xml_id = fields.Many2one(
        'account.journal', 
        string='Diario para XML', 
        domain="[('type', '=', 'purchase')]"
    )
