# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    categoria_aprobacion_id = fields.Many2one(
        "approval.category",
        string="Categoría de aprobación (Approvals)",
        config_parameter="causacion_terceros_autorizaciones.categoria_aprobacion_id",
        help="Categoría usada cuando se crea solicitud de autorización desde el extractor.",
    )
 
 
 

    ocr_backend = fields.Selection([
        ('tesseract', 'Tesseract (legacy)'),
        ('openai', 'OpenAI (GPT-4o-mini)'),
    ], string="Backend OCR", default='openai',
        config_parameter='transcriptor_ocr.ocr_backend')

    openai_api_key = fields.Char(
        string="API Key de OpenAI",
        config_parameter='transcriptor_ocr.openai_api_key'
    )
    
        
    # Configuración Multi-Compañía para Diarios movida a res.company
    diario_pdf_id = fields.Many2one(
        related='company_id.diario_defecto_pdf_id',
        readonly=False,
    )
    diario_xml_id = fields.Many2one(
        related='company_id.diario_defecto_xml_id',
        readonly=False,
    )
    
    porcentaje_iva_mayor_valor = fields.Float(
        related='company_id.porcentaje_iva_mayor_valor',
        readonly=False,
    )

    def set_values(self):
        super(ResConfigSettings, self).set_values()

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        return res