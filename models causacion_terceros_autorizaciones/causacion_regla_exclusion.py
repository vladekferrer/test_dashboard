# -*- coding: utf-8 -*-
from odoo import models, fields

class CausacionReglaExclusion(models.Model):
    _name = 'causacion.regla.exclusion'
    _description = 'Regla Visual de Exclusión de Impuestos'

    name = fields.Char(string='Nombre de la Regla', required=True)
    
    # Condiciones (Booleanos)
    filtro_regimen_simplificado = fields.Boolean(string='Aplica a Régimen Simplificado')
    filtro_regimen_simple = fields.Boolean(string='Aplica a Régimen Simple')
    filtro_regimen_comun = fields.Boolean(string='Aplica a Régimen Común')
    filtro_autorretenedor = fields.Boolean(string='Aplica a Autorretenedor')
    
    # Acción
    impuestos_a_excluir_ids = fields.Many2many(
        'l10n_co_cei.tax_type', 
        string='Impuestos a Excluir'
    )
