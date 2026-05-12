# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class DianInvoiceLine(models.Model):
    _inherit = "dian.invoice.line"

    servicio_id = fields.Many2one(
        "maestro.servicios",
        string="Servicio contable",
        help="Servicio que define cuenta e impuestos para esta línea."
    )

    cuenta_id = fields.Many2one(
        "account.account",
        string="Cuenta (derivada)",
        compute="_compute_config_contable",
        store=True,
        readonly=True,
    )

    impuesto_id = fields.Many2one(
        "account.tax",
        string="Impuesto (derivado)",
        compute="_compute_config_contable",
        store=True,
        readonly=True,
    )

    @api.depends("servicio_id", "servicio_id.linea_exclusion_ids")
    def _compute_config_contable(self):
        """
        Disparador que popula cuenta_id e impuesto_id en la línea del OCR
        basándose en la configuración del maestro de servicios asignado.
        """
        for line in self:
            cuenta = False
            impuesto = False
            
            if line.servicio_id and line.servicio_id.linea_exclusion_ids:
                # Tomar la primera configuración disponible en el maestro
                cfg = line.servicio_id.linea_exclusion_ids[0]
                if cfg.cuentas:
                    cuenta = cfg.cuentas
                if cfg.grupo_impuestos:
                    impuesto = cfg.grupo_impuestos[0]
                    
            line.cuenta_id = cuenta
            line.impuesto_id = impuesto