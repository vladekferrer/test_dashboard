"""
Monitor estratégico TBS.

Mide el avance de los 6 objetivos del plan estratégico:
  1. Densificación de los 9 hoteles top (portafolio: ≥6 de 8 categorías core)
  2. Recuperación de cuentas Vacante 87
  3. Codificación de marcas estratégicas
  4. Control de cartera (< 8% vencida)
  5. Captación de clientes nuevos (≥2 por vendedor/mes)
  6. Evolución del mix premium (% GMV en categorías premium)

Diferencia con monitor.py:
  monitor.py  → estado operativo hoy (quién visitó, cuota del mes)
  estrategia.py → avance del plan a 3-6 meses (qué está funcionando)
"""
from sqlalchemy import create_engine, text
from config import config

COMPANY_ID = 2
MESES_ANALISIS = 4   # cuántos meses hacia atrás analizar tendencia

# Hoteles objetivo del plan
HOTELES_OBJETIVO = [
    "HOTEL CARIBE",
    "HOTEL SANTA CLARA",
    "CASA DON LUIS",
    "HOTEL SAN PEDRO",
    "HYATT REGENCY",
    "VOILA HOTEL",
    "HOTEL LAS ISLAS",
    "ARSENAL HOTEL",
    "HOTELES DE LA ANTIGUA",
]

# Metas del plan (ajustar según realidad)
METAS = {
    "profundidad_hoteles_meta":   6,      # categorías core activas por hotel (de 8 posibles)
    "marcas_cobertura_target":   70.0,   # % cuentas top con marcas estratégicas
    "cartera_vencida_max":        8.0,   # % máximo de cartera vencida >30d
    "clientes_nuevos_mes":        6,     # total equipo por mes
    "pct_gmv_premium_min":       35.0,   # % mínimo GMV en categorías premium
    "cuentas_vacante_recuperar":  30,    # cuentas de vacante 87 a recuperar
}

# Categorías consideradas "premium" para el mix
CATEGORIAS_PREMIUM = [
    "Whisky", "Vinos", "Espumantes", "Gin",
    "Mezcal", "Ron", "Tequila",
]


def _engine():
    return create_engine(config.DB_URL, echo=False)


# ════════════════════════════════════════════════════════
# OBJ 1 — DENSIFICACIÓN DE HOTELES TOP
# ════════════════════════════════════════════════════════

def obj_densificacion_hoteles() -> dict:
    """
    Mide la profundidad de portafolio en los 9 hoteles objetivo.
    Profundidad = cuántas de las 8 categorías core del portafolio TBS
    ha comprado cada hotel en los últimos 3 meses.

    Métrica elegida: número de categorías activas, no Share of Wallet.
    TBS no conoce el gasto total del hotel en licores, así que no puede
    calcular SoW. La profundidad de portafolio se puede medir exactamente
    con los datos de Odoo y es igualmente accionable.
    """
    CATEGORIAS_CORE = [
        ("Whisky",          ["WHISKY", "WHISKEY", "SCOTCH", "BOURBON"]),
        ("Vinos",           ["VINO ", "WINE", "MERLOT", "CABERNET", "CHARDONNAY",
                             "SAUVIGNON", "PINOT"]),
        ("Espumantes",      ["ESPUMANTE", "CHAMPAGNE", "CHAMPA", "PROSECCO",
                             "CAVA", "ESPUMOSO"]),
        ("Gin",             ["GIN", "GINEBRA"]),
        ("Mezcal/Tequila",  ["MEZCAL", "TEQUILA"]),
        ("Ron",             ["RON ", "RUM"]),
        ("Vodka",           ["VODKA"]),
        ("Aperitivos",      ["APERITIVO", "VERMOUTH", "VERMUT", "CAMPARI",
                             "APEROL", "BITTER"]),
    ]
    N_CORE = len(CATEGORIAS_CORE)
    META_CATEGORIAS = 6   # meta: ≥6 de 8 categorías activas por hotel

    FILTRO_HOTELES = """(
        UPPER(rp.name) LIKE '%HOTEL CARIBE%' OR
        UPPER(rp.name) LIKE '%SANTA CLARA%'  OR
        UPPER(rp.name) LIKE '%DON LUIS%'     OR
        UPPER(rp.name) LIKE '%SAN PEDRO DE MAJAGUA%' OR
        UPPER(rp.name) LIKE '%HYATT%'        OR
        UPPER(rp.name) LIKE '%VOILA%'        OR
        UPPER(rp.name) LIKE '%LAS ISLAS%'    OR
        UPPER(rp.name) LIKE '%ARSENAL HOTEL%' OR
        UPPER(rp.name) LIKE '%ANTIGUA%'
    )"""

    engine = _engine()
    with engine.connect() as conn:

        # GMV y tendencia por hotel (para ordenar y ver si crecen)
        gmv_rows = conn.execute(text(f"""
            SELECT
                rp.name                                       AS hotel,
                strftime('%Y-%m', so.date_order)              AS mes,
                ROUND(SUM(so.amount_untaxed), 0)              AS gmv
            FROM raw_sale_order so
            JOIN raw_partner rp ON so.partner_id = rp.id
            WHERE so.company_id = :cid
              AND so.state IN ('sale','done')
              AND so.date_order >= date('now', '-4 months')
              AND {FILTRO_HOTELES}
            GROUP BY rp.name, strftime('%Y-%m', so.date_order)
            ORDER BY rp.name, mes
        """), {"cid": COMPANY_ID}).mappings().fetchall()

        # Líneas de venta por hotel por categoría (últimos 3 meses)
        lineas = conn.execute(text(f"""
            SELECT
                rp.name                                           AS hotel,
                UPPER(COALESCE(rpt.name, rp2.name, ''))          AS producto
            FROM raw_sale_order so
            JOIN raw_partner rp       ON so.partner_id = rp.id
            JOIN raw_sale_order_line sol ON sol.order_id = so.id
            LEFT JOIN raw_product rp2  ON sol.product_id = rp2.id
            LEFT JOIN raw_product_template rpt
                ON rp2.product_tmpl_id = rpt.id
            WHERE so.company_id = :cid
              AND so.state IN ('sale','done')
              AND so.date_order >= date('now', '-3 months')
              AND {FILTRO_HOTELES}
        """), {"cid": COMPANY_ID}).mappings().fetchall()

    # Construir mapa: hotel → set de categorías compradas
    hotel_categorias = {}
    for r in lineas:
        hotel = r["hotel"]
        prod  = r["producto"]
        if hotel not in hotel_categorias:
            hotel_categorias[hotel] = set()
        for nombre_cat, keywords in CATEGORIAS_CORE:
            if any(kw in prod for kw in keywords):
                hotel_categorias[hotel].add(nombre_cat)

    # Construir mapa de GMV y tendencia
    gmv_por_hotel = {}
    for r in gmv_rows:
        h = r["hotel"]
        if h not in gmv_por_hotel:
            gmv_por_hotel[h] = []
        gmv_por_hotel[h].append({"mes": r["mes"], "gmv": r["gmv"]})

    # Ensamblar resultado
    resumen = []
    for hotel, cats_activas in hotel_categorias.items():
        cats_faltantes = [c[0] for c in CATEGORIAS_CORE
                          if c[0] not in cats_activas]
        n_activas = len(cats_activas)
        cobertura_pct = round(n_activas / N_CORE * 100, 1)

        meses = gmv_por_hotel.get(hotel, [])
        gmv_actual = meses[-1]["gmv"] if meses else 0
        gmv_prom   = sum(m["gmv"] for m in meses) / len(meses) if meses else 0

        # Tendencia de GMV
        n = len(meses)
        if n >= 2:
            tend_pct = (meses[-1]["gmv"] - meses[0]["gmv"]) /                        max(meses[0]["gmv"], 1) * 100
        else:
            tend_pct = 0

        estado_profundidad = (
            "en_meta"    if n_activas >= META_CATEGORIAS else
            "progresando" if n_activas >= META_CATEGORIAS * 0.6 else
            "bajo"
        )

        resumen.append({
            "hotel":             hotel,
            "gmv_mes_actual":    gmv_actual,
            "gmv_promedio":      round(gmv_prom, 0),
            "tendencia_gmv_pct": round(tend_pct, 1),
            "categorias_activas":   sorted(cats_activas),
            "categorias_faltantes": cats_faltantes,
            "n_categorias_activas": n_activas,
            "n_categorias_core":    N_CORE,
            "cobertura_pct":        cobertura_pct,
            "estado":               estado_profundidad,
            "meta_categorias":      META_CATEGORIAS,
        })

    resumen.sort(key=lambda x: x["gmv_mes_actual"], reverse=True)

    en_meta    = sum(1 for h in resumen if h["estado"] == "en_meta")
    bajo       = sum(1 for h in resumen if h["estado"] == "bajo")
    cob_prom   = sum(h["cobertura_pct"] for h in resumen) / len(resumen)                  if resumen else 0

    return {
        "objetivo":       "Profundidad de portafolio en 9 hoteles top (meta: ≥6/8 categorías)",
        "meta_categorias": META_CATEGORIAS,
        "n_categorias_core": N_CORE,
        "hoteles":        resumen,
        "resumen": {
            "total_hoteles":    len(resumen),
            "en_meta":          en_meta,
            "progresando":      len(resumen) - en_meta - bajo,
            "bajo":             bajo,
            "cobertura_promedio_pct": round(cob_prom, 1),
            "gmv_total_actual": sum(h["gmv_mes_actual"] for h in resumen),
        },
        "alerta": bajo >= 3 or cob_prom < 50,
    }


# ════════════════════════════════════════════════════════
# OBJ 2 — RECUPERACIÓN VACANTE 87
# ════════════════════════════════════════════════════════

def obj_recuperacion_vacante() -> dict:
    """
    Mide cuántas de las 46 cuentas huérfanas de Vacante 87
    están siendo recuperadas (tienen pedido en los últimos 30 días).
    """
    engine = _engine()
    with engine.connect() as conn:

        # Cuentas que tuvieron actividad con Vacante 87 en 2025
        vacante_cuentas = conn.execute(text("""
            SELECT DISTINCT so.partner_id, rp.name AS cliente,
                   SUM(so.amount_untaxed) AS gmv_historico,
                   MAX(so.date_order) AS ultimo_pedido
            FROM raw_sale_order so
            JOIN raw_partner rp ON so.partner_id = rp.id
            LEFT JOIN raw_user ru ON so.user_id = ru.id
            WHERE so.company_id = :cid
              AND so.state IN ('sale','done')
              AND (ru.name LIKE '%VACANTE%'
                   OR ru.name LIKE '%87%'
                   OR so.user_id IS NULL)
              AND so.date_order >= '2025-01-01'
            GROUP BY so.partner_id
            ORDER BY gmv_historico DESC
        """), {"cid": COMPANY_ID}).mappings().fetchall()

        total_cuentas = len(vacante_cuentas)

        # Cuáles tienen pedido reciente (últimos 60 días, cualquier vendedor)
        ids = [r["partner_id"] for r in vacante_cuentas]
        recuperadas = 0
        perdidas = 0
        if ids:
            ids_str = ",".join(str(i) for i in ids)
            recientes = conn.execute(text(f"""
                SELECT DISTINCT partner_id
                FROM raw_sale_order
                WHERE company_id = :cid
                  AND state IN ('sale','done')
                  AND date_order >= date('now', '-60 days')
                  AND partner_id IN ({ids_str})
            """), {"cid": COMPANY_ID}).fetchall()
            recuperadas = len(recientes)
            perdidas = total_cuentas - recuperadas

    gmv_en_riesgo = sum(
        r["gmv_historico"] for r in vacante_cuentas
    ) / 12  # promedio mensual

    return {
        "objetivo": "Recuperar 30 de 46 cuentas Vacante 87",
        "meta": METAS["cuentas_vacante_recuperar"],
        "total_cuentas_vacante": total_cuentas,
        "recuperadas_60d": recuperadas,
        "en_riesgo": perdidas,
        "pct_recuperado": round(recuperadas / total_cuentas * 100, 1)
                          if total_cuentas else 0,
        "gmv_mensual_en_riesgo": round(gmv_en_riesgo, 0),
        "top_cuentas_perdidas": [
            {"cliente": r["cliente"],
             "gmv_mensual": round(r["gmv_historico"] / 12, 0),
             "ultimo_pedido": str(r["ultimo_pedido"])}
            for r in vacante_cuentas[:5]
        ],
        "alerta": perdidas > 20,
    }


# ════════════════════════════════════════════════════════
# OBJ 3 — CODIFICACIÓN DE MARCAS
# ════════════════════════════════════════════════════════

def obj_codificacion_marcas() -> dict:
    """
    Mide el avance de codificación de marcas estratégicas
    en el top 30 de cuentas.
    """
    from agente.monitor import codificacion_marcas
    marcas = codificacion_marcas(top_n=30)

    con_cobertura_alta = sum(1 for m in marcas if m["cobertura_pct"] >= 70)
    cobertura_promedio = sum(m["cobertura_pct"] for m in marcas) / len(marcas) \
                         if marcas else 0

    return {
        "objetivo": "Codificar marcas estratégicas en top 30 cuentas",
        "meta": METAS["marcas_cobertura_target"],
        "cobertura_promedio_pct": round(cobertura_promedio, 1),
        "cuentas_sobre_70pct": con_cobertura_alta,
        "total_cuentas": len(marcas),
        "cuentas_con_gaps": [
            m for m in marcas if m["marcas_faltantes"]
        ][:8],
        "alerta": cobertura_promedio < 50,
    }


# ════════════════════════════════════════════════════════
# OBJ 4 — CONTROL DE CARTERA
# ════════════════════════════════════════════════════════

def obj_cartera() -> dict:
    """
    Evolución mensual del % de cartera vencida >30d.
    Identifica si la tendencia es de mejora o deterioro.
    """
    engine = _engine()
    with engine.connect() as conn:

        cartera_actual = conn.execute(text("""
            SELECT
                ROUND(SUM(amount_residual), 0)         AS cartera_total,
                ROUND(SUM(CASE
                    WHEN julianday('now') -
                         julianday(invoice_date_due) > 30
                    THEN amount_residual ELSE 0
                END), 0)                               AS vencida_30d,
                ROUND(SUM(CASE
                    WHEN julianday('now') -
                         julianday(invoice_date_due) > 60
                    THEN amount_residual ELSE 0
                END), 0)                               AS vencida_60d,
                ROUND(SUM(CASE
                    WHEN julianday('now') -
                         julianday(invoice_date_due) > 90
                    THEN amount_residual ELSE 0
                END), 0)                               AS vencida_90d
            FROM raw_account_move
            WHERE move_type = 'out_invoice'
              AND state     = 'posted'
              AND amount_residual > 0
        """)).mappings().first()

        total = cartera_actual["cartera_total"] or 1
        pct_30 = (cartera_actual["vencida_30d"] or 0) / total * 100
        pct_60 = (cartera_actual["vencida_60d"] or 0) / total * 100
        pct_90 = (cartera_actual["vencida_90d"] or 0) / total * 100

    return {
        "objetivo": "Mantener cartera vencida <8%",
        "meta": METAS["cartera_vencida_max"],
        "cartera_total": cartera_actual["cartera_total"],
        "vencida_30d": cartera_actual["vencida_30d"],
        "vencida_60d": cartera_actual["vencida_60d"],
        "vencida_90d": cartera_actual["vencida_90d"],
        "pct_vencida_30d": round(pct_30, 1),
        "pct_vencida_60d": round(pct_60, 1),
        "pct_vencida_90d": round(pct_90, 1),
        "estado": "critico" if pct_30 > 15
                  else "alerta" if pct_30 > 8
                  else "sano",
        "alerta": pct_30 > 8,
    }


# ════════════════════════════════════════════════════════
# OBJ 5 — CAPTACIÓN DE CLIENTES NUEVOS
# ════════════════════════════════════════════════════════

def obj_clientes_nuevos() -> dict:
    """
    Captación mensual de clientes nuevos vs meta del plan.
    Tendencia de los últimos meses.
    """
    engine = _engine()
    with engine.connect() as conn:

        mensual = conn.execute(text("""
            SELECT
                strftime('%Y-%m', so.date_order) AS mes,
                COUNT(DISTINCT so.partner_id)     AS clientes_nuevos
            FROM raw_sale_order so
            WHERE so.company_id = :cid
              AND so.state IN ('sale','done')
              AND so.partner_id != 3
              AND so.date_order >= date('now', '-5 months')
              AND so.partner_id NOT IN (
                  SELECT DISTINCT partner_id
                  FROM raw_sale_order
                  WHERE company_id = :cid
                    AND state IN ('sale','done')
                    AND date_order < date(so.date_order, 'start of month')
              )
            GROUP BY strftime('%Y-%m', so.date_order)
            ORDER BY mes DESC
        """), {"cid": COMPANY_ID}).mappings().fetchall()

    meses = [dict(r) for r in mensual]
    promedio = sum(m["clientes_nuevos"] for m in meses) / len(meses) \
               if meses else 0
    mes_actual = meses[0]["clientes_nuevos"] if meses else 0

    return {
        "objetivo": f"≥{METAS['clientes_nuevos_mes']} clientes nuevos por mes (equipo)",
        "meta_mensual": METAS["clientes_nuevos_mes"],
        "mes_actual": mes_actual,
        "promedio_ultimos_meses": round(promedio, 1),
        "tendencia_meses": meses,
        "cumpliendo_meta": mes_actual >= METAS["clientes_nuevos_mes"],
        "alerta": mes_actual < METAS["clientes_nuevos_mes"] * 0.5,
    }


# ════════════════════════════════════════════════════════
# OBJ 6 — MIX PREMIUM
# ════════════════════════════════════════════════════════

def obj_mix_premium() -> dict:
    """
    Evolución mensual del % de GMV en categorías premium.
    Detecta si el negocio se está commoditizando.
    """
    engine = _engine()
    cat_cases = " ".join([
        f"WHEN UPPER(COALESCE(rpt.name, rp.name, '')) LIKE '%{c.upper()}%' THEN '{c}'"
        for c in CATEGORIAS_PREMIUM
    ])

    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT
                strftime('%Y-%m', so.date_order)     AS mes,
                ROUND(SUM(sol.price_subtotal), 0)     AS gmv_total,
                ROUND(SUM(CASE
                    WHEN (CASE {cat_cases} ELSE NULL END) IS NOT NULL
                    THEN sol.price_subtotal ELSE 0
                END), 0)                              AS gmv_premium
            FROM raw_sale_order so
            JOIN raw_sale_order_line sol       ON sol.order_id = so.id
            LEFT JOIN raw_product rp           ON sol.product_id = rp.id
            LEFT JOIN raw_product_template rpt ON rp.product_tmpl_id = rpt.id
            WHERE so.company_id = :cid
              AND so.state IN ('sale','done')
              AND so.date_order >= date('now', '-5 months')
            GROUP BY strftime('%Y-%m', so.date_order)
            ORDER BY mes DESC
        """), {"cid": COMPANY_ID}).mappings().fetchall()

    meses = []
    for r in rows:
        pct = (r["gmv_premium"] or 0) / max(r["gmv_total"] or 1, 1) * 100
        meses.append({
            "mes": r["mes"],
            "gmv_total": r["gmv_total"],
            "gmv_premium": r["gmv_premium"],
            "pct_premium": round(pct, 1),
        })

    pct_actual = meses[0]["pct_premium"] if meses else 0
    tendencia = meses[0]["pct_premium"] - meses[-1]["pct_premium"] \
                if len(meses) >= 2 else 0

    return {
        "objetivo": f"≥{METAS['pct_gmv_premium_min']}% GMV en categorías premium",
        "meta": METAS["pct_gmv_premium_min"],
        "pct_actual": pct_actual,
        "tendencia_ppts": round(tendencia, 1),
        "tendencia_meses": meses,
        "estado": "sano" if pct_actual >= METAS["pct_gmv_premium_min"]
                  else "alerta" if pct_actual >= METAS["pct_gmv_premium_min"] * 0.8
                  else "critico",
        "alerta": tendencia < -3,
    }


# ════════════════════════════════════════════════════════
# SNAPSHOT ESTRATÉGICO COMPLETO
# ════════════════════════════════════════════════════════

def snapshot_estrategico() -> dict:
    """
    Retorna el estado de los 6 objetivos estratégicos.
    Es la entrada principal para el análisis del LLM.
    """
    return {
        "hoteles":    obj_densificacion_hoteles(),
        "vacante":    obj_recuperacion_vacante(),
        "marcas":     obj_codificacion_marcas(),
        "cartera":    obj_cartera(),
        "nuevos":     obj_clientes_nuevos(),
        "mix":        obj_mix_premium(),
    }
