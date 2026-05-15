"""
Agente supervisor LLM de TBS.

Arquitectura de prompt en tres capas
------------------------------------
El prompt que recibe Claude se ensambla SIEMPRE con tres capas separadas
por su tasa de cambio, para que la informacion volatil nunca quede congelada
dentro de un archivo estatico:

  Capa 1 - ESTRATEGIA (estatica, cambia con decisiones)
     knowledge_base/plan_estrategico.md
     knowledge_base/supervisor.md  (principios operativos)

  Capa 3 - CONTEXTO ACTUAL (dinamica, se genera en cada llamada)
     _contexto_vivo_operativo()   -> equipo, cuentas, alertas de hoy
     _contexto_vivo_estrategico() -> avance real de los 6 objetivos
     Sale de cuotas.py + la base de datos SQLite, con fecha y hora.

Regla de oro: si un dato puede cambiar sin una decision estrategica
(una cuota, quien atiende una cuenta, el GMV del mes, cuantas categorias
tiene un hotel), NO va en los .md. Va en el contexto vivo.

Salidas que produce este modulo:
1. briefing_diario()        - briefing operativo del equipo para el director
2. mensajes_whatsapp()      - mensajes individuales por vendedor
3. responder_director()     - respuestas a preguntas operativas
4. analisis_estrategico()   - analisis del avance del plan a 3-6 meses
5. responder_sobre_estrategia() - respuestas a preguntas estrategicas
"""
import json
from datetime import datetime
from pathlib import Path
import anthropic
from config import config
from agente.monitor import (
    estado_equipo, cuentas_en_riesgo,
    profundidad_portafolio, compromisos_pendientes,
)

KB_DIR = Path(__file__).parent / "knowledge_base"
MODEL = "claude-sonnet-4-5"


# ════════════════════════════════════════════════════════
# CAPA 1 - LECTURA DE KNOWLEDGE BASE ESTATICA
# ════════════════════════════════════════════════════════

def _leer_kb(nombre: str) -> str:
    """Lee un archivo de knowledge base. nombre sin extension."""
    ruta = KB_DIR / f"{nombre}.md"
    if not ruta.exists():
        return f"[knowledge base '{nombre}' no encontrada]"
    return ruta.read_text(encoding="utf-8")


# ════════════════════════════════════════════════════════
# SNAPSHOTS CRUDOS (datos desde SQLite)
# ════════════════════════════════════════════════════════

def _snapshot() -> dict:
    """Snapshot operativo crudo del estado del equipo."""
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


# ════════════════════════════════════════════════════════
# CAPA 3 - CONTEXTO VIVO OPERATIVO
# Convierte el snapshot crudo en texto legible y fechado.
# Esto es lo que ANTES estaba (desactualizado) dentro de supervisor.md
# ════════════════════════════════════════════════════════

def _contexto_vivo_operativo(snapshot: dict) -> str:
    """
    Genera la seccion de contexto actual del equipo en texto legible.
    Incluye sello de fecha para que la antiguedad del dato sea evidente.
    """
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
    L = [f"_(Generado {ahora} — datos en vivo desde Odoo/SQLite)_", ""]

    # --- Equipo: cada vendedor con su cuota y avance real ---
    eq = snapshot.get("equipo", {})
    vendedores = eq.get("vendedores", [])
    totales = eq.get("totales", {})

    L.append("### Equipo de ventas — estado del mes en curso")
    if not vendedores:
        L.append("- (sin datos de ventas este mes)")
    for v in vendedores:
        nombre = v["nombre"]
        # Vacante / cuentas sin asignar se marcan explicito
        if v["cuota_gmv"] == 0:
            L.append(
                f"- **{nombre}**: cuentas SIN VENDEDOR asignado. "
                f"{v['cuentas_activas']} cuentas con movimiento, "
                f"GMV ${v['gmv_mes']:,.0f}. Estas cuentas estan huerfanas "
                f"y son la urgencia de reasignacion."
            )
            continue
        L.append(
            f"- **{nombre}**: GMV ${v['gmv_mes']:,.0f} de "
            f"${v['cuota_gmv']:,.0f} ({v['avance_gmv_pct']}% de cuota) · "
            f"{v['cuentas_activas']}/{v['cuota_cuentas']} cuentas activas · "
            f"{v['clientes_nuevos']}/{v['cuota_nuevos']} clientes nuevos · "
            f"cartera vencida {v['pct_cartera']}% (max {v['cuota_cartera']}%) · "
            f"semaforo {v['semaforo'].upper()}"
        )

    if totales:
        L.append(
            f"- **Equipo total**: GMV ${totales.get('gmv_mes',0):,.0f} de "
            f"${totales.get('cuota_gmv',0):,.0f} · "
            f"{totales.get('cuentas',0)} cuentas activas · "
            f"{totales.get('nuevos',0)} clientes nuevos"
        )

    # --- Concentracion: lo detecta el dato, no el .md ---
    activos = [v for v in vendedores if v["cuota_gmv"] > 0 and v["gmv_mes"] > 0]
    gmv_equipo = sum(v["gmv_mes"] for v in activos)
    if gmv_equipo > 0:
        lider = max(activos, key=lambda x: x["gmv_mes"])
        pct_lider = lider["gmv_mes"] / gmv_equipo * 100
        if pct_lider >= 35:
            L.append(
                f"- ⚠️ **Concentracion**: {lider['nombre']} representa "
                f"{pct_lider:.0f}% del GMV del equipo este mes. "
                f"Riesgo estructural — ver principio de concentracion."
            )

    # --- Cuentas en riesgo ---
    riesgo = snapshot.get("cuentas_en_riesgo", [])
    L.append("")
    L.append("### Cuentas top sin pedido reciente (>14 dias)")
    if not riesgo:
        L.append("- (ninguna cuenta top en riesgo ahora mismo)")
    for c in riesgo[:8]:
        L.append(
            f"- **{c['cliente']}** — {c['dias_inactivo']} dias sin pedido · "
            f"vendedor: {c['vendedor']} · "
            f"GMV mensual promedio ${c.get('gmv_mensual_prom',0):,.0f}"
        )

    # --- Portafolio bajo ---
    portafolio = snapshot.get("portafolio_bajo", [])
    if portafolio:
        L.append("")
        L.append("### Cuentas top con portafolio poco profundo (<60% categorias core)")
        for p in portafolio:
            faltan = ", ".join(p.get("categorias_faltantes", [])) or "—"
            L.append(
                f"- **{p['cliente']}** — {p['n_categorias']}/{p['n_core']} "
                f"categorias core · vendedor: {p['vendedor']} · "
                f"le falta: {faltan}"
            )

    # --- Compromisos ---
    venc = snapshot.get("compromisos_vencidos", [])
    hoy = snapshot.get("compromisos_hoy", [])
    if venc or hoy:
        L.append("")
        L.append("### Compromisos del equipo")
        for c in venc:
            L.append(
                f"- 🔴 VENCIDO ({abs(c['dias_restantes'])}d): {c['vendedor']} — "
                f"{c['descripcion']} ({c.get('cliente','')})"
            )
        for c in hoy:
            L.append(
                f"- 🟡 VENCE HOY: {c['vendedor']} — "
                f"{c['descripcion']} ({c.get('cliente','')})"
            )

    return "\n".join(L)


# ════════════════════════════════════════════════════════
# CAPA 3 - CONTEXTO VIVO ESTRATEGICO
# Convierte el snapshot de los 6 objetivos en texto legible y fechado.
# ════════════════════════════════════════════════════════

def _contexto_vivo_estrategico(snap: dict) -> str:
    """
    Genera la seccion de contexto actual del plan en texto legible.
    snap viene de agente.estrategia.snapshot_estrategico().
    """
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
    L = [f"_(Generado {ahora} — avance real desde Odoo/SQLite)_", ""]

    # El detalle de cada objetivo se entrega como JSON estructurado
    # porque el LLM lo razona bien y los objetivos tienen formas distintas.
    # Lo importante es que esta CLARAMENTE marcado como dato en vivo y fechado.
    L.append("### Avance actual de los 6 objetivos del plan")
    L.append("```json")
    L.append(json.dumps(snap, ensure_ascii=False, indent=2, default=str))
    L.append("```")

    return "\n".join(L)


# ════════════════════════════════════════════════════════
# ENSAMBLADO DE PROMPTS - LAS TRES CAPAS JUNTAS
# ════════════════════════════════════════════════════════

def _sistema_operativo(snapshot: dict) -> str:
    """System prompt operativo: principios estaticos + contexto vivo."""
    principios = _leer_kb("supervisor")
    contexto = _contexto_vivo_operativo(snapshot)
    return f"""{principios}

═══════════════════════════════════════════════════════════
CONTEXTO ACTUAL — datos en vivo, NO son parte de los principios
═══════════════════════════════════════════════════════════
{contexto}
"""


def _sistema_estrategico(snap: dict, incluir_supervisor: bool = False) -> str:
    """System prompt estrategico: plan estatico + contexto vivo."""
    plan = _leer_kb("plan_estrategico")
    bloque_principios = ""
    if incluir_supervisor:
        bloque_principios = "\n\n## PRINCIPIOS OPERATIVOS\n" + _leer_kb("supervisor")
    contexto = _contexto_vivo_estrategico(snap)
    return f"""{plan}{bloque_principios}

═══════════════════════════════════════════════════════════
CONTEXTO ACTUAL — avance real del plan, NO es parte del plan escrito
═══════════════════════════════════════════════════════════
{contexto}
"""


# ════════════════════════════════════════════════════════
# 1. BRIEFING DIARIO OPERATIVO
# ════════════════════════════════════════════════════════

def briefing_diario() -> str:
    """Briefing diario del equipo para el director."""
    if not config.ANTHROPIC_API_KEY:
        return "⚠️ ANTHROPIC_API_KEY no configurada en .env"

    snapshot = _snapshot()
    system = _sistema_operativo(snapshot)
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    prompt = """Genera el briefing diario del supervisor de ventas.

Usa EXCLUSIVAMENTE los datos de la seccion CONTEXTO ACTUAL para nombres,
cifras y cuentas. Los principios de arriba te dicen como interpretar, no
que datos usar.

Formato exacto:

**Estado del equipo hoy**: [1 frase sobre si el equipo va bien, regular o mal]

**🔴 Intervencion inmediata** (maximo 2):
- [Vendedor | Cliente/situacion | Accion concreta | Impacto si no se actua]

**🟡 Atencion esta semana** (maximo 3):
- [Vendedor | Situacion | Accion sugerida]

**✅ Lo que va bien**:
- [1-2 cosas positivas del equipo para reforzar]

**Numero del dia**: [La metrica mas importante a mover hoy y cuanto]

Reglas:
- Menciona nombres reales de vendedores y clientes del contexto actual
- Usa cifras concretas del contexto actual
- Sin frases genericas"""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=700,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


# ════════════════════════════════════════════════════════
# 2. MENSAJES INDIVIDUALES POR VENDEDOR
# ════════════════════════════════════════════════════════

def mensajes_whatsapp() -> dict:
    """Mensajes de WhatsApp listos para enviar a cada vendedor."""
    if not config.ANTHROPIC_API_KEY:
        return {}

    snapshot = _snapshot()
    system = _sistema_operativo(snapshot)
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    vendedores = [v for v in snapshot["equipo"]["vendedores"]
                  if v["cuota_gmv"] > 0]

    mensajes = {}
    for v in vendedores:
        mis_riesgos = [c for c in snapshot["cuentas_en_riesgo"]
                       if c.get("vendedor") == v["nombre"]]

        prompt = f"""Escribe el mensaje de WhatsApp del director comercial para \
{v['nombre'].split()[0]}.

Los datos de este vendedor y sus cuentas en riesgo estan en la seccion
CONTEXTO ACTUAL del sistema. Cuentas en riesgo de {v['nombre'].split()[0]}:
{json.dumps(mis_riesgos[:3], ensure_ascii=False, default=str)}

Formato: mensaje directo, sin saludo formal, maximo 5 lineas.
Debe incluir: 1 reconocimiento O 1 alerta, 1 accion concreta con cliente
nombrado, 1 meta especifica del dia.

Solo el mensaje, sin explicaciones."""

        resp = client.messages.create(
            model=MODEL,
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        mensajes[v["nombre"]] = resp.content[0].text

    return mensajes


# ════════════════════════════════════════════════════════
# 3. RESPUESTAS A PREGUNTAS OPERATIVAS
# ════════════════════════════════════════════════════════

def responder_director(pregunta: str, historial: list = None) -> str:
    """Responde preguntas operativas del director sobre el equipo."""
    if not config.ANTHROPIC_API_KEY:
        return "API key no configurada."

    snapshot = _snapshot()
    system = _sistema_operativo(snapshot) + """

Responde en espanol, directo, maximo 120 palabras.
Usa cifras reales del CONTEXTO ACTUAL cuando apliquen."""

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

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
# 4. ANALISIS ESTRATEGICO (avance del plan a 3-6 meses)
# ════════════════════════════════════════════════════════

def analisis_estrategico() -> str:
    """
    Analisis del avance del plan estrategico TBS.
    Diferencia vs briefing_diario:
    - briefing_diario: estado operativo HOY (visitas, cuota del mes)
    - analisis_estrategico: avance del PLAN a 3-6 meses (que funciona)
    """
    if not config.ANTHROPIC_API_KEY:
        return "⚠️ ANTHROPIC_API_KEY no configurada en .env"

    from agente.estrategia import snapshot_estrategico

    snap = snapshot_estrategico()
    system = _sistema_estrategico(snap, incluir_supervisor=True)
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    prompt = """Genera el analisis estrategico mensual.

Usa EXCLUSIVAMENTE los datos de la seccion CONTEXTO ACTUAL para el avance
real de cada objetivo. El plan de arriba te dice cuales son las metas y como
juzgar; el contexto actual te dice donde estamos parados.

Formato exacto:

**Resumen ejecutivo**: [2 frases: como va el plan en general y cual es el mayor riesgo]

**Estado de cada objetivo**:

1. Densificacion hoteles: [estado] — [que esta pasando, con nombres de hoteles especificos]
2. Cuentas huerfanas: [estado] — [cuantas recuperadas, que riesgo hay]
3. Marcas estrategicas: [estado] — [que marcas tienen gaps en que cuentas]
4. Cartera: [estado] — [tendencia y si hay riesgo sistemico]
5. Clientes nuevos: [estado] — [ritmo actual vs meta]
6. Mix premium: [estado] — [tendencia e implicacion para el margen]

**Lo que esta funcionando bien** (maximo 2 puntos):
- [especifico, con datos]

**Lo que NO esta funcionando** (maximo 3 puntos):
- [especifico, con hipotesis de por que]

**Ajuste recomendado al plan**:
[1 cambio concreto en la estrategia o el enfoque — no en la operacion diaria]

**Proyeccion a 90 dias**:
[Si continuamos asi, llegamos a EBITDA positivo o no? Que cambiaria la trayectoria?]

Reglas:
- Usa cifras reales del contexto actual
- Menciona hoteles, marcas y situaciones por nombre
- Distingue entre problema de ejecucion y problema de estrategia
- No repitas lo del briefing operativo
- Se directo sobre que NO esta funcionando aunque sea incomodo"""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=900,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


# ════════════════════════════════════════════════════════
# 5. RESPUESTAS A PREGUNTAS ESTRATEGICAS
# ════════════════════════════════════════════════════════

def responder_sobre_estrategia(pregunta: str, historial: list = None) -> str:
    """
    Responde preguntas estrategicas del director.
    A diferencia de responder_director (operativo), tiene acceso al
    snapshot estrategico completo de los 6 objetivos.
    """
    if not config.ANTHROPIC_API_KEY:
        return "API key no configurada."

    from agente.estrategia import snapshot_estrategico

    snap = snapshot_estrategico()
    system = _sistema_estrategico(snap, incluir_supervisor=False) + """

Responde con perspectiva estrategica (no operativa).
Maximo 150 palabras. Directo y con datos del contexto actual cuando apliquen."""

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

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
