"""
Cuotas mensuales del equipo TBS Cartagena.

CAMBIO DE FUENTE
----------------
Antes este modulo tenia las cuotas quemadas en diccionarios estaticos.
Ahora la cuota de GMV mensual viene de `cuotas.xlsx` en la raiz del proyecto,
con columnas: PROVEEDOR, PLAN, ASESOR (numero de zona comercial).

La firma publica se mantiene IGUAL para no romper monitor.py, supervisor_llm.py
ni ningun otro script:
    get_cuota(nombre_vendedor) -> dict con las mismas 6 llaves de siempre
    get_todos_vendedores()     -> list[str]
    CUOTAS_DEFAULT             -> dict
    MARCAS_ESTRATEGICAS        -> list[str]
    CATEGORIAS_CORE            -> list[str]

Lo que SI cambia internamente:
- `gmv_mensual` por vendedor = SUMA(PLAN) de su zona en el Excel.
- Los otros 5 campos (`cuentas_activas`, `clientes_nuevos`, `cartera_max_pct`,
  `visitas_semana`, `skus_promedio`) SIGUEN quemados aqui en `CAMPOS_NO_EXCEL`
  porque el Excel no los trae. Si quieres llevarlos al Excel tambien, hay que
  agregar columnas y ampliar el lector.

La caja de lectura cachea el Excel por mtime: si editas y guardas el .xlsx,
la proxima llamada lo relee solo. No hace falta reiniciar el servidor.

Funciones nuevas (no rompen nada, son extra):
    get_plan_proveedores(nombre)  -> dict {proveedor: monto}
    estado_carga()                -> info de cuando se leyo y si hubo error
    recargar()                    -> fuerza relectura ignorando el cache

NOTA SOBRE EL MAPEO ZONA -> VENDEDOR
------------------------------------
El Excel usa numeros de zona (84, 86, 87) como identificador. Para mapear
zona -> nombre de vendedor de Odoo, usamos `ZONA_A_VENDEDOR` mas abajo.

Esto sigue siendo un dato quemado en codigo. Lo limpio a futuro: agregar
una hoja "zonas" al mismo cuotas.xlsx con columnas ZONA, VENDEDOR y leerla
aqui, asi no hay que tocar codigo cuando se reasignen zonas.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ─── Ruta del Excel ──────────────────────────────────────────────────
# Sube 2 niveles desde agente/cuotas.py para llegar a la raiz del proyecto
ROOT = Path(__file__).resolve().parent.parent
XLSX_PATH = ROOT / "cuotas.xlsx"


# ─── Mapeo zona (Excel) -> nombre de vendedor (Odoo) ────────────────
# La clave debe coincidir EXACTAMENTE con `ru.name` en raw_user.
# El "VACANTE 87" usa el numero de zona como sufijo, por eso encaja con la
# zona 87 del Excel.
ZONA_A_VENDEDOR = {
    84: "ZORAIDA MARIA HERNANDEZ ALVARADO",
    86: "RONALD RUDAS SEÑA",
    87: "VACANTE 87",
}
VENDEDOR_A_ZONA = {v: k for k, v in ZONA_A_VENDEDOR.items()}


# ─── Defaults ────────────────────────────────────────────────────────
# Se usan cuando un vendedor NO tiene zona en el Excel
# (ej: Jazmin, Oficina Cartagena, vendedores nuevos)
CUOTAS_DEFAULT = {
    "gmv_mensual":       80_000_000,
    "cuentas_activas":   50,
    "clientes_nuevos":   2,
    "cartera_max_pct":   8.0,
    "visitas_semana":    20,
    "skus_promedio":     3.0,
}

# Campos que NO vienen del Excel y que se aplican por vendedor.
# Si un vendedor no aparece aqui, usa el default.
# (gmv_mensual no va aqui — siempre sale del Excel via la zona)
CAMPOS_NO_EXCEL = {
    "ZORAIDA MARIA HERNANDEZ ALVARADO": {
        "cuentas_activas":   70,
        "clientes_nuevos":   3,
        "cartera_max_pct":   6.0,
        "visitas_semana":    25,
        "skus_promedio":     3.5,
    },
    "RONALD RUDAS SEÑA": {
        "cuentas_activas":   70,
        "clientes_nuevos":   3,
        "cartera_max_pct":   8.0,
        "visitas_semana":    25,
        "skus_promedio":     3.0,
    },
    "OFICINA CARTAGENA TBS": {
        "cuentas_activas":   20,
        "clientes_nuevos":   1,
        "cartera_max_pct":   10.0,
        "visitas_semana":    0,
        "skus_promedio":     2.5,
    },
    "VACANTE 87": {
        "cuentas_activas":   0,
        "clientes_nuevos":   0,
        "cartera_max_pct":   100.0,
        "visitas_semana":    0,
        "skus_promedio":     0,
    },
}


# ─── Marcas y categorias estrategicas (no vienen del Excel) ─────────
MARCAS_ESTRATEGICAS = [
    "JOHNNIE WALKER",
    "BUCHANAN",
    "RON PARCE",
    "TANQUERAY",
    "MEZCAL UNION",
    "MUMM",
    "LA HECHICERA",
]

CATEGORIAS_CORE = [
    "Whisky",
    "Vinos",
    "Espumantes",
    "Gin",
    "Ron",
]


# ─── Caja de lectura del Excel con cache por mtime ──────────────────
_cache = {
    "mtime":        None,   # timestamp del archivo cuando se cargo
    "loaded_at":    None,   # cuando lo cargo este proceso
    "error":        None,   # texto del error si hubo, sino None
    "por_zona":     {},     # {zona_id: {"plan_total": float, "por_proveedor": {...}}}
}


def _cargar_excel(forzar: bool = False) -> None:
    """
    Lee el Excel si cambio o si nunca se ha leido. Actualiza `_cache`.
    No relanza excepciones — registra el error en `_cache["error"]` y deja
    el sistema corriendo con defaults. La cuota tiene que ser robusta:
    si alguien borra el .xlsx por accidente, el dashboard no debe caerse.
    """
    if not XLSX_PATH.exists():
        _cache["error"] = (
            f"No existe {XLSX_PATH.name} en la raiz del proyecto. "
            f"Usando cuotas por defecto."
        )
        _cache["por_zona"] = {}
        _cache["mtime"] = None
        _cache["loaded_at"] = datetime.now()
        return

    mtime_actual = XLSX_PATH.stat().st_mtime
    if (not forzar) and _cache["mtime"] == mtime_actual and _cache["error"] is None:
        return  # cache valido, no relee

    try:
        df = pd.read_excel(XLSX_PATH, sheet_name=0)
        # Normalizar nombres de columna por si tienen espacios o mayusc/minusc
        df.columns = [str(c).strip().upper() for c in df.columns]

        requeridas = {"PROVEEDOR", "PLAN", "ASESOR"}
        faltan = requeridas - set(df.columns)
        if faltan:
            raise ValueError(
                f"Faltan columnas en cuotas.xlsx: {sorted(faltan)}. "
                f"Encontradas: {sorted(df.columns)}"
            )

        # Limpiar tipos
        df["ASESOR"] = pd.to_numeric(df["ASESOR"], errors="coerce").astype("Int64")
        df["PLAN"] = pd.to_numeric(df["PLAN"], errors="coerce").fillna(0.0)
        df["PROVEEDOR"] = df["PROVEEDOR"].astype(str).str.strip()
        df = df.dropna(subset=["ASESOR"])

        por_zona = {}
        for zona, sub in df.groupby("ASESOR"):
            zona_int = int(zona)
            por_zona[zona_int] = {
                "plan_total": float(sub["PLAN"].sum()),
                "por_proveedor": {
                    row["PROVEEDOR"]: float(row["PLAN"])
                    for _, row in sub.iterrows()
                    if row["PROVEEDOR"]
                },
            }

        _cache["por_zona"] = por_zona
        _cache["mtime"] = mtime_actual
        _cache["loaded_at"] = datetime.now()
        _cache["error"] = None
        logger.info(
            "cuotas.xlsx cargado: %d zonas (%s)",
            len(por_zona), sorted(por_zona.keys()),
        )

    except Exception as e:  # pylint: disable=broad-except
        _cache["error"] = f"Error leyendo cuotas.xlsx: {e}"
        _cache["por_zona"] = {}
        _cache["mtime"] = None
        _cache["loaded_at"] = datetime.now()
        logger.exception("Fallo leyendo cuotas.xlsx")


def _gmv_para_vendedor(nombre: str) -> Optional[float]:
    """Devuelve el GMV mensual del vendedor segun el Excel, o None si no tiene zona."""
    zona = VENDEDOR_A_ZONA.get(nombre)
    if zona is None:
        return None
    info = _cache["por_zona"].get(zona)
    if not info:
        return None
    return float(info["plan_total"])


# ─── API publica (firma INTACTA) ────────────────────────────────────

def get_cuota(nombre_vendedor: str) -> dict:
    """
    Retorna las cuotas de un vendedor con la MISMA estructura que antes:
        {gmv_mensual, cuentas_activas, clientes_nuevos,
         cartera_max_pct, visitas_semana, skus_promedio}

    Logica de fallback:
        - gmv_mensual: del Excel (suma por zona). Si no esta en el Excel
                       o el vendedor no tiene zona, cae al default.
        - los otros 5 campos: vienen de CAMPOS_NO_EXCEL por vendedor,
                              y si el vendedor no esta, cae al default.
    """
    _cargar_excel()

    # Empezamos con el default y vamos sobreescribiendo lo que tengamos
    cuota = dict(CUOTAS_DEFAULT)

    # Campos por vendedor no-Excel
    if nombre_vendedor in CAMPOS_NO_EXCEL:
        cuota.update(CAMPOS_NO_EXCEL[nombre_vendedor])

    # GMV desde el Excel
    gmv_excel = _gmv_para_vendedor(nombre_vendedor)
    if gmv_excel is not None:
        cuota["gmv_mensual"] = gmv_excel

    return cuota


def get_todos_vendedores() -> list:
    """
    Retorna la lista de vendedores con cuotas definidas.
    Union de los que estan en CAMPOS_NO_EXCEL y los que tienen zona en el Excel.
    """
    _cargar_excel()
    nombres = set(CAMPOS_NO_EXCEL.keys())
    for zona in _cache["por_zona"]:
        if zona in ZONA_A_VENDEDOR:
            nombres.add(ZONA_A_VENDEDOR[zona])
    return sorted(nombres)


# ─── API nueva (no rompe nada, solo agrega) ─────────────────────────

def get_plan_proveedores(nombre_vendedor: str) -> dict:
    """
    Detalle del plan por proveedor para un vendedor.
    Retorna {} si el vendedor no tiene zona o el Excel no se pudo cargar.
    """
    _cargar_excel()
    zona = VENDEDOR_A_ZONA.get(nombre_vendedor)
    if zona is None:
        return {}
    info = _cache["por_zona"].get(zona)
    if not info:
        return {}
    return dict(info["por_proveedor"])


def estado_carga() -> dict:
    """
    Diagnostico de la carga del Excel. Util para el endpoint /cuotas
    y para depurar cuando algo no cuadra.
    """
    _cargar_excel()
    return {
        "ruta_archivo": str(XLSX_PATH),
        "archivo_existe": XLSX_PATH.exists(),
        "ultima_lectura": (
            _cache["loaded_at"].isoformat() if _cache["loaded_at"] else None
        ),
        "mtime_archivo": (
            datetime.fromtimestamp(_cache["mtime"]).isoformat()
            if _cache["mtime"] else None
        ),
        "error": _cache["error"],
        "zonas_cargadas": sorted(_cache["por_zona"].keys()),
        "vendedores_con_excel": sorted(
            ZONA_A_VENDEDOR[z]
            for z in _cache["por_zona"]
            if z in ZONA_A_VENDEDOR
        ),
        "vendedores_solo_default": sorted(
            n for n in CAMPOS_NO_EXCEL
            if VENDEDOR_A_ZONA.get(n) not in _cache["por_zona"]
        ),
    }


def recargar() -> dict:
    """Fuerza relectura del Excel ignorando el cache. Retorna el estado nuevo."""
    _cargar_excel(forzar=True)
    return estado_carga()
