"""
Integración con Claude API para el dashboard TBS.

Dos funciones principales:
- generar_insight_diario(): analiza el snapshot de KPIs y genera 3 recomendaciones
- responder_pregunta(): responde preguntas del director comercial en contexto

Usar desde scripts/generar_insight.py (cron diario)
y desde api/main.py (endpoint /api/chat en tiempo real).
"""
import json
import logging
from datetime import datetime
from pathlib import Path
import anthropic
from sqlalchemy import create_engine, text
from config import config

logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_PATH = (
    Path(__file__).parent / "knowledge_base" / "estrategia.md"
)


def _leer_knowledge_base() -> str:
    with open(KNOWLEDGE_BASE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _obtener_snapshot_kpis() -> dict:
    """
    Extrae el estado actual del negocio desde las vistas analíticas.
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

        # Estado de los 9 hoteles top
        hoteles = conn.execute(text("""
            SELECT nombre, gmv_mes_actual, variacion_pct,
                   dias_sin_pedido, estado
            FROM v_clientes_top
            WHERE es_hotel_top = 1 OR ranking <= 9
            LIMIT 9
        """)).mappings().fetchall()

        # Vendedores
        vendedores = conn.execute(text("""
            SELECT nombre, gmv_mes_actual, clientes_unicos, estado
            FROM v_vendedores
            ORDER BY gmv_mes_actual DESC
        """)).mappings().fetchall()

        # Tendencia últimos 3 meses
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
        "hoteles_top": [dict(h) for h in hoteles],
        "vendedores": [dict(v) for v in vendedores],
        "tendencia_reciente": [dict(t) for t in tendencia],
    }


def generar_insight_diario() -> str:
    """
    Genera el insight estratégico diario.
    Llama a Claude con el snapshot de KPIs + knowledge base.
    Retorna el texto del insight.
    """
    if not config.ANTHROPIC_API_KEY:
        return "⚠️ API key de Anthropic no configurada. Agrega ANTHROPIC_API_KEY en .env"

    knowledge_base = _leer_knowledge_base()
    snapshot = _obtener_snapshot_kpis()

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    prompt = f"""Eres el asesor comercial senior de TBS DESTILADOS, distribuidora
de licores premium en Cartagena. Conoces profundamente el negocio.

═══════════════════════════════════════════════════════════
BASE DE CONOCIMIENTO ESTRATÉGICA (estable — cambia con decisiones)
═══════════════════════════════════════════════════════════
{knowledge_base}

═══════════════════════════════════════════════════════════
CONTEXTO ACTUAL ({snapshot['fecha_analisis']}) — datos en vivo desde Odoo/SQLite
NO es parte de la base de conocimiento. Usa estos datos para nombres y cifras.
═══════════════════════════════════════════════════════════
{json.dumps(snapshot, ensure_ascii=False, indent=2)}

Analiza los datos y genera un informe ejecutivo BREVE con exactamente este formato:

**Estado del mes**: [1 frase que resume si el negocio va bien, regular o mal y por qué]

**Movimiento prioritario esta semana**:
1. [Acción específica + cliente o cuenta nombrada + impacto estimado en pesos]
2. [Acción específica + cliente o cuenta nombrada + impacto estimado en pesos]
3. [Acción específica + cliente o cuenta nombrada + impacto estimado en pesos]

**Alerta que no puede esperar**: [La situación más urgente con el riesgo concreto si no se actúa]

Reglas:
- Sé específico con nombres de clientes y cifras reales del snapshot
- No uses frases genéricas como "mejorar el servicio" o "fortalecer relaciones"
- Cada acción debe ser ejecutable esta semana
- Si no hay datos suficientes para algo, dilo directamente"""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text


def responder_pregunta(pregunta: str, historial: list = None) -> str:
    """
    Responde una pregunta del director comercial en el contexto de TBS.

    pregunta: texto libre del usuario
    historial: lista de dicts {"rol": "user"|"assistant", "contenido": "..."}
    """
    if not config.ANTHROPIC_API_KEY:
        return "API key de Anthropic no configurada."

    knowledge_base = _leer_knowledge_base()

    try:
        snapshot = _obtener_snapshot_kpis()
        contexto_datos = json.dumps(snapshot, ensure_ascii=False, indent=2)
    except Exception as e:
        contexto_datos = f"Error obteniendo datos: {e}"

    system_prompt = f"""Eres el analista comercial de TBS DESTILADOS en Cartagena.
Respondes preguntas del director comercial sobre el negocio.

═══════════════════════════════════════════════════════════
CONTEXTO ESTRATÉGICO (estable — cambia con decisiones)
═══════════════════════════════════════════════════════════
{knowledge_base}

═══════════════════════════════════════════════════════════
CONTEXTO ACTUAL — datos en vivo desde Odoo/SQLite, NO parte del contexto estratégico
═══════════════════════════════════════════════════════════
{contexto_datos}

Instrucciones:
- Responde en español, de forma directa y ejecutiva
- Usa los datos reales del CONTEXTO ACTUAL cuando apliquen
- Si la pregunta está fuera del contexto de TBS, redirige amablemente
- Máximo 150 palabras por respuesta
- Si no tienes el dato exacto, dilo y sugiere cómo conseguirlo"""

    messages = []
    if historial:
        for h in historial[-6:]:  # máximo 6 turnos de historial
            messages.append({
                "role": h["rol"],
                "content": h["contenido"]
            })
    messages.append({"role": "user", "content": pregunta})

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=300,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text


def guardar_insight_en_db(texto: str):
    """
    Guarda el insight generado en la tabla llm_insights.
    """
    engine = create_engine(config.DB_URL, echo=False)
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO llm_insights (fecha, tipo, contenido, modelo)
            VALUES (:fecha, 'diario', :contenido, 'claude-sonnet-4-5')
        """), {
            "fecha": datetime.now().isoformat(),
            "contenido": texto,
        })
        conn.commit()
    logger.info("Insight guardado en base de datos")
