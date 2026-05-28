# -*- coding: utf-8 -*-
from odoo import models, fields

class CausacionReglaExclusion(models.Model):
    _name = 'causacion.regla.exclusion'
    _description = 'Regla Visual de Exclusión de Impuestos'

    name = fields.Char(string='Nombre de la Regla', required=True)
    
    # Condiciones (Booleanos)
    filtro_regimen_simplificado = fields.Boolean(string='Aplica a Régimen Simplificado')
    filtro_regimen_simple = fields.Boolean(string='Aplica a Régimen Simple')
    filtro_autorretenedor = fields.Boolean(string='Aplica a Autorretenedor')
    
    # Acción
    tipo_impuesto_a_excluir = fields.Selection([
        ('iva', 'IVA'),
        ('retefuente', 'Retefuente'),
        ('reteica', 'ReteICA'),
        ('reteiva', 'ReteIVA')
    ], string='Tipo de Impuesto a Excluir', required=True)
