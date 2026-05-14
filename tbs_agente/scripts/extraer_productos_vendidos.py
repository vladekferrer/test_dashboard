"""
Extrae todos los productos que tienen ventas en TBS
y sus templates con el costo correcto (force_company=2).

Guarda en raw_product y raw_product_template.

Correr después de migrar_product_templates.py:
    python -m scripts.extraer_productos_vendidos

Incluir en el pipeline de extracción incremental
después de extraer_incremental.py.
"""
import sys
import logging
from datetime import datetime
from sqlalchemy import create_engine, text
from extraccion.odoo_client import OdooClient
from config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("extraer_productos")

# Contexto correcto para leer costos de TBS
CTX_TBS = {
    "active_test": False,
    "force_company": 2,
    "allowed_company_ids": [2],
    "company_id": 2,
}

COMPANY_ID = 2


def m2o(value):
    """Extrae el ID de un campo many2one de Odoo."""
    if isinstance(value, list) and value:
        return value[0]
    return None


def limpiar(texto, largo=256):
    """Limpia caracteres inválidos de nombres."""
    if not texto:
        return None
    texto = str(texto).encode("utf-8", errors="ignore").decode("utf-8")
    texto = "".join(c if ord(c) >= 32 else " " for c in texto)
    return texto[:largo].strip() or None


def obtener_product_ids_vendidos(engine):
    """Retorna todos los product_id únicos que tienen ventas en TBS."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT sol.product_id
            FROM raw_sale_order_line sol
            JOIN raw_sale_order so ON so.id = sol.order_id
            WHERE so.company_id = :cid
              AND so.state IN ('sale', 'done')
              AND sol.product_id IS NOT NULL
        """), {"cid": COMPANY_ID}).fetchall()
    ids = [r[0] for r in rows]
    logger.info(f"Productos únicos vendidos en TBS: {len(ids)}")
    return ids


def extraer_variantes(c, ids):
    """
    Lee product.product para los IDs vendidos.
    Incluye product_tmpl_id para hacer el JOIN al template.
    """
    CAMPOS = ["id", "name", "display_name", "standard_price",
              "product_tmpl_id", "categ_id", "active"]
    productos = []
    BATCH = 200

    for i in range(0, len(ids), BATCH):
        batch = ids[i:i + BATCH]
        bloque = c.models.execute_kw(
            c.db, c.uid, c.password,
            "product.product", "read",
            [batch],
            {"fields": CAMPOS, "context": CTX_TBS},
        )
        productos.extend(bloque)

    logger.info(f"Variantes leídas: {len(productos)}")
    return productos


def extraer_templates(c, productos):
    """
    Lee product.template para todos los templates referenciados.
    Usa force_company=2 para obtener el costo correcto.
    """
    tmpl_ids = list({m2o(p.get("product_tmpl_id"))
                     for p in productos
                     if m2o(p.get("product_tmpl_id"))})

    CAMPOS = ["id", "name", "standard_price", "categ_id", "active", "company_id"]
    templates = []
    BATCH = 200

    for i in range(0, len(tmpl_ids), BATCH):
        batch = tmpl_ids[i:i + BATCH]
        bloque = c.models.execute_kw(
            c.db, c.uid, c.password,
            "product.template", "read",
            [batch],
            {"fields": CAMPOS, "context": CTX_TBS},
        )
        templates.extend(bloque)

    con_costo = sum(1 for t in templates if t.get("standard_price", 0) > 0)
    logger.info(f"Templates leídos: {len(templates)} | con costo > 0: {con_costo}")
    return templates


def guardar(engine, productos, templates):
    """Guarda en raw_product y raw_product_template con INSERT OR REPLACE."""
    now = datetime.now().isoformat()

    with engine.begin() as conn:
        # raw_product
        for p in productos:
            conn.execute(text("""
                INSERT OR REPLACE INTO raw_product (
                    id, name, standard_price, product_tmpl_id,
                    categ_id, active, extracted_at
                ) VALUES (
                    :id, :name, :standard_price, :product_tmpl_id,
                    :categ_id, :active, :extracted_at
                )
            """), {
                "id":              p["id"],
                "name":            limpiar(p.get("display_name") or p.get("name")),
                "standard_price":  p.get("standard_price") or 0,
                "product_tmpl_id": m2o(p.get("product_tmpl_id")),
                "categ_id":        m2o(p.get("categ_id")),
                "active":          bool(p.get("active")),
                "extracted_at":    now,
            })

        # raw_product_template
        for t in templates:
            conn.execute(text("""
                INSERT OR REPLACE INTO raw_product_template (
                    id, name, standard_price,
                    categ_id, active, company_id, extracted_at
                ) VALUES (
                    :id, :name, :standard_price,
                    :categ_id, :active, :company_id, :extracted_at
                )
            """), {
                "id":             t["id"],
                "name":           limpiar(t.get("name")),
                "standard_price": t.get("standard_price") or 0,
                "categ_id":       m2o(t.get("categ_id")),
                "active":         bool(t.get("active")),
                "company_id":     m2o(t.get("company_id")) or COMPANY_ID,
                "extracted_at":   now,
            })

    logger.info(f"Guardados: {len(productos)} variantes, {len(templates)} templates")


def validar(engine):
    """Valida la cobertura de costos después de guardar."""
    with engine.connect() as conn:
        r = conn.execute(text("""
            SELECT
                COUNT(DISTINCT sol.product_id)   AS productos_vendidos,
                COUNT(DISTINCT rpt.id)            AS templates_con_datos,
                SUM(CASE WHEN COALESCE(rpt.standard_price,
                                       rp.standard_price, 0) > 0
                         THEN 1 ELSE 0 END)      AS lineas_con_costo,
                COUNT(sol.id)                     AS total_lineas,
                ROUND(SUM(sol.price_subtotal), 0) AS gmv_total,
                ROUND(SUM(CASE
                    WHEN COALESCE(rpt.standard_price,
                                  rp.standard_price, 0) > 0
                    THEN sol.price_subtotal ELSE 0 END), 0) AS gmv_con_costo,
                ROUND(1.0 - SUM(COALESCE(rpt.standard_price,
                                         rp.standard_price, 0)
                                * sol.product_uom_qty)
                    / NULLIF(SUM(sol.price_subtotal), 0), 4) AS margen_pct
            FROM raw_sale_order_line sol
            JOIN raw_sale_order so ON so.id = sol.order_id
            LEFT JOIN raw_product rp
                ON rp.id = sol.product_id
            LEFT JOIN raw_product_template rpt
                ON rpt.id = rp.product_tmpl_id
            WHERE so.company_id = :cid
              AND so.state IN ('sale', 'done')
        """), {"cid": COMPANY_ID}).mappings().first()

    cobertura = (r["gmv_con_costo"] or 0) / max(r["gmv_total"] or 1, 1) * 100

    print("\n" + "=" * 55)
    print("VALIDACIÓN DE COSTOS")
    print("=" * 55)
    print(f"  Productos únicos vendidos:  {r['productos_vendidos']}")
    print(f"  Líneas con costo > 0:       {r['lineas_con_costo']}/{r['total_lineas']}")
    print(f"  GMV total:                  ${r['gmv_total']:,.0f}")
    print(f"  GMV con costo cubierto:     ${r['gmv_con_costo']:,.0f}")
    print(f"  Cobertura de GMV:           {cobertura:.1f}%")
    print(f"  Margen bruto calculado:     {(r['margen_pct'] or 0)*100:.1f}%")

    if cobertura >= 90:
        print("\n  ✓ Cobertura suficiente — margen calculado es confiable")
    else:
        print(f"\n  ⚠ Cobertura baja ({cobertura:.1f}%) — usar fallback 22.3%")
    print("=" * 55)


def main():
    engine = create_engine(config.DB_URL, echo=False)
    c = OdooClient()
    c.autenticar()

    logger.info("Extrayendo productos vendidos en TBS...")
    ids = obtener_product_ids_vendidos(engine)

    if not ids:
        logger.error("Sin product_ids vendidos. ¿Corriste extraer_inicial.py?")
        sys.exit(1)

    productos  = extraer_variantes(c, ids)
    templates  = extraer_templates(c, productos)
    guardar(engine, productos, templates)
    validar(engine)


if __name__ == "__main__":
    main()
