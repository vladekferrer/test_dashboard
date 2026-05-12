# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import UserError
import json
import base64
import io
from pdf2image import convert_from_bytes
import pytesseract
from datetime import datetime

from ..services.llm_ocr_service import OpenAIOCRService
import re
import logging

_logger = logging.getLogger(__name__)


class TranscriptorOCR(models.Model):

    _name = "transcriptor.ocr"
    _description = "Extracción de Datos OCR y JSON"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(default="/")

    # Compañía para filtrar reglas
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        default=lambda self: self.env.company,
    )

    # Archivo original (compatibilidad con dian.invoice.extractor)
    archivo = fields.Binary(string="Archivo")
    filename = fields.Char(string="Nombre archivo")

    original_file = fields.Binary(string="Archivo original (compatibilidad)")
    file_name = fields.Char(string="Nombre archivo (compatibilidad)")

    # Resultado OCR
    texto_ocr = fields.Text(string="Texto OCR")
    json_resultado = fields.Text(string="JSON resultado")

    # Campos de compatibilidad usados por dian.invoice.extractor
    raw_text = fields.Text(string="Texto bruto OCR")
    extracted_data = fields.Text(string="Datos extraídos (JSON)")

    estado = fields.Selection(
        [
            ("borrador", "Borrador"),
            ("procesado", "Procesado"),
            ("error", "Error"),
        ],
        default="borrador",
    )

    # Datos de la factura
    numero_factura = fields.Char(string="Número factura")
    fecha_emision = fields.Date(string="Fecha de emisión")

    # Identificación proveedor (char + M2O)
    nit_proveedor = fields.Char(string="NIT proveedor (texto)")
    proveedor_id = fields.Many2one("res.partner", string="Proveedor")
    direccion_proveedor = fields.Char(string="Dirección proveedor")

    cliente = fields.Char(string="Cliente")
    id_cliente = fields.Char(string="ID cliente / NIT cliente")

    total = fields.Float(string="Total documento")
    conceptos = fields.Text(string="Conceptos / detalle")

    # -----------------------
    # Helpers internos
    # -----------------------

    def _safe_b64decode(self, value):
        if not value:
            return None

        # Odoo a veces entrega Binary como bytes ascii base64 (no PDF crudo)
        # o como string base64. También puede venir como data-url.
        raw = value
        if isinstance(raw, str):
            raw = raw.strip()
            # data:application/pdf;base64,....
            if raw.lower().startswith("data:"):
                parts = raw.split(",", 1)
                raw = parts[1] if len(parts) == 2 else ""
            raw_bytes = raw.encode("utf-8")
        else:
            raw_bytes = raw

        if not isinstance(raw_bytes, (bytes, bytearray)):
            return None

        # 1) si ya es PDF crudo
        if raw_bytes.startswith(b"%PDF"):
            return bytes(raw_bytes)

        # 2) si es base64 en bytes/str, decodificar y validar PDF
        # (ej. comienza con JVBERi0x...)
        try:
            decoded = base64.b64decode(raw_bytes, validate=True)
            if decoded.startswith(b"%PDF"):
                return decoded
        except Exception:
            try:
                decoded = base64.b64decode(raw_bytes)
                if decoded.startswith(b"%PDF"):
                    return decoded
            except Exception:
                pass

        # 3) último recurso: devolver bytes originales (para que el validador falle con mensaje claro)
        return bytes(raw_bytes)

    def _normalizar_identificacion(self, value):
        if not value:
            return None
        # Solo extrae números, limpia guiones, puntos y espacios. No recorta.
        digits = re.sub(r"\D+", "", str(value))
        return digits or None

    def _extraer_posibles_nits(self, texto):
        """Devuelve una lista de candidatos NIT (solo dígitos) desde el texto OCR."""
        if not texto:
            return []

        candidatos = set()

        # Caso típico: "NIT: 900.794.787-1" o variaciones
        for m in re.finditer(r"\bNIT\b\s*[:\-]?\s*([0-9][0-9\.\-\s]{6,16}[0-9])", texto, re.IGNORECASE):
            nit = self._normalizar_identificacion(m.group(1))
            if nit and len(nit) >= 8:
                candidatos.add(nit)

        # Fallback: números largos con separadores (sin depender de la palabra NIT)
        for m in re.finditer(r"\b([0-9][0-9\.\-\s]{7,16}[0-9])\b", texto):
            nit = self._normalizar_identificacion(m.group(1))
            if nit and 8 <= len(nit) <= 11:
                candidatos.add(nit)

        # Ordenar: primero los de 9-10 dígitos (común en Colombia)
        ordenados = sorted(candidatos, key=lambda x: (0 if len(x) in (9, 10) else 1, -len(x), x))
        return ordenados[:20]

    def _buscar_partner_por_identificacion(self, nit):
        nit_norm = self._normalizar_identificacion(nit)
        if not nit_norm:
            return self.env["res.partner"]

        def _buscar_exacto(numero):
            # Buscar primero por fe_nit (si existe en el partner)
            candidatos = self.env["res.partner"].search([("fe_nit", "ilike", numero)], limit=20)
            for p in candidatos:
                if self._normalizar_identificacion(getattr(p, "fe_nit", "")) == numero:
                    return p

            # Luego por vat estándar
            candidatos = self.env["res.partner"].search([("vat", "ilike", numero)], limit=20)
            for p in candidatos:
                if self._normalizar_identificacion(getattr(p, "vat", "")) == numero:
                    return p
            
            return False

        # Primera validación: Buscar número exacto
        partner = _buscar_exacto(nit_norm)
        if partner:
            return partner

        # Segunda validación: Si el número tiene más de 9 dígitos, intentar buscar sin el último dígito (Dígito de Verificación)
        if len(nit_norm) > 9:
            nit_sin_dv = nit_norm[:-1]
            partner = _buscar_exacto(nit_sin_dv)
            if partner:
                _logger.info("Proveedor encontrado omitiendo el dígito de verificación: %s -> %s", nit_norm, nit_sin_dv)
                return partner

        return self.env["res.partner"]

    def _parse_fecha(self, valor):
        if not valor:
            return False
        valor = str(valor).strip()
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(valor, fmt).date()
            except ValueError:
                continue
        return False

    def _obtener_llm_service(self):
        """Construye el OpenAIOCRService leyendo la API Key de parámetros de sistema."""
        icp = self.env["ir.config_parameter"].sudo()
        api_key = icp.get_param("transcriptor_ocr.openai_api_key", "")
        
        if not api_key:
            _logger.warning("No se encontró 'transcriptor_ocr.openai_api_key' en los parámetros del sistema.")
            
        return OpenAIOCRService(api_key=api_key)

    def action_test_openai_connection(self):
        """Prueba la conexión con OpenAI usando la API Key configurada."""
        icp = self.env["ir.config_parameter"].sudo()
        api_key = icp.get_param("transcriptor_ocr.openai_api_key", "")
        
        if not api_key:
            raise UserError("No hay una API Key de OpenAI configurada. Revise los Ajustes del sistema.")

        try:
            import requests
            url = "https://api.openai.com/v1/models"
            headers = {"Authorization": f"Bearer {api_key}"}
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Conexión Exitosa',
                    'message': 'Se conectó correctamente a la API de OpenAI.',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            raise UserError(f"Fallo al conectar con OpenAI: {str(e)}")

    def _preparar_imagenes_base64(self, pdf_bytes):
        """Convierte un PDF en una lista de imágenes base64 para enviar a OpenAI."""
        if not pdf_bytes:
            return []

        head = (pdf_bytes or b"")[:4]
        if not head.startswith(b"%PDF"):
            # Podría ser ya una imagen
            try:
                # Verificar si es una imagen válida
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(pdf_bytes))
                img_buffer = io.BytesIO()
                # Convertir a RGB por si es PNG con transparencia
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                img.save(img_buffer, format='JPEG')
                return [base64.b64encode(img_buffer.getvalue()).decode("utf-8")]
            except Exception as e:
                raise UserError("El archivo cargado no es un PDF ni una imagen válida.")

        try:
            paginas = convert_from_bytes(pdf_bytes, dpi=200, fmt='jpeg')
            _logger.info("PDF convertido a %s imágenes", len(paginas))
        except Exception as e:
            _logger.exception("Error en pdf2image.convert_from_bytes")
            raise UserError(
                "No se pudo leer el PDF (posiblemente está dañado o no es un PDF estándar). "
                "Detalle técnico: %s" % str(e)
            )

        imagenes_b64 = []
        import io
        import base64
        for img in paginas:
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='JPEG')
            imagenes_b64.append(base64.b64encode(img_buffer.getvalue()).decode("utf-8"))
            
        return imagenes_b64

    # -----------------------
    # API principal
    # -----------------------

    def process_ocr(self):
        """Método de compatibilidad llamado desde dian.invoice.extractor."""
        for rec in self:
            # Sincronizar campos de compatibilidad a los nativos
            if rec.original_file and not rec.archivo:
                rec.archivo = rec.original_file
            if rec.file_name and not rec.filename:
                rec.filename = rec.file_name
            rec.action_procesar_documento()
        return True

    def action_procesar_documento(self):
        """Ejecuta OCR + LLM usando OpenAI y llena campos."""

        for rec in self:
            try:
                _logger.info(
                    "Inicio action_procesar_documento para transcriptor.ocr %s (company_id=%s, proveedor_id=%s)",
                    rec.id,
                    rec.company_id.id if rec.company_id else None,
                    rec.proveedor_id.id if rec.proveedor_id else None,
                )
                bin_src = rec.archivo or rec.original_file
                if not bin_src:
                    raise UserError("Debe cargar un archivo primero.")

                pdf_bytes = rec._safe_b64decode(bin_src)
                if not pdf_bytes:
                    raise UserError("No se pudo decodificar el archivo PDF o Imagen.")

                rec.estado = "procesado"

                # Obtener el servicio (OpenAI)
                service = rec._obtener_llm_service()
                if not getattr(service, "api_key", None):
                    raise UserError("No se ha configurado la API Key de OpenAI. Verifique 'transcriptor_ocr.openai_api_key' en Parámetros del Sistema.")

                # Preparar imágenes
                imagenes_b64 = rec._preparar_imagenes_base64(pdf_bytes)
                if not imagenes_b64:
                    raise UserError("No se pudo extraer ninguna imagen del documento.")

                # Petición 1: Extraer Texto y NIT
                resultado_peticion_1 = service.extraer_texto_y_nit(imagenes_b64)
                
                if resultado_peticion_1.get("error"):
                    _logger.error("Error en Petición 1 (Texto y NIT): %s", resultado_peticion_1.get("error"))
                    rec.message_post(body=f"Error al extraer texto y NIT con OpenAI: {resultado_peticion_1.get('error')}")
                    # No detenemos el flujo, asignamos texto vacío si no hay
                    texto_ocr = resultado_peticion_1.get("texto", "")
                    nit_extraido = ""
                else:
                    texto_ocr = resultado_peticion_1.get("texto", "")
                    nit_extraido = resultado_peticion_1.get("nit_proveedor", "")

                rec.texto_ocr = texto_ocr
                rec.raw_text = texto_ocr

                # Búsqueda y Asignación del Proveedor
                proveedor = False
                nit_norm = rec._normalizar_identificacion(nit_extraido)
                
                if nit_norm:
                    _logger.info("NIT detectado por OpenAI: %s", nit_norm)
                    partner = rec._buscar_partner_por_identificacion(nit_norm)
                    if partner:
                        proveedor = partner
                        rec.proveedor_id = proveedor.id
                        rec.nit_proveedor = nit_norm
                        _logger.info("Proveedor detectado por NIT: %s", proveedor.name)
                    else:
                        _logger.warning("No se encontró proveedor con el NIT %s en res.partner.", nit_norm)
                        rec.message_post(body=f"No se encontró proveedor en Odoo con el NIT extraído: {nit_norm}")
                else:
                    _logger.warning("OpenAI no logró extraer un NIT válido.")
                    rec.message_post(body="OpenAI no logró extraer el NIT del proveedor en el documento.")

                # Petición 2: Creación del JSON (Prompt Universal)
                prompt_body = """
Extrae la información del documento. Devuelve ESTRICTAMENTE un objeto JSON válido. NO cambies los nombres de las claves. Si un dato no existe, usa null.

{
  "nit_proveedor": "...",
  "nombre_proveedor": "...",
  "numero_factura": "...",
  "nit_cliente": "...",
  "fecha_emision": "YYYY-MM-DD",
  "total_a_pagar": 0.0,
  "line_items": [
    {
      "codigo": "...",
      "descripcion": "...",
      "valor_total_linea": 0.0
    }
  ]
}

REGLAS CRÍTICAS DE EXTRACCIÓN (CUMPLIMIENTO OBLIGATORIO Y ESTRICTO): 
1. IDENTIDADES: EL NIT 800089872 (DISMEL) ES SIEMPRE EL CLIENTE. Prohibido usarlo como proveedor. 
2. NÚMERO DE FACTURA Y CIUDAD: Usa el real. Si no hay consecutivo, combina primer nombre y fecha. La ciudad es donde se prestó el servicio. 
3. REGLA DE ORO PARA TABLAS (FACTURAS FORMALES): 
   - Si el documento tiene una tabla con múltiples conceptos: DEBES extraer CADA fila como un objeto separado en `line_items`. 
   - ESTÁ TOTALMENTE PROHIBIDO poner el 'Total de la factura' dentro de un `valor_total_linea` individual. 
   - El `valor_total_linea` DEBE ser exactamente el subtotal de esa fila (Precio Unitario x Cantidad). 
   - IGNORA POR COMPLETO cualquier fila de la tabla que sea puramente un impuesto (ej. filas que digan "IVA Descontable", "IVA Mayor Valor Gasto", "Retención"). Solo extrae los servicios reales (ej. "Almacenamiento", "Alistamiento"). 
4. REGLA PARA CUENTAS DE COBRO INFORMALES (SIN TABLA): 
   - SOLO si es un documento informal en texto corrido sin desglose de precios individuales: Agrupa los servicios separados por comas en la descripción de UNA sola línea en `line_items`, y asigna el total global a esa línea. 
5. TOTAL A PAGAR: El `total_a_pagar` general (fuera del arreglo) DEBE ser el monto final exacto que se debe transferir (incluyendo todos los impuestos). 
"""

                # Ejecutar Petición 2
                _logger.info("Iniciando Petición 2 (Generación JSON) para transcriptor.ocr %s", rec.id)
                datos_json = service.extraer_json_final(texto_ocr, prompt_body)

                if datos_json.get("error"):
                    err = datos_json.get("error")
                    _logger.error("Error en Petición 2 (JSON): %s", err)
                    rec.message_post(body=f"Error al estructurar JSON con OpenAI: {err}")
                    rec.json_resultado = f"Error procesando OCR/LLM:\n{err}"
                    # No detenemos el flujo con raise UserError
                else:
                    # Guardar JSON bruto
                    rec.json_resultado = json.dumps(
                        datos_json,
                        indent=4,
                        ensure_ascii=False,
                    )
                    rec.extracted_data = rec.json_resultado

                    # Mapear JSON → CAMPOS DEL MODELO
                    rec._llenar_campos_desde_dict(datos_json)

                # Notificación visual no bloqueante si hubo problemas
                if not proveedor or datos_json.get("error") or resultado_peticion_1.get("error"):
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'reload',
                    }

            except UserError as e:
                # Si es un UserError explícito (ej. sin archivo), lo subimos
                raise e
            except Exception as e:
                rec.estado = "error"
                rec.json_resultado = f"Error crítico procesando documento:\n{str(e)}"
                _logger.exception("Error crítico procesando documento")
                self.env.cr.commit()
                rec.message_post(body=f"Error crítico en el flujo de OCR: {str(e)}")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                }

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    # -----------------------
    # MAPEAR JSON → CAMPOS
    # -----------------------

    def _llenar_campos_desde_dict(self, datos):
        """Mapea el dict JSON extraído a los campos de este modelo."""
        if not isinstance(datos, dict):
            return

        self.numero_factura = (datos.get("numero_factura") or "").strip() or False

        nit_prov = datos.get("nit_proveedor")
        if nit_prov:
            nit_norm = self._normalizar_identificacion(nit_prov)
            self.nit_proveedor = nit_norm
            partner = self._buscar_partner_por_identificacion(nit_norm)
            if partner:
                self.proveedor_id = partner.id

        self.direccion_proveedor = datos.get("direccion_proveedor") or False

        self.cliente = datos.get("cliente") or False
        self.id_cliente = datos.get("id_cliente") or False

        total = datos.get("total_a_pagar") or datos.get("total")
        if total is not None:
            try:
                if isinstance(total, str):
                    s = total.replace("$", "").replace(" ", "").strip()
                    # Si tiene comas y puntos (ej. 1.234,56 o 1,234.56)
                    if ',' in s and '.' in s:
                        if s.rfind(',') > s.rfind('.'):
                            # Formato europeo: 1.234,56 -> 1234.56
                            s = s.replace('.', '').replace(',', '.')
                        else:
                            # Formato americano: 1,234.56 -> 1234.56
                            s = s.replace(',', '')
                    elif ',' in s:
                        # Si solo tiene coma, asumimos que es separador decimal si tiene 1 o 2 dígitos después
                        partes = s.split(',')
                        if len(partes[-1]) <= 2:
                            s = s.replace(',', '.')
                        else:
                            # Si tiene 3 dígitos, asumimos separador de miles
                            s = s.replace(',', '')
                    
                    self.total = float(s)
                else:
                    self.total = float(total)
            except Exception:
                pass

        # conceptos: campo libre si viene en el JSON
        line_items = datos.get("line_items")
        if line_items and isinstance(line_items, list):
            lineas = []
            for it in line_items:
                if isinstance(it, dict):
                    if any(it.get(k) for k in ("codigo", "descripcion", "cantidad", "valor_total_linea")):
                        lineas.append(str(it))
            if lineas:
                self.conceptos = "\n".join(lineas)
        else:
            self.conceptos = datos.get("conceptos") or self.conceptos

        # fecha_emision
        fecha = datos.get("fecha_emision") or datos.get("fecha_factura")
        parsed = self._parse_fecha(fecha)
        if parsed:
            self.fecha_emision = parsed






