"""
Endpoints del agente supervisor TBS.
Se incluyen desde api/main.py con:
    from api.agente_routes import router as agente_router
    app.include_router(agente_router, prefix="/api/agente")
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from datetime import datetime, date
from config import config

router = APIRouter()
engine = create_engine(config.DB_URL, echo=False)


def q(sql, params=None):
    with engine.connect() as conn:
        r = conn.execute(text(sql), params or {})
        cols = list(r.keys())
        return [dict(zip(cols, row)) for row in r.fetchall()]


def q1(sql, params=None):
    rows = q(sql, params)
    return rows[0] if rows else {}


# ── Estado del equipo ─────────────────────────────────────────
@router.get("/estado-equipo")
def estado_equipo():
    from agente.monitor import estado_equipo as _estado
    return _estado()


# ── Cuentas en riesgo ─────────────────────────────────────────
@router.get("/cuentas-riesgo")
def cuentas_riesgo(dias: int = 14):
    from agente.monitor import cuentas_en_riesgo
    return {"cuentas": cuentas_en_riesgo(dias)}


# ── Profundidad de portafolio ─────────────────────────────────
@router.get("/portafolio")
def portafolio(top_n: int = 20):
    from agente.monitor import profundidad_portafolio
    return {"portafolio": profundidad_portafolio(top_n)}


# ── Codificación de marcas ────────────────────────────────────
@router.get("/marcas")
def marcas(top_n: int = 20):
    from agente.monitor import codificacion_marcas
    return {"marcas": codificacion_marcas(top_n)}


# ── Briefing del día ──────────────────────────────────────────
@router.get("/briefing")
def get_briefing():
    row = q1("""
        SELECT fecha, contenido, mensajes
        FROM briefing_diario
        ORDER BY fecha DESC LIMIT 1
    """)
    if not row:
        return {"contenido": "Sin briefing. Ejecuta: python -m scripts.generar_briefing",
                "fecha": None, "mensajes": {}}
    import json
    row["mensajes"] = json.loads(row.get("mensajes") or "{}")
    return row


@router.post("/briefing/regenerar")
def regenerar_briefing():
    try:
        from agente.supervisor_llm import briefing_diario, mensajes_whatsapp
        import json
        briefing = briefing_diario()
        mensajes = mensajes_whatsapp()
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO briefing_diario
                    (fecha, contenido, mensajes, modelo)
                VALUES (:fecha, :contenido, :mensajes, :modelo)
            """), {
                "fecha": datetime.now().isoformat(),
                "contenido": briefing,
                "mensajes": json.dumps(mensajes, ensure_ascii=False),
                "modelo": "claude-sonnet-4-5",
            })
        return {"contenido": briefing, "mensajes": mensajes}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Chat del supervisor ───────────────────────────────────────
class PreguntaReq(BaseModel):
    pregunta: str
    historial: list = []


@router.post("/chat")
def chat_supervisor(req: PreguntaReq):
    if not req.pregunta.strip():
        raise HTTPException(400, "Pregunta vacía")
    try:
        from agente.supervisor_llm import responder_director
        r = responder_director(req.pregunta, req.historial)
        return {"respuesta": r}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Visitas ───────────────────────────────────────────────────
class VisitaReq(BaseModel):
    vendedor: str
    cliente: str
    partner_id: int = 0
    tipo: str = "presencial"
    resultado: str = ""
    compromiso: str = ""
    monto_pedido: float = 0


@router.get("/visitas")
def get_visitas(vendedor: str = None):
    from agente.monitor import visitas_semana
    return {"visitas": visitas_semana(vendedor)}


@router.post("/visitas")
def registrar_visita(req: VisitaReq):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO visitas_vendedor
                (vendedor, cliente, partner_id, fecha, tipo,
                 resultado, compromiso, monto_pedido, created_at)
            VALUES
                (:vendedor, :cliente, :partner_id, :fecha, :tipo,
                 :resultado, :compromiso, :monto_pedido, :created_at)
        """), {
            "vendedor": req.vendedor, "cliente": req.cliente,
            "partner_id": req.partner_id, "fecha": date.today().isoformat(),
            "tipo": req.tipo, "resultado": req.resultado,
            "compromiso": req.compromiso, "monto_pedido": req.monto_pedido,
            "created_at": datetime.now().isoformat(),
        })
    return {"ok": True}


# ── Compromisos ───────────────────────────────────────────────
class CompromisoReq(BaseModel):
    vendedor: str
    cliente: str
    partner_id: int = 0
    descripcion: str
    tipo: str = "visita"
    fecha_compromiso: str   # YYYY-MM-DD


@router.get("/compromisos")
def get_compromisos():
    from agente.monitor import compromisos_pendientes
    return {"compromisos": compromisos_pendientes()}


@router.post("/compromisos")
def crear_compromiso(req: CompromisoReq):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO compromisos_vendedor
                (vendedor, cliente, partner_id, descripcion,
                 tipo, fecha_compromiso, estado, created_at)
            VALUES
                (:vendedor, :cliente, :partner_id, :descripcion,
                 :tipo, :fecha_compromiso, 'pendiente', :created_at)
        """), {
            "vendedor": req.vendedor, "cliente": req.cliente,
            "partner_id": req.partner_id, "descripcion": req.descripcion,
            "tipo": req.tipo, "fecha_compromiso": req.fecha_compromiso,
            "created_at": datetime.now().isoformat(),
        })
    return {"ok": True}


@router.patch("/compromisos/{id}/cerrar")
def cerrar_compromiso(id: int, resultado: str = ""):
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE compromisos_vendedor
            SET estado='cumplido', resultado=:resultado,
                closed_at=:closed_at
            WHERE id=:id
        """), {"id": id, "resultado": resultado,
               "closed_at": datetime.now().isoformat()})
    return {"ok": True}


# ── Clientes buscador (para autocompletar en formularios) ──────
@router.get("/clientes/buscar")
def buscar_clientes(q_str: str = "", limit: int = 10):
    rows = q("""
        SELECT id, name FROM raw_partner
        WHERE customer_rank > 0
          AND UPPER(name) LIKE UPPER(:q)
        ORDER BY name LIMIT :limit
    """, {"q": f"%{q_str}%", "limit": limit})
    return {"clientes": rows}


# ════════════════════════════════════════════════════════
# ANÁLISIS ESTRATÉGICO
# ════════════════════════════════════════════════════════

@router.get("/estrategia/snapshot")
def estrategia_snapshot():
    """Estado actual de los 6 objetivos estratégicos."""
    from agente.estrategia import snapshot_estrategico
    return snapshot_estrategico()


@router.get("/estrategia/analisis")
def get_analisis_estrategico():
    """Último análisis estratégico guardado."""
    row = q1("""
        SELECT id, fecha, contenido, modelo
        FROM llm_insights
        WHERE tipo = 'estrategico'
        ORDER BY fecha DESC LIMIT 1
    """)
    if not row:
        return {
            "contenido": "Sin análisis disponible. Ejecuta desde el dashboard.",
            "fecha": None
        }
    return row


@router.post("/estrategia/analizar")
def generar_analisis_estrategico():
    """Genera un análisis estratégico fresco con Claude."""
    try:
        from agente.supervisor_llm import analisis_estrategico
        texto = analisis_estrategico()
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO llm_insights (fecha, tipo, contenido, modelo)
                VALUES (:fecha, 'estrategico', :contenido, :modelo)
            """), {
                "fecha":    datetime.now().isoformat(),
                "contenido": texto,
                "modelo":   "claude-sonnet-4-5",
            })
        return {"contenido": texto, "generado": True}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/estrategia/hoteles")
def estrategia_hoteles():
    from agente.estrategia import obj_densificacion_hoteles
    return obj_densificacion_hoteles()


@router.get("/estrategia/vacante")
def estrategia_vacante():
    from agente.estrategia import obj_recuperacion_vacante
    return obj_recuperacion_vacante()


class PreguntaEstrategicaReq(BaseModel):
    pregunta: str
    historial: list = []


@router.post("/estrategia/chat")
def chat_estrategico(req: PreguntaEstrategicaReq):
    """Chat estratégico — diferente al chat operativo."""
    if not req.pregunta.strip():
        raise HTTPException(400, "Pregunta vacía")
    try:
        from agente.supervisor_llm import responder_sobre_estrategia
        r = responder_sobre_estrategia(req.pregunta, req.historial)
        return {"respuesta": r}
    except Exception as e:
        raise HTTPException(500, str(e))
