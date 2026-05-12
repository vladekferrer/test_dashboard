import re
import logging
from datetime import timedelta
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class MaestroServiciosEtiqueta(models.Model):
    _name = 'maestro.servicios.etiqueta'
    _description = 'Etiqueta de Servicio'

    name = fields.Char(string='Descripción', required=True)
    servicio_id = fields.Many2one('maestro.servicios', string='Servicio', ondelete='cascade')

class MaestroServiciosLine(models.Model):
    _name = 'maestro.servicios.line'
    
    maestro_id = fields.Many2one('maestro.servicios')
    cuentas = fields.Many2one('account.account', string='Cuentas')
    grupo_impuestos = fields.Many2many('account.tax', string='Impuestos')

class MaestroServicios(models.Model):
    _name = 'maestro.servicios'
    
    name = fields.Char(string='Nombre', required=True)
    codigo = fields.Char(string='Código')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    cuenta_pago = fields.Many2one('account.account', string='Cuenta de Pago')
    
    
    linea_exclusion_ids = fields.One2many(
        'maestro.servicios.line', 
        'maestro_id', 
        string='Exclusiones'
    )
    
    etiquetas_ids = fields.One2many(
        'maestro.servicios.etiqueta',
        'servicio_id',
        string='Etiquetas Sincronizadas'
    )

    def action_sincronizar_etiquetas(self):
        """
        Sincroniza descripciones de los apuntes contables (account.move.line) de los últimos 14 días
        basado en el rango de cuentas configuradas en las exclusiones del servicio.
        """
        self.ensure_one()
        
        cuentas_validas = self.linea_exclusion_ids.filtered(lambda l: l.cuentas and l.grupo_impuestos)
        if not cuentas_validas:
            self.etiquetas_ids.unlink()
            _logger.info("Sincronización abortada para servicio %s: No hay líneas con cuenta e impuesto configurado. Se eliminaron las etiquetas previas.", self.id)
            return

        codigos_numericos = []
        for line in cuentas_validas:
            codigo_str = line.cuentas.code
            if not codigo_str:
                continue
            # Extraer solo números
            solo_numeros = re.sub(r'\D', '', codigo_str)
            if solo_numeros:
                codigos_numericos.append(int(solo_numeros))

        if not codigos_numericos:
            self.etiquetas_ids.unlink()
            _logger.info("Sincronización abortada para servicio %s: No se encontraron códigos numéricos válidos en las cuentas.", self.id)
            return

        min_code = min(codigos_numericos)
        max_code = max(codigos_numericos)

        # Buscar las cuentas que caigan en ese rango numérico
        # Odoo guarda los 'code' como Char, así que debemos evaluarlos en memoria
        # Para optimizar un poco, traemos todas las cuentas de la compañía actual
        todas_cuentas = self.env['account.account'].search([('company_id', '=', self.company_id.id)])
        account_ids_encontrados = []
        for cuenta in todas_cuentas:
            if not cuenta.code:
                continue
            num_code = re.sub(r'\D', '', cuenta.code)
            if num_code and min_code <= int(num_code) <= max_code:
                account_ids_encontrados.append(cuenta.id)

        if not account_ids_encontrados:
            _logger.info("Servicio %s: No se encontraron cuentas en el rango %s - %s.", self.id, min_code, max_code)
            return

        # Calcular fecha hace 14 días
        # fecha_hace_14_dias = fields.Date.context_today(self) - timedelta(days=14)

        # Buscar en account.move.line
        apuntes = self.env['account.move.line'].search([
            ('account_id', 'in', account_ids_encontrados),
            ('company_id', '=', self.company_id.id), 
        ], order='date desc, id desc', limit=20000)

        _logger.info("Servicio %s: Se escanearon los últimos %s apuntes contables (límite 20k) para el rango de cuentas %s - %s.", self.id, len(apuntes), min_code, max_code)

        descripciones_encontradas = set()
        for apunte in apuntes:
            nombre = apunte.name
            if nombre and nombre.strip() and nombre.strip() != '/':
                descripciones_encontradas.add(nombre.strip())

        # Descripciones ya existentes en el One2many
        descripciones_existentes = set(self.etiquetas_ids.mapped('name'))

        # Filtrar solo las nuevas
        nuevas_descripciones = descripciones_encontradas - descripciones_existentes

        if nuevas_descripciones:
            # Crear los registros en bloque
            etiquetas_vals = [{'name': desc, 'servicio_id': self.id} for desc in nuevas_descripciones]
            self.env['maestro.servicios.etiqueta'].create(etiquetas_vals)
    
        _logger.info("Servicio %s: Sincronización completada. Se agregaron %s etiquetas nuevas.", self.id, len(nuevas_descripciones))
    
    
class AccountTax(models.Model):
    _inherit = 'account.tax'
    
    
    monto_uvt = fields.Float(string='Monto UVT', store=True)
    
    
class ResPartner(models.Model):
    _inherit = "res.partner"
    
    # Heredar y extender el campo de selección
    fe_es_compania = fields.Selection(
        selection_add=[
            ('3', 'Natural declarante')
        ]
    )