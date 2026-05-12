from extraccion.odoo_client import OdooClient

c = OdooClient()
c.autenticar()

# Leer los primeros 5 productos con contexto de compañía
productos = c.models.execute_kw(
    c.db, c.uid, c.password,
    'product.product', 'search_read',
    [[['active', 'in', [True, False]]]],
    {
        'fields': ['id', 'name', 'standard_price'],
        'limit': 100,
        'context': {'force_company': 2}  # ← con contexto de compañía
    }
)

print("Con contexto de compañía (force_company=2):")
for p in productos:
    print(f"  ID {p['id']} | {p['name'][:40]} | costo: ${p['standard_price']:,.2f}")

# Comparar sin contexto
productos_sin = c.models.execute_kw(
    c.db, c.uid, c.password,
    'product.product', 'search_read',
    [[['active', 'in', [True, False]]]],
    {
        'fields': ['id', 'name', 'standard_price'],
        'limit': 100
    }
)

print("\nSin contexto de compañía:")
for p in productos_sin:
    print(f"  ID {p['id']} | {p['name'][:40]} | costo: ${p['standard_price']:,.2f}")