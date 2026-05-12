"""
API del dashboard TBS — versión Día 3.
Agrega endpoints de insights LLM y chat.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import create_engine, text
from pydantic import BaseModel
from pathlib import Path
from config import config

app = FastAPI(title="TBS Dashboard API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

engine = create_engine(config.DB_URL, echo=False)
FRONTEND_DIR = Path(__file__).parent / "frontend"


def query(sql: str, params: dict = None) -> list:
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        cols = list(result.keys())
        return [dict(zip(cols, row)) for row in result.fetchall()]


def query_one(sql: str, params: dict = None) -> dict:
    rows = query(sql, params)
    return rows[0] if rows else {}


@app.get("/")
def home():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/north-star")
def north_star():
    return query_one("SELECT * FROM v_north_star")


@app.get("/api/tendencia-mensual")
def tendencia_mensual():
    return {"meses": query("SELECT * FROM v_tendencia_mensual")}


@app.get("/api/clientes-top")
def clientes_top(limite: int = 30):
    return {"clientes": query(f"SELECT * FROM v_clientes_top LIMIT {min(limite, 100)}")}


@app.get("/api/clientes-top/{id_cliente}")
def cliente_detalle(id_cliente: int):
    cliente = query_one("SELECT * FROM v_clientes_top WHERE id_cliente = :id", {"id": id_cliente})
    if not cliente:
        raise HTTPException(404, "Cliente no encontrado")
    historial = query("""
        SELECT strftime('%Y-%m', date_order) AS mes,
               ROUND(SUM(amount_untaxed), 0) AS gmv, COUNT(id) AS ordenes
        FROM raw_sale_order
        WHERE partner_id = :id AND state IN ('sale','done')
          AND company_id = 2 AND date_order >= date('now', '-12 months')
        GROUP BY strftime('%Y-%m', date_order) ORDER BY mes
    """, {"id": id_cliente})
    white_space = query("SELECT * FROM v_white_space WHERE partner_id = :id", {"id": id_cliente})
    return {"cliente": cliente, "historial_mensual": historial, "white_space": white_space}


@app.get("/api/vendedores")
def vendedores():
    return {"vendedores": query("SELECT * FROM v_vendedores")}


@app.get("/api/cartera-aging")
def cartera_aging():
    resumen = query("""
        SELECT bucket_aging, COUNT(*) AS facturas,
               ROUND(SUM(saldo_pendiente), 0) AS total,
               COUNT(DISTINCT partner_id) AS clientes
        FROM v_cartera_aging GROUP BY bucket_aging
        ORDER BY CASE bucket_aging
            WHEN '0-30 dias' THEN 1 WHEN '31-45 dias' THEN 2
            WHEN '46-60 dias' THEN 3 WHEN '61-90 dias' THEN 4
            WHEN '+90 dias' THEN 5 ELSE 6 END
    """)
    top_deudores = query("""
        SELECT cliente, ROUND(SUM(saldo_pendiente), 0) AS total_adeudado,
               MAX(dias_vencido) AS max_dias_vencido, COUNT(*) AS facturas_pendientes
        FROM v_cartera_aging GROUP BY partner_id, cliente
        ORDER BY total_adeudado DESC LIMIT 10
    """)
    return {"resumen_aging": resumen, "top_deudores": top_deudores}


@app.get("/api/categorias")
def categorias():
    return {"categorias": query("SELECT * FROM v_categorias")}


@app.get("/api/alertas")
def alertas():
    rojas = query("SELECT * FROM v_alertas WHERE semaforo='rojo' LIMIT 20")
    amarillas = query("SELECT * FROM v_alertas WHERE semaforo='amarillo' LIMIT 20")
    return {"rojas": rojas, "amarillas": amarillas,
            "total_rojas": len(rojas), "total_amarillas": len(amarillas)}


@app.get("/api/white-space")
def white_space_top():
    return {"oportunidades": query("""
        SELECT cliente, COUNT(*) AS categorias_faltantes,
               GROUP_CONCAT(categoria, ', ') AS que_no_compra
        FROM v_white_space WHERE es_white_space = 1
        GROUP BY partner_id, cliente HAVING categorias_faltantes >= 2
        ORDER BY categorias_faltantes DESC LIMIT 20
    """)}


@app.get("/api/insights")
def get_insights():
    insight = query_one("SELECT id, fecha, contenido, modelo FROM llm_insights ORDER BY fecha DESC LIMIT 1")
    if not insight:
        return {"contenido": "Sin insight disponible. Ejecuta: python -m scripts.generar_insight", "fecha": None}
    return insight


@app.post("/api/insights/regenerar")
def regenerar_insight():
    try:
        from llm.claude_client import generar_insight_diario, guardar_insight_en_db
        texto = generar_insight_diario()
        guardar_insight_en_db(texto)
        return {"contenido": texto, "generado": True}
    except Exception as e:
        raise HTTPException(500, f"Error: {str(e)}")


class PreguntaRequest(BaseModel):
    pregunta: str
    historial: list = []


@app.post("/api/chat")
def chat(req: PreguntaRequest):
    if not req.pregunta.strip():
        raise HTTPException(400, "Pregunta vacía")
    try:
        from llm.claude_client import responder_pregunta
        respuesta = responder_pregunta(req.pregunta, req.historial)
        return {"respuesta": respuesta}
    except Exception as e:
        raise HTTPException(500, f"Error: {str(e)}")


@app.get("/api/salud")
def salud():
    try:
        result = query_one("SELECT COUNT(*) AS ordenes FROM raw_sale_order")
        return {"estado": "ok", "ordenes_en_db": result.get("ordenes", 0)}
    except Exception as e:
        return {"estado": "error", "mensaje": str(e)}
