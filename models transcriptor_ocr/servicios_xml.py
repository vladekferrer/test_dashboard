from odoo import models, fields, api
import base64
from lxml import etree
from datetime import datetime
import logging
import re
import json

_logger = logging.getLogger(__name__)

class DianInvoiceExtractor(models.Model):
    _name = 'dian.invoice.extractor'
    _description = 'Extractor de Facturas Electrónicas DIAN Colombia'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    # Información del archivo
    name = fields.Char(string='Referencia', compute='_compute_name', store=True)
    file_data = fields.Binary(string='Archivo XML', required=True)
    file_name = fields.Char(string='Nombre del archivo')
    upload_date = fields.Datetime(string='Fecha de carga', default=fields.Datetime.now)
    
    # Estado del proceso
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('processed', 'Procesado'),
        ('error', 'Error'),
    ], string='Estado', default='draft')
    
    # Información básica de la factura
    invoice_number = fields.Char(string='Número de Factura')
    cufe = fields.Char(string='CUFE/CUDE')
    invoice_type_code = fields.Char(string='Tipo de Factura')
    invoice_uuid = fields.Char(string='UUID')
    
    # Fechas
    issue_date = fields.Date(string='Fecha de Emisión')
    issue_time = fields.Char(string='Hora de Emisión')
    due_date = fields.Date(string='Fecha de Vencimiento')
    invoice_period_start = fields.Date(string='Periodo Inicio')
    invoice_period_end = fields.Date(string='Periodo Fin')
    
    # Moneda
    currency_code = fields.Char(string='Código Moneda', default='COP')
    
    # Información del Emisor (Proveedor)
    supplier_name = fields.Char(string='Nombre del Emisor')
    supplier_nit = fields.Char(string='NIT Emisor')
    supplier_company_id = fields.Char(string='ID Empresa Emisor')
    supplier_tax_level = fields.Char(string='Régimen Emisor')
    supplier_address = fields.Text(string='Dirección Emisor')
    supplier_city = fields.Char(string='Ciudad Emisor')
    supplier_department = fields.Char(string='Departamento Emisor')
    supplier_phone = fields.Char(string='Teléfono Emisor')
    supplier_email = fields.Char(string='Email Emisor')
    
    # Información del Receptor (Cliente)
    customer_name = fields.Char(string='Nombre del Receptor')
    customer_nit = fields.Char(string='NIT Receptor')
    customer_company_id = fields.Char(string='ID Empresa Receptor')
    customer_tax_level = fields.Char(string='Régimen Receptor')
    customer_address = fields.Text(string='Dirección Receptor')
    customer_city = fields.Char(string='Ciudad Receptor')
    customer_department = fields.Char(string='Departamento Receptor')
    customer_phone = fields.Char(string='Teléfono Receptor')
    customer_email = fields.Char(string='Email Receptor')
    
    # Información de DIAN
    dian_authorization = fields.Char(string='Autorización DIAN')
    dian_authorization_start = fields.Date(string='Inicio Autorización')
    dian_authorization_end = fields.Date(string='Fin Autorización')
    dian_prefix = fields.Char(string='Prefijo Autorizado')
    dian_from = fields.Char(string='Desde')
    dian_to = fields.Char(string='Hasta')
    software_provider_id = fields.Char(string='ID Proveedor Software')
    software_id = fields.Char(string='ID Software')
    qr_code = fields.Text(string='Código QR')
    
    # Totales financieros
    line_extension_amount = fields.Float(string='Valor Bruto', digits=(16, 2))
    tax_exclusive_amount = fields.Float(string='Base Imponible', digits=(16, 2))
    tax_inclusive_amount = fields.Float(string='Valor con Impuestos', digits=(16, 2))
    payable_amount = fields.Float(string='Valor a Pagar', digits=(16, 2))
    allowance_total_amount = fields.Float(string='Total Descuentos', digits=(16, 2))
    charge_total_amount = fields.Float(string='Total Cargos', digits=(16, 2))
    prepaid_amount = fields.Float(string='Valor Anticipo', digits=(16, 2))
    
    # Impuestos
    total_tax_amount = fields.Float(string='Total Impuestos', digits=(16, 2))
    total_iva = fields.Float(string='Total IVA', digits=(16, 2))
    total_rete_fuente = fields.Float(string='Total ReteFuente', digits=(16, 2))
    total_rete_iva = fields.Float(string='Total ReteIVA', digits=(16, 2))
    total_rete_ica = fields.Float(string='Total ReteICA', digits=(16, 2))
    
    # Información de pago
    payment_means_code = fields.Char(string='Forma de Pago')
    payment_id = fields.Char(string='Referencia de Pago')
    payment_due_date = fields.Date(string='Fecha Vencimiento Pago')
    
    # Referencias
    purchase_order = fields.Char(string='Orden de Compra')
    dispatch_document = fields.Char(string='Guía de Remisión')
    receipt_document = fields.Char(string='Documento de Recepción')
    additional_document_ref = fields.Char(string='Referencia Adicional')
    
    # Respuesta de DIAN (ApplicationResponse)
    dian_response_code = fields.Char(string='Código Respuesta DIAN')
    dian_response_description = fields.Text(string='Descripción Respuesta DIAN')
    dian_validation_date = fields.Date(string='Fecha Validación DIAN')
    dian_validation_time = fields.Char(string='Hora Validación DIAN')
    
    # Líneas de producto
    invoice_lines = fields.One2many('dian.invoice.line', 'invoice_id', string='Líneas de Factura')
    
    # Campos computados
    total_lines = fields.Integer(string='Total Líneas', compute='_compute_totals')
    total_quantity = fields.Float(string='Cantidad Total', compute='_compute_totals')
    total_value = fields.Float(string='Valor Total', compute='_compute_totals')
    
    # Logs y mensajes
    processing_log = fields.Text(string='Log de Procesamiento')
    error_message = fields.Text(string='Mensaje de Error')
    

    
    def _detectar_proveedor(self):
        """
        Detecta proveedor desde el texto OCR.
        """
        for rec in self:
            if rec.proveedor_id:
                continue

            partner = rec._extraer_nit_proveedor(rec.texto_ocr)

            if partner:
                rec.proveedor_id = partner.id
        
        
    
    def _extraer_nit_proveedor(self, texto):
        """
        Busca posibles NIT en el texto OCR.
        """
        if not texto:
            return False

        posibles = re.findall(r"\b\d{8,10}-?\d?\b", texto)

        for nit in posibles:
            nit_limpio = nit.replace("-", "")
            partner = self.env["res.partner"].search([
                ("vat", "ilike", nit_limpio)
            ], limit=1)

            if partner:
                return partner

        return False
    
    
    
    @api.depends('invoice_number', 'supplier_name')
    def _compute_name(self):
        for record in self:
            if record.invoice_number and record.supplier_name:
                record.name = f"{record.supplier_name} - {record.invoice_number}"
            elif record.invoice_number:
                record.name = record.invoice_number
            else:
                record.name = "Factura sin procesar"
    
    @api.depends('invoice_lines.quantity', 'invoice_lines.line_extension_amount')
    def _compute_totals(self):
        for record in self:
            record.total_lines = len(record.invoice_lines)
            record.total_quantity = sum(line.quantity for line in record.invoice_lines)
            record.total_value = sum(line.line_extension_amount for line in record.invoice_lines)
    
    @api.model
    def create(self, vals):
        record = super(DianInvoiceExtractor, self).create(vals)
        if record.file_data:
            record.process_xml_invoice()
        return record
    
    def write(self, vals):
        if 'file_data' in vals and vals['file_data']:
            result = super(DianInvoiceExtractor, self).write(vals)
            self.process_xml_invoice()
            return result
        return super(DianInvoiceExtractor, self).write(vals)
    
    def process_xml_invoice(self):
        _logger.info("Iniciando procesamiento de factura DIAN...")
        self.processing_log = "Iniciando procesamiento...\n"
        
        try:
            # Decodificar el archivo binario
            xml_data = base64.b64decode(self.file_data)
            
            # Parsear el XML
            parser = etree.XMLParser(ns_clean=True, recover=True, encoding='utf-8')
            root = etree.fromstring(xml_data, parser=parser)
            
            # Método SIMPLE que ignora namespaces
            self._extract_without_namespaces(root)
            
            self.state = 'processed'
            self.processing_log += "Procesamiento completado exitosamente.\n"
            _logger.info("Factura DIAN procesada exitosamente")
            
        except Exception as e:
            import traceback
            self.state = 'error'
            self.error_message = f"Error al procesar XML: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            self.processing_log += f"ERROR: {str(e)}\n"
            _logger.error(f"Error procesando factura DIAN: {str(e)}")
    
    
    
    def _extract_without_namespaces(self, root):
        """Extraer información ignorando namespaces (método simple)"""
        self.processing_log += "Extrayendo información (ignorando namespaces)...\n"
        
        # Función auxiliar para buscar ignorando namespaces
        def find_text(xpath):
            try:
                # Reemplazar namespaces en el XPath
                xpath_no_ns = xpath.replace('cbc:', '*[local-name()="').replace('cac:', '*[local-name()="')
                xpath_no_ns = xpath_no_ns.replace(']/', '"]/').replace('/text()', '"]/text()')
                
                # Si no terminó correctamente, ajustar
                if '"]' not in xpath_no_ns and 'local-name()' in xpath_no_ns:
                    xpath_no_ns = xpath_no_ns + '"]'
                
                result = root.xpath(xpath_no_ns)
                if result:
                    return result[0]
            except Exception as e:
                self.processing_log += f"Error en XPath {xpath}: {str(e)}\n"
            
            return None
        
        # Información básica
        doc_id = find_text('//cbc:ID')
        if doc_id:
            self.invoice_number = doc_id
        
        issue_date = find_text('//cbc:IssueDate')
        if issue_date:
            try:
                self.issue_date = datetime.strptime(issue_date, '%Y-%m-%d').date()
            except:
                pass
        
        # Buscar factura embebida
        descriptions = root.xpath('//*[local-name()="Description"]/text()')
        for desc in descriptions:
            if '<?xml' in desc and '<Invoice' in desc:
                try:
                    self._process_embedded_invoice_simple(desc)
                    break
                except Exception as e:
                    self.processing_log += f"Error procesando factura embebida: {str(e)}\n"    
    
    
    
    def _process_embedded_invoice_simple(self, xml_string):
        """Procesar factura embebida de manera simple"""
        try:
            # Extraer solo el XML de Invoice
            start = xml_string.find('<Invoice')
            if start == -1:
                return
            
            # Buscar el cierre de Invoice
            end = xml_string.find('</Invoice>')
            if end == -1:
                return
            
            invoice_xml = xml_string[start:end + len('</Invoice>')]
            
            # Parsear la factura
            parser = etree.XMLParser(ns_clean=True, recover=True, encoding='utf-8')
            invoice_root = etree.fromstring(invoice_xml.encode('utf-8'), parser=parser)
            
            # Extraer información básica
            # ID
            id_elem = invoice_root.xpath('//*[local-name()="ID"]')
            if id_elem:
                self.invoice_number = id_elem[0].text
            
            # CUFE
            uuid_elem = invoice_root.xpath('//*[local-name()="UUID"]')
            if uuid_elem:
                self.cufe = uuid_elem[0].text
            
            # Emisor
            supplier_name = invoice_root.xpath('//*[local-name()="AccountingSupplierParty"]//*[local-name()="Name"]')
            if supplier_name:
                self.supplier_name = supplier_name[0].text
            
            supplier_nit = invoice_root.xpath('//*[local-name()="AccountingSupplierParty"]//*[local-name()="CompanyID"]')
            if supplier_nit:
                self.supplier_nit = supplier_nit[0].text
            
            # Receptor
            customer_name = invoice_root.xpath('//*[local-name()="AccountingCustomerParty"]//*[local-name()="Name"]')
            if customer_name:
                self.customer_name = customer_name[0].text
            
            customer_nit = invoice_root.xpath('//*[local-name()="AccountingCustomerParty"]//*[local-name()="CompanyID"]')
            if customer_nit:
                self.customer_nit = customer_nit[0].text
            
            # Totales
            payable = invoice_root.xpath('//*[local-name()="PayableAmount"]')
            if payable:
                try:
                    self.payable_amount = float(payable[0].text)
                except:
                    pass
            
            # IVA
            tax_total = invoice_root.xpath('//*[local-name()="TaxTotal"]//*[local-name()="TaxAmount"]')
            if tax_total:
                try:
                    self.total_tax_amount = float(tax_total[0].text)
                except:
                    pass
            
            self.processing_log += "Factura embebida procesada exitosamente\n"
            
        except Exception as e:
            self.processing_log += f"Error en _process_embedded_invoice_simple: {str(e)}\n"    
    
    
    
    def _extract_attached_document_info(self, root, ns):
        """Extraer información del documento adjunto"""
        self.processing_log += "Extrayendo información del documento adjunto...\n"
        
        # Información del documento
        doc_id = root.xpath('//cbc:ID/text()', namespaces=ns)
        if doc_id:
            self.invoice_number = doc_id[0]
            self.processing_log += f"Número de documento: {doc_id[0]}\n"
        
        # Fechas del documento adjunto
        issue_date = root.xpath('//cbc:IssueDate/text()', namespaces=ns)
        if issue_date:
            try:
                self.issue_date = datetime.strptime(issue_date[0], '%Y-%m-%d').date()
            except:
                pass
        
        issue_time = root.xpath('//cbc:IssueTime/text()', namespaces=ns)
        if issue_time:
            self.issue_time = issue_time[0]
        
        # Información del Sender (Emisor)
        sender_name = root.xpath('//cac:SenderParty/cac:PartyTaxScheme/cbc:RegistrationName/text()', namespaces=ns)
        if sender_name:
            self.supplier_name = sender_name[0]
        
        sender_nit = root.xpath('//cac:SenderParty/cac:PartyTaxScheme/cbc:CompanyID/text()', namespaces=ns)
        if sender_nit:
            self.supplier_nit = sender_nit[0]
        
        # Información del Receiver (Receptor)
        receiver_name = root.xpath('//cac:ReceiverParty/cac:PartyTaxScheme/cbc:RegistrationName/text()', namespaces=ns)
        if receiver_name:
            self.customer_name = receiver_name[0]
        
        receiver_nit = root.xpath('//cac:ReceiverParty/cac:PartyTaxScheme/cbc:CompanyID/text()', namespaces=ns)
        if receiver_nit:
            self.customer_nit = receiver_nit[0]
    
    def _process_embedded_invoice(self, root, ns):
        """Procesar la factura embebida en el XML"""
        self.processing_log += "Procesando factura embebida...\n"
        
        # Buscar el XML embebido en la descripción
        description_nodes = root.xpath('//cbc:Description/text()', namespaces=ns)
        embedded_invoice = None
        
        for desc in description_nodes:
            if '<?xml' in desc and '<Invoice' in desc:
                try:
                    # Limpiar y parsear el XML embebido
                    embedded_xml = desc.strip()
                    # Extraer solo el XML desde <?xml hasta </Invoice>
                    start = embedded_xml.find('<?xml')
                    end = embedded_xml.find('</Invoice>') + len('</Invoice>')
                    if start != -1 and end != -1:
                        invoice_xml = embedded_xml[start:end]
                        parser = etree.XMLParser(ns_clean=True, recover=True, encoding='utf-8')
                        embedded_invoice = etree.fromstring(invoice_xml.encode('utf-8'), parser=parser)
                        break
                except Exception as e:
                    self.processing_log += f"Error parseando XML embebido: {str(e)}\n"
                    continue
        
        if not embedded_invoice:
            self.processing_log += "No se encontró factura embebida válida\n"
            return
        
        # Procesar la factura embebida
        self._extract_invoice_info(embedded_invoice, ns)
        self._extract_invoice_lines(embedded_invoice, ns)
    
    def _extract_invoice_info(self, invoice_root, ns):
        """Extraer información de la factura embebida"""
        self.processing_log += "Extrayendo información de la factura...\n"
        
        # Información básica de la factura
        invoice_id = invoice_root.xpath('//cbc:ID/text()', namespaces=ns)
        if invoice_id:
            self.invoice_number = invoice_id[0]
        
        cufe = invoice_root.xpath('//cbc:UUID/text()', namespaces=ns)
        if cufe:
            self.cufe = cufe[0]
        
        # Fechas
        issue_date = invoice_root.xpath('//cbc:IssueDate/text()', namespaces=ns)
        if issue_date:
            try:
                self.issue_date = datetime.strptime(issue_date[0], '%Y-%m-%d').date()
            except:
                pass
        
        due_date = invoice_root.xpath('//cbc:DueDate/text()', namespaces=ns)
        if due_date:
            try:
                self.due_date = datetime.strptime(due_date[0], '%Y-%m-%d').date()
            except:
                pass
        
        # Periodo de facturación
        period_start = invoice_root.xpath('//cac:InvoicePeriod/cbc:StartDate/text()', namespaces=ns)
        if period_start:
            try:
                self.invoice_period_start = datetime.strptime(period_start[0], '%Y-%m-%d').date()
            except:
                pass
        
        period_end = invoice_root.xpath('//cac:InvoicePeriod/cbc:EndDate/text()', namespaces=ns)
        if period_end:
            try:
                self.invoice_period_end = datetime.strptime(period_end[0], '%Y-%m-%d').date()
            except:
                pass
        
        # Tipo de factura
        invoice_type = invoice_root.xpath('//cbc:InvoiceTypeCode/text()', namespaces=ns)
        if invoice_type:
            self.invoice_type_code = invoice_type[0]
        
        # Información del Emisor (AccountingSupplierParty)
        supplier_name = invoice_root.xpath('//cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name/text()', namespaces=ns)
        if supplier_name:
            self.supplier_name = supplier_name[0]
        
        supplier_nit = invoice_root.xpath('//cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID/text()', namespaces=ns)
        if supplier_nit:
            self.supplier_nit = supplier_nit[0]
        
        supplier_tax_level = invoice_root.xpath('//cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:TaxLevelCode/text()', namespaces=ns)
        if supplier_tax_level:
            self.supplier_tax_level = supplier_tax_level[0]
        
        # Dirección del emisor
        supplier_address = invoice_root.xpath('//cac:AccountingSupplierParty/cac:Party/cac:PhysicalLocation/cac:Address/cac:AddressLine/cbc:Line/text()', namespaces=ns)
        if supplier_address:
            self.supplier_address = "\n".join(supplier_address)
        
        supplier_city = invoice_root.xpath('//cac:AccountingSupplierParty/cac:Party/cac:PhysicalLocation/cac:Address/cbc:CityName/text()', namespaces=ns)
        if supplier_city:
            self.supplier_city = supplier_city[0]
        
        # Información del Receptor (AccountingCustomerParty)
        customer_name = invoice_root.xpath('//cac:AccountingCustomerParty/cac:Party/cac:PartyName/cbc:Name/text()', namespaces=ns)
        if customer_name:
            self.customer_name = customer_name[0]
        
        customer_nit = invoice_root.xpath('//cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID/text()', namespaces=ns)
        if customer_nit:
            self.customer_nit = customer_nit[0]
        
        customer_tax_level = invoice_root.xpath('//cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme/cbc:TaxLevelCode/text()', namespaces=ns)
        if customer_tax_level:
            self.customer_tax_level = customer_tax_level[0]
        
        # Dirección del receptor
        customer_address = invoice_root.xpath('//cac:AccountingCustomerParty/cac:Party/cac:PhysicalLocation/cac:Address/cac:AddressLine/cbc:Line/text()', namespaces=ns)
        if customer_address:
            self.customer_address = "\n".join(customer_address)
        
        # Información de DIAN (DianExtensions)
        dian_auth = invoice_root.xpath('//sts:InvoiceAuthorization/text()', namespaces=ns)
        if dian_auth:
            self.dian_authorization = dian_auth[0]
        
        auth_start = invoice_root.xpath('//sts:AuthorizationPeriod/cbc:StartDate/text()', namespaces=ns)
        if auth_start:
            try:
                self.dian_authorization_start = datetime.strptime(auth_start[0], '%Y-%m-%d').date()
            except:
                pass
        
        auth_end = invoice_root.xpath('//sts:AuthorizationPeriod/cbc:EndDate/text()', namespaces=ns)
        if auth_end:
            try:
                self.dian_authorization_end = datetime.strptime(auth_end[0], '%Y-%m-%d').date()
            except:
                pass
        
        dian_prefix = invoice_root.xpath('//sts:Prefix/text()', namespaces=ns)
        if dian_prefix:
            self.dian_prefix = dian_prefix[0]
        
        dian_from = invoice_root.xpath('//sts:From/text()', namespaces=ns)
        if dian_from:
            self.dian_from = dian_from[0]
        
        dian_to = invoice_root.xpath('//sts:To/text()', namespaces=ns)
        if dian_to:
            self.dian_to = dian_to[0]
        
        software_provider = invoice_root.xpath('//sts:ProviderID/text()', namespaces=ns)
        if software_provider:
            self.software_provider_id = software_provider[0]
        
        software_id = invoice_root.xpath('//sts:SoftwareID/text()', namespaces=ns)
        if software_id:
            self.software_id = software_id[0]
        
        qr_code = invoice_root.xpath('//sts:QRCode/text()', namespaces=ns)
        if qr_code:
            self.qr_code = qr_code[0]
        
        # Información de pago
        payment_means = invoice_root.xpath('//cac:PaymentMeans/cbc:PaymentMeansCode/text()', namespaces=ns)
        if payment_means:
            self.payment_means_code = payment_means[0]
        
        payment_due = invoice_root.xpath('//cac:PaymentMeans/cbc:PaymentDueDate/text()', namespaces=ns)
        if payment_due:
            try:
                self.payment_due_date = datetime.strptime(payment_due[0], '%Y-%m-%d').date()
            except:
                pass
        
        # Referencias
        order_ref = invoice_root.xpath('//cac:OrderReference/cbc:ID/text()', namespaces=ns)
        if order_ref:
            self.purchase_order = order_ref[0]
        
        dispatch_ref = invoice_root.xpath('//cac:DespatchDocumentReference/cbc:ID/text()', namespaces=ns)
        if dispatch_ref:
            self.dispatch_document = dispatch_ref[0]
        
        receipt_ref = invoice_root.xpath('//cac:ReceiptDocumentReference/cbc:ID/text()', namespaces=ns)
        if receipt_ref:
            self.receipt_document = receipt_ref[0]
        
        # Totales financieros
        line_extension = invoice_root.xpath('//cac:LegalMonetaryTotal/cbc:LineExtensionAmount/text()', namespaces=ns)
        if line_extension:
            try:
                self.line_extension_amount = float(line_extension[0])
            except:
                pass
        
        tax_exclusive = invoice_root.xpath('//cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount/text()', namespaces=ns)
        if tax_exclusive:
            try:
                self.tax_exclusive_amount = float(tax_exclusive[0])
            except:
                pass
        
        tax_inclusive = invoice_root.xpath('//cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount/text()', namespaces=ns)
        if tax_inclusive:
            try:
                self.tax_inclusive_amount = float(tax_inclusive[0])
            except:
                pass
        
        payable = invoice_root.xpath('//cac:LegalMonetaryTotal/cbc:PayableAmount/text()', namespaces=ns)
        if payable:
            try:
                self.payable_amount = float(payable[0])
            except:
                pass
        
        allowance = invoice_root.xpath('//cac:LegalMonetaryTotal/cbc:AllowanceTotalAmount/text()', namespaces=ns)
        if allowance:
            try:
                self.allowance_total_amount = float(allowance[0])
            except:
                pass
        
        charge = invoice_root.xpath('//cac:LegalMonetaryTotal/cbc:ChargeTotalAmount/text()', namespaces=ns)
        if charge:
            try:
                self.charge_total_amount = float(charge[0])
            except:
                pass
        
        # Impuestos
        tax_total = invoice_root.xpath('//cac:TaxTotal/cbc:TaxAmount/text()', namespaces=ns)
        if tax_total:
            try:
                self.total_tax_amount = float(tax_total[0])
            except:
                pass
        
        # Impuestos por tipo (ejemplo para IVA)
        tax_subtotals = invoice_root.xpath('//cac:TaxTotal/cac:TaxSubtotal', namespaces=ns)
        for tax in tax_subtotals:
            tax_id = tax.xpath('cac:TaxCategory/cac:TaxScheme/cbc:ID/text()', namespaces=ns)
            tax_amount = tax.xpath('cbc:TaxAmount/text()', namespaces=ns)
            
            if tax_id and tax_amount:
                tax_id = tax_id[0]
                try:
                    amount = float(tax_amount[0])
                    if tax_id == '01':  # IVA
                        self.total_iva = amount
                    elif tax_id == '06':  # ReteFuente
                        self.total_rete_fuente = amount
                    # Puedes agregar más tipos de impuestos aquí
                except:
                    pass
        
        # Withholding taxes (retenciones)
        withholding_totals = invoice_root.xpath('//cac:WithholdingTaxTotal/cbc:TaxAmount/text()', namespaces=ns)
        if withholding_totals:
            try:
                # Sumar todas las retenciones
                total_withholding = sum(float(wt) for wt in withholding_totals if wt.strip())
                self.total_rete_fuente = total_withholding  # Ajustar según necesidad
            except:
                pass
    
    def _extract_invoice_lines(self, invoice_root, ns):
        """Extraer líneas de productos/servicios de la factura"""
        self.processing_log += "Extrayendo líneas de la factura...\n"
        
        # Eliminar líneas existentes
        self.invoice_lines.unlink()
        
        # Buscar todas las líneas de factura
        invoice_lines = invoice_root.xpath('//cac:InvoiceLine', namespaces=ns)
        
        for idx, line in enumerate(invoice_lines, 1):
            line_data = {
                'sequence': idx,
                'invoice_id': self.id,
            }
            
            # ID de la línea
            line_id = line.xpath('cbc:ID/text()', namespaces=ns)
            if line_id:
                line_data['line_id'] = line_id[0]
            
            # Descripción del producto/servicio
            description = line.xpath('cac:Item/cbc:Description/text()', namespaces=ns)
            if description:
                line_data['description'] = description[0]
            
            # Código del producto
            item_id = line.xpath('cac:Item/cac:StandardItemIdentification/cbc:ID/text()', namespaces=ns)
            if item_id:
                line_data['product_code'] = item_id[0]
            
            # Cantidad
            quantity = line.xpath('cbc:InvoicedQuantity/text()', namespaces=ns)
            if quantity:
                try:
                    line_data['quantity'] = float(quantity[0])
                except:
                    line_data['quantity'] = 0.0
            
            # Unidad de medida
            unit_code = line.xpath('cbc:InvoicedQuantity/@unitCode', namespaces=ns)
            if unit_code:
                line_data['unit_code'] = unit_code[0]
            
            # Precio unitario
            price_amount = line.xpath('cac:Price/cbc:PriceAmount/text()', namespaces=ns)
            if price_amount:
                try:
                    line_data['price_unit'] = float(price_amount[0])
                except:
                    line_data['price_unit'] = 0.0
            
            # Valor de la línea (sin impuestos)
            line_extension = line.xpath('cbc:LineExtensionAmount/text()', namespaces=ns)
            if line_extension:
                try:
                    line_data['line_extension_amount'] = float(line_extension[0])
                except:
                    line_data['line_extension_amount'] = 0.0
            
            # Impuestos de la línea
            tax_amount = line.xpath('cac:TaxTotal/cbc:TaxAmount/text()', namespaces=ns)
            if tax_amount:
                try:
                    line_data['tax_amount'] = float(tax_amount[0])
                except:
                    line_data['tax_amount'] = 0.0
            
            # Porcentaje de impuesto
            tax_percent = line.xpath('cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:Percent/text()', namespaces=ns)
            if tax_percent:
                try:
                    line_data['tax_percent'] = float(tax_percent[0])
                except:
                    line_data['tax_percent'] = 0.0
            
            # Tipo de impuesto
            tax_scheme = line.xpath('cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cac:TaxScheme/cbc:ID/text()', namespaces=ns)
            if tax_scheme:
                line_data['tax_scheme'] = tax_scheme[0]
            
            # Información adicional del producto
            additional_props = line.xpath('cac:Item/cac:AdditionalItemProperty', namespaces=ns)
            if additional_props:
                additional_info = {}
                for prop in additional_props:
                    prop_name = prop.xpath('cbc:Name/text()', namespaces=ns)
                    prop_value = prop.xpath('cbc:Value/text()', namespaces=ns)
                    if prop_name and prop_value:
                        additional_info[prop_name[0]] = prop_value[0]
                
                if additional_info:
                    line_data['additional_info'] = json.dumps(additional_info, ensure_ascii=False)
            
            # Referencias de remisión (si las hay)
            remision_ref = line.xpath("cac:Item/cac:AdditionalItemProperty[cbc:Name='AYS_Cremision']/cbc:Value/text()", namespaces=ns)
            if remision_ref:
                line_data['remision_reference'] = remision_ref[0]
            
            # Crear la línea de factura
            self.env['dian.invoice.line'].create(line_data)
        
        self.processing_log += f"Se extrajeron {len(invoice_lines)} líneas de producto\n"
    
    def _process_dian_response(self, root, ns):
        """Procesar la respuesta de validación de DIAN"""
        self.processing_log += "Buscando respuesta de validación DIAN...\n"
        
        # Buscar ApplicationResponse embebido
        description_nodes = root.xpath('//cbc:Description/text()', namespaces=ns)
        dian_response = None
        
        for desc in description_nodes:
            if '<?xml' in desc and '<ApplicationResponse' in desc:
                try:
                    # Limpiar y parsear el XML embebido
                    embedded_xml = desc.strip()
                    start = embedded_xml.find('<?xml')
                    end = embedded_xml.find('</ApplicationResponse>') + len('</ApplicationResponse>')
                    if start != -1 and end != -1:
                        response_xml = embedded_xml[start:end]
                        parser = etree.XMLParser(ns_clean=True, recover=True, encoding='utf-8')
                        dian_response = etree.fromstring(response_xml.encode('utf-8'), parser=parser)
                        break
                except Exception as e:
                    self.processing_log += f"Error parseando respuesta DIAN: {str(e)}\n"
                    continue
        
        if not dian_response:
            self.processing_log += "No se encontró respuesta de validación DIAN\n"
            return
        
        # Extraer información de la respuesta
        response_code = dian_response.xpath('//cac:DocumentResponse/cac:Response/cbc:ResponseCode/text()', namespaces=ns)
        if response_code:
            self.dian_response_code = response_code[0]
        
        response_desc = dian_response.xpath('//cac:DocumentResponse/cac:Response/cbc:Description/text()', namespaces=ns)
        if response_desc:
            self.dian_response_description = response_desc[0]
        
        # Información de validación
        validation_date = dian_response.xpath('//cac:ResultOfVerification/cbc:ValidationDate/text()', namespaces=ns)
        if validation_date:
            try:
                self.dian_validation_date = datetime.strptime(validation_date[0], '%Y-%m-%d').date()
            except:
                pass
        
        validation_time = dian_response.xpath('//cac:ResultOfVerification/cbc:ValidationTime/text()', namespaces=ns)
        if validation_time:
            self.dian_validation_time = validation_time[0]
        
        # Respuestas por línea (si las hay)
        line_responses = dian_response.xpath('//cac:LineResponse', namespaces=ns)
        if line_responses:
            response_details = []
            for lr in line_responses:
                line_id = lr.xpath('cac:LineReference/cbc:LineID/text()', namespaces=ns)
                line_code = lr.xpath('cac:Response/cbc:ResponseCode/text()', namespaces=ns)
                line_desc = lr.xpath('cac:Response/cbc:Description/text()', namespaces=ns)
                
                if line_id and line_code and line_desc:
                    response_details.append(f"Línea {line_id[0]}: {line_code[0]} - {line_desc[0]}")
            
            if response_details:
                self.dian_response_description += "\n\nValidaciones por línea:\n" + "\n".join(response_details)
        
        self.processing_log += "Respuesta DIAN procesada\n"
    
    def action_reprocess(self):
        """Re-procesar el XML"""
        self.state = 'draft'
        self.processing_log = ""
        self.error_message = ""
        self.process_xml_invoice()
    
    def action_view_lines(self):
        """Ver las líneas de la factura"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Líneas de Factura {self.invoice_number}',
            'res_model': 'dian.invoice.line',
            'view_mode': 'tree,form',
            'domain': [('invoice_id', '=', self.id)],
            'context': {'default_invoice_id': self.id},
        }


class DianInvoiceLine(models.Model):
    _name = 'dian.invoice.line'
    _description = 'Línea de Factura DIAN'
    _order = 'sequence, id'
    
    # Relaciones
    invoice_id = fields.Many2one('dian.invoice.extractor', string='Factura', required=True, ondelete='cascade')
    
    # Información básica
    sequence = fields.Integer(string='Secuencia', default=1)
    line_id = fields.Char(string='ID Línea')
    product_code = fields.Char(string='Código Producto')
    description = fields.Text(string='Descripción')
    
    # Cantidad y precio
    quantity = fields.Float(string='Cantidad', digits=(16, 3))
    unit_code = fields.Char(string='Unidad')
    price_unit = fields.Float(string='Precio Unitario', digits=(16, 2))
    line_extension_amount = fields.Float(string='Valor Línea', digits=(16, 2))
    
    # Impuestos
    tax_amount = fields.Float(string='Valor Impuesto', digits=(16, 2))
    tax_percent = fields.Float(string='Porcentaje Impuesto', digits=(16, 2))
    tax_scheme = fields.Char(string='Tipo Impuesto')
    
    # Información adicional
    additional_info = fields.Text(string='Información Adicional')
    remision_reference = fields.Char(string='Referencia Remisión')
    
    # Campos calculados
    line_total = fields.Float(string='Total Línea', compute='_compute_line_total', digits=(16, 2))
    
    @api.depends('line_extension_amount', 'tax_amount')
    def _compute_line_total(self):
        for line in self:
            line.line_total = line.line_extension_amount + line.tax_amount
    
    def action_view_additional_info(self):
        """Ver información adicional en formato JSON"""
        self.ensure_one()
        if self.additional_info:
            try:
                info_dict = json.loads(self.additional_info)
                info_text = json.dumps(info_dict, indent=2, ensure_ascii=False)
                
                return {
                    'type': 'ir.actions.act_window',
                    'name': 'Información Adicional',
                    'res_model': 'dian.invoice.line',
                    'view_mode': 'form',
                    'res_id': self.id,
                    'target': 'new',
                    'context': {'form_view_initial_mode': 'view'},
                }
            except:
                pass
        return False