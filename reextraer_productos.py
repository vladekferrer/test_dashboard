from sqlalchemy import create_engine, text
from extraccion.odoo_client import OdooClient
from extraccion.extractor import transformar_product, CAMPOS_PRODUCT
from extraccion.modelo_db import crear_db

engine = crear_db()
c = OdooClient()
c.autenticar()

total = c.contar('product.product', [['active', 'in', [True, False]]])
print(f"Productos en Odoo: {total}")

cargados = 0
limite = 100  # Bloques chiquitos para aislar el daño

for offset in range(0, total, limite):
    try:
        bloque = c.buscar_y_leer(
            'product.product',
            [['active', 'in', [True, False]]],
            CAMPOS_PRODUCT,
            limite=limite,
            offset=offset
        )
        with engine.connect() as conn:
            for r in bloque:
                reg = transformar_product(r)
                cols = ", ".join(reg.keys())
                placeholders = ", ".join([f":{k}" for k in reg.keys()])
                conn.execute(
                    text(f"INSERT OR REPLACE INTO raw_product ({cols}) VALUES ({placeholders})"),
                    reg
                )
            conn.commit()
        cargados += len(bloque)
        print(f"  {cargados}/{total} productos cargados...")
    except Exception as e:
        print(f"  [ALERTA] Odoo tiró basura en el bloque {offset}. Lo esquivamos y seguimos...")

print("\nListo. Total en base:")
with engine.connect() as conn:
    n = conn.execute(text("SELECT COUNT(*) FROM raw_product")).scalar()
    print(f"  raw_product: {n:,} productos salvados.")