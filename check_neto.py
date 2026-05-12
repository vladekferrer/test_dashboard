from extraccion.odoo_client import OdooClient

c = OdooClient()
c.autenticar()

from sqlalchemy import create_engine, text
from config import config
engine = create_engine(config.DB_URL)

with engine.connect() as conn:
    resultado = conn.execute(text("""
        SELECT 
            strftime('%Y', date_order) as anio,
            COUNT(*) as ordenes,
            SUM(amount_total) as total_con_impuestos,
            SUM(amount_untaxed) as total_sin_impuestos,
            ROUND(SUM(amount_total) / SUM(amount_untaxed), 2) as factor_impuesto
        FROM raw_sale_order
        WHERE state IN ('sale', 'done')
          AND partner_id != 3
          AND date_order >= '2025-01-01'
          AND date_order < '2026-01-01'
        GROUP BY anio
    """)).fetchall()
    
    for row in resultado:
        print(f"Año: {row[0]}")
        print(f"  Órdenes:              {row[1]:,}")
        print(f"  Total CON impuestos:  ${row[2]:,.0f}")
        print(f"  Total SIN impuestos:  ${row[3]:,.0f}")
        print(f"  Factor de impuesto:   {row[4]}x")