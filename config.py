#config.py

"""
Configuracion central del dashboard TBS.
Lee variables de entorno desde el archivo .env.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    ODOO_URL = os.getenv("ODOO_URL", "").rstrip("/")
    ODOO_DB = os.getenv("ODOO_DB", "")
    ODOO_USERNAME = os.getenv("ODOO_USERNAME", "")
    ODOO_PASSWORD = os.getenv("ODOO_PASSWORD", "")

    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

    DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "tbs.db"))
    DB_URL = f"sqlite:///{DB_PATH}"

    EXTRACT_FROM_DATE = os.getenv("EXTRACT_FROM_DATE", "2024-07-01")

    LOG_DIR = BASE_DIR / "logs"
    LOG_DIR.mkdir(exist_ok=True)

    @classmethod
    def validate(cls):
        faltantes = []
        if not cls.ODOO_URL:
            faltantes.append("ODOO_URL")
        if not cls.ODOO_DB:
            faltantes.append("ODOO_DB")
        if not cls.ODOO_USERNAME:
            faltantes.append("ODOO_USERNAME")
        if not cls.ODOO_PASSWORD:
            faltantes.append("ODOO_PASSWORD")
        if faltantes:
            raise RuntimeError(
                f"Faltan variables en .env: {', '.join(faltantes)}. "
                f"Copia .env.example a .env y completa los valores."
            )

config = Config()
