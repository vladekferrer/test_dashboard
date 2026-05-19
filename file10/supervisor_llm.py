"""
Agente supervisor LLM de TBS (Arquitectura de 3 Capas).

Genera tres tipos de output:
1. Briefing diario para el director (resumen del equipo)
2. Mensajes individuales por vendedor (listos para WhatsApp)
3. Respuestas a preguntas del director sobre el equipo
"""
import json
import os
from datetime import datetime
from pathlib import Path
from openai import OpenAI
from config import config
from agente.monitor import (
    estado_equipo, cuentas_en_riesgo,
    profundidad_portafolio, compromisos_pendientes
)

KB_PATH = Path(__file__).parent / "knowledge_base" / "supervisor.md"
PLAN_PATH = Path(__file__).parent / "knowledge_base" / "plan_estrategico.md"
MODEL = "gpt-4o" 

API_KEY = getattr(config, 'OPENAI_API_KEY', os.getenv('OPENAI_API_KEY'))


def _kb_supervisor() -> str:
    with open(KB_PATH, "r", encoding="utf-8") as f:
        return f.read()

def _kb_plan() -> str:
    with open(PLAN_PATH, "r", encoding="utf-8") as f:
        return f.read()

def _snapshot() -> dict:
    """Construye el snapshot completo del estado del equipo estructurado por vendedor."""
    equipo  = estado_equipo()
    riesgo  = cuentas_en_riesgo(dias=14)
    portafolio = profundidad_portafolio(top_n=15)
    compromisos = compromisos_pendientes()

    # EL ANTÍDOTO CONTRA LAS ALUCINACIONES:
    alertas_por_vendedor = {}
    for v in equipo.get("vendedores", []):
        nombre = v["nombre"]
        if "VACANTE" in nombre.upper() or "OFICINA" in nombre.upper() or nombre == "Sin asignar":
            continue
            
        alertas_por_vendedor[nombre] = {
            "estado_mensual": v,
            "clientes_en_riesgo": [c for c in riesgo if nombre in (c.get("vendedor") or "")][:5],
            "portafolio_bajo": [p for p in portafolio if nombre in (p.get("vendedor") or "") and p.get("cobertura_pct", 100) < 60][:5],
            "compromisos": [c for c in compromisos if c.get("vendedor") == nombre]
        }

    return {
        "totales_equipo": equipo.get("totales", {}),
        "detalle_por_vendedor": alertas_por_vendedor
    }

def _generar_contexto_vivo(snapshot: dict) -> str:
    """Genera la capa dinámica con los datos exactos del momento."""
    fecha = datetime.now().strftime('%Y-%m-%d %H:%M')
    return f"--- CONTEXTO ACTUAL (Generado el {fecha}) ---\n" + json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)


def briefing_diario() -> str:
    if not API_KEY:
        return "⚠️ OPENAI_API_KEY no configurada"

    estrategia = _kb_plan()
    supervisor = _kb_supervisor()
    snapshot = _snapshot()
    contexto_vivo = _generar_contexto_vivo(snapshot)
    client = OpenAI(api_key=API_KEY)

    prompt = f"""ESTRATEGIA FIJA:
{estrategia}

PRINCIPIOS OPERATIVOS:
{supervisor}

{contexto_vivo}

Genera el briefing diario del supervisor. Formato exacto:

**Estado del equipo hoy**: [1 frase sobre si el equipo va bien, regular o mal]

**🔴 Intervención inmediata** (máximo 2):
- [Vendedor | Cliente/situación | Acción concreta | Impacto si no se actúa]

**🟡 Atención esta semana** (máximo 3):
- [Vendedor | Situación | Acción sugerida]

**✅ Lo que va bien**:
- [1-2 cosas positivas del equipo para reforzar]

**Número del día**: [La métrica más importante a mover hoy y cuánto. Formatealo como dinero, ej: $17.1M]

Reglas:
- REGLA DE ORO: Los clientes listados bajo un vendedor en el CONTEXTO ACTUAL le pertenecen ÚNICA Y EXCLUSIVAMENTE a ese vendedor. JAMÁS asocies un cliente de un vendedor a otro distinto.
- CLASIFICACIÓN DE INACTIVIDAD: Cada cliente en riesgo tiene un campo `tipo_inactividad` que YA viene clasificado en los datos. RESPÉTALO al pie de la letra:
  * CARTERA → el cliente tiene deuda pendiente. La inactividad es por bloqueo de cobro, NO por falta de gestión comercial. La acción correcta es verificar estado de pago, esperar soporte, o escalar cobro. NUNCA recomiendes "visitar con propuesta de productos" a un cliente tipo CARTERA.
  * DATOS → el cliente lleva mucho tiempo sin pedido y NO tiene deuda. Probablemente cambió de razón social, cerró, o es un duplicado en Odoo. La acción correcta es depurar el dato, NO visitar ni proponer productos.
  * COMERCIAL → inactividad genuina de ventas. AQUÍ SÍ aplica visitar con propuesta de categorías faltantes del portafolio.
  Si un cliente es tipo CARTERA o DATOS, NO lo pongas en intervención inmediata como si fuera oportunidad de venta. Ponlo como lo que es.
- Menciona nombres reales de vendedores y clientes.
- Usa cifras concretas del contexto actual.
- Sin frases genéricas."""

    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=700,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.choices[0].message.content


def mensajes_whatsapp() -> dict:
    if not API_KEY:
        return {}

    supervisor = _kb_supervisor()
    snapshot = _snapshot()
    client = OpenAI(api_key=API_KEY)

    mensajes = {}
    
    for nombre_vendedor, datos in snapshot.get("detalle_por_vendedor", {}).items():
        if datos["estado_mensual"]["cuota_gmv"] <= 0:
            continue

        fecha = datetime.now().strftime('%Y-%m-%d %H:%M')
        contexto_vendedor = f"--- DATOS EN VIVO DE {nombre_vendedor} (Generado el {fecha}) ---\n" + json.dumps(datos, ensure_ascii=False, indent=2, default=str)

        prompt = f"""PRINCIPIOS OPERATIVOS:
{supervisor}

{contexto_vendedor}

Escribe el mensaje de WhatsApp para {nombre_vendedor.split()[0]} del director comercial.

Formato: mensaje directo, sin saludo formal, máximo 5 líneas.
Debe incluir: 1 reconocimiento O 1 alerta, 1 acción concreta con cliente nombrado,
1 meta específica del día.

Regla de oro:
SOLO exige acciones sobre los clientes que aparecen ESTRICTAMENTE en el bloque de DATOS EN VIVO. 
ESTÁ TOTALMENTE PROHIBIDO usar nombres de clientes que aparezcan en los PRINCIPIOS OPERATIVOS como ejemplos. Si el vendedor no tiene clientes en riesgo en sus datos, decile que busque clientes nuevos, pero NO INVENTES CLIENTES ni recicles los del manual.

Clasificación de inactividad:
Si un cliente en riesgo tiene tipo_inactividad = CARTERA, la acción es cobro (verificar pago, esperar soporte), NO proponer productos.
Si tiene tipo_inactividad = DATOS, la acción es pedir que se depure en Odoo (cambio de razón social, cierre, duplicado), NO visitar.
Solo si tipo_inactividad = COMERCIAL, recomienda visitar con propuesta de categorías.
Solo el mensaje, sin explicaciones."""

        resp = client.chat.completions.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        mensajes[nombre_vendedor] = resp.choices[0].message.content

    return mensajes


def responder_director(pregunta: str, historial: list = None) -> str:
    if not API_KEY:
        return "API key no configurada."

    estrategia = _kb_plan()
    supervisor = _kb_supervisor()
    snapshot = _snapshot()
    contexto_vivo = _generar_contexto_vivo(snapshot)
    client = OpenAI(api_key=API_KEY)

    system = f"""Eres el supervisor de ventas de TBS Cartagena.
Respondes preguntas del director comercial sobre el equipo.

Estrategia Fija:
{estrategia}

Principios Operativos:
{supervisor}

{contexto_vivo}

Responde en español, directo, máximo 120 palabras.
Usa cifras reales del contexto actual cuando aplique.
Respeta a rajatabla quién es el asesor actual de cada cuenta."""

    msgs = [{"role": "system", "content": system}]
    if historial:
        for h in historial[-4:]:
            rol_openai = "assistant" if h["rol"] == "supervisor" else "user"
            msgs.append({"role": rol_openai, "content": h["contenido"]})
    msgs.append({"role": "user", "content": pregunta})

    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=300,
        messages=msgs,
    )
    return resp.choices[0].message.content


# ════════════════════════════════════════════════════════
# ANÁLISIS ESTRATÉGICO
# ════════════════════════════════════════════════════════

def analisis_estrategico() -> str:
    if not API_KEY:
        return "⚠️ OPENAI_API_KEY no configurada"

    from agente.estrategia import snapshot_estrategico
    estrategia = _kb_plan()
    supervisor = _kb_supervisor()
    snap = snapshot_estrategico()
    fecha = datetime.now().strftime('%Y-%m-%d %H:%M')
    contexto_vivo = f"--- ESTADO ACTUAL DE LOS 6 OBJETIVOS (Generado el {fecha}) ---\n" + json.dumps(snap, ensure_ascii=False, indent=2, default=str)
    
    client = OpenAI(api_key=API_KEY)

    prompt = f"""PLAN ESTRATÉGICO TBS:
{estrategia}

PRINCIPIOS OPERATIVOS:
{supervisor}

{contexto_vivo}

Genera el análisis estratégico mensual. Formato exacto:

**Resumen ejecutivo**: [2 frases]

**Estado de cada objetivo**:
1. Densificación hoteles: [estado] — [qué está pasando realmente]
2. Vacante 87: [estado] — [riesgo]
3. Marcas estratégicas: [estado] — [gaps]
4. Cartera: [estado] — [tendencia]
5. Clientes nuevos: [estado] — [ritmo vs meta]
6. Mix premium: [estado] — [implicación margen]

**Lo que está funcionando bien** (máximo 2 puntos):
- [específico]

**Lo que NO está funcionando** (máximo 3 puntos):
- [específico]

**Ajuste recomendado al plan**:
[1 cambio concreto]

**Proyección a 90 días**:
[Proyección clara]

Reglas:
- Usa cifras reales del contexto actual.
- No inventes dueños de clientes."""

    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=900,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.choices[0].message.content


def responder_sobre_estrategia(pregunta: str, historial: list = None) -> str:
    if not API_KEY:
        return "API key no configurada."

    from agente.estrategia import snapshot_estrategico
    estrategia = _kb_plan()
    snap = snapshot_estrategico()
    fecha = datetime.now().strftime('%Y-%m-%d %H:%M')
    contexto_vivo = f"--- ESTADO ACTUAL DE LOS 6 OBJETIVOS (Generado el {fecha}) ---\n" + json.dumps(snap, ensure_ascii=False, indent=2, default=str)

    client = OpenAI(api_key=API_KEY)

    system = f"""Eres el analista estratégico.
Plan estratégico:
{estrategia}

{contexto_vivo}

Responde con perspectiva estratégica (no operativa).
Máximo 150 palabras."""

    msgs = [{"role": "system", "content": system}]
    if historial:
        for h in historial[-4:]:
            rol_openai = "assistant" if h["rol"] == "supervisor" else "user"
            msgs.append({"role": rol_openai, "content": h["contenido"]})
    msgs.append({"role": "user", "content": pregunta})

    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=400,
        messages=msgs,
    )
    return resp.choices[0].message.content