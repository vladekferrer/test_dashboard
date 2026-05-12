from extraccion.extractor import OdooClient, extraer_modelo, transformar_product, CAMPOS_PRODUCT, crear_db
from config import config
from sqlalchemy import create_engine
engine = crear_db()
c = OdooClient()
c.autenticar()
r = extraer_modelo(c, 'product.product', CAMPOS_PRODUCT,
    [['active', 'in', [True, False]]],
    'raw_product', transformar_product, engine)
print(r)
