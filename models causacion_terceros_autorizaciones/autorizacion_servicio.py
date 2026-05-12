# -*- coding: utf-8 -*-
import re
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AutorizacionServicio(models.Model):
    _name = "autorizacion.servicio"
    _description = "Autorización de servicio / gasto"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(string="Número", default="/", copy=False, readonly=True, tracking=True)

    compania_id = fields.Many2one(
        "res.company", string="Compañía", required=True, tracking=True
    )
    proveedor_id = fields.Many2one(
        "res.partner", string="Proveedor", required=True, tracking=True
    )
    servicio_id = fields.Many2one(
        "maestro.servicios", string="Servicio", required=True, tracking=True
    )

    ciudad_id = fields.Many2one("res.city", string="Ciudad", tracking=True)

    tipo_contratacion = fields.Selection(
        [
            ("unica", "Única"),
            ("recurrente", "Recurrente"),
            ("anual", "Anual (contrato)"),
        ],
        string="Tipo de contratación",
        required=True,
        default="unica",
        tracking=True,
    )

    fecha_inicio = fields.Date(string="Inicio vigencia", required=True, tracking=True)
    fecha_fin = fields.Date(string="Fin vigencia", required=True, tracking=True)

    monto_mensual_fijo = fields.Monetary(
        string="Monto mensual fijo",
        currency_field="currency_id",
        tracking=True,
        help="Si está definido, el documento debe coincidir con este monto (tolerancia mínima).",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        default=lambda self: self.env.company.currency_id.id,
        required=True,
    )

    approval_request_id = fields.Many2one(
        "approval.request",
        string="Solicitud de aprobación origen",
        tracking=True,
        ondelete="set null",
    )

    estado = fields.Selection(
        [
            ("vigente", "Vigente"),
            ("vencida", "Vencida"),
        ],
        string="Estado",
        compute="_compute_estado",
        store=True,
        tracking=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("autorizacion.servicio") or "/"
        return super().create(vals_list)

    @api.depends("fecha_inicio", "fecha_fin")
    def _compute_estado(self):
        hoy = fields.Date.context_today(self)
        for rec in self:
            if rec.fecha_inicio and rec.fecha_fin and rec.fecha_inicio <= hoy <= rec.fecha_fin:
                rec.estado = "vigente"
            else:
                rec.estado = "vencida"

    @api.constrains("fecha_inicio", "fecha_fin")
    def _check_fechas(self):
        for rec in self:
            if rec.fecha_inicio and rec.fecha_fin and rec.fecha_fin < rec.fecha_inicio:
                raise ValidationError(_("La fecha fin no puede ser menor que la fecha inicio."))

    @api.constrains("compania_id", "proveedor_id", "servicio_id", "fecha_inicio", "fecha_fin")
    def _check_solapamiento(self):
        for rec in self:
            if not (rec.compania_id and rec.proveedor_id and rec.servicio_id and rec.fecha_inicio and rec.fecha_fin):
                continue
            domain = [
                ("id", "!=", rec.id),
                ("compania_id", "=", rec.compania_id.id),
                ("proveedor_id", "=", rec.proveedor_id.id),
                ("servicio_id", "=", rec.servicio_id.id),
                ("fecha_inicio", "<=", rec.fecha_fin),
                ("fecha_fin", ">=", rec.fecha_inicio),
                ("estado", "=", "vigente"),
            ]
            if self.search_count(domain):
                raise ValidationError(
                    _("Existe otra autorización vigente que se solapa en fechas para esta compañía/proveedor/servicio.")
                )

    @api.model
    def cron_actualizar_vencimientos(self):
        # Solo fuerza recomputación del estado
        autorizaciones = self.search([])
        autorizaciones._compute_estado()
