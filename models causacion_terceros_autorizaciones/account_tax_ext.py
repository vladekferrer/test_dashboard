# -*- coding: utf-8 -*-
from odoo import models, fields, api

class AccountTax(models.Model):
    _inherit = 'account.tax'

    es_iva = fields.Boolean(compute='_compute_clasificacion_fiscal', string='Es IVA')
    es_retefuente = fields.Boolean(compute='_compute_clasificacion_fiscal', string='Es Retefuente')
    es_reteica = fields.Boolean(compute='_compute_clasificacion_fiscal', string='Es ReteICA')
    es_reteiva = fields.Boolean(compute='_compute_clasificacion_fiscal', string='Es ReteIVA')

    @api.depends('tipo_impuesto_id')
    def _compute_clasificacion_fiscal(self):
        for rec in self:
            codigo = rec.tipo_impuesto_id.code if hasattr(rec, 'tipo_impuesto_id') and rec.tipo_impuesto_id else False
            rec.es_iva = (codigo == '01')
            rec.es_retefuente = (codigo == '06')
            rec.es_reteica = (codigo == '07')
            rec.es_reteiva = (codigo == '05')

#comentario