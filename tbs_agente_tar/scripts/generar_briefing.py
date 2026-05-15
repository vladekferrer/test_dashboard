"""
Genera el briefing diario del supervisor de ventas TBS.

Correr cada mañana (cron 7:30 AM):
    0 7 * * 1-6 cd /ruta/tbs_dashboard && python -m scripts.generar_briefing

También corre automáticamente al abrir el dashboard del agente.
"""
import sys, json, logging
from datetime import datetime
from sqlalchemy import create_engine, text
from agente.supervisor_llm import briefing_diario, mensajes_whatsapp
from config import config

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("briefing")


def main():
    logger.info("Generando briefing diario del supervisor...")

    briefing = briefing_diario()
    mensajes = mensajes_whatsapp()

    engine = create_engine(config.DB_URL)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO briefing_diario
                (fecha, contenido, mensajes, modelo)
            VALUES (:fecha, :contenido, :mensajes, :modelo)
        """), {
            "fecha":     datetime.now().isoformat(),
            "contenido": briefing,
            "mensajes":  json.dumps(mensajes, ensure_ascii=False),
            "modelo":    "claude-sonnet-4-5",
        })

    logger.info("Briefing guardado.")
    print("\n" + "=" * 60)
    print("BRIEFING DEL SUPERVISOR")
    print("=" * 60)
    print(briefing)
    if mensajes:
        print("\n" + "=" * 60)
        print("MENSAJES PARA WHATSAPP")
        print("=" * 60)
        for vendedor, msg in mensajes.items():
            print(f"\n── {vendedor.split()[0]} ──")
            print(msg)
    print("=" * 60)


if __name__ == "__main__":
    main()
