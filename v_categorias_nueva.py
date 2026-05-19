# ════════════════════════════════════════════════════════════════
# REEMPLAZAR el bloque VISTAS["v_categorias"] actual de vistas.py
# por este. La categoría ya NO se adivina del nombre del producto:
# se toma de categ_id -> raw_product_category (la clasificación real
# de Odoo). Si una categoría está mal, se corrige en Odoo, no aquí.
# ════════════════════════════════════════════════════════════════

VISTAS["v_categorias"] = """
CREATE VIEW IF NOT EXISTS v_categorias AS
WITH base AS (
    SELECT
        rc.name AS ruta,
        sol.price_subtotal AS revenue,
        COALESCE(rpt.standard_price, rp.standard_price, 0)
            * sol.product_uom_qty                       AS costo,
        CASE
            WHEN COALESCE(rpt.standard_price, rp.standard_price, 0) > 0
            THEN sol.price_subtotal
            ELSE 0
        END                                             AS revenue_con_costo
    FROM raw_sale_order so
    JOIN raw_sale_order_line sol
        ON sol.order_id = so.id
    LEFT JOIN raw_product rp
        ON sol.product_id = rp.id
    LEFT JOIN raw_product_template rpt
        ON rpt.id = rp.product_tmpl_id
       AND rpt.company_id = 2
    LEFT JOIN raw_product_category rc
        ON rc.id = rpt.categ_id
    WHERE so.state IN ('sale', 'done')
      AND so.company_id = 2
      AND so.partner_id != 3
      AND so.date_order >= date('now', '-12 months')
),
-- Quita el prefijo "Todas / " de la ruta de categoria de Odoo.
norm AS (
    SELECT
        CASE
            WHEN ruta IS NULL OR ruta = ''      THEN '##NULL##'
            WHEN ruta NOT LIKE 'Todas / %'      THEN ruta
            ELSE substr(ruta, 9)
        END AS resto,
        revenue, costo, revenue_con_costo
    FROM base
),
-- Toma el tipo de licor: 2do segmento de la ruta ya sin prefijo
-- ("Licores / Whiskys / Blend" -> "Whiskys"). Si solo hay un
-- segmento ("Licores"), usa ese. NULL -> "Sin categoria".
categorias AS (
    SELECT
        CASE
            WHEN resto = '##NULL##' THEN 'Sin categoría'
            WHEN instr(resto, ' / ') = 0 THEN resto
            WHEN instr(substr(resto, instr(resto, ' / ') + 3), ' / ') = 0
                THEN substr(resto, instr(resto, ' / ') + 3)
            ELSE substr(
                     substr(resto, instr(resto, ' / ') + 3),
                     1,
                     instr(substr(resto, instr(resto, ' / ') + 3), ' / ') - 1
                 )
        END AS categoria,
        revenue, costo, revenue_con_costo
    FROM norm
)
SELECT
    categoria,
    ROUND(SUM(revenue), 0)                                      AS gmv_neto,
    ROUND(SUM(revenue) * 100.0 / SUM(SUM(revenue)) OVER (), 1)  AS pct_gmv,
    ROUND((SUM(revenue) - SUM(costo)) / NULLIF(SUM(revenue), 0) * 100, 1) AS margen_pct,
    ROUND(SUM(revenue_con_costo) / NULLIF(SUM(revenue), 0) * 100, 1) AS cobertura_costo_pct,
    COUNT(*)                                                     AS lineas_vendidas
FROM categorias
GROUP BY categoria
ORDER BY gmv_neto DESC
"""
