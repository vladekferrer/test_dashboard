# AGREGAR ESTO A extraccion/modelo_db.py
# Pegar antes de la función crear_db()

# class LlmInsight(Base):
#     """
#     Historial de insights generados por Claude.
#     """
#     __tablename__ = "llm_insights"
#
#     id = Column(Integer, primary_key=True, autoincrement=True)
#     fecha = Column(DateTime, index=True)
#     tipo = Column(String(32))       # 'diario', 'semanal', 'alerta'
#     contenido = Column(Text)
#     modelo = Column(String(64))
#
# TAMBIÉN: agregar LlmInsight a los imports de crear_db():
#   Base.metadata.create_all(engine)  ← ya crea todas las tablas automáticamente

# ---- SNIPPET COMPLETO PARA COPIAR ----
SNIPPET = """
class LlmInsight(Base):
    __tablename__ = "llm_insights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fecha = Column(DateTime, index=True)
    tipo = Column(String(32))
    contenido = Column(Text)
    modelo = Column(String(64))
"""
