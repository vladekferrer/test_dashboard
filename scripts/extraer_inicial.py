"""
Script de extraccion inicial.

Uso:
    python -m scripts.extraer_inicial

Ejecuta una extraccion completa desde EXTRACT_FROM_DATE.
Crea la base SQLite si no existe.
Idempotente: si se ejecuta dos veces, simplemente actualiza los datos.
"""
import logging
import sys
from datetime import datetime

from extraccion.extractor import ejecutar_extraccion


def configurar_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        handlers=[
            logging.FileHandler(f"logs/extraccion_{datetime.now():%Y%m%d_%H%M}.log"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main():
    configurar_logging()
    logger = logging.getLogger("extraer_inicial")

    logger.info("=" * 60)
    logger.info("EXTRACCION INICIAL TBS")
    logger.info("=" * 60)
    inicio = datetime.now()

    try:
        resultados = ejecutar_extraccion(modo="inicial")
    except Exception as e:
        logger.error(f"Extraccion fallo: {e}", exc_info=True)
        sys.exit(1)

    duracion = (datetime.now() - inicio).total_seconds()
    total_registros = sum(r["registros"] for r in resultados)
    fallos = [r for r in resultados if r["estado"] != "ok"]

    logger.info("=" * 60)
    logger.info(f"COMPLETADO en {duracion:.1f}s")
    logger.info(f"Total registros: {total_registros}")
    logger.info(f"Modelos OK:      {len(resultados) - len(fallos)}")
    logger.info(f"Modelos fallo:   {len(fallos)}")
    if fallos:
        for f in fallos:
            logger.error(f"  - {f['modelo']}: {f['mensaje']}")
    logger.info("=" * 60)

    sys.exit(0 if not fallos else 1)


if __name__ == "__main__":
    main()
