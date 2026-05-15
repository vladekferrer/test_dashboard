"""
Extractor TBS: trae datos de Odoo 14 a la base SQLite analitica.

Modos de extraccion:
- inicial: trae historico desde EXTRACT_FROM_DATE
- incremental: trae solo cambios desde ultima extraccion exitosa

Ambos modos usan UPSERT (insert or replace) sobre las tablas raw_*,
asi que reejecutar es seguro.
"""
import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from config import config
from extraccion.odoo_client import OdooClient
from extraccion.modelo_db import (
    crear_db, RawSaleOrder, RawSaleOrderLine, RawAccountMove,
    RawPartner, RawProduct, RawUser, RawProductCategory, LogExtraccion,
)

logger = logging.getLogger(__name__)


CAMPOS_SALE_ORDER = [
    "id", "name", "date_order", "partner_id", "user_id",
    "state", "invoice_status", "amount_untaxed", "amount_tax",
    "amount_total", "company_id",
]

CAMPOS_SALE_ORDER_LINE = [
    "id", "order_id", "product_id", "product_uom_qty",
    "price_unit", "price_subtotal", "price_total", "discount",
]

CAMPOS_ACCOUNT_MOVE = [
    "id", "name", "partner_id", "invoice_date", "invoice_date_due",
    "move_type", "state", "payment_state", "amount_untaxed",
    "amount_tax", "amount_total", "amount_residual", "invoice_origin",
]

CAMPOS_PARTNER = [
    "id", "name", "is_company", "customer_rank", "supplier_rank",
    "city", "state_id", "country_id", "street", "phone", "email",
    "create_date",
]

CAMPOS_PRODUCT = [
    "id", "name", "default_code", "barcode", "list_price",
    "standard_price", "categ_id", "type", "active",
]

CAMPOS_USER = ["id", "name", "login", "active"]

CAMPOS_PRODUCT_CATEGORY = ["id", "name", "parent_id"]


def _normalizar_many2one(valor):
    """
    Odoo devuelve relaciones many2one como [id, 'nombre'] o False.
    Esta funcion extrae el id o devuelve None.
    """
    if valor is False or valor is None:
        return None
    if isinstance(valor, list) and len(valor) > 0:
        return valor[0]
    return None


def _normalizar_fecha(valor):
    """
    Odoo a veces devuelve False en lugar de NULL para fechas vacias.
    """
    if valor is False or valor is None or valor == "":
        return None
    return valor


def extraer_modelo(
    cliente: OdooClient,
    modelo_odoo: str,
    campos: List[str],
    dominio: List[Any],
    tabla_destino: str,
    transformador,
    engine,
) -> Dict[str, Any]:
    """
    Extrae un modelo Odoo y lo carga en SQLite usando INSERT OR REPLACE.
    Retorna stats de la extraccion.
    """
    inicio = time.time()
    total = 0
    Session = sessionmaker(bind=engine)

    try:
        for bloque in cliente.buscar_y_leer_paginado(
            modelo_odoo, dominio, campos, tamano_pagina=500
        ):
            registros_normalizados = [transformador(r) for r in bloque]
            with Session() as session:
                for reg in registros_normalizados:
                    cols = ", ".join(reg.keys())
                    placeholders = ", ".join([f":{k}" for k in reg.keys()])
                    sql = text(
                        f"INSERT OR REPLACE INTO {tabla_destino} ({cols}) "
                        f"VALUES ({placeholders})"
                    )
                    session.execute(sql, reg)
                session.commit()
            total += len(bloque)

        duracion = time.time() - inicio
        return {
            "modelo": modelo_odoo,
            "registros": total,
            "duracion": duracion,
            "estado": "ok",
            "mensaje": "",
        }
    except Exception as e:
        return {
            "modelo": modelo_odoo,
            "registros": total,
            "duracion": time.time() - inicio,
            "estado": "error",
            "mensaje": str(e),
        }


def transformar_sale_order(r):
    return {
        "id": r["id"],
        "name": r.get("name"),
        "date_order": _normalizar_fecha(r.get("date_order")),
        "partner_id": _normalizar_many2one(r.get("partner_id")),
        "user_id": _normalizar_many2one(r.get("user_id")),
        "state": r.get("state"),
        "invoice_status": r.get("invoice_status"),
        "amount_untaxed": r.get("amount_untaxed", 0) or 0,
        "amount_tax": r.get("amount_tax", 0) or 0,
        "amount_total": r.get("amount_total", 0) or 0,
        "company_id": _normalizar_many2one(r.get("company_id")),
        "extracted_at": datetime.now().isoformat(),
    }


def transformar_sale_order_line(r):
    return {
        "id": r["id"],
        "order_id": _normalizar_many2one(r.get("order_id")),
        "product_id": _normalizar_many2one(r.get("product_id")),
        "product_uom_qty": r.get("product_uom_qty", 0) or 0,
        "price_unit": r.get("price_unit", 0) or 0,
        "price_subtotal": r.get("price_subtotal", 0) or 0,
        "price_total": r.get("price_total", 0) or 0,
        "discount": r.get("discount", 0) or 0,
        "extracted_at": datetime.now().isoformat(),
    }


def transformar_account_move(r):
    return {
        "id": r["id"],
        "name": r.get("name"),
        "partner_id": _normalizar_many2one(r.get("partner_id")),
        "invoice_date": _normalizar_fecha(r.get("invoice_date")),
        "invoice_date_due": _normalizar_fecha(r.get("invoice_date_due")),
        "move_type": r.get("move_type"),
        "state": r.get("state"),
        "payment_state": r.get("payment_state"),
        "amount_untaxed": r.get("amount_untaxed", 0) or 0,
        "amount_tax": r.get("amount_tax", 0) or 0,
        "amount_total": r.get("amount_total", 0) or 0,
        "amount_residual": r.get("amount_residual", 0) or 0,
        "invoice_origin": r.get("invoice_origin"),
        "extracted_at": datetime.now().isoformat(),
    }


def transformar_partner(r):
    return {
        "id": r["id"],
        "name": r.get("name", "")[:256] if r.get("name") else None,
        "is_company": bool(r.get("is_company")),
        "customer_rank": r.get("customer_rank", 0) or 0,
        "supplier_rank": r.get("supplier_rank", 0) or 0,
        "city": r.get("city") or None,
        "state_id": _normalizar_many2one(r.get("state_id")),
        "country_id": _normalizar_many2one(r.get("country_id")),
        "street": r.get("street") or None,
        "phone": r.get("phone") or None,
        "email": r.get("email") or None,
        "create_date": _normalizar_fecha(r.get("create_date")),
        "extracted_at": datetime.now().isoformat(),
    }


def transformar_product(r):
    return {
        "id": r["id"],
        "name": r.get("name", "")[:256] if r.get("name") else None,
        "default_code": r.get("default_code") or None,
        "barcode": r.get("barcode") or None,
        "list_price": r.get("list_price", 0) or 0,
        "standard_price": r.get("standard_price", 0) or 0,
        "categ_id": _normalizar_many2one(r.get("categ_id")),
        "type": r.get("type"),
        "active": bool(r.get("active")),
        "extracted_at": datetime.now().isoformat(),
    }


def transformar_user(r):
    return {
        "id": r["id"],
        "name": r.get("name"),
        "login": r.get("login"),
        "active": bool(r.get("active")),
        "extracted_at": datetime.now().isoformat(),
    }


def transformar_product_category(r):
    return {
        "id": r["id"],
        "name": r.get("name"),
        "parent_id": _normalizar_many2one(r.get("parent_id")),
        "extracted_at": datetime.now().isoformat(),
    }


def ejecutar_extraccion(modo: str = "inicial"):
    """
    modo: 'inicial' o 'incremental'.

    Inicial:     trae todo desde EXTRACT_FROM_DATE.
    Incremental: trae solo lo modificado desde la ultima extraccion exitosa.
    """
    config.validate()
    engine = crear_db()
    cliente = OdooClient()
    cliente.autenticar()

    Session = sessionmaker(bind=engine)

    if modo == "incremental":
        with Session() as session:
            ultimo = session.execute(text(
                "SELECT MAX(timestamp) FROM log_extraccion WHERE estado='ok'"
            )).scalar()
            fecha_corte = ultimo if ultimo else config.EXTRACT_FROM_DATE
    else:
        fecha_corte = config.EXTRACT_FROM_DATE

    logger.info(f"Iniciando extraccion {modo} desde {fecha_corte}")

    extracciones = [
        ("res.users",         CAMPOS_USER,             [],
         "raw_user",          transformar_user),
        ("product.category",  CAMPOS_PRODUCT_CATEGORY, [],
         "raw_product_category", transformar_product_category),
        ("product.product",   CAMPOS_PRODUCT,          [["active", "in", [True, False]]],
         "raw_product",       transformar_product),
        ("res.partner",       CAMPOS_PARTNER,          [["customer_rank", ">", 0]],
         "raw_partner",       transformar_partner),
        ("sale.order",        CAMPOS_SALE_ORDER,       [["date_order", ">=", fecha_corte]],
         "raw_sale_order",    transformar_sale_order),
        ("sale.order.line",   CAMPOS_SALE_ORDER_LINE,  [["create_date", ">=", fecha_corte]],
         "raw_sale_order_line", transformar_sale_order_line),
        ("account.move",      CAMPOS_ACCOUNT_MOVE,
         [["move_type", "in", ["out_invoice", "out_refund"]],
          ["invoice_date", ">=", fecha_corte]],
         "raw_account_move",  transformar_account_move),
    ]

    resultados = []
    for modelo_odoo, campos, dominio, tabla, transformador in extracciones:
        logger.info(f">>> Extrayendo {modelo_odoo}")
        resultado = extraer_modelo(
            cliente, modelo_odoo, campos, dominio,
            tabla, transformador, engine,
        )
        resultados.append(resultado)
        logger.info(
            f"<<< {modelo_odoo}: {resultado['registros']} registros "
            f"en {resultado['duracion']:.1f}s [{resultado['estado']}]"
        )

        with Session() as session:
            log = LogExtraccion(
                timestamp=datetime.now(),
                tipo=modo,
                modelo=modelo_odoo,
                registros=resultado["registros"],
                duracion_seg=resultado["duracion"],
                estado=resultado["estado"],
                mensaje=resultado["mensaje"],
            )
            session.add(log)
            session.commit()

    return resultados
