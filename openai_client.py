"""
Integracion con OpenAI para el dashboard TBS (lado del director).

Este modulo contiene las funciones LLM del director comercial.
Conviven con las del supervisor (agente.supervisor_llm) pero con proposito
distinto:

  - generar_insight_diario():  insight ejecutivo del negocio para el director.
                                Mira North Star, alertas, hoteles top, vendedores,
                                tendencia. Sale en el dashboard de /index.
  - responder_pregunta():       chat del analista IA del director.
                                Responde sobre KPIs del negocio en general.

Esto NO se confunde con:
  - agente.supervisor_llm.analisis_estrategico  -> avance del plan a 3-6 meses
  - agente.supervisor_llm.briefing_diario       -> operativo del equipo de ventas

Uso:
  - llm/generar_insight.py (cron diario) llama generar_insight_diario + guardar.
  - main.py expone /api/chat y /api/insights/regenerar.
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from openai import OpenAI
from sqlalchemy import create_engine, text
from config import config

logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_PATH = (
    Path(__file__).parent / "knowledge_base" / "estrategia.md"
)

MODEL = "gpt-4o"
API_KEY = getattr(config, "OPENAI_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")


def _leer_knowledge_base() -> str:
    with open(KNOWLEDGE_BASE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _obtener_snapshot_kpis() -> dict:
    """
    Extrae el estado actual del negocio desde las vistas analiticas.
    Este snapshot es el contexto que recibe el LLM.
    """
    engine = create_engine(config.DB_URL, echo=False)

    with engine.connect() as conn:
        # North Star
        ns = conn.execute(text("SELECT * FROM v_north_star")).mappings().first()

        # Top alertas
        alertas = conn.execute(text("""
            SELECT descripcion_alerta, cliente, dias_inactivo,
                   cartera_vencida, semaforo
            FROM v_alertas
            WHERE semaforo IN ('rojo', 'amarillo')
            ORDER BY CASE semaforo WHEN 'rojo' THEN 1 ELSE 2 END
            LIMIT 5
        """)).mappings().fetchall()

        # Top 10 cuentas por ranking de GMV
        top_cuentas = conn.execute(text("""
            SELECT nombre, gmv_mes_actual, gmv_mensual_prom,
                   variacion_pct, dias_sin_pedido,
                   cartera_vencida, estado
            FROM v_clientes_top
            WHERE ranking <= 10
            ORDER BY ranking
        """)).mappings().fetchall()

        # Vendedores
        vendedores = conn.execute(text("""
            SELECT nombre, gmv_mes_actual, clientes_unicos, estado
            FROM v_vendedores
            ORDER BY gmv_mes_actual DESC
        """)).mappings().fetchall()

        # Tendencia ultimos 3 meses
        tendencia = conn.execute(text("""
            SELECT mes, gmv_neto, clientes_activos
            FROM v_tendencia_mensual
            ORDER BY mes DESC
            LIMIT 3
        """)).mappings().fetchall()

    return {
        "fecha_analisis": datetime.now().strftime("%Y-%m-%d"),
        "north_star": dict(ns) if ns else {},
        "alertas_activas": [dict(a) for a in alertas],
        "top_cuentas": [dict(c) for c in top_cuentas],
        "vendedores": [dict(v) for v in vendedores],
        "tendencia_reciente": [dict(t) for t in tendencia],
    }


def generar_insight_diario() -> str:
    """
    Genera el insight estrategico diario para el director.
    Retorna el texto del insight.

    Si falla (sin API key, error de red, etc.) LANZA una excepción.
    NUNCA devuelve el error como texto: si lo hiciera, el endpoint lo
    guardaria en llm_insights como si fuera un insight real y el panel
    quedaria mostrando el mensaje de error para siempre.
    """
    if not API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY no configurada. Agrégala en el archivo .env"
        )

    knowledge_base = _leer_knowledge_base()
    snapshot = _obtener_snapshot_kpis()
    client = OpenAI(api_key=API_KEY)

    prompt = f"""Eres el asesor comercial senior de TBS DESTILADOS, distribuidora
de licores premium en Cartagena. Conoces profundamente el negocio.

═══════════════════════════════════════════════════════════
BASE DE CONOCIMIENTO ESTRATEGICA (estable — cambia con decisiones)
═══════════════════════════════════════════════════════════
{knowledge_base}

═══════════════════════════════════════════════════════════
CONTEXTO ACTUAL ({snapshot['fecha_analisis']}) — datos en vivo desde Odoo/SQLite
NO es parte de la base de conocimiento. Usa estos datos para nombres y cifras.
═══════════════════════════════════════════════════════════
{json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)}

Analiza los datos y genera un informe ejecutivo BREVE con exactamente este formato:

**Estado del mes**: [1 frase que resume si el negocio va bien, regular o mal y por que]

**Movimiento prioritario esta semana**:
1. [Accion especifica + cliente o cuenta nombrada + impacto estimado en pesos]
2. [Accion especifica + cliente o cuenta nombrada + impacto estimado en pesos]
3. [Accion especifica + cliente o cuenta nombrada + impacto estimado en pesos]

**Alerta que no puede esperar**: [La situacion mas urgente con el riesgo concreto si no se actua]

Reglas:
- Se especifico con nombres de clientes y cifras reales del CONTEXTO ACTUAL
- No uses frases genericas como "mejorar el servicio" o "fortalecer relaciones"
- Cada accion debe ser ejecutable esta semana
- Si no hay datos suficientes para algo, dilo directamente"""

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


def responder_pregunta(pregunta: str, historial: list = None) -> str:
    """
    Responde una pregunta del director comercial en el contexto de TBS.

    pregunta: texto libre del usuario
    historial: lista de dicts {"rol": "user"|"assistant", "contenido": "..."}
    """
    if not API_KEY:
        return "API key de OpenAI no configurada."

    knowledge_base = _leer_knowledge_base()

    try:
        snapshot = _obtener_snapshot_kpis()
        contexto_datos = json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        contexto_datos = f"Error obteniendo datos: {e}"

    system_prompt = f"""Eres el analista comercial de TBS DESTILADOS en Cartagena.
Respondes preguntas del director comercial sobre el negocio.

═══════════════════════════════════════════════════════════
CONTEXTO ESTRATEGICO (estable — cambia con decisiones)
═══════════════════════════════════════════════════════════
{knowledge_base}

═══════════════════════════════════════════════════════════
CONTEXTO ACTUAL — datos en vivo desde Odoo/SQLite, NO parte del contexto estrategico
═══════════════════════════════════════════════════════════
{contexto_datos}

Instrucciones:
- Responde en espanol, de forma directa y ejecutiva
- Usa los datos reales del CONTEXTO ACTUAL cuando apliquen
- Si la pregunta esta fuera del contexto de TBS, redirige amablemente
- Maximo 150 palabras por respuesta
- Si no tienes el dato exacto, dilo y sugiere como conseguirlo"""

    messages = [{"role": "system", "content": system_prompt}]
    if historial:
        for h in historial[-6:]:  # maximo 6 turnos
            rol = h.get("rol", "user")
            # Normalizar roles que pueda enviar el frontend
            if rol not in ("user", "assistant"):
                rol = "assistant" if rol in ("supervisor", "bot", "analista") else "user"
            messages.append({"role": rol, "content": h["contenido"]})
    messages.append({"role": "user", "content": pregunta})

    client = OpenAI(api_key=API_KEY)
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=300,
        messages=messages,
    )
    return response.choices[0].message.content


def guardar_insight_en_db(texto: str):
    """
    Guarda el insight generado en la tabla llm_insights.
    """
    engine = create_engine(config.DB_URL, echo=False)
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO llm_insights (fecha, tipo, contenido, modelo)
            VALUES (:fecha, 'diario', :contenido, :modelo)
        """), {
            "fecha": datetime.now().isoformat(),
            "contenido": texto,
            "modelo": MODEL,
        })
        conn.commit()
    logger.info("Insight guardado en base de datos")
