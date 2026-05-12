# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ReglaAsignacionServicio(models.Model):
    _name = "regla.asignacion.servicio"
    _description = "Regla de asignación de servicio (cruce extractor -> maestro.servicios)"
    _order = "prioridad desc, id desc"

    name = fields.Char(string="Nombre", required=True)

    active = fields.Boolean(default=True, string="Activa")

    company_id = fields.Many2one("res.company", string="Compañía", required=True, default=lambda self: self.env.company)

    proveedor_id = fields.Many2one("res.partner", string="Proveedor (opcional)")

    tipo_documento = fields.Selection(
        [
            ("xml", "Factura XML"),
            ("cuenta_cobro", "Cuenta de cobro (OCR)"),
            ("servicio_publico", "Servicio público (OCR)"),
            ("otro", "Otro (OCR)"),
        ],
        string="Tipo documento (opcional)"
    )

    # Ciudad: si tienes base_address_city y partner.city_id
    ciudad_id = fields.Many2one("res.city", string="Ciudad (opcional)")
    ciudad_texto = fields.Char(string="Ciudad texto (opcional)", help="Se compara con partner.city en mayúsculas.")

    contiene_texto = fields.Char(
        string="Contiene texto",
        required=True,
        help="Texto que debe aparecer en (concepto / emisor / texto OCR). Comparación case-insensitive."
    )

    servicio_id = fields.Many2one("maestro.servicios", string="Servicio a asignar", required=True)

    prioridad = fields.Integer(string="Prioridad", default=10)
    
    
    aplica_a = fields.Selection(
        [("documento", "Documento"), ("linea", "Línea")],
        string="Aplica a",
        default="linea",
        required=True
    )

    codigo_producto = fields.Char(
        string="Código producto (opcional)",
        help="Si se define, hace match exacto contra dian.invoice.line.product_code (AL01, AC08, etc.)."
    )
    

    @api.constrains("contiene_texto")
    def _check_contiene_texto(self):
        for r in self:
            if r.contiene_texto and len(r.contiene_texto.strip()) < 3:
                raise ValidationError(_("El 'Contiene texto' debe tener al menos 3 caracteres."))

    def match(self, payload):
        """
        payload: dict con claves:
        - company_id (int)
        - proveedor_id (int|False)
        - tipo_documento (str)
        - ciudad_id (int|False)
        - ciudad_texto (str|False)
        - texto_busqueda (str)
        """
        
        
        if self.aplica_a != payload.get("aplica_a"):
            return False

        if self.codigo_producto:
            if (payload.get("codigo_producto") or "").strip().upper() != self.codigo_producto.strip().upper():
                return False
                
        
        self.ensure_one()
        if not self.active:
            return False
        if self.company_id.id != payload.get("company_id"):
            return False

        if self.proveedor_id and self.proveedor_id.id != payload.get("proveedor_id"):
            return False

        if self.tipo_documento and self.tipo_documento != payload.get("tipo_documento"):
            return False

        if self.ciudad_id and payload.get("ciudad_id") and self.ciudad_id.id != payload.get("ciudad_id"):
            return False

        if self.ciudad_texto:
            ciudad = (payload.get("ciudad_texto") or "").upper()
            if self.ciudad_texto.strip().upper() not in ciudad:
                return False

        texto = (payload.get("texto_busqueda") or "").upper()
        return (self.contiene_texto or "").strip().upper() in texto



