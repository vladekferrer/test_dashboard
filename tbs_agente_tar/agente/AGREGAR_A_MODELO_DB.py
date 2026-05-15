"""
INSTRUCCIÓN: Agregar estas clases a extraccion/modelo_db.py
ANTES de la función crear_db() que está al final del archivo.

Las tablas se crearán automáticamente la próxima vez que
se corra crear_db() o construir_modelo.py.
"""

# ── PEGAR ESTO EN extraccion/modelo_db.py ────────────────────

NUEVAS_CLASES = '''

class VisitaVendedor(Base):
    """
    Registro manual de visitas del equipo comercial.
    El director o el vendedor las registran desde el dashboard.
    """
    __tablename__ = "visitas_vendedor"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    vendedor        = Column(String(128), index=True)
    cliente         = Column(String(256))
    partner_id      = Column(Integer, index=True)
    fecha           = Column(Date, index=True)
    tipo            = Column(String(32))   # presencial | llamada | whatsapp
    resultado       = Column(String(256))  # resumen de qué pasó
    compromiso      = Column(Text)         # qué prometió el cliente o el vendedor
    monto_pedido    = Column(Float)        # si generó pedido, cuánto
    created_at      = Column(DateTime)


class CompromisoVendedor(Base):
    """
    Compromisos del equipo: clientes a contactar, pedidos a cerrar,
    cuentas a recuperar. El director los asigna, el sistema los sigue.
    """
    __tablename__ = "compromisos_vendedor"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    vendedor         = Column(String(128), index=True)
    cliente          = Column(String(256))
    partner_id       = Column(Integer)
    descripcion      = Column(Text)
    tipo             = Column(String(32))  # visita | pedido | cartera | nuevo_cliente
    fecha_compromiso = Column(Date, index=True)
    estado           = Column(String(16), default="pendiente")  # pendiente | cumplido | vencido
    resultado        = Column(Text)
    created_at       = Column(DateTime)
    closed_at        = Column(DateTime)


class CuotaMensual(Base):
    """
    Cuotas por vendedor por mes. Permite registrar
    cambios históricos de cuota sin tocar cuotas.py.
    """
    __tablename__ = "cuota_mensual"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    vendedor        = Column(String(128), index=True)
    mes             = Column(String(7), index=True)  # YYYY-MM
    gmv_mensual     = Column(Float)
    cuentas_activas = Column(Integer)
    clientes_nuevos = Column(Integer)
    cartera_max_pct = Column(Float)
    visitas_semana  = Column(Integer)
    created_at      = Column(DateTime)


class BriefingDiario(Base):
    """
    Historial de briefings generados por el agente supervisor.
    """
    __tablename__ = "briefing_diario"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    fecha      = Column(DateTime, index=True)
    contenido  = Column(Text)
    mensajes   = Column(Text)   # JSON: {vendedor: mensaje_whatsapp}
    modelo     = Column(String(64))
'''

print("Copia el contenido de NUEVAS_CLASES en extraccion/modelo_db.py")
print("Antes de la función crear_db() al final del archivo.")
