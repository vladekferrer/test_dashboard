from sqlalchemy import create_engine, text
from config import config

engine = create_engine(config.DB_URL)

with engine.connect() as conn:
    resultado = conn.execute(text("""
        SELECT
            COUNT(sol.id)                                       AS total_lineas,
            SUM(CASE WHEN rp.id IS NOT NULL THEN 1 ELSE 0 END) AS lineas_con_producto,
            SUM(CASE WHEN rp.standard_price > 0 THEN 1 ELSE 0 END) AS lineas_con_costo,
            SUM(CASE WHEN rp.id IS NULL THEN 1 ELSE 0 END)     AS lineas_sin_producto,
            ROUND(SUM(sol.price_subtotal), 0)                   AS revenue_total,
            ROUND(SUM(
                COALESCE(rp.standard_price, 0) * sol.product_uom_qty
            ), 0)                                               AS costo_total
        FROM raw_sale_order_line sol
        LEFT JOIN raw_product rp ON sol.product_id = rp.id
        WHERE sol.order_id IN (
            SELECT id FROM raw_sale_order
              WHERE state IN ('sale','done')
              AND strftime('%Y-%m', date_order) =
                  strftime('%Y-%m', 'now', 'localtime')
        )
    """)).mappings().first()

    print(f"\nDiagnóstico de margen — mes actual:")
    print(f"  Total líneas de venta:        {resultado['total_lineas']:,}")
    print(f"  Líneas con producto en BD:    {resultado['lineas_con_producto']:,}")
    print(f"  Líneas con costo > 0:         {resultado['lineas_con_costo']:,}")
    print(f"  Líneas SIN producto en BD:    {resultado['lineas_sin_producto']:,}")
    print(f"  Revenue total:                ${resultado['revenue_total']:,.0f}")
    print(f"  Costo calculado:              ${resultado['costo_total']:,.0f}")
    if resultado['revenue_total'] and resultado['revenue_total'] > 0:
        margen = (1 - resultado['costo_total'] / resultado['revenue_total']) * 100
        print(f"  Margen implícito:             {margen:.1f}%")