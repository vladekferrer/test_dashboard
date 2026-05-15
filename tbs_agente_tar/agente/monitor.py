"""
Monitor del agente supervisor TBS.

Calcula el estado actual de cada vendedor vs cuotas,
genera el scorecard del equipo y las alertas prioritarias.
"""
from sqlalchemy import create_engine, text
from config import config
from agente.cuotas import get_cuota, MARCAS_ESTRATEGICAS, CATEGORIAS_CORE

COMPANY_ID = 2


def _engine():
    return create_engine(config.DB_URL, echo=False)


# ============================================================
# ESTADO DEL EQUIPO (nivel macro)
# ============================================================

def estado_equipo() -> dict:
    """Resumen del equipo completo vs cuotas este mes."""
    engine = _engine()
    with engine.connect() as conn:

        # GMV y cuentas del mes actual
        gmv = conn.execute(text("""
            SELECT
                COALESCE(ru.name, 'Sin asignar') AS vendedor,
                ROUND(SUM(so.amount_untaxed), 0)   AS gmv_mes,
                COUNT(DISTINCT so.partner_id)       AS cuentas_activas,
                COUNT(so.id)                        AS ordenes
            FROM raw_sale_order so
            LEFT JOIN raw_user ru ON so.user_id = ru.id
            WHERE so.company_id = :cid
              AND so.state IN ('sale','done')
              AND so.partner_id != 3
              AND strftime('%Y-%m', so.date_order) =
                  strftime('%Y-%m', 'now', 'localtime')
            GROUP BY so.user_id, ru.name
            ORDER BY gmv_mes DESC
        """), {"cid": COMPANY_ID}).mappings().fetchall()

        # Clientes nuevos del mes
        nuevos = conn.execute(text("""
            SELECT
                COALESCE(ru.name, 'Sin asignar') AS vendedor,
                COUNT(DISTINCT so.partner_id)     AS nuevos
            FROM raw_sale_order so
            LEFT JOIN raw_user ru ON so.user_id = ru.id
            WHERE so.company_id = :cid
              AND so.state IN ('sale','done')
              AND strftime('%Y-%m', so.date_order) =
                  strftime('%Y-%m', 'now', 'localtime')
              AND so.partner_id NOT IN (
                  SELECT DISTINCT partner_id
                  FROM raw_sale_order
                  WHERE company_id = :cid
                    AND state IN ('sale','done')
                    AND date_order <
                        date('now','localtime','start of month')
              )
            GROUP BY so.user_id, ru.name
        """), {"cid": COMPANY_ID}).mappings().fetchall()
        nuevos_map = {r["vendedor"]: r["nuevos"] for r in nuevos}

        # Cartera vencida por vendedor
        # company_id filtrado via raw_sale_order (columna puede no existir en raw_account_move)
        cartera = conn.execute(text("""
            SELECT
                COALESCE(ru.name, 'Sin asignar')    AS vendedor,
                ROUND(SUM(am.amount_residual), 0)    AS cartera_total,
                ROUND(SUM(CASE
                    WHEN julianday('now') -
                         julianday(am.invoice_date_due) > 30
                    THEN am.amount_residual ELSE 0
                END), 0)                             AS cartera_vencida
            FROM raw_account_move am
            JOIN (
                SELECT DISTINCT partner_id, user_id
                FROM raw_sale_order
                WHERE company_id = :cid
                  AND state IN ('sale','done')
            ) so ON so.partner_id = am.partner_id
            LEFT JOIN raw_user ru ON so.user_id = ru.id
            WHERE am.move_type      = 'out_invoice'
              AND am.state          = 'posted'
              AND am.amount_residual > 0
            GROUP BY so.user_id, ru.name
        """), {"cid": COMPANY_ID}).mappings().fetchall()
        cartera_map = {r["vendedor"]: r for r in cartera}

        # SKU promedio por orden este mes
        skus = conn.execute(text("""
            SELECT
                COALESCE(ru.name, 'Sin asignar') AS vendedor,
                ROUND(AVG(lineas_por_orden), 2)   AS skus_promedio
            FROM (
                SELECT so.user_id,
                       so.id AS orden_id,
                       COUNT(DISTINCT sol.product_id) AS lineas_por_orden
                FROM raw_sale_order so
                JOIN raw_sale_order_line sol ON sol.order_id = so.id
                WHERE so.company_id = :cid
                  AND so.state IN ('sale','done')
                  AND strftime('%Y-%m', so.date_order) =
                      strftime('%Y-%m', 'now', 'localtime')
                GROUP BY so.id, so.user_id
            ) sub
            LEFT JOIN raw_user ru ON sub.user_id = ru.id
            GROUP BY sub.user_id, ru.name
        """), {"cid": COMPANY_ID}).mappings().fetchall()
        skus_map = {r["vendedor"]: r["skus_promedio"] for r in skus}

    vendedores = []
    for row in gmv:
        nombre = row["vendedor"]
        cuota = get_cuota(nombre)
        c = cartera_map.get(nombre, {})
        cartera_total = c.get("cartera_total", 0) or 0
        cartera_vencida = c.get("cartera_vencida", 0) or 0
        gmv_mes = row["gmv_mes"] or 0
        cuentas = row["cuentas_activas"] or 0
        skus_prom = skus_map.get(nombre, 0) or 0
        nuevos_mes = nuevos_map.get(nombre, 0)
        pct_cartera = (cartera_vencida / cartera_total * 100) if cartera_total else 0

        avance_gmv     = gmv_mes / cuota["gmv_mensual"] * 100 if cuota["gmv_mensual"] else 0
        avance_cuentas = cuentas / cuota["cuentas_activas"] * 100 if cuota["cuentas_activas"] else 0

        # Semáforo general
        if avance_gmv >= 80 and pct_cartera <= cuota["cartera_max_pct"]:
            semaforo = "verde"
        elif avance_gmv >= 50 or pct_cartera <= cuota["cartera_max_pct"] * 1.5:
            semaforo = "amarillo"
        else:
            semaforo = "rojo"

        vendedores.append({
            "nombre":           nombre,
            "gmv_mes":          gmv_mes,
            "cuota_gmv":        cuota["gmv_mensual"],
            "avance_gmv_pct":   round(avance_gmv, 1),
            "cuentas_activas":  cuentas,
            "cuota_cuentas":    cuota["cuentas_activas"],
            "avance_cuentas_pct": round(avance_cuentas, 1),
            "clientes_nuevos":  nuevos_mes,
            "cuota_nuevos":     cuota["clientes_nuevos"],
            "skus_promedio":    skus_prom,
            "cuota_skus":       cuota["skus_promedio"],
            "cartera_total":    cartera_total,
            "cartera_vencida":  cartera_vencida,
            "pct_cartera":      round(pct_cartera, 1),
            "cuota_cartera":    cuota["cartera_max_pct"],
            "ordenes":          row["ordenes"],
            "semaforo":         semaforo,
        })

    return {
        "vendedores": vendedores,
        "totales": {
            "gmv_mes":    sum(v["gmv_mes"] for v in vendedores),
            "cuota_gmv":  sum(v["cuota_gmv"] for v in vendedores),
            "cuentas":    sum(v["cuentas_activas"] for v in vendedores),
            "nuevos":     sum(v["clientes_nuevos"] for v in vendedores),
        }
    }


# ============================================================
# CUENTAS EN RIESGO (sin pedido > N días)
# ============================================================

def cuentas_en_riesgo(dias: int = 14) -> list:
    """Cuentas del top 30 sin pedido en los últimos N días, por vendedor."""
    engine = _engine()
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
                rp.name                                             AS cliente,
                COALESCE(ru.name, 'Sin asignar')                   AS vendedor,
                MAX(so.date_order)                                  AS ultimo_pedido,
                CAST(julianday('now') -
                     julianday(MAX(so.date_order)) AS INT)         AS dias_inactivo,
                ROUND(SUM(so.amount_untaxed) /
                      COUNT(DISTINCT strftime('%Y-%m',
                      so.date_order)), 0)                          AS gmv_mensual_prom,
                COUNT(DISTINCT strftime('%Y-%m',
                      so.date_order))                              AS meses_activo
            FROM raw_sale_order so
            JOIN raw_partner rp ON so.partner_id = rp.id
            LEFT JOIN raw_user ru ON so.user_id = ru.id
            WHERE so.company_id = :cid
              AND so.state IN ('sale','done')
              AND so.partner_id != 3
              AND so.partner_id IN (
                  SELECT partner_id
                  FROM raw_sale_order
                  WHERE company_id = :cid
                    AND state IN ('sale','done')
                    AND partner_id != 3
                    AND date_order >= date('now', '-12 months')
                  GROUP BY partner_id
                  ORDER BY SUM(amount_untaxed) DESC
                  LIMIT 50
              )
            GROUP BY so.partner_id, ru.name
            HAVING dias_inactivo > :dias
            ORDER BY dias_inactivo DESC, gmv_mensual_prom DESC
        """), {"cid": COMPANY_ID, "dias": dias}).mappings().fetchall()
    return [dict(r) for r in rows]


# ============================================================
# PROFUNDIDAD DE PORTAFOLIO
# ============================================================

def profundidad_portafolio(top_n: int = 20) -> list:
    """
    Para cada cuenta top, qué categorías core tiene y cuáles faltan.
    Retorna lista de cuentas con su cobertura de categorías.
    """
    engine = _engine()
    categorias_sql = ", ".join([f"'{c}'" for c in CATEGORIAS_CORE])

    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            WITH top_cuentas AS (
                SELECT partner_id, SUM(amount_untaxed) AS gmv
                FROM raw_sale_order
                WHERE company_id = :cid
                  AND state IN ('sale','done')
                  AND partner_id != 3
                  AND date_order >= date('now', '-3 months')
                GROUP BY partner_id
                ORDER BY gmv DESC LIMIT :top_n
            ),
            ventas_cat AS (
                SELECT
                    so.partner_id,
                    CASE
                        WHEN UPPER(COALESCE(rpt.name, rp.name, ''))
                             LIKE '%WHISKY%' OR
                             UPPER(COALESCE(rpt.name, rp.name, ''))
                             LIKE '%WHISKEY%'      THEN 'Whisky'
                        WHEN UPPER(COALESCE(rpt.name, rp.name, ''))
                             LIKE '%VINO%' OR
                             UPPER(COALESCE(rpt.name, rp.name, ''))
                             LIKE '%WINE%'         THEN 'Vinos'
                        WHEN UPPER(COALESCE(rpt.name, rp.name, ''))
                             LIKE '%ESPUMANTE%' OR
                             UPPER(COALESCE(rpt.name, rp.name, ''))
                             LIKE '%CHAMPAGNE%' OR
                             UPPER(COALESCE(rpt.name, rp.name, ''))
                             LIKE '%PROSECCO%'     THEN 'Espumantes'
                        WHEN UPPER(COALESCE(rpt.name, rp.name, ''))
                             LIKE '%GIN%' OR
                             UPPER(COALESCE(rpt.name, rp.name, ''))
                             LIKE '%GINEBRA%'      THEN 'Gin'
                        WHEN UPPER(COALESCE(rpt.name, rp.name, ''))
                             LIKE '%RON%' OR
                             UPPER(COALESCE(rpt.name, rp.name, ''))
                             LIKE '%RUM%'          THEN 'Ron'
                        ELSE NULL
                    END AS categoria
                FROM raw_sale_order so
                JOIN raw_sale_order_line sol ON sol.order_id = so.id
                LEFT JOIN raw_product rp ON sol.product_id = rp.id
                LEFT JOIN raw_product_template rpt
                    ON rp.product_tmpl_id = rpt.id
                WHERE so.company_id = :cid
                  AND so.state IN ('sale','done')
                  AND so.date_order >= date('now', '-3 months')
                  AND so.partner_id IN (SELECT partner_id FROM top_cuentas)
                  AND categoria IS NOT NULL
            )
            SELECT
                rp2.name                                           AS cliente,
                COALESCE(ru.name, 'Sin asignar')                  AS vendedor,
                GROUP_CONCAT(DISTINCT vc.categoria)               AS categorias_activas,
                COUNT(DISTINCT vc.categoria)                      AS n_categorias,
                {len(CATEGORIAS_CORE)}                            AS n_core,
                ROUND(
                    COUNT(DISTINCT vc.categoria) * 100.0 /
                    {len(CATEGORIAS_CORE)}, 1
                )                                                  AS cobertura_pct
            FROM top_cuentas tc
            JOIN raw_partner rp2 ON tc.partner_id = rp2.id
            LEFT JOIN ventas_cat vc ON vc.partner_id = tc.partner_id
            LEFT JOIN raw_sale_order so_last
                ON so_last.partner_id = tc.partner_id
                AND so_last.company_id = :cid
            LEFT JOIN raw_user ru ON so_last.user_id = ru.id
            GROUP BY tc.partner_id, rp2.name
            ORDER BY cobertura_pct ASC, tc.gmv DESC
        """), {"cid": COMPANY_ID, "top_n": top_n}).mappings().fetchall()

    resultado = []
    for r in rows:
        activas = set((r["categorias_activas"] or "").split(","))
        activas.discard("")
        faltantes = [c for c in CATEGORIAS_CORE if c not in activas]
        resultado.append({
            **dict(r),
            "categorias_faltantes": faltantes,
        })
    return resultado


# ============================================================
# CODIFICACIÓN DE MARCAS ESTRATÉGICAS
# ============================================================

def codificacion_marcas(top_n: int = 20) -> list:
    """
    Para cada cuenta top, qué marcas estratégicas ha comprado
    en los últimos 3 meses.
    """
    engine = _engine()
    with engine.connect() as conn:
        filas = []
        for marca in MARCAS_ESTRATEGICAS:
            rows = conn.execute(text("""
                SELECT DISTINCT so.partner_id, rp2.name AS cliente
                FROM raw_sale_order so
                JOIN raw_sale_order_line sol ON sol.order_id = so.id
                LEFT JOIN raw_product rp     ON sol.product_id = rp.id
                LEFT JOIN raw_product_template rpt
                    ON rp.product_tmpl_id = rpt.id
                JOIN raw_partner rp2 ON so.partner_id = rp2.id
                WHERE so.company_id = :cid
                  AND so.state IN ('sale','done')
                  AND so.date_order >= date('now', '-3 months')
                  AND UPPER(COALESCE(rpt.name, rp.name, ''))
                      LIKE :marca
                  AND so.partner_id IN (
                      SELECT partner_id
                      FROM raw_sale_order
                      WHERE company_id = :cid
                        AND state IN ('sale','done')
                        AND partner_id != 3
                        AND date_order >= date('now', '-12 months')
                      GROUP BY partner_id
                      ORDER BY SUM(amount_untaxed) DESC
                      LIMIT :top_n
                  )
            """), {"cid": COMPANY_ID,
                   "marca": f"%{marca}%",
                   "top_n": top_n}).fetchall()
            for r in rows:
                filas.append({
                    "partner_id": r[0],
                    "cliente": r[1],
                    "marca": marca,
                    "codificada": True,
                })

        # Armar matriz cliente × marca
        codificados = {}
        for f in filas:
            k = (f["partner_id"], f["cliente"])
            if k not in codificados:
                codificados[k] = []
            codificados[k].append(f["marca"])

        # Top cuentas
        top = conn.execute(text("""
            SELECT partner_id, rp.name AS cliente,
                   COALESCE(ru.name,'Sin asignar') AS vendedor
            FROM raw_sale_order so
            JOIN raw_partner rp ON so.partner_id = rp.id
            LEFT JOIN raw_user ru ON so.user_id = ru.id
            WHERE so.company_id = :cid
              AND so.state IN ('sale','done')
              AND so.partner_id != 3
              AND so.date_order >= date('now', '-12 months')
            GROUP BY so.partner_id
            ORDER BY SUM(so.amount_untaxed) DESC LIMIT :top_n
        """), {"cid": COMPANY_ID, "top_n": top_n}).mappings().fetchall()

    resultado = []
    for t in top:
        k = (t["partner_id"], t["cliente"])
        marcas_activas = codificados.get(k, [])
        marcas_faltantes = [m for m in MARCAS_ESTRATEGICAS
                            if m not in marcas_activas]
        resultado.append({
            "cliente":          t["cliente"],
            "vendedor":         t["vendedor"],
            "marcas_activas":   marcas_activas,
            "marcas_faltantes": marcas_faltantes,
            "cobertura_pct":    round(
                len(marcas_activas) / len(MARCAS_ESTRATEGICAS) * 100, 1
            ),
        })
    return resultado


# ============================================================
# VISITAS (registradas manualmente en la BD)
# ============================================================

def visitas_semana(vendedor: str = None) -> list:
    """Visitas registradas en la semana actual."""
    engine = _engine()
    with engine.connect() as conn:
        filtro = "AND vendedor = :vendedor" if vendedor else ""
        rows = conn.execute(text(f"""
            SELECT id, vendedor, cliente, fecha, tipo,
                   resultado, compromiso, monto_pedido
            FROM visitas_vendedor
            WHERE fecha >= date('now', 'weekday 0', '-7 days')
            {filtro}
            ORDER BY fecha DESC
        """), {"vendedor": vendedor} if vendedor else {}).mappings().fetchall()
    return [dict(r) for r in rows]


def compromisos_pendientes() -> list:
    """Compromisos abiertos del equipo ordenados por vencimiento."""
    engine = _engine()
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT c.id, c.vendedor, c.descripcion,
                   c.fecha_compromiso, c.cliente,
                   c.estado,
                   CAST(julianday(c.fecha_compromiso) -
                        julianday('now') AS INT) AS dias_restantes
            FROM compromisos_vendedor c
            WHERE c.estado = 'pendiente'
            ORDER BY dias_restantes ASC
        """)).mappings().fetchall()
    return [dict(r) for r in rows]
