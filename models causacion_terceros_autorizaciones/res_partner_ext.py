from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = 'res.partner'


    es_regimen_simplificado = fields.Boolean(compute='_compute_clasificacion_proveedor', string='Régimen Simplificado')
    es_regimen_simple = fields.Boolean(compute='_compute_clasificacion_proveedor', string='Régimen Simple')
    es_regimen_comun = fields.Boolean(compute='_compute_clasificacion_proveedor', string='Régimen Común')
    es_autorretenedor_renta = fields.Boolean(compute='_compute_clasificacion_proveedor', string='Autorretenedor de Renta')

    @api.depends('fe_tipo_regimen', 'fe_responsabilidad_tributaria', 'responsabilidad_fiscal_fe')
    def _compute_clasificacion_proveedor(self):
        for rec in self:
            # 1. Agarramos los valores directos y los pasamos a string/mayúsculas
            val_regimen = str(rec.fe_tipo_regimen or '').upper()
            val_trib = str(rec.fe_responsabilidad_tributaria or '').upper()
            
            # 2. Extracción directa al Many2one Golpe de nocaut
            fisc_code = ''
            fisc_significado = ''
            
            if rec.responsabilidad_fiscal_fe:
                fisc_code = str(rec.responsabilidad_fiscal_fe.codigo_fe_dian or '').upper()
                fisc_significado = str(rec.responsabilidad_fiscal_fe.significado or '').upper()
            
            # 3. Unificamos todo en una sola bolsa para el escaneo
            texto_responsabilidades = f"{val_trib} {fisc_code} {fisc_significado}"
            
            # Evaluamos los (Regímenes)
            rec.es_regimen_simplificado = (val_regimen in ['00', '0'])
            rec.es_regimen_simple = (val_regimen in ['04', '4'])
            rec.es_regimen_comun = (val_regimen in ['02', '2'])
            
            # Buscamos el cinturón de Autorretenedor en nuestro texto unificado
            rec.es_autorretenedor_renta = ('O-15' in texto_responsabilidades) or ('AUTORRETENEDOR' in texto_responsabilidades) or ('15' in texto_responsabilidades)