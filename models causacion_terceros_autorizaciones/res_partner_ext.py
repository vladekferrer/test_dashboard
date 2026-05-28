# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    es_regimen_simplificado = fields.Boolean(compute='_compute_clasificacion_proveedor', string='Régimen Simplificado')
    es_regimen_simple = fields.Boolean(compute='_compute_clasificacion_proveedor', string='Régimen Simple')
    es_autorretenedor_renta = fields.Boolean(compute='_compute_clasificacion_proveedor', string='Autorretenedor de Renta')

    @api.depends('fe_tipo_regimen', 'fe_responsabilidad_tributaria')
    def _compute_clasificacion_proveedor(self):
        for rec in self:
            regimen = getattr(rec, 'fe_tipo_regimen', False)
            resp = getattr(rec, 'fe_responsabilidad_tributaria', False) or ''
            
            rec.es_regimen_simplificado = (regimen == '00')
            rec.es_regimen_simple = (regimen == '04')
            
            # string 'O-15' o 'Autorretenedor'
            rec.es_autorretenedor_renta = ('O-15' in resp) or ('Autorretenedor' in resp)
