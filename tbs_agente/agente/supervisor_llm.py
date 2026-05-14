"""
Agente supervisor LLM de TBS.

Genera tres tipos de output:
1. Briefing diario para el director (resumen del equipo)
2. Mensajes individuales por vendedor (listos para WhatsApp)
3. Respuestas a preguntas del director sobre el equipo
"""
import json
from pathlib import Path
import anthropic
from config import config
from agente.monitor import (
    estado_equipo, cuentas_en_riesgo,
    profundidad_portafolio, compromisos_pendientes
)

KB_PATH = Path(__file__).parent / "knowledge_base" / "supervisor.md"
MODEL = "claude-sonnet-4-5"


def _kb() -> str:
    with open(KB_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _snapshot() -> dict:
    """Construye el snapshot completo del estado del equipo."""
    equipo  = estado_equipo()
    riesgo  = cuentas_en_riesgo(dias=14)
    portafolio = profundidad_portafolio(top_n=15)
    compromisos = compromisos_pendientes()

    return {
        "equipo": equipo,
        "cuentas_en_riesgo": riesgo[:10],
        "portafolio_bajo": [p for p in portafolio if p["cobertura_pct"] < 60][:8],
        "compromisos_vencidos": [c for c in compromisos if c["dias_restantes"] < 0],
        "compromisos_hoy": [c for c in compromisos if 0 <= c["dias_restantes"] <= 1],
    }


def briefing_diario() -> str:
    """
    Genera el briefing diario del equipo para el director.
    Llama a Claude y retorna el texto del análisis.
    """
    if not config.ANTHROPIC_API_KEY:
        return "⚠️ ANTHROPIC_API_KEY no configurada en .env"

    kb = _kb()
    snapshot = _snapshot()
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    prompt = f"""BASE DE CONOCIMIENTO:
{kb}

ESTADO ACTUAL DEL EQUIPO:
{json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)}

Genera el briefing diario del supervisor. Formato exacto:

**Estado del equipo hoy**: [1 frase sobre si el equipo va bien, regular o mal]

**🔴 Intervención inmediata** (máximo 2):
- [Vendedor | Cliente/situación | Acción concreta | Impacto si no se actúa]

**🟡 Atención esta semana** (máximo 3):
- [Vendedor | Situación | Acción sugerida]

**✅ Lo que va bien**:
- [1-2 cosas positivas del equipo para reforzar]

**Número del día**: [La métrica más importante a mover hoy y cuánto]

Reglas:
- Menciona nombres reales de vendedores y clientes
- Usa cifras concretas del snapshot
- Sin frases genéricas"""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=700,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.content[0].text


def mensajes_whatsapp() -> dict:
    """
    Genera mensajes de WhatsApp listos para enviar a cada vendedor.
    Retorna dict: {nombre_vendedor: texto_mensaje}
    """
    if not config.ANTHROPIC_API_KEY:
        return {}

    kb = _kb()
    snapshot = _snapshot()
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    vendedores = [v for v in snapshot["equipo"]["vendedores"]
                  if v["cuota_gmv"] > 0 and v["nombre"] != "VACANTE 87"]

    mensajes = {}
    for v in vendedores:
        # Cuentas en riesgo asignadas a este vendedor
        mis_riesgos = [c for c in snapshot["cuentas_en_riesgo"]
                       if c.get("vendedor") == v["nombre"]]

        prompt = f"""BASE DE CONOCIMIENTO:
{kb}

DATOS DE {v['nombre']}:
{json.dumps(v, ensure_ascii=False, default=str)}

CUENTAS EN RIESGO ASIGNADAS:
{json.dumps(mis_riesgos[:3], ensure_ascii=False, default=str)}

Escribe el mensaje de WhatsApp para {v['nombre'].split()[0]} del director comercial.

Formato: mensaje directo, sin saludo formal, máximo 5 líneas.
Debe incluir: 1 reconocimiento O 1 alerta, 1 acción concreta con cliente nombrado,
1 meta específica del día.

Solo el mensaje, sin explicaciones."""

        resp = client.messages.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        mensajes[v["nombre"]] = resp.content[0].text

    return mensajes


def responder_director(pregunta: str, historial: list = None) -> str:
    """
    Responde preguntas del director sobre el equipo de ventas.
    """
    if not config.ANTHROPIC_API_KEY:
        return "API key no configurada."

    kb = _kb()
    snapshot = _snapshot()
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    system = f"""Eres el supervisor de ventas de TBS Cartagena.
Respondes preguntas del director comercial sobre el equipo.

Base de conocimiento:
{kb}

Estado actual del equipo:
{json.dumps(snapshot, ensure_ascii=False, default=str)}

Responde en español, directo, máximo 120 palabras.
Usa cifras reales del estado del equipo cuando aplique."""

    msgs = []
    if historial:
        for h in historial[-4:]:
            msgs.append({"role": h["rol"], "content": h["contenido"]})
    msgs.append({"role": "user", "content": pregunta})

    resp = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=system,
        messages=msgs,
    )
    return resp.content[0].text


# ════════════════════════════════════════════════════════
# ANÁLISIS ESTRATÉGICO (diferente al briefing operativo)
# ════════════════════════════════════════════════════════

def analisis_estrategico() -> str:
    """
    Análisis del avance del plan estratégico TBS.
    Diferencia clave vs briefing_diario:
    - briefing_diario: estado operativo HOY (visitas, cuota del mes)
    - analisis_estrategico: avance del PLAN a 3-6 meses (qué funciona)

    Retorna un análisis estructurado con:
    - Estado de cada objetivo estratégico
    - Qué está funcionando vs qué no
    - Ajustes recomendados al plan
    - Proyección de si se alcanzarán las metas
    """
    if not config.ANTHROPIC_API_KEY:
        return "⚠️ ANTHROPIC_API_KEY no configurada en .env"

    from agente.estrategia import snapshot_estrategico
    from pathlib import Path

    # Cargar ambas knowledge bases
    plan_path = Path(__file__).parent / "knowledge_base" / "plan_estrategico.md"
    supervisor_path = Path(__file__).parent / "knowledge_base" / "supervisor.md"

    plan_kb = plan_path.read_text(encoding="utf-8")
    supervisor_kb = supervisor_path.read_text(encoding="utf-8")

    snap = snapshot_estrategico()
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    prompt = f"""PLAN ESTRATÉGICO TBS:
{plan_kb}

CONTEXTO DEL EQUIPO:
{supervisor_kb}

ESTADO ACTUAL DE LOS 6 OBJETIVOS:
{json.dumps(snap, ensure_ascii=False, indent=2, default=str)}

Genera el análisis estratégico mensual. Formato exacto:

**Resumen ejecutivo**: [2 frases: cómo va el plan en general y cuál es el mayor riesgo]

**Estado de cada objetivo**:

1. Densificación hoteles: [estado] — [qué está pasando realmente, con nombres de hoteles específicos]
2. Vacante 87: [estado] — [cuántas cuentas recuperadas, qué riesgo hay]
3. Marcas estratégicas: [estado] — [qué marcas tienen gaps en qué cuentas]
4. Cartera: [estado] — [tendencia y si hay riesgo sistémico]
5. Clientes nuevos: [estado] — [ritmo actual vs meta]
6. Mix premium: [estado] — [tendencia y implicación para el margen]

**Lo que está funcionando bien** (máximo 2 puntos):
- [específico, con datos]

**Lo que NO está funcionando** (máximo 3 puntos):
- [específico, con hipótesis de por qué]

**Ajuste recomendado al plan**:
[1 cambio concreto en la estrategia o en el enfoque — no en la operación diaria]

**Proyección a 90 días**:
[Si continuamos así, ¿llegamos a EBITDA positivo o no? ¿Qué cambiaría la trayectoria?]

Reglas:
- Usa cifras reales del snapshot
- Menciona hoteles, marcas y situaciones por nombre
- Distingue entre problema de ejecución y problema de estrategia
- No repitas lo del briefing operativo
- Sé directo sobre qué NO está funcionando aunque sea incómodo"""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=900,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.content[0].text


def responder_sobre_estrategia(pregunta: str, historial: list = None) -> str:
    """
    Responde preguntas estratégicas del director.
    A diferencia de responder_director (operativo),
    este tiene acceso al snapshot estratégico completo.
    """
    if not config.ANTHROPIC_API_KEY:
        return "API key no configurada."

    from agente.estrategia import snapshot_estrategico
    from pathlib import Path

    plan_path = Path(__file__).parent / "knowledge_base" / "plan_estrategico.md"
    plan_kb = plan_path.read_text(encoding="utf-8")
    snap = snapshot_estrategico()

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    system = f"""Eres el analista estratégico de TBS Cartagena.
Tienes acceso al plan estratégico y al estado actual de los 6 objetivos.

Plan estratégico:
{plan_kb}

Estado actual:
{json.dumps(snap, ensure_ascii=False, default=str)}

Responde con perspectiva estratégica (no operativa).
Máximo 150 palabras. Directo y con datos cuando aplique."""

    msgs = []
    if historial:
        for h in historial[-4:]:
            msgs.append({"role": h["rol"], "content": h["contenido"]})
    msgs.append({"role": "user", "content": pregunta})

    resp = client.messages.create(
        model=MODEL,
        max_tokens=400,
        system=system,
        messages=msgs,
    )
    return resp.content[0].text
