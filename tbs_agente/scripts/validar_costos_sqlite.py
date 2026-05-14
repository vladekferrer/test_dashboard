"""
Valida la cobertura de costos en la base SQLite.

Uso:
    python -m scripts.validar_costos_sqlite
"""
from sqlalchemy import create_engine, text
from config import config

COMPANY_ID = 2
engine = create_engine(config.DB_URL)

with engine.connect() as conn:

    # Resumen general
    r = conn.execute(text("""
        SELECT
            COUNT(DISTINCT sol.product_id)    AS productos_vendidos,
            COUNT(DISTINCT rpt.id)            AS templates_con_datos,
            COUNT(sol.id)                     AS total_lineas,
            SUM(CASE WHEN COALESCE(rpt.standard_price,
                                   rp.standard_price, 0) > 0
                     THEN 1 ELSE 0 END)      AS lineas_con_costo,
            ROUND(SUM(sol.price_subtotal), 0) AS gmv_total,
            ROUND(SUM(CASE
                WHEN COALESCE(rpt.standard_price,
                              rp.standard_price, 0) > 0
                THEN sol.price_subtotal ELSE 0
            END), 0)                          AS gmv_con_costo,
            ROUND(SUM(
                COALESCE(rpt.standard_price, rp.standard_price, 0)
                * sol.product_uom_qty
            ), 0)                             AS costo_total,
            ROUND(1.0 - SUM(
                COALESCE(rpt.standard_price, rp.standard_price, 0)
                * sol.product_uom_qty
            ) / NULLIF(SUM(sol.price_subtotal), 0), 4) AS margen_pct
        FROM raw_sale_order_line sol
        JOIN raw_sale_order so ON so.id = sol.order_id
        LEFT JOIN raw_product rp
            ON rp.id = sol.product_id
        LEFT JOIN raw_product_template rpt
            ON rpt.id = rp.product_tmpl_id
        WHERE so.company_id = :cid
          AND so.state IN ('sale', 'done')
          AND sol.product_id IS NOT NULL
    """), {"cid": COMPANY_ID}).mappings().first()

    gmv_total   = r["gmv_total"] or 1
    gmv_costo   = r["gmv_con_costo"] or 0
    cobertura   = gmv_costo / gmv_total * 100
    margen_real = (r["margen_pct"] or 0) * 100

    print("\n" + "=" * 55)
    print("VALIDACIÓN DE COSTOS TBS")
    print("=" * 55)
    print(f"  Productos únicos vendidos:  {r['productos_vendidos']}")
    print(f"  Templates en BD:            {r['templates_con_datos']}")
    print(f"  Líneas con costo > 0:       {r['lineas_con_costo']}/{r['total_lineas']}")
    print(f"  GMV total:                  ${gmv_total:,.0f}")
    print(f"  GMV con costo cubierto:     ${gmv_costo:,.0f}")
    print(f"  Cobertura de GMV:           {cobertura:.1f}%")
    print(f"  Costo total calculado:      ${r['costo_total']:,.0f}")
    print(f"  Margen bruto calculado:     {margen_real:.1f}%")

    if cobertura >= 90:
        print(f"\n  ✓ Cobertura suficiente — margen de {margen_real:.1f}% es confiable")
    else:
        print(f"\n  ⚠ Cobertura baja ({cobertura:.1f}%) — usar fallback 22.3%")

    # Productos sin costo con venta real
    sin_costo = conn.execute(text("""
        SELECT
            sol.product_id,
            COALESCE(rpt.name, rp.name, 'sin nombre') AS producto,
            SUM(sol.price_subtotal)   AS venta_neta,
            SUM(sol.product_uom_qty)  AS cantidad
        FROM raw_sale_order_line sol
        JOIN raw_sale_order so ON so.id = sol.order_id
        LEFT JOIN raw_product rp
            ON rp.id = sol.product_id
        LEFT JOIN raw_product_template rpt
            ON rpt.id = rp.product_tmpl_id
        WHERE so.company_id = :cid
          AND so.state IN ('sale', 'done')
          AND COALESCE(rpt.standard_price, rp.standard_price, 0) <= 0
        GROUP BY sol.product_id, producto
        HAVING venta_neta > 0
        ORDER BY venta_neta DESC
    """), {"cid": COMPANY_ID}).mappings().fetchall()

    if sin_costo:
        print(f"\n  Productos con venta real pero sin costo ({len(sin_costo)}):")
        for row in sin_costo:
            print(f"    ID {row['product_id']} | "
                  f"${row['venta_neta']:,.0f} | "
                  f"{row['producto'][:45]}")
    else:
        print("\n  ✓ Todos los productos con venta tienen costo cargado")

    print("=" * 55)
