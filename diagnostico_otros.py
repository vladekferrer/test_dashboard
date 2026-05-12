from sqlalchemy import create_engine, text
from config import config

engine = create_engine(config.DB_URL)

with engine.connect() as conn:

    # Causa 1: ¿el industry_id llegó desde Odoo?
    con_sector = conn.execute(text("""
        SELECT COUNT(*) FROM raw_partner
        WHERE industry_id IS NOT NULL AND customer_rank > 0
    """)).scalar()
    sin_sector = conn.execute(text("""
        SELECT COUNT(*) FROM raw_partner
        WHERE industry_id IS NULL AND customer_rank > 0
    """)).scalar()
    print(f"Clientes CON sector en Odoo:  {con_sector}")
    print(f"Clientes SIN sector en Odoo:  {sin_sector}")

    # Causa 2: clientes en 'Otros' con su GMV real desde raw_sale_order
    print("\nTop 30 clientes clasificados como 'Otros':")
    rows = conn.execute(text("""
        SELECT
            dc.nombre,
            dc.es_top30,
            ROUND(SUM(so.amount_untaxed) / 12, 0) AS gmv_mensual_prom
        FROM dim_cliente dc
        JOIN raw_sale_order so
            ON dc.id_cliente = so.partner_id
        WHERE dc.tipo_horeca = 'Otros'
          AND so.state IN ('sale', 'done')
          AND so.company_id = 2
          AND so.date_order >= date('now', '-12 months')
        GROUP BY dc.id_cliente, dc.nombre, dc.es_top30
        ORDER BY gmv_mensual_prom DESC
        LIMIT 30
    """)).fetchall()

    for r in rows:
        top = "★ TOP30" if r[1] else "      "
        print(f"  {top}  ${r[2]/1000000:.1f}M/mes  {r[0]}")