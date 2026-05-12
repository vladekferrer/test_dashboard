"""
Script de extraccion incremental para correr cada 4 horas.

Uso:
    python -m scripts.extraer_incremental

Configurar como cron job:
    Linux/Mac:
        0 */4 * * * cd /ruta/tbs_dashboard && /usr/bin/python3 -m scripts.extraer_incremental >> logs/cron.log 2>&1
    Windows:
        Task Scheduler con trigger de 4 horas
"""
import logging
import sys
from datetime import datetime
from extraccion.extractor import ejecutar_extraccion


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("logs/incremental.log"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logger = logging.getLogger("incremental")
    logger.info("Iniciando extraccion incremental")

    try:
        resultados = ejecutar_extraccion(modo="incremental")
        fallos = [r for r in resultados if r["estado"] != "ok"]
        if fallos:
            logger.warning(f"Extraccion completada con {len(fallos)} fallos")
            sys.exit(1)
        logger.info("Extraccion incremental OK")
    except Exception as e:
        logger.error(f"Fallo critico: {e}", exc_info=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
