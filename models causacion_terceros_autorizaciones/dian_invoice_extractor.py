# -*- coding: utf-8 -*-
import base64
import re
import json
import logging
from datetime import datetime, timedelta
import time
from difflib import SequenceMatcher

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

CODIGO_RE = re.compile(r"^(?P<code>[A-Z]{2}\d{2})(?:\s+(?P<cc>\d+))?\s+(?P<body>.+)$")


class DianInvoiceExtractor(models.Model):
    _inherit = "dian.invoice.extractor"

    # -------------------------
    # Campos nuevos (coherentes con tu módulo y tus vistas)
    # -------------------------
    compania_id = fields.Many2one("res.company", string="Compañía", tracking=True, default=lambda self: self.env.company)

    # Compatibilidad: si algún código aún usa company_id, esto evita errores.
    company_id = fields.Many2one("res.company", related="compania_id", store=True, readonly=False)

    proveedor_id = fields.Many2one("res.partner", string="Proveedor", tracking=True)
    servicio_id = fields.Many2one("maestro.servicios", string="Servicio", tracking=True)

    fecha_efectiva = fields.Date(string="Fecha efectiva", tracking=True)
    monto_documento = fields.Monetary(string="Valor a pagar", currency_field="currency_id", tracking=True)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id.id)

    es_xml = fields.Boolean(string="Es XML", readonly=True, tracking=True)

    estado_ocr = fields.Selection(
        [("no_aplica", "No aplica (XML)"),
         ("pendiente", "Pendiente validación"),
         ("validado", "Validado")],
        string="Estado OCR",
        default="no_aplica",
        tracking=True,
    )
    texto_ocr = fields.Text(string="Texto OCR", readonly=True)
    datos_ocr_json = fields.Text(string="Datos OCR (JSON)", readonly=True)

    naturaleza_documento = fields.Selection(
        [("productos", "Productos"),
         ("servicios", "Servicios"),
         ("mixto", "Mixto"),
         ("desconocido", "Desconocido")],
        string="Naturaleza",
        default="desconocido",
        tracking=True,
    )
    ciudad_documento = fields.Char(string="Ciudad (documento)", tracking=True)

    bloqueado = fields.Boolean(string="Bloqueado", default=False, tracking=True)
    motivo_bloqueo = fields.Text(string="Motivo bloqueo", tracking=True)

    autorizacion_servicio_id = fields.Many2one(
        "autorizacion.servicio", string="Autorización vigente", tracking=True
    )

    factura_proveedor_id = fields.Many2one(
        "account.move", string="Factura proveedor", readonly=True, tracking=True, ondelete="set null"
    )

    ciudad_prestacion = fields.Char(string="Ciudad Prestación", help="Ciudad extraída por OCR para asignación analítica")



    def _crear_linea_generica(self):
        """Crea una línea genérica si no hay líneas pero hay monto total."""
        self.invoice_lines.unlink()
        self.env["dian.invoice.line"].create({
            'invoice_id': self.id,
            'sequence': 1,
            'description': _('Servicio según documento'),
            'quantity': 1.0,
            'price_unit': self.monto_documento,
            'line_extension_amount': self.monto_documento,
            'tax_amount': 0.0,
            'tax_percent': 0.0,
        })





    def _crear_lineas_desde_line_items(self, line_items):
        """Crea líneas de factura a partir de line_items, manejando valores nulos."""
        self.invoice_lines.unlink()  # Eliminar líneas anteriores
        Line = self.env["dian.invoice.line"]
        seq = 1

        # Cargar etiquetas en memoria para Fuzzy Matching
        etiquetas = self.env['maestro.servicios.etiqueta'].search([])

        # Asegurar que line_items sea una lista
        if not isinstance(line_items, list):
            line_items = [line_items] if line_items else []

        # Lógica Anti-Ceros: Si todas las líneas tienen valor 0, pero hay un monto global, inyectarlo a la primera
        if line_items and self.monto_documento:
            todos_cero = all(self._parse_money(it.get('valor_total_linea', 0.0)) == 0 for it in line_items if isinstance(it, dict))
            if todos_cero:
                _logger.warning("Lógica Anti-Ceros: Todas las líneas extraídas tienen valor 0. Inyectando monto global %s a la primera línea.", self.monto_documento)
                for it in line_items:
                    if isinstance(it, dict):
                        it['valor_total_linea'] = self.monto_documento
                        break  # Solo a la primera línea

        for item in line_items:
            if not item or not isinstance(item, dict):
                continue

            # Forzar cantidad a 1 y usar el valor total como precio unitario sin cálculos
            cantidad = 1.0
            valor_total = self._parse_money(item.get('valor_total_linea', 0.0))
            price_unit = valor_total
            base_sin_iva = valor_total

            descripcion = (item.get('descripcion') or '').strip()
            
            # Fuzzy Matching para asignar servicio
            servicio_asignado_id = False
            umbral_minimo = 0.90 if getattr(self, 'es_xml', False) else 0.40
            
            if descripcion:
                mejor_ratio = 0.0
                mejor_etiqueta = None
                for etiqueta in etiquetas:
                    if not etiqueta.name:
                        continue
                    ratio = SequenceMatcher(None, descripcion.lower(), etiqueta.name.lower()).ratio()
                    if ratio > mejor_ratio:
                        mejor_ratio = ratio
                        mejor_etiqueta = etiqueta

                if mejor_ratio >= umbral_minimo and mejor_etiqueta:
                    servicio_asignado_id = mejor_etiqueta.servicio_id.id
                    _logger.info("OCR Fuzzy Match: Línea '%s' asignada al servicio '%s' (Ratio: %.2f%%)", descripcion, mejor_etiqueta.servicio_id.name, mejor_ratio * 100)
                else:
                    _logger.info("OCR Fuzzy Match: Línea '%s' sin coincidencia suficiente (Mejor ratio: %.2f%%, requerido: %.2f%%)", descripcion, mejor_ratio * 100, umbral_minimo * 100)

            # Fallback (El Paracaídas del Servicio)
            if not servicio_asignado_id:
                servicio_asignado_id = self.servicio_id.id if self.servicio_id else False
                _logger.info("OCR Paracaídas: Asignando servicio por defecto de la cabecera (ID: %s)", servicio_asignado_id)

            vals = {
                'invoice_id': self.id,
                'sequence': seq,
                'product_code': (item.get('codigo') or '').strip(),
                'description': descripcion,
                'quantity': cantidad,
                'price_unit': round(price_unit, 6),
                'line_extension_amount': round(base_sin_iva, 2),
                'tax_amount': 0.0,
                'tax_percent': 0.0,
                'tax_scheme': '',
                'servicio_id': servicio_asignado_id,
            }
            Line.create(vals)
            seq += 1



    def _mapear_datos_llm_a_campos(self, extracted):
        """Convierte el dict del LLM en un dict con valores normalizados para los campos."""
        datos = {}

        # --- FECHA DE EMISIÓN ---
        fecha_emision = extracted.get('fecha_emision')
        if fecha_emision:
            try:
                # Intentar varios formatos comunes
                fecha_str = str(fecha_emision).strip()
                for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
                    try:
                        datos['fecha_efectiva'] = datetime.strptime(fecha_str, fmt).date()
                        break
                    except ValueError:
                        continue
            except Exception:
                pass

        # Si no hay fecha_emision, probar con periodo_fin
        if not datos.get('fecha_efectiva') and extracted.get('periodo_fin'):
            try:
                fecha_str = str(extracted['periodo_fin']).strip()
                for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
                    try:
                        datos['fecha_efectiva'] = datetime.strptime(fecha_str, fmt).date()
                        break
                    except ValueError:
                        continue
            except Exception:
                pass

        # --- NÚMERO DE FACTURA ---
        if extracted.get('numero_factura'):
            datos['invoice_number'] = str(extracted['numero_factura']).strip()

        # --- NIT PROVEEDOR (solo dígitos) ---
        nit_prov = extracted.get('nit_proveedor')
        if nit_prov:
            nit_prov = re.sub(r'\D', '', str(nit_prov))
            if len(nit_prov) > 9:
                nit_prov = nit_prov[:9]  # Colombia: NIT de 9 dígitos
            datos['nit_proveedor'] = nit_prov

        # --- NIT CLIENTE ---
        nit_cli = extracted.get('id_cliente')
        if nit_cli:
            nit_cli = re.sub(r'\D', '', str(nit_cli))
            if len(nit_cli) > 9:
                nit_cli = nit_cli[:9]
            datos['nit_cliente'] = nit_cli

        # --- NOMBRE PROVEEDOR ---
        if extracted.get('nombre_proveedor'):
            datos['nombre_proveedor'] = str(extracted['nombre_proveedor']).strip()

        # --- TOTAL (convertir a float) ---
        total = extracted.get('total')
        if total is not None:
            datos['monto_documento'] = self._parse_money(total)

        # --- TIPO DE DOCUMENTO (opcional, para clasificación) ---
        if extracted.get('tipo_documento'):
            tipo = str(extracted['tipo_documento']).lower()
            if 'invoice' in tipo or 'factura' in tipo:
                datos['tipo_documento'] = 'invoice'
            elif 'charge' in tipo or 'cuenta' in tipo:
                datos['tipo_documento'] = 'charge'
            else:
                datos['tipo_documento'] = 'other'

        return datos




    # =====================================================================
    # FIX RAÍZ: process_xml_invoice() NO debe intentar parsear PDF/IMG
    # (porque el modelo original lo llama automáticamente en create/write)
    # =====================================================================
    def process_xml_invoice(self):
        """
        El modelo original (transcriptor_ocr) llama process_xml_invoice() en create/write
        SIN validar el tipo de archivo. Este override evita que intente parsear PDF/IMG.
        """
        for rec in self:
            data, filename = rec._obtener_binario_y_nombre()
            if not data:
                return True
            if not rec._parece_xml(data, filename):
                # No es XML => NO ejecutar el parser XML del módulo original.
                _logger.info("process_xml_invoice(): archivo NO XML (%s). Se omite parseo XML.", filename)
                return True

            # Sí es XML => ejecutar el método original
            return super(DianInvoiceExtractor, rec).process_xml_invoice()

        return True

    # -------------------------
    # Hooks create/write
    # -------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Heredar servicio_id si viene con autorizacion_servicio_id y no trae servicio
            if not vals.get('servicio_id') and vals.get('autorizacion_servicio_id'):
                auth = self.env['autorizacion.servicio'].browse(vals['autorizacion_servicio_id'])
                if auth.exists() and auth.servicio_id:
                    vals['servicio_id'] = auth.servicio_id.id

        records = super().create(vals_list)
        # Autoprocesar si entró archivo al crear
        for rec, vals in zip(records, vals_list):
            if rec._cambio_archivo_en_vals(vals):
                rec.action_procesar_documento()
        return records

    def write(self, vals):
        res = super().write(vals)

        # Reprocesar si cambió el archivo
        if self._cambio_archivo_en_vals(vals):
            self.with_context(evitar_bucle_proceso=True).action_procesar_documento()

        # Re-evaluar bloqueo si cambian campos clave
        if {"compania_id", "proveedor_id", "servicio_id", "fecha_efectiva", "monto_documento", "estado_ocr"} & set(vals.keys()):
            self._evaluar_bloqueo()

        if 'servicio_id' in vals and vals['servicio_id']:
            for rec in self:
                lineas_vacias = rec.invoice_lines.filtered(lambda l: not l.servicio_id)
                if lineas_vacias:
                    lineas_vacias.write({'servicio_id': vals['servicio_id']})

        return res

    def _cambio_archivo_en_vals(self, vals):
        posibles = {"file_data", "archivo", "original_file", "attachment_id", "file", "datas", "file_name"}
        return bool(posibles & set(vals.keys()))

    # -------------------------
    # Acciones UI
    # -------------------------
    def action_procesar_documento(self):
        action_res = None
        for rec in self:
            data, filename = rec._obtener_binario_y_nombre()
            if not data:
                continue

            if rec._parece_xml(data, filename):
                rec._procesar_xml_usando_extractor(data, filename)
            else:
                res = rec._procesar_ocr(data, filename)
                if isinstance(res, dict) and res.get('type') == 'ir.actions.client':
                    action_res = res
            rec._aplicar_reglas_asignacion_servicio()
            rec._evaluar_bloqueo()
        return action_res

    def action_validar_ocr(self):
        for rec in self:
            if rec.estado_ocr != "pendiente":
                continue
            rec.estado_ocr = "validado"

            # Si es OCR y no hay líneas, generarlas
            if not rec.es_xml and not rec.invoice_lines:
                rec._generar_invoice_lines_desde_ocr()

            rec._aplicar_reglas_asignacion_servicio()
            rec._evaluar_bloqueo()

    def action_solicitar_autorizacion(self):
        self.ensure_one()
        if not self.bloqueado:
            raise UserError(_("Este documento no está bloqueado."))

        categoria_id = self.env["ir.config_parameter"].sudo().get_param(
            "causacion_terceros_autorizaciones.categoria_aprobacion_id"
        )
        if not categoria_id:
            raise UserError(_(
                "No está configurada la categoría de aprobación.\n"
                "Ve a Ajustes > Causación terceros > Categoría de aprobación."
            ))

        vals = {
            "name": _("Autorización: %s") % (self.servicio_id.display_name if self.servicio_id else _("(sin servicio)")),
            "category_id": int(categoria_id),
            "request_owner_id": self.env.user.id,
            "compania_id": self.compania_id.id,
            "proveedor_id": self.proveedor_id.id,
            "servicio_id": self.servicio_id.id,
            "fecha_inicio": self.fecha_efectiva or fields.Date.context_today(self),
            "monto_mensual_fijo": self.monto_documento,
            "tipo_contratacion": "unica",
        }
        req = self.env["approval.request"].create(vals)

        return {
            "type": "ir.actions.act_window",
            "name": _("Solicitud de aprobación"),
            "res_model": "approval.request",
            "res_id": req.id,
            "view_mode": "form",
            "target": "current",
        }




    def _construir_lineas_factura_desde_invoice_lines(self): 
        self.ensure_one() 

        if not self.invoice_lines: 
            raise UserError(_("No hay líneas DIAN para construir la factura.")) 

        # exigir servicio por línea (para cuentas distintas) 
        faltantes = self.invoice_lines.filtered(lambda l: not getattr(l, "servicio_id", False)) 
        if faltantes: 
            cods = ", ".join([(l.product_code or "SIN-COD") for l in faltantes[:10]]) 
            raise UserError(_("Hay líneas sin servicio asignado. Ejemplos: %s") % cods) 

        cmds = [] 
        
        # Obtener el porcentaje dinámicamente desde la compañía 
        porcentaje = self.compania_id.porcentaje_iva_mayor_valor if self.compania_id else self.env.company.porcentaje_iva_mayor_valor 
        ratio_mv = porcentaje / 100.0 
        ratio_desc = 1.0 - ratio_mv 
        
        # Acumulador global para el IVA Mayor Valor 
        total_iva_mayor_valor_acumulado = 0.0 

        for l in self.invoice_lines: 
            servicio = l.servicio_id 

            # tu maestro.servicios usa linea_exclusion_ids, y la cuenta es 'cuentas', impuesto 'grupo_impuestos' 
            if not servicio.linea_exclusion_ids: 
                raise UserError(_("El servicio '%s' no tiene líneas configuradas (linea_exclusion_ids).") % servicio.display_name) 

            cfg = servicio.linea_exclusion_ids[0] 
            if not cfg.cuentas: 
                raise UserError(_("El servicio '%s' no tiene cuenta (cuentas).") % servicio.display_name) 

            qty = l.quantity or 1.0 
            base = l.line_extension_amount or 0.0 
            # Mantenemos alta precisión para el cálculo base 
            price_unit = round((base / qty) if qty else base, 6) 

            vals = { 
                "name": (l.description or servicio.display_name), 
                "quantity": qty, 
                "price_unit": price_unit, 
                "account_id": cfg.cuentas.id, 
            } 
            
            # Recolectar impuestos EXCLUSIVAMENTE desde el maestro.servicios 
            tax_ids = [] 
            
            if servicio and servicio.linea_exclusion_ids: 
                for linea in servicio.linea_exclusion_ids: 
                    if linea.grupo_impuestos: 
                        for impuesto in linea.grupo_impuestos: 
                            if impuesto.id not in tax_ids: 
                                tax_ids.append(impuesto.id) 
                                
            # Identificar si hay IVA (impuesto con monto > 0) 
            tiene_iva = False 
            other_tax_ids = [] 
            tasa_iva = 0.0 
            
            if tax_ids: 
                impuestos = self.env['account.tax'].browse(tax_ids) 
                for imp in impuestos: 
                    if imp.amount > 0: # Asumimos que IVA tiene amount > 0 
                        tiene_iva = True 
                        tasa_iva = imp.amount / 100.0 # Convertir 19.0 a 0.19 
                    else: 
                        other_tax_ids.append(imp.id) 
                        
            # Prorrateo Nativo 
            if ratio_mv > 0.0 and tiene_iva: 
                # Obtener cuenta Mayor Valor (última fila de exclusión del servicio) 
                cuenta_mayor_valor_id = False 
                if servicio.linea_exclusion_ids: 
                    cuenta_mayor_valor_id = servicio.linea_exclusion_ids[-1].cuentas.id 
                    
                if not cuenta_mayor_valor_id: 
                    raise UserError(_("El servicio '%s' no tiene cuenta configurada en su última línea de exclusión para el IVA Mayor Valor Gasto.") % servicio.display_name) 
                
                # Cálculo virtual del IVA Mayor Valor a acumular 
                monto_iva_mv = (price_unit * ratio_mv) * tasa_iva 
                total_iva_mayor_valor_acumulado += (monto_iva_mv * qty) 
                
                # Línea 1 (Gasto 90% - Descontable) 
                vals_desc = vals.copy() 
                vals_desc["price_unit"] = round(price_unit * ratio_desc, 6) 
                if tax_ids: 
                    vals_desc["tax_ids"] = [(6, 0, tax_ids)] 
                cmds.append((0, 0, vals_desc)) 
                
                # Línea 2 (Gasto 10% - Mayor Valor) 
                vals_mv = vals.copy() 
                pct_entero = int(porcentaje) if porcentaje.is_integer() else round(porcentaje, 2) 
                vals_mv["name"] = vals_mv["name"] + f" - {pct_entero}% Base Gasto" 
                vals_mv["price_unit"] = round(price_unit * ratio_mv, 6) 
                vals_mv["account_id"] = cfg.cuentas.id # LA MISMA cuenta de gasto 
                if other_tax_ids: 
                    vals_mv["tax_ids"] = [(6, 0, other_tax_ids)] # Retenciones sí, IVA no 
                else: 
                    vals_mv.pop("tax_ids", None) # Remove if empty 
                cmds.append((0, 0, vals_mv)) 
                
                subtotal_calculado = round(qty * round(price_unit * ratio_desc, 6), 2) + round(qty * round(price_unit * ratio_mv, 6), 2) 
                _logger.info("Línea dividida por Prorrateo IVA: Ratio MV %s, Ratio Desc %s, IVA Acumulado: %s", ratio_mv, ratio_desc, monto_iva_mv) 
            else: 
                if tax_ids: 
                    vals["tax_ids"] = [(6, 0, tax_ids)] 
                cmds.append((0, 0, vals)) 
                subtotal_calculado = round(qty * price_unit, 2) 

            # Validación de seguridad: Ajuste de redondeo por pérdida de precisión 
            base_esperada = round(base, 2) 
            diferencia = round(base_esperada - subtotal_calculado, 2) 
            
            if diferencia != 0.0: 
                ajuste_vals = { 
                    "name": _("Ajuste automático de redondeo OCR"), 
                    "quantity": 1.0, 
                    "price_unit": diferencia, 
                    "account_id": cfg.cuentas.id, 
                } 
                if tax_ids: 
                    ajuste_vals["tax_ids"] = [(6, 0, tax_ids)] 
                    
                cmds.append((0, 0, ajuste_vals)) 
                _logger.warning("OCR Ajuste de redondeo: Diferencia de %s detectada en la línea '%s'. Línea de ajuste inyectada.", diferencia, l.description) 

        # Inyectar línea final de IVA Mayor Valor Acumulado si aplica 
        if total_iva_mayor_valor_acumulado > 0: 
            cuenta_mayor_valor_final_id = False 
            servicio_final = self.servicio_id or (self.invoice_lines[-1].servicio_id if self.invoice_lines else False) 
            if servicio_final and servicio_final.linea_exclusion_ids: 
                cuenta_mayor_valor_final_id = servicio_final.linea_exclusion_ids[-1].cuentas.id 
                
            if cuenta_mayor_valor_final_id: 
                vals_iva_acumulado = { 
                    "name": "Total IVA Mayor Valor Gasto", 
                    "quantity": 1.0, 
                    "price_unit": round(total_iva_mayor_valor_acumulado, 2), 
                    "account_id": cuenta_mayor_valor_final_id, 
                } 
                cmds.append((0, 0, vals_iva_acumulado)) 
                _logger.info("Inyectada línea global de Total IVA Mayor Valor Gasto por monto: %s", vals_iva_acumulado["price_unit"]) 
            else: 
                _logger.error("No se pudo inyectar la línea global de IVA Mayor Valor porque no se encontró cuenta en el servicio.") 

        return cmds




    def action_crear_factura_proveedor(self):
        """
        Crea un account.move (in_invoice) validando autorizaciones y 
        mapeando las líneas del OCR a líneas contables.
        """
        for rec in self:
            rec._asegurar_listo_para_contabilizar()

            if rec.factura_proveedor_id:
                return rec._action_abrir_factura(rec.factura_proveedor_id)

            # Validación de Autorización
            if not rec.autorizacion_servicio_id:
                raise UserError(_(
                    "No se puede crear la factura: Este documento no tiene una autorización "
                    "de servicio vigente asignada (autorizacion_servicio_id)."
                ))


            # Obtener diario
            company = rec.company_id or self.env.company
            if getattr(rec, 'es_xml', False):
                journal_id = company.diario_defecto_xml_id.id
            else:
                journal_id = company.diario_defecto_pdf_id.id
                
            if not journal_id:
                raise UserError(_("No se puede crear la factura: Por favor configure los diarios por defecto (XML/PDF) en los ajustes de la compañía %s.") % company.name)

            # B. Cuenta Analítica por ciudad_prestacion (Prioridad)
            analitica = False
            ciudad_limpia = ""
            if rec.ciudad_prestacion:
                ciudad_limpia = rec.ciudad_prestacion.strip()
            elif rec.proveedor_id:
                if getattr(rec.proveedor_id, 'city_id', False):
                    ciudad_limpia = rec.proveedor_id.city_id.name.strip()
                elif getattr(rec.proveedor_id, 'city', False):
                    ciudad_limpia = rec.proveedor_id.city.strip()





            if ciudad_limpia:
                # Buscar cuenta analítica con operador ilike
                analitica = self.env['account.analytic.account'].search([('name', '=ilike', f'%{ciudad_limpia}%')], limit=1)
                if analitica:
                    _logger.info("Cuenta Analítica encontrada para ciudad '%s': %s (ID: %s)", ciudad_limpia, analitica.name, analitica.id)
                else:
                    _logger.warning("No se encontró cuenta analítica para la ciudad '%s'", ciudad_limpia)

            # Mapear líneas de factura desde las líneas extraídas (dian.invoice.line)
            lineas_factura = rec._construir_lineas_factura_desde_invoice_lines()
            
            # C. Distribución Binaria del IVA (Mayor Valor Gasto)
            nuevas_lineas = []
            for comando in lineas_factura:
                if comando[0] == 0:
                    vals = comando[2]
                    
                    
                    # 1. Asignar Analítica si la cuenta empieza por '5'
                    if analitica:
                        cuenta_id = vals.get('account_id')
                        if cuenta_id:
                            cuenta = self.env['account.account'].browse(cuenta_id)
                            if cuenta.exists() and cuenta.code and cuenta.code.startswith('5'):
                                vals['analytic_account_id'] = analitica.id
                                _logger.info("Cuenta analítica %s asignada a línea con cuenta contable %s", analitica.name, cuenta.code)

                # Si no es un comando de creación o no aplica prorrateo, agregar tal cual (con o sin analítica)
                nuevas_lineas.append(comando)
            
            lineas_factura = nuevas_lineas

            # Armar referencia concatenando el número de factura y el servicio
            numero_factura = rec._get_numero_documento() or ''
            servicio = rec.servicio_id
            ref_str = f"{numero_factura} - {servicio.name}" if servicio else numero_factura

            # Lógica de Forma de Pago y Vencimiento Automático
            fecha_factura = rec._get_fecha_emision() or rec.fecha_efectiva or fields.Date.context_today(rec)
            invoice_date_due = fecha_factura
            forma_de_pago = '1' # Por defecto Contado
            payment_term_id = False
            
            if rec.proveedor_id.property_supplier_payment_term_id:
                payment_term = rec.proveedor_id.property_supplier_payment_term_id
                payment_term_id = payment_term.id
                # Buscar el plazo máximo de días en las líneas
                max_days = max([line.days for line in payment_term.line_ids], default=0)
                
                if max_days > 0:
                    forma_de_pago = '2' # Crédito
                    invoice_date_due = fecha_factura + timedelta(days=max_days)
            
            # Valores para crear el account.move
            move_vals = {
                "move_type": "in_invoice",
                "company_id": rec.compania_id.id,
                "partner_id": rec.proveedor_id.id,
                "journal_id": journal_id,
                "invoice_date": fecha_factura,
                "invoice_date_due": invoice_date_due,
                "invoice_payment_term_id": payment_term_id,
                "forma_de_pago": forma_de_pago,
                "ref": ref_str,
                "payment_reference": ref_str,
                "invoice_line_ids": lineas_factura,
            }

            # Crear factura de proveedor
            move = self.env["account.move"].with_company(rec.compania_id.id).create(move_vals)
            
            # Relacionar factura con el extractor
            rec.factura_proveedor_id = move.id
            
            # Agregar la factura como adjunto/referencia al chatter
            rec.message_post(
                body=_("Factura de proveedor creada exitosamente: %s") % move.name,
            )

            return rec._action_abrir_factura(move)

    def _action_abrir_factura(self, move):
        return {
            "type": "ir.actions.act_window",
            "name": _("Factura proveedor"),
            "res_model": "account.move",
            "res_id": move.id,
            "view_mode": "form",
            "target": "current",
        }

    # -------------------------
    # Validaciones previas
    # -------------------------
    def _asegurar_listo_para_contabilizar(self):
        self.ensure_one()

        if self.bloqueado:
            raise UserError(_("Documento bloqueado: %s") % (self.motivo_bloqueo or ""))

        if not self.compania_id:
            raise UserError(_("Falta Compañía."))

        if not self.proveedor_id:
            raise UserError(_("Falta Proveedor."))

        if not self.servicio_id:
            raise UserError(_("Falta Servicio (maestro.servicios)."))

        if not self.es_xml and self.estado_ocr != "validado":
            raise UserError(_("Debe validar el OCR antes de crear la factura."))

        if not self.monto_documento:
            raise UserError(_("Falta monto (valor a pagar)."))

    # -------------------------
    # Lectura / detección archivo
    # -------------------------
    def _safe_b64decode(self, value):
        if not value:
            return None
        if isinstance(value, bytes):
            # si ya parece binario real (PDF/PNG/JPG), no lo decodifiques
            if value.startswith((b"%PDF", b"\x89PNG", b"\xff\xd8")):
                return value
            try:
                return base64.b64decode(value, validate=True)
            except Exception:
                try:
                    return base64.b64decode(value)
                except Exception:
                    return value
        if isinstance(value, str):
            return base64.b64decode(value)
        return value

    def _obtener_binario_y_nombre(self):
        self.ensure_one()
        filename = self.file_name or None
        data = None

        # modelo original: file_data siempre existe
        if "file_data" in self._fields and self.file_data:
            data = self._safe_b64decode(self.file_data)

        return data, filename

    def _parece_xml(self, data: bytes, filename: str):
        # Por extensión: nunca confundir PDF/imagenes con XML
        if filename and filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")):
            return False

        head = (data or b"")[:2048].lstrip()

        # Firmas binarias
        if head.startswith(b"%PDF") or head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8"):
            return False

        low = head.lower()
        if low.startswith(b"<?xml"):
            return True

        # XML DIAN/UBL puede iniciar con <Invoice> o <AttachedDocument> etc.
        if low.startswith(b"<") and (b"<invoice" in low or b"<attacheddocument" in low or b"<creditnote" in low or b"<debitnote" in low):
            return True

        return False

    # -------------------------
    # Procesamiento XML
    # -------------------------
    def _procesar_xml_usando_extractor(self, data: bytes, filename: str):
        self.ensure_one()
        self.es_xml = True
        self.estado_ocr = "no_aplica"
        self.texto_ocr = False
        self.datos_ocr_json = False

        from lxml import etree
        _logger.info("Iniciando parseo de XML nativo para el documento ID: %s", self.id)
        lines_data = []
        
        try:
            root = etree.fromstring(data)
            
            # [2. EXTRACCIÓN DEL CDATA (BLINDADA)]
            _logger.info("Buscando nodo CDATA (AttachedDocument/Description)...")
            cdata_nodes = root.xpath("//*[local-name()='Description'][contains(text(), 'Invoice')]")
            if not cdata_nodes:
                cdata_nodes = root.xpath(".//*[local-name()='Attachment']//*[local-name()='Description']")
                
            if not cdata_nodes:
                _logger.warning("NO SE ENCONTRÓ CDATA EN EL XML")
                raise UserError(_("No se pudo extraer la factura del sobre DIAN (CDATA no encontrado)."))
                
            cdata_text = cdata_nodes[0].text
            _logger.info("CDATA encontrado con longitud: %s", len(cdata_text))
            
            root_factura = etree.fromstring(cdata_text.encode('utf-8'))
            
            # Extraer campos de cabecera desde la factura (dentro del CDATA)
            invoice_number = root_factura.xpath('//*[local-name()="ID"]/text()')
            if invoice_number:
                self.invoice_number = invoice_number[0]
                
            # [3. SECUENCIA ESTRICTA: PROVEEDOR -> AUTORIZACIÓN -> SERVICIO]
            supplier_nit = root_factura.xpath('//*[local-name()="AccountingSupplierParty"]//*[local-name()="PartyTaxScheme"]/*[local-name()="CompanyID"]/text()')
            if supplier_nit:
                self.supplier_nit = supplier_nit[0]
                _logger.info("Buscando proveedor con NIT: %s", self.supplier_nit)
                
                nit_prov = self._normalizar_identificacion(self.supplier_nit)
                if nit_prov:
                    prov = self._buscar_partner_por_identificacion(nit_prov)
                    if prov:
                        self.proveedor_id = prov.id
                        _logger.info("Proveedor encontrado: %s", prov.name)
                        
                        _logger.info("Buscando autorización vigente para proveedor %s...", prov.name)
                        auth = self.env['autorizacion.servicio'].search([
                            ('proveedor_id', '=', prov.id),
                            ('compania_id', '=', self.compania_id.id),
                            ('estado', '=', 'vigente')
                        ], limit=1)
                        
                        if auth:
                            _logger.info("Autorización vigente encontrada: %s", auth.display_name)
                            self.autorizacion_servicio_id = auth.id
                            self.servicio_id = auth.servicio_id.id
                        else:
                            _logger.info("No se encontró autorización vigente para el proveedor %s", prov.name)
                    else:
                        _logger.warning("Proveedor con NIT %s no encontrado en res.partner", self.supplier_nit)
                
            customer_nit = root_factura.xpath('//*[local-name()="AccountingCustomerParty"]//*[local-name()="PartyTaxScheme"]/*[local-name()="CompanyID"]/text()')
            if customer_nit:
                self.customer_nit = customer_nit[0]
                nit_cliente = self._normalizar_identificacion(self.customer_nit)
                if nit_cliente:
                    compania = self._buscar_compania_por_nit(nit_cliente)
                    if compania:
                        self.compania_id = compania.id
                
            issue_date = root_factura.xpath('//*[local-name()="IssueDate"]/text()')
            if issue_date:
                self.issue_date = issue_date[0]
                
            payable_amount = root_factura.xpath('//*[local-name()="LegalMonetaryTotal"]/*[local-name()="PayableAmount"]/text()')
            if payable_amount:
                self.payable_amount = payable_amount[0]
                
            # [4. CREACIÓN DE LÍNEAS DIAN]
            invoice_lines = root_factura.xpath('//*[local-name()="InvoiceLine"]')
            _logger.info("Líneas encontradas en el XML: %s", len(invoice_lines))
            
            for line in invoice_lines:
                desc = line.xpath('.//*[local-name()="Item"]/*[local-name()="Description"]/text()')
                amount = line.xpath('.//*[local-name()="LineExtensionAmount"]/text()')
                
                lines_data.append({
                    'descripcion': desc[0] if desc else '',
                    'valor_total_linea': float(amount[0]) if amount else 0.0
                })
                
        except Exception as e:
            _logger.error("Error en extracción XML: %s", str(e))
            raise UserError(_("Error procesando el XML: %s") % str(e))

        self.fecha_efectiva = self.invoice_period_end or self.issue_date or fields.Date.context_today(self)
        self.monto_documento = float(self.payable_amount or 0.0)

        # Llenar 'invoice_lines' desde la extracción nativa
        if lines_data:
            self._crear_lineas_desde_line_items(lines_data)

        # --- LÓGICA DE AUTOMATIZACIÓN XML -> FACTURA ---
        # 1. Propagar servicio_id a la cabecera si está vacío y alguna línea hizo Fuzzy Match
        if not self.servicio_id:
            linea_con_servicio = self.invoice_lines.filtered(lambda l: l.servicio_id)
            if linea_con_servicio:
                self.servicio_id = linea_con_servicio[0].servicio_id.id
                _logger.info("Auto-propagación XML: servicio_id %s asignado a la cabecera desde la línea.", self.servicio_id.name)

        # 2. Automatizar validación y creación de factura si los datos críticos están listos
        self._aplicar_reglas_asignacion_servicio()
        self._evaluar_bloqueo()
        
        if self.proveedor_id and self.servicio_id and not self.bloqueado:
            _logger.info("Automatización XML: Documento %s tiene proveedor y servicio. Intentando crear factura...", self.id)
            try:
                self.action_crear_factura_proveedor()
                _logger.info("Automatización XML: Factura creada exitosamente para el documento %s.", self.id)
            except Exception as e:
                _logger.error("Automatización XML falló al crear factura para el documento %s: %s", self.id, str(e))
                self._crear_actividad_si_aplica(_("Fallo en la automatización de la factura XML: %s") % str(e))
        else:
            self._crear_actividad_si_aplica(_("Revisar XML: Completar Proveedor/Servicio o revisar bloqueos."))

    # -------------------------
    # OCR
    # -------------------------
    def _parse_json_dict(self, value):
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return json.loads(value)
            except Exception:
                return {}
        return {}

    def _limpiar_texto_llm(self, text):
        if not text:
            return ""
        s = re.sub(r'!\[[^\]]*\]\([^)]+\)', ' ', text)
        s = re.sub(r'<[^>]+>', ' ', s)
        s = re.sub(r'\s+', ' ', s)
        return s.strip()

    def _buscar_regla_llm(self):
        """DEPRECATED: El prompt ahora es universal."""
        return True

    def _procesar_ocr(self, data: bytes, filename: str):
        self.ensure_one()
        self.es_xml = False
        self.estado_ocr = "pendiente"

        if not self.env.registry.get("transcriptor.ocr"):
            raise UserError(_("No existe el modelo transcriptor.ocr o el módulo OCR no está instalado."))

        # Crear documento OCR con company_id para que encuentre la regla correcta
        t_inicio_ocr = time.time()
        ocr_vals = {
            "name": filename or _("Documento OCR"),
            "original_file": base64.b64encode(data).decode('utf-8'),
            "file_name": filename or False,
        }
        
        # Pasar company_id si ya está asignado
        if self.compania_id:
            ocr_vals["company_id"] = self.compania_id.id
        
        ocr_doc = self.env["transcriptor.ocr"].create(ocr_vals)
        
        # Ejecutar OCR + LLM (esto ya busca la regla y extrae con LLM)
        res_action = ocr_doc.action_procesar_documento()
        
        _logger.info(
            "OCR terminado para extractor %s en %.2fs",
            self.id,
            time.time() - t_inicio_ocr,
        )

        # Obtener resultados ya procesados por transcriptor.ocr
        self.texto_ocr = self._limpiar_texto_llm(ocr_doc.raw_text or "")
        extracted_raw = ocr_doc.extracted_data or "{}"

        # Guardar JSON extraído
        self.datos_ocr_json = extracted_raw if isinstance(extracted_raw, str) else json.dumps(extracted_raw, ensure_ascii=False, indent=2)

        # Parsear JSON
        extracted_data = self._parse_json_dict(extracted_raw)
        datos_mapeados = self._mapear_datos_llm_a_campos(extracted_data)
        
        _logger.info(
            "Datos extraídos para extractor %s: claves JSON=%s, datos_mapeados=%s",
            self.id,
            list(extracted_data.keys()) if isinstance(extracted_data, dict) else type(extracted_data),
            list(datos_mapeados.keys()),
        )

        # Copiar proveedor_id desde transcriptor.ocr si fue detectado
        if ocr_doc.proveedor_id and not self.proveedor_id:
            self.proveedor_id = ocr_doc.proveedor_id.id
            _logger.info(
                "Proveedor copiado desde transcriptor.ocr %s: %s",
                ocr_doc.id,
                ocr_doc.proveedor_id.name,
            )

        # Asignar compañía usando NIT del cliente
        nit_cliente = datos_mapeados.get('nit_cliente')
        if nit_cliente and not self.compania_id:
            company = self._buscar_compania_por_nit(nit_cliente)
            if company:
                self.compania_id = company.id

        # Fallback: buscar proveedor por NIT si no fue detectado
        if not self.proveedor_id:
            nit_proveedor = datos_mapeados.get('nit_proveedor')
            if nit_proveedor:
                partner = self._buscar_partner_por_identificacion(nit_proveedor)
                if partner:
                    self.proveedor_id = partner.id

        # Fallback: buscar por nombre de proveedor
        if not self.proveedor_id and datos_mapeados.get('nombre_proveedor'):
            partner = self.env['res.partner'].search([
                ('name', 'ilike', datos_mapeados['nombre_proveedor']),
                ('company_type', '=', 'company')
            ], limit=1)
            if partner:
                self.proveedor_id = partner.id

        # Fallback: regex NIT en texto OCR
        if not self.proveedor_id and self.texto_ocr:
            m = re.search(r'\bNIT[:\s]*([0-9\.\-]+)', self.texto_ocr, re.IGNORECASE)
            if m:
                nit_fallback = re.sub(r'\D', '', m.group(1))
                nit_fallback = nit_fallback[:9] if len(nit_fallback) > 9 else nit_fallback
                if nit_fallback:
                    partner = self._buscar_partner_por_identificacion(nit_fallback)
                    if partner:
                        self.proveedor_id = partner.id
                        _logger.info(
                            "Proveedor asignado por regex NIT en extractor %s: %s (%s)",
                            self.id,
                            partner.id,
                            nit_fallback,
                        )

        # Asignar campos básicos desde datos mapeados
        if datos_mapeados.get('fecha_efectiva'):
            self.fecha_efectiva = datos_mapeados['fecha_efectiva']
        if extracted_data.get('total_a_pagar') is not None:
            self.monto_documento = self._parse_money(extracted_data['total_a_pagar'])
        elif datos_mapeados.get('monto_documento') is not None:
            self.monto_documento = datos_mapeados['monto_documento']
        if datos_mapeados.get('invoice_number'):
            self.invoice_number = datos_mapeados['invoice_number']
            
        # Asignar ciudad_prestacion extraída del JSON para uso posterior
        if extracted_data.get('ciudad_prestacion'):
            self.ciudad_prestacion = extracted_data.get('ciudad_prestacion')

        # Generar líneas de factura desde line_items
        if extracted_data.get('line_items'):
            self._crear_lineas_desde_line_items(extracted_data['line_items'])
        else:
            # Fallback al método tradicional
            self._generar_invoice_lines_desde_ocr()

        # Si aún no hay líneas pero hay monto, crear una línea genérica
        if not self.invoice_lines and self.monto_documento:
            self._crear_linea_generica()

        # --- LÓGICA DE AUTOMATIZACIÓN OCR -> FACTURA ---
        # 1. Propagar servicio_id a la cabecera si está vacío y alguna línea hizo Fuzzy Match
        if not self.servicio_id:
            linea_con_servicio = self.invoice_lines.filtered(lambda l: l.servicio_id)
            if linea_con_servicio:
                self.servicio_id = linea_con_servicio[0].servicio_id.id
                _logger.info("Auto-propagación: servicio_id %s asignado a la cabecera desde la línea.", self.servicio_id.name)

        # 2. Automatizar validación y creación de factura si los datos críticos están listos
        if self.proveedor_id and self.servicio_id:
            _logger.info("Automatización OCR: Documento %s tiene proveedor y servicio. Intentando validar y crear factura...", self.id)
            try:
                self.action_validar_ocr()
                # Omitimos el return de la acción de vista de la factura para no interrumpir el flujo backend
                self.action_crear_factura_proveedor()
                _logger.info("Automatización OCR: Factura creada exitosamente para el documento %s.", self.id)
            except Exception as e:
                _logger.error("Automatización OCR falló al crear factura para el documento %s: %s", self.id, str(e))
                self._crear_actividad_si_aplica(_("Fallo en la automatización de la factura: %s") % str(e))
        else:
            # Crear actividad para que el usuario revise si faltan datos clave
            self._crear_actividad_si_aplica(_("Validar OCR y completar Proveedor/Servicio/Compañía."))

        return res_action

    # -------------------------
    # Bloqueo por autorización + datos maestros
    # -------------------------
    def _evaluar_bloqueo(self):
        for rec in self:
            faltantes = []

            if not rec.compania_id:
                faltantes.append("Compañía")
            if not rec.proveedor_id:
                faltantes.append("Proveedor")
            if not rec.servicio_id:
                faltantes.append("Servicio")
            if not rec.fecha_efectiva:
                faltantes.append("Fecha efectiva")
            if not rec.monto_documento:
                faltantes.append("Monto (valor a pagar)")

            if not rec.es_xml and rec.estado_ocr != "validado":
                faltantes.append("Validación OCR")

            # Ciudad: acepta city_id o city (Char)
            tiene_ciudad = False
            if rec.proveedor_id:
                if "city_id" in rec.proveedor_id._fields and rec.proveedor_id.city_id:
                    tiene_ciudad = True
                elif (rec.proveedor_id.city or "").strip():
                    tiene_ciudad = True
            if not tiene_ciudad:
                faltantes.append("Ciudad del proveedor (configurar en Contactos)")

            if faltantes:
                rec.bloqueado = True
                rec.autorizacion_servicio_id = False
                rec.motivo_bloqueo = _("Faltan datos: %s") % ", ".join(faltantes)
                rec._crear_actividad_si_aplica(rec.motivo_bloqueo)
                continue

            autorizacion = rec._buscar_autorizacion_vigente(
                compania_id=rec.compania_id.id,
                proveedor_id=rec.proveedor_id.id,
                servicio_id=rec.servicio_id.id,
                fecha=rec.fecha_efectiva,
            )

            if not autorizacion:
                rec.bloqueado = True
                rec.autorizacion_servicio_id = False
                rec.motivo_bloqueo = _("No existe autorización vigente para este proveedor/servicio en esa fecha.")
                rec._crear_actividad_si_aplica(rec.motivo_bloqueo)
                continue

            monto_aut = autorizacion.monto_mensual_fijo or 0.0
            if monto_aut and abs((rec.monto_documento or 0.0) - monto_aut) > 0.01:
                rec.bloqueado = True
                rec.autorizacion_servicio_id = autorizacion.id
                rec.motivo_bloqueo = _(
                    "Monto no coincide con monto fijo autorizado. Documento: %(doc)s / Autorizado: %(aut)s"
                ) % {"doc": rec.monto_documento, "aut": monto_aut}
                rec._crear_actividad_si_aplica(rec.motivo_bloqueo)
                continue

            rec.bloqueado = False
            rec.autorizacion_servicio_id = autorizacion.id
            rec.motivo_bloqueo = False

    def _buscar_autorizacion_vigente(self, compania_id, proveedor_id, servicio_id, fecha):
        Aut = self.env["autorizacion.servicio"]
        domain = [
            ("compania_id", "=", compania_id),
            ("proveedor_id", "=", proveedor_id),
            ("servicio_id", "=", servicio_id),
            ("fecha_inicio", "<=", fecha),
            ("fecha_fin", ">=", fecha),
            ("estado", "=", "vigente"),
        ]

        # Si hay city_id estructurado, permite autorización sin ciudad o con la misma
        city_id = self._get_ciudad_proveedor_id()
        if city_id:
            domain += ["|", ("ciudad_id", "=", False), ("ciudad_id", "=", city_id)]

        return Aut.search(domain, limit=1)

    # -------------------------
    # Construcción factura proveedor
    # -------------------------
    # -------------------------
    # TODO lo demás: dejo tu código intacto debajo (helpers, líneas, etc.)
    # -------------------------

    def _obtener_linea_configuracion_servicio(self):
        self.ensure_one()
        servicio = self.servicio_id

        line_field = self._find_first_field(servicio, ["line_ids", "linea_ids", "servicio_line_ids", "servicios_line_ids", "linea_exclusion_ids"])
        if not line_field:
            raise UserError(_("No encontré el One2many de líneas en maestro.servicios."))

        lineas = getattr(servicio, line_field)
        if not lineas:
            raise UserError(_("El servicio no tiene líneas de configuración."))

        # filtrar por company si existe en la línea (y usar compania_id)
        if self._field_exists(lineas, "company_id"):
            lineas = lineas.filtered(lambda l: (not l.company_id) or (l.company_id.id == self.compania_id.id)) or lineas

        # filtrar por ciudad si existe
        ciudad_id = self._get_ciudad_proveedor_id()
        for city_field in ("city_id", "ciudad_id"):
            if self._field_exists(lineas, city_field) and ciudad_id:
                lineas_ciudad = lineas.filtered(lambda l: getattr(l, city_field).id == ciudad_id)
                if lineas_ciudad:
                    lineas = lineas_ciudad
                    break

        return lineas[:1]

    # ----- (aquí sigue tu mismo bloque de métodos tal como lo tenías) -----

    def _construir_lineas_factura(self, linea_cfg):
        # tu implementación actual
        cuenta_id = self._get_cuenta_gasto_id(linea_cfg)
        impuestos_ids = []
        if self._field_exists(linea_cfg, "grupo_impuestos") and linea_cfg.grupo_impuestos:
            impuestos_ids = linea_cfg.grupo_impuestos.ids
        analytic_id = self._get_analytic_id(linea_cfg)

        extracted_lines = self._get_extracted_lines()
        commands = []

        if extracted_lines:
            for l in extracted_lines:
                nombre = self._get_line_value(l, ["description", "name", "concept", "producto", "item_name"]) or self.servicio_id.display_name
                qty = self._to_float(self._get_line_value(l, ["quantity", "qty", "cantidad"])) or 1.0
                price_unit = self._to_float(self._get_line_value(l, ["price_unit", "unit_price", "valor_unitario", "unitValue"]))
                subtotal = self._to_float(self._get_line_value(l, ["subtotal", "price_subtotal", "line_extension_amount", "base"]))
                if not price_unit:
                    if subtotal and qty:
                        price_unit = subtotal / qty
                    else:
                        price_unit = (self.monto_documento or 0.0) / qty

                vals = {
                    "name": nombre,
                    "quantity": qty,
                    "price_unit": price_unit,
                    "account_id": cuenta_id,
                }
                if impuestos_ids:
                    vals["tax_ids"] = [(6, 0, impuestos_ids)]
                if analytic_id:
                    vals["analytic_account_id"] = analytic_id
                commands.append((0, 0, vals))
        else:
            vals = {
                "name": self.servicio_id.display_name,
                "quantity": 1.0,
                "price_unit": self.monto_documento,
                "account_id": cuenta_id,
            }
            if impuestos_ids:
                vals["tax_ids"] = [(6, 0, impuestos_ids)]
            if analytic_id:
                vals["analytic_account_id"] = analytic_id
            commands.append((0, 0, vals))

        return commands

    def _get_extracted_lines(self):
        self.ensure_one()
        for fname in ["line_ids", "invoice_line_ids", "lines", "detalle_ids", "item_ids", "invoice_lines"]:
            if fname in self._fields:
                lines = getattr(self, fname)
                if lines:
                    return lines
        return False

    def _get_line_value(self, line, names):
        for n in names:
            if hasattr(line, n):
                return getattr(line, n)
        return False

    def _get_cuenta_gasto_id(self, linea_cfg):
        self.ensure_one()
        candidatos = [
            "account_id", "cuenta_id", "cuenta_gasto_id", "cuenta_gastos_id",
            "expense_account_id", "account_expense_id", "cuentas"
        ]
        for f in candidatos:
            if self._field_exists(linea_cfg, f):
                acc = getattr(linea_cfg, f)
                if acc:
                    return acc.id
        raise UserError(_("No encontré la cuenta de gasto en maestro.servicios.line."))

    def _get_analytic_id(self, linea_cfg):
        for f in ["analytic_account_id", "cuenta_analitica_id", "analytic_id"]:
            if self._field_exists(linea_cfg, f):
                a = getattr(linea_cfg, f)
                return a.id if a else False
        return False

    def _get_fecha_emision(self):
        return self._get_first_existing_value(["issue_date", "fecha_emision", "invoice_date"])

    def _get_numero_documento(self):
        return self._get_first_existing_value(["invoice_number", "numero", "number", "ref", "cufe", "uuid"])

    def _get_first_existing_value(self, field_names):
        for fn in field_names:
            if fn in self._fields:
                v = getattr(self, fn)
                if v:
                    return v
        return False

    def _get_ciudad_proveedor_id(self):
        self.ensure_one()
        p = self.proveedor_id
        if not p:
            return False
        if "city_id" in p._fields and p.city_id:
            return p.city_id.id
        return False

    def _normalizar_identificacion(self, value):
        if not value:
            return None
        digits = re.sub(r"\D+", "", str(value))
        if len(digits) >= 9:
            return digits[:9]
        return digits or None



    def _buscar_partner_por_identificacion(self, nit_9):
        if not nit_9:
            return self.env["res.partner"]
        
        domain_base = [('id', '!=', self.env.company.partner_id.id)]
        
        candidatos = self.env["res.partner"].search(domain_base + [("fe_nit", "ilike", nit_9)], limit=20)
        nit_9_norm = self._normalizar_identificacion(nit_9)
        for p in candidatos:
            if self._normalizar_identificacion(getattr(p, "fe_nit", "")) == nit_9_norm:
                return p

        candidatos = self.env["res.partner"].search(domain_base + [("vat", "ilike", nit_9)], limit=20)
        for p in candidatos:
            if self._normalizar_identificacion(getattr(p, "vat", "")) == nit_9_norm:
                return p

        return self.env["res.partner"]

    def _buscar_compania_por_nit(self, nit_9):
        if not nit_9:
            return self.env["res.company"]
        comps = self.env["res.company"].search([("partner_id.fe_nit", "ilike", nit_9)])
        nit_9 = self._normalizar_identificacion(nit_9)
        for c in comps:
            if self._normalizar_identificacion(getattr(c.partner_id, "fe_nit", "")) == nit_9:
                return c
        return self.env["res.company"]

    def _to_float(self, value):
        if value in (None, False, ""):
            return 0.0
        try:
            if isinstance(value, str):
                v = value.replace(".", "").replace(",", ".")
                return float(v)
            return float(value)
        except Exception:
            return 0.0

    def _field_exists(self, recordset_or_record, field_name):
        try:
            return field_name in recordset_or_record._fields
        except Exception:
            return False

    def _find_first_field(self, record, candidates):
        for c in candidates:
            if c in record._fields:
                return c
        return False

    def _crear_actividad_si_aplica(self, nota):
        self.ensure_one()
        try:
            actividad_tipo = self.env.ref("mail.mail_activity_data_todo")
        except Exception:
            return
        existente = self.env["mail.activity"].search([
            ("res_model", "=", self._name),
            ("res_id", "=", self.id),
            ("activity_type_id", "=", actividad_tipo.id),
            ("user_id", "=", self.env.user.id),
        ], limit=1)
        if existente:
            return
        self.activity_schedule(
            activity_type_id=actividad_tipo.id,
            user_id=self.env.user.id,
            summary=_("Pendiente"),
            note=nota or "",
        )



    def action_aplicar_reglas_servicio(self):
        for rec in self:
            rec._aplicar_reglas_asignacion_servicio()
            rec._evaluar_bloqueo()

    def _aplicar_reglas_asignacion_servicio(self):
        """
        Busca y asigna un servicio contable tanto a la cabecera como a las líneas 
        de la factura extraída basándose en el proveedor o la ciudad usando las reglas.
        """
        self.ensure_one()
        if not self.compania_id:
            return

        # 1. Asignación a nivel de Cabecera (Extractor)
        if not self.servicio_id:
            ciudad_id = False
            ciudad_texto = False
            
            if self.proveedor_id:
                if "city_id" in self.proveedor_id._fields and self.proveedor_id.city_id:
                    ciudad_id = self.proveedor_id.city_id.id
                ciudad_texto = (self.proveedor_id.city or "").upper()

            payload_cabecera = {
                "aplica_a": "documento",
                "company_id": self.compania_id.id,
                "proveedor_id": self.proveedor_id.id if self.proveedor_id else False,
                "ciudad_id": ciudad_id,
                "ciudad_texto": ciudad_texto,
                "texto_busqueda": (self.texto_ocr or "").strip(),
            }

            reglas_cabecera = self.env["regla.asignacion.servicio"].search([
                ("active", "=", True),
                ("company_id", "=", self.compania_id.id),
                ("aplica_a", "=", "documento"),
                "|", ("proveedor_id", "=", False), ("proveedor_id", "=", self.proveedor_id.id if self.proveedor_id else False),
            ], order="prioridad desc, id desc")

            for r in reglas_cabecera:
                if r.match(payload_cabecera):
                    self.servicio_id = r.servicio_id.id
                    self.message_post(body=_("Servicio de cabecera asignado por regla: %s") % r.name)
                    break

        # 2. Asignación a nivel de Líneas (dian.invoice.line)
        if not self.invoice_lines:
            # Si no hay líneas creadas, no hay nada que asignar.
            # En OCR esto debe dispararse después de crear las líneas genéricas.
            return

        reglas_linea = self.env["regla.asignacion.servicio"].search([
            ("active", "=", True),
            ("company_id", "=", self.compania_id.id),
            ("aplica_a", "=", "linea"),
            "|", ("proveedor_id", "=", False), ("proveedor_id", "=", self.proveedor_id.id if self.proveedor_id else False),
        ], order="prioridad desc, id desc")

        for line in self.invoice_lines:
            # Si ya tiene servicio, lo respetamos
            if line.servicio_id:
                continue

            payload_linea = {
                "aplica_a": "linea",
                "company_id": self.compania_id.id,
                "proveedor_id": self.proveedor_id.id if self.proveedor_id else False,
                "ciudad_id": self.proveedor_id.city_id.id if (self.proveedor_id and "city_id" in self.proveedor_id._fields and self.proveedor_id.city_id) else False,
                "ciudad_texto": (self.proveedor_id.city or "") if self.proveedor_id else "",
                "codigo_producto": (line.product_code or "").strip(),
                "texto_busqueda": (line.description or "").strip(),
            }

            asignado = False
            for r in reglas_linea:
                if r.match(payload_linea):
                    line.servicio_id = r.servicio_id.id
                    asignado = True
                    break
            
            # Fallback: Si no hay regla de línea que aplique, pero hay un servicio de cabecera,
            # se lo asignamos por defecto a la línea para no romper la facturación.
            if not asignado and self.servicio_id:
                line.servicio_id = self.servicio_id.id






    def action_asignar_servicios_lineas(self):
        for rec in self:
            # Si no hay líneas, intentar generarlas (solo OCR)
            if not rec.invoice_lines and not rec.es_xml:
                if rec.estado_ocr != "validado":
                    raise UserError(_("Debes validar el OCR antes de asignar servicios por línea."))
                rec._generar_invoice_lines_desde_ocr()

            if not rec.invoice_lines:
                raise UserError(_("No hay líneas DIAN en esta factura."))


            reglas = rec.env["regla.asignacion.servicio"].search([
                ("active", "=", True),
                ("company_id", "=", rec.compania_id.id),
                ("aplica_a", "=", "linea"),
                "|", ("proveedor_id", "=", False), ("proveedor_id", "=", rec.proveedor_id.id),
            ], order="prioridad desc, id desc")

            for line in rec.invoice_lines:
                if line.servicio_id:
                    continue

                payload = {
                    "aplica_a": "linea",
                    "company_id": rec.compania_id.id,
                    "proveedor_id": rec.proveedor_id.id if rec.proveedor_id else False,
                    # "tipo_documento": "xml" if rec.es_xml else "otro",
                    "ciudad_id": rec.proveedor_id.city_id.id if (rec.proveedor_id and "city_id" in rec.proveedor_id._fields and rec.proveedor_id.city_id) else False,
                    "ciudad_texto": (rec.proveedor_id.city or "") if rec.proveedor_id else "",
                    "codigo_producto": (line.product_code or "").strip(),
                    "texto_busqueda": (line.description or ""),
                }

                asignado = False
                for r in reglas:
                    if r.match(payload):
                        line.servicio_id = r.servicio_id.id
                        asignado = True
                        break
                if not asignado and rec.servicio_id:
                    line.servicio_id = rec.servicio_id.id
                    
                    
                    
                    
    def _parse_money(self, value):
        """
        Convierte cualquier string de moneda o porcentaje devuelto por el OCR en un float válido.
        Maneja formatos latinos y americanos, remueve símbolos ($, %, COP, etc) y espacios.
        """
        if value is None or value == "":
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        try:
            # 1. Limpiar todo lo que no sea dígito, punto, coma o signo negativo
            s = str(value)
            s = re.sub(r'[^\d\.,\-]', '', s).strip()
            
            if not s:
                return 0.0

            # 2. Encontrar el último separador (. o ,)
            last_dot = s.rfind('.')
            last_comma = s.rfind(',')
            last_separator_idx = max(last_dot, last_comma)

            # 3. Lógica heurística para determinar si el último separador es decimal
            is_decimal = False
            if last_separator_idx != -1:
                # Si el separador está a 1, 2 o 3 posiciones del final, lo tratamos como decimal
                # (Ej: 3,50 / 3.500 / 19,5)
                # OJO: Si es exactamente 3 dígitos, podría ser miles (ej: 1.000).
                # Para evitar ese error, si hay OTRO separador antes, o si la longitud decimal no es 3, es decimal.
                chars_after = len(s) - last_separator_idx - 1
                if chars_after in (1, 2):
                    is_decimal = True
                elif chars_after == 3:
                    # Caso ambiguo: "1.000" vs "1,000". Si el separador es coma y no hay puntos, suele ser miles en latam o decimal en US.
                    # Verificamos si hay otro separador del mismo tipo antes (ej: 1,000,000)
                    if s.count(s[last_separator_idx]) > 1:
                        is_decimal = False # Es un separador de miles repetido
                    # Si hay punto y coma (ej: 1,000.000 o 1.000,000), el último manda
                    elif last_dot != -1 and last_comma != -1:
                        is_decimal = True
                    else:
                        # Por defecto asumimos que un solo punto/coma con 3 dígitos es separador de miles
                        is_decimal = False
                else:
                    # Más de 3 decimales? Raro en facturas, pero lo asumimos decimal
                    is_decimal = True

            # 4. Formatear el string para float() de Python
            if is_decimal:
                # Extraer la parte entera y decimal
                integer_part = s[:last_separator_idx]
                decimal_part = s[last_separator_idx + 1:]
                # Limpiar cualquier separador que haya quedado en la parte entera
                integer_part = integer_part.replace('.', '').replace(',', '')
                s_final = f"{integer_part}.{decimal_part}"
            else:
                # No hay decimales, limpiar todo punto y coma
                s_final = s.replace('.', '').replace(',', '')

            return float(s_final)
        except Exception as e:
            _logger.warning("Error en _parse_money al convertir '%s': %s", value, str(e))
            return 0.0

    def _is_percent(self, token):
        t = token.strip().replace("%", "")
        return t.isdigit()

    def _is_number(self, token):
        t = token.strip().replace(".", "").replace(",", "")
        return t.isdigit()

    def _extraer_items_tabla_desde_texto(self, raw_text):
        """
        Parser específico para facturas tipo Faster:
        CODIGO  C.C.  DESCRIPCION  CANTIDAD  %IVA  VALOR TOTAL
        """
        if not raw_text:
            return []

        lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
        items = []
        current = None

        for l in lines:
            m = CODIGO_RE.match(l)
            if m:
                # guarda el anterior
                if current:
                    items.append(current)  
                current = {
                    "product_code": m.group("code"),
                    "cc": m.group("cc") or "",
                    "raw": m.group("body"),
                }
                
            else:
                # continuación de descripción (ej. última línea “Almacenamiento de Enero…”)
                if current:
                    current["raw"] += " " + l

        if current:
            items.append(current)

        parsed = []
        for it in items:
            tokens = it["raw"].split()
            if len(tokens) < 4:
                continue

            # valor total suele ser el último token monetario
            valor_total = self._parse_money(tokens[-1])

            # iva% suele ser penúltimo token (19% o 19)
            iva_token = tokens[-2]
            iva_pct = float(iva_token.replace("%", "")) if self._is_percent(iva_token) else 0.0

            # cantidad suele ser el token antes del iva
            qty_token = tokens[-3]
            qty = float(qty_token.replace(",", ".")) if self._is_number(qty_token) else 1.0

            # descripción: lo que queda entre tokens[0: -3]
            desc = " ".join(tokens[:-3]).strip()

            # Si el valor total incluye IVA (como en Faster), calculamos base e impuesto
            base = valor_total
            tax_amount = 0.0
            if iva_pct > 0:
                base = round(valor_total / (1.0 + iva_pct / 100.0), 2)
                tax_amount = round(valor_total - base, 2)

            parsed.append({
                "product_code": it["product_code"],
                "description": desc,
                "quantity": qty,
                "tax_percent": iva_pct,
                "line_extension_amount": base,   # base sin IVA
                "tax_amount": tax_amount,
                "tax_scheme": "IVA" if iva_pct else "",
            })

        return parsed


    def _generar_invoice_lines_desde_ocr(self):
        self.ensure_one()
        if self.es_xml:
            return

        # Intentar obtener line_items del JSON extraído
        line_items = []
        if self.datos_ocr_json:
            try:
                datos = json.loads(self.datos_ocr_json)
                line_items = datos.get('line_items', [])
            except:
                pass

        if line_items:
            valido = False
            for it in line_items:
                if any(it.get(k) for k in ("codigo", "descripcion", "cantidad", "valor_total_linea")):
                    valido = True
                    break
            if not valido:
                line_items = []

        if line_items:
            # Usar los ítems proporcionados por el LLM
            self.invoice_lines.unlink()
            Line = self.env["dian.invoice.line"]
            seq = 1
            
            # Cargar etiquetas en memoria para Fuzzy Matching
            etiquetas = self.env['maestro.servicios.etiqueta'].search([])

            for it in line_items:          
                qty = self._parse_money(it.get('cantidad', 1.0))
                base = self._parse_money(it.get('valor_total_linea', 0.0))
                iva_pct = self._parse_money(it.get('porcentaje_iva', 0.0))
                # La base ya viene sin IVA en el valor extraído de las facturas de proveedores
                base_sin_iva = base
                
                # Calcular monto de impuesto
                if iva_pct > 0:
                    tax_amount = base_sin_iva * (iva_pct / 100.0)
                else:
                    tax_amount = 0.0

                # Precio unitario (evitar división por cero)
                price_unit = base_sin_iva / qty if qty else base_sin_iva

                descripcion = it.get('descripcion', '').strip()
                
                # Fuzzy Matching para asignar servicio
                servicio_asignado_id = False
                if descripcion:
                    mejor_ratio = 0.0
                    mejor_etiqueta = None
                    for etiqueta in etiquetas:
                        if not etiqueta.name:
                            continue
                        ratio = SequenceMatcher(None, descripcion.lower(), etiqueta.name.lower()).ratio()
                        if ratio > mejor_ratio:
                            mejor_ratio = ratio
                            mejor_etiqueta = etiqueta

                    if mejor_ratio >= 0.90 and mejor_etiqueta:
                        servicio_asignado_id = mejor_etiqueta.servicio_id.id
                        _logger.info("OCR Fuzzy Match: Línea '%s' asignada al servicio '%s' (Ratio: %.2f%%)", descripcion, mejor_etiqueta.servicio_id.name, mejor_ratio * 100)
                    else:
                        _logger.info("OCR Fuzzy Match: Línea '%s' sin coincidencia suficiente (Mejor ratio: %.2f%%)", descripcion, mejor_ratio * 100)

                # Fallback
                if not servicio_asignado_id:
                    servicio_asignado_id = self.servicio_id.id if self.servicio_id else False

                Line.create({
                    'invoice_id': self.id,
                    'sequence': seq,
                    'product_code': it.get('codigo', ''),
                    'description': descripcion,
                    'quantity': qty,
                    'price_unit': round(price_unit, 6),
                    'line_extension_amount': round(base_sin_iva, 2),
                    'tax_amount': round(tax_amount, 2),
                    'tax_percent': iva_pct,
                    'tax_scheme': 'IVA' if iva_pct else '',
                    'servicio_id': servicio_asignado_id,
                })
                seq += 1
        else:
            # Si no hay line_items, usar el parseo tradicional (regex)
            raw = self.texto_ocr or ""
            items = self._extraer_items_tabla_desde_texto(raw)
            # ... (código existente para crear líneas)
