# -*- coding: utf-8 -*-
import json
import base64
from difflib import SequenceMatcher
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class ApprovalProductLine(models.Model):
    _inherit = "approval.product.line"

    servicio_id = fields.Many2one("maestro.servicios", string="Servicio (IA)")
    price_unit = fields.Float(string="Precio Unitario")


class ApprovalRequest(models.Model):
    _inherit = "approval.request"

    # Datos “de negocio” para crear autorización
    proveedor_id = fields.Many2one("res.partner", string="Proveedor", tracking=True)
    servicio_id = fields.Many2one("maestro.servicios", string="Servicio", tracking=True)
    ciudad_id = fields.Many2one("res.city", string="Ciudad", tracking=True)

    tipo_contratacion = fields.Selection(
        [
            ("unica", "Única"),
            ("recurrente", "Recurrente"),
            ("anual", "Anual (contrato)"),
        ],
        string="Tipo de contratación",
        default="unica",
        required=True,
        tracking=True,
    )

    meses_vigencia = fields.Integer(
        string="Meses vigencia",
        tracking=True,
        help="Solo aplica para contratación recurrente.",
    )

    fecha_inicio = fields.Date(string="Inicio vigencia", tracking=True, default=lambda self: fields.Date.context_today(self))
    fecha_fin = fields.Date(string="Fin vigencia", tracking=True)

    monto_mensual_fijo = fields.Monetary(
        string="Monto mensual fijo",
        currency_field="currency_id",
        tracking=True,
    )
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id.id)

    autorizacion_servicio_id = fields.Many2one(
        "autorizacion.servicio",
        string="Autorización generada",
        readonly=True,
        tracking=True,
        ondelete="set null",
    )

    analisis_cotizaciones_json = fields.Text(string="Análisis JSON (Oculto)", copy=False)
    tablas_cotizaciones_html = fields.Html(string="Análisis Comparativo", compute="_compute_tablas_cotizaciones_html", store=False)
    cotizacion_ganadora_id = fields.Many2one(
        "ir.attachment", 
        string="Cotización Ganadora", 
        domain="[('res_model', '=', 'approval.request'), ('res_id', '=', id)]", 
        copy=False
    )
    
    requiere_correccion_creador = fields.Boolean(string="Requiere Corrección Creador", default=False, copy=False)
    is_approver = fields.Boolean(string="Es Aprobador", compute="_compute_is_approver")

    @api.depends("approver_ids.user_id")
    def _compute_is_approver(self):
        for rec in self:
            rec.is_approver = self.env.user in rec.approver_ids.mapped("user_id")

    @api.depends("analisis_cotizaciones_json")
    def _compute_tablas_cotizaciones_html(self):
        for rec in self:
            if not rec.analisis_cotizaciones_json:
                rec.tablas_cotizaciones_html = "<p>No hay análisis de cotizaciones.</p>"
                continue
                
            try:
                data = json.loads(rec.analisis_cotizaciones_json)
                html = "<div style='max-height: 400px; overflow-y: auto; overflow-x: hidden;'>"
                html += "<div style='display:flex; flex-wrap:wrap; gap:20px;'>"
                for item in data:
                    att_name = item.get("attachment_name", "")
                    info = item.get("data", {})
                    proveedor = info.get("proveedor", "Desconocido")
                    nit = info.get("nit", "N/A")
                    total = info.get("total_final", 0.0)
                    
                    html += f"<div style='border:1px solid #ddd; padding:15px; border-radius:5px; flex:1; min-width:300px;'>"
                    html += f"<h4>{proveedor} (NIT: {nit})</h4>"
                    html += f"<h5>Archivo: {att_name}</h5>"
                    
                    html += "<table style='width:100%; border-collapse:collapse; margin-bottom:10px;'>"
                    html += "<tr><th style='border:1px solid #ccc; padding:8px; background-color:#f8f9fa;'>Descripción</th><th style='border:1px solid #ccc; padding:8px; background-color:#f8f9fa;'>Precio Unitario</th></tr>"
                    
                    line_items = info.get("line_items", [])
                    for line in line_items:
                        desc = line.get("descripcion", "")
                        precio = line.get("precio_unitario", 0.0)
                        html += f"<tr><td style='border:1px solid #ccc; padding:8px;'>{desc}</td><td style='border:1px solid #ccc; padding:8px; text-align:right;'>${precio:,.2f}</td></tr>"
                    
                    html += f"<tr><td style='border:1px solid #ccc; padding:8px; font-weight:bold; text-align:right;'>TOTAL FINAL</td><td style='border:1px solid #ccc; padding:8px; font-weight:bold; text-align:right;'>${total:,.2f}</td></tr>"
                    html += "</table>"
                    html += "</div>"
                    
                html += "</div></div>"
                rec.tablas_cotizaciones_html = html
            except Exception as e:
                rec.tablas_cotizaciones_html = f"<p>Error al procesar el análisis: {str(e)}</p>"

    def action_analizar_cotizaciones(self):
        self.ensure_one()
        attachments = self.env['ir.attachment'].search([
            ('res_model', '=', 'approval.request'),
            ('res_id', '=', self.id)
        ])
        
        if not attachments:
            raise UserError(_("No hay cotizaciones adjuntas para analizar."))
            
        Transcriptor = self.env['transcriptor.ocr']
        transcriptor = Transcriptor.new({})
        llm_service = transcriptor._obtener_llm_service()
        if not llm_service:
            raise UserError(_("No se pudo obtener el servicio LLM. Verifique la API Key."))
            
        resultados = []
        for att in attachments:
            if not att.datas:
                continue
                
            pdf_bytes = base64.b64decode(att.datas)
            imagenes_b64 = transcriptor._preparar_imagenes_base64(pdf_bytes)
            if not imagenes_b64:
                continue
                
            res_paso1 = llm_service.extraer_texto_y_nit(imagenes_b64)
            texto = res_paso1.get("texto", "")
            if not texto:
                continue
                
            prompt_regla = """
Extrae el Nombre del Proveedor, el NIT o Cédula (solo números) y el TOTAL FINAL a pagar. Devuelve un JSON. 
REGLAS CRÍTICAS DE EXTRACCIÓN: 

REGLA 1 (IDENTIDAD): El NIT 800089872 (o 800089872-0) y el nombre 'DISMEL' corresponden SIEMPRE al cliente. ESTÁ TOTALMENTE PROHIBIDO poner a DISMEL como proveedor. El proveedor es la otra parte (puede ser una empresa o una persona natural con Cédula). 

REGLA 2 (ESTRUCTURA VISUAL Y SÍNTESIS): Si el documento tiene una tabla formal con varios conceptos, extrae CADA concepto como un ítem separado dentro del arreglo 'line_items'. SOLO si el documento es informal y NO tiene tabla (ej. texto corrido o listas sin formato), CREA UNA SOLA LÍNEA en 'line_items'. Para la 'descripcion' de esta única línea, SINTETIZA de qué trata el servicio creando un título corto y general de MÁXIMO 10 PALABRAS (Ej: 'Servicios de mantenimiento y desmontaje general'). ESTÁ ESTRICTAMENTE PROHIBIDO copiar y pegar todo el texto descriptivo original. 

REGLA 3 (TOTAL FINAL): El 'total_final' general DEBE ser el monto final y absoluto a pagar. IGNORA por completo anticipos, señas, o porcentajes. 

Devuelve un JSON con esta estructura: 
{ 
    "proveedor": "Nombre del proveedor", 
    "nit": "NIT", 
    "total_final": 0.0, 
    "line_items": [ 
        { 
            "descripcion": "Descripción (sintetizada si es informal)", 
            "precio_unitario": 0.0 
        } 
    ] 
} 
"""
            res_paso2 = llm_service.extraer_json_final(texto, prompt_regla)
            
            resultados.append({
                "attachment_id": att.id,
                "attachment_name": att.name,
                "data": res_paso2
            })
            
        self.analisis_cotizaciones_json = json.dumps(resultados, indent=4, ensure_ascii=False)
        return True

    @api.onchange('cotizacion_ganadora_id')
    def _onchange_cotizacion_ganadora_id(self):
        if not self.cotizacion_ganadora_id or not self.analisis_cotizaciones_json:
            return
            
        try:
            data = json.loads(self.analisis_cotizaciones_json)
            for item in data:
                if item.get("attachment_id") == self.cotizacion_ganadora_id.id:
                    info = item.get("data", {})
                    total = info.get("total_final", 0.0)
                    nit = info.get("nit", "")
                    line_items = info.get("line_items", [])
                    
                    if total:
                        self.monto_mensual_fijo = total
                        
                    if nit:
                        Transcriptor = self.env['transcriptor.ocr']
                        ocr_temp = Transcriptor.new({})
                        partner = ocr_temp._buscar_partner_por_identificacion(str(nit))
                        if partner:
                            self.proveedor_id = partner.id
                            
                    cmds = [(5, 0, 0)]
                    etiquetas = self.env['maestro.servicios.etiqueta'].search([])
                    requiere_correccion = False
                    
                    for line in line_items:
                        descripcion = line.get("descripcion", "")
                        precio = line.get("precio_unitario", 0.0)
                        
                        mejor_ratio = 0.0
                        mejor_etiqueta = None
                        for etiqueta in etiquetas:
                            if not etiqueta.name:
                                continue
                            ratio = SequenceMatcher(None, descripcion.lower(), etiqueta.name.lower()).ratio()
                            if ratio > mejor_ratio:
                                mejor_ratio = ratio
                                mejor_etiqueta = etiqueta
                                
                        servicio_id = False
                        if mejor_ratio >= 0.40 and mejor_etiqueta:
                            servicio_id = mejor_etiqueta.servicio_id.id
                            
                        if not servicio_id:
                            requiere_correccion = True
                            
                        cmds.append((0, 0, {
                            'description': descripcion,
                            'quantity': 1.0,
                            'price_unit': precio,
                            'servicio_id': servicio_id,
                        }))
                        
                    self.product_line_ids = cmds
                    self.requiere_correccion_creador = requiere_correccion
                    
                    # Asignar el servicio_id a la cabecera basado en la primera línea que tenga match
                    for cmd in cmds:
                        if cmd[0] == 0 and cmd[2].get('servicio_id'):
                            self.servicio_id = cmd[2]['servicio_id']
                            break
                    
                    if requiere_correccion and self._origin:
                        self._origin.message_post(
                            body=_("La cotización ganadora fue seleccionada, pero algunas líneas no pudieron ser emparejadas con un servicio. Por favor, asigne los servicios manualmente en la pestaña 'Detalle de la Propuesta'."),
                            partner_ids=[self._origin.request_owner_id.partner_id.id] if getattr(self._origin, "request_owner_id", False) else []
                        )
                    break
        except Exception:
            pass

    @api.onchange("tipo_contratacion", "meses_vigencia", "fecha_inicio")
    def _onchange_vigencia(self):
        for rec in self:
            if not rec.fecha_inicio:
                continue
            if rec.tipo_contratacion == "unica":
                rec.meses_vigencia = 0
                rec.fecha_fin = rec.fecha_inicio
            elif rec.tipo_contratacion == "recurrente":
                if rec.meses_vigencia and rec.meses_vigencia > 0:
                    rec.fecha_fin = rec.fecha_inicio + relativedelta(months=rec.meses_vigencia, days=-1)
                else:
                    rec.fecha_fin = False
            elif rec.tipo_contratacion == "anual":
                rec.meses_vigencia = 0
                rec.fecha_fin = rec.fecha_inicio + relativedelta(years=1, days=-1)

    def _validar_campos_para_autorizacion(self):
        for rec in self:
            faltantes = []
            if not rec.company_id:
                faltantes.append("Compañía")
            if not rec.proveedor_id:
                faltantes.append("Proveedor")
            if not rec.servicio_id:
                faltantes.append("Servicio")
            if not rec.fecha_inicio:
                faltantes.append("Inicio vigencia")
            if not rec.fecha_fin:
                faltantes.append("Fin vigencia")
            if rec.tipo_contratacion == "recurrente" and not (rec.meses_vigencia and rec.meses_vigencia > 0):
                faltantes.append("Meses vigencia (recurrente)")

            if faltantes:
                raise ValidationError(_("Faltan campos para autorizar: %s") % ", ".join(faltantes))

    def write(self, vals):
            # Regla: cuando ya no está en borrador, no permitir editar campos clave
            campos_clave = {
                "company_id", "proveedor_id", "servicio_id", "ciudad_id",
                "tipo_contratacion", "meses_vigencia", "fecha_inicio", "fecha_fin",
                "monto_mensual_fijo", "currency_id",
            }
            
            # Omitir la validación si la escritura incluye la asignación de la cotización ganadora.
            # Esto indica que los campos fueron inyectados legítimamente por el onchange de la IA.
            if any(k in vals for k in campos_clave) and "cotizacion_ganadora_id" not in vals:
                for rec in self:
                    estado = getattr(rec, "request_status", False)
                    # Permitir edición de campos si requiere corrección creador
                    if estado and estado != "new" and not rec.requiere_correccion_creador:
                        raise ValidationError(_("No puedes modificar Compañía/Proveedor/Servicio/Vigencia una vez enviada a aprobación."))

            res = super().write(vals)

            if "cotizacion_ganadora_id" in vals or "requiere_correccion_creador" in vals:
                for rec in self:
                    if rec.requiere_correccion_creador:
                        rec.message_post(
                            body=_("La cotización ganadora fue seleccionada, pero algunas líneas no pudieron ser emparejadas con un servicio. Por favor, asigne los servicios manualmente en la pestaña 'Detalle de la Propuesta'."),
                            partner_ids=[rec.request_owner_id.partner_id.id] if getattr(rec, "request_owner_id", False) else []
                        )

            # Validación al pasar a "pending"/"approved" (depende de tu flujo en Approvals)
            if "request_status" in vals and vals["request_status"] in ("pending", "approved"):
                self._validar_campos_para_autorizacion()

            return res

    def action_approve(self):
        res = super().action_approve()

        for rec in self:
            estado = getattr(rec, "request_status", False)
            if estado != "approved":
                continue

            rec._validar_campos_para_autorizacion()

            # Crear/actualizar autorización
            autorizacion_vals = {
                "compania_id": rec.company_id.id,
                "proveedor_id": rec.proveedor_id.id,
                "servicio_id": rec.servicio_id.id,
                "ciudad_id": rec.ciudad_id.id,
                "tipo_contratacion": rec.tipo_contratacion,
                "fecha_inicio": rec.fecha_inicio,
                "fecha_fin": rec.fecha_fin,
                "monto_mensual_fijo": rec.monto_mensual_fijo,
                "currency_id": rec.currency_id.id,
                "approval_request_id": rec.id,
            }

            Aut = self.env["autorizacion.servicio"]
            autorizacion = Aut.search([("approval_request_id", "=", rec.id)], limit=1)
            if autorizacion:
                autorizacion.write(autorizacion_vals)
            else:
                autorizacion = Aut.create(autorizacion_vals)

            rec.autorizacion_servicio_id = autorizacion.id

        return res
