"""
Cuotas mensuales del equipo TBS Cartagena.

El director comercial edita este archivo directamente.
Después de cada cambio correr:
    python -m scripts.construir_modelo

TIPOS DE CUOTA:
  gmv_mensual        → COP sin impuestos
  cuentas_activas    → mínimo de cuentas con ≥1 pedido en el mes
  clientes_nuevos    → cuentas con primer pedido en el mes
  cartera_max_pct    → % máximo de cartera vencida >30d sobre GMV
  visitas_semana     → visitas presenciales mínimas por semana
  skus_promedio      → SKUs distintos promedio por orden
"""

# Meses: formato "YYYY-MM"
# Si el mes no está definido, se usa CUOTAS_DEFAULT

CUOTAS_DEFAULT = {
    "gmv_mensual":       80_000_000,
    "cuentas_activas":   50,
    "clientes_nuevos":   2,
    "cartera_max_pct":   8.0,
    "visitas_semana":    20,
    "skus_promedio":     3.0,
}

# Cuotas específicas por vendedor
# La clave debe coincidir EXACTAMENTE con el nombre en Odoo
CUOTAS_POR_VENDEDOR = {

    "ZORAIDA MARIA HERNANDEZ ALVARADO": {
        "gmv_mensual":       140_000_000,
        "cuentas_activas":   70,
        "clientes_nuevos":   3,
        "cartera_max_pct":   6.0,
        "visitas_semana":    25,
        "skus_promedio":     3.5,
    },

    "RONALD RUDAS SEÑA": {
        "gmv_mensual":       90_000_000,
        "cuentas_activas":   70,
        "clientes_nuevos":   3,
        "cartera_max_pct":   8.0,
        "visitas_semana":    25,
        "skus_promedio":     3.0,
    },

    "OFICINA CARTAGENA TBS": {
        "gmv_mensual":       40_000_000,
        "cuentas_activas":   20,
        "clientes_nuevos":   1,
        "cartera_max_pct":   10.0,
        "visitas_semana":    0,
        "skus_promedio":     2.5,
    },

    "VACANTE 87": {
        "gmv_mensual":       0,
        "cuentas_activas":   0,
        "clientes_nuevos":   0,
        "cartera_max_pct":   100.0,
        "visitas_semana":    0,
        "skus_promedio":     0,
    },

    # Agregar vendedores nuevos aquí con el mismo formato
}

# Marcas estratégicas a codificar (presencia esperada en cuentas top)
MARCAS_ESTRATEGICAS = [
    "JOHNNIE WALKER",
    "BUCHANAN",
    "RON PARCE",
    "TANQUERAY",
    "MEZCAL UNION",
    "MUMM",
    "LA HECHICERA",
]

# Categorías que deben estar presentes en cuentas top
CATEGORIAS_CORE = [
    "Whisky",
    "Vinos",
    "Espumantes",
    "Gin",
    "Ron",
]


def get_cuota(nombre_vendedor: str) -> dict:
    """Retorna las cuotas de un vendedor, con fallback a CUOTAS_DEFAULT."""
    return CUOTAS_POR_VENDEDOR.get(nombre_vendedor, CUOTAS_DEFAULT)


def get_todos_vendedores() -> list:
    """Retorna la lista de vendedores con cuotas definidas."""
    return list(CUOTAS_POR_VENDEDOR.keys())
