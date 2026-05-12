from sqlalchemy import create_engine, text
from config import config

engine = create_engine(config.DB_URL)
with engine.connect() as conn:
    rows = conn.execute(text('''
        SELECT tipo_horeca, COUNT(*) as total
        FROM dim_cliente
        GROUP BY tipo_horeca
        ORDER BY total DESC
    ''')).fetchall()
    
    print("\n📊 RESULTADOS DE LA AUDITORÍA DE SECTORES:")
    print("-" * 40)
    for r in rows:
        print(f"  {r[0]}: {r[1]} clientes")
    print("-" * 40)