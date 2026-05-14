"""
Generador de insight diario TBS.

Uso manual:
    python -m scripts.generar_insight

Configurar como cron a las 7 AM:
    0 7 * * 1-6 cd /ruta/tbs_dashboard && python -m scripts.generar_insight
"""
import sys
import logging
from datetime import datetime
from llm.claude_client import generar_insight_diario, guardar_insight_en_db


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("logs/insights.log"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logger = logging.getLogger("generar_insight")
    logger.info("Generando insight diario...")

    try:
        texto = generar_insight_diario()
        guardar_insight_en_db(texto)
        logger.info("Insight generado y guardado correctamente")
        print("\n" + "=" * 60)
        print("INSIGHT GENERADO:")
        print("=" * 60)
        print(texto)
        print("=" * 60)
    except Exception as e:
        logger.error(f"Error generando insight: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
