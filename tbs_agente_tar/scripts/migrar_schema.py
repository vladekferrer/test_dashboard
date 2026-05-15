"""
Migración completa del schema de TBS.

Agrega columnas y tablas nuevas sin tocar los datos existentes.
Seguro correr múltiples veces — verifica antes de modificar.

Uso:
    python -m scripts.migrar_schema
"""
from sqlalchemy import create_engine, text
from config import config


def col_existe(conn, tabla, columna):
    cols = conn.execute(text(f"PRAGMA table_info({tabla})")).fetchall()
    return columna in {c[1] for c in cols}


def tabla_existe(conn, tabla):
    r = conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:t"
    ), {"t": tabla}).fetchone()
    return r is not None


def main():
    engine = create_engine(config.DB_URL)
    print("Iniciando migración de schema TBS...")

    with engine.begin() as conn:

        # ── 1. Columnas nuevas en tablas existentes ────────────────

        # raw_account_move → company_id
        if not col_existe(conn, "raw_account_move", "company_id"):
            conn.execute(text(
                "ALTER TABLE raw_account_move ADD COLUMN company_id INTEGER"
            ))
            print("  ✓ raw_account_move.company_id agregado")
        else:
            print("  · raw_account_move.company_id ya existe")

        # raw_product → product_tmpl_id
        if not col_existe(conn, "raw_product", "product_tmpl_id"):
            conn.execute(text(
                "ALTER TABLE raw_product ADD COLUMN product_tmpl_id INTEGER"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_raw_product_tmpl_id "
                "ON raw_product(product_tmpl_id)"
            ))
            print("  ✓ raw_product.product_tmpl_id agregado")
        else:
            print("  · raw_product.product_tmpl_id ya existe")

        # raw_partner → industry_id
        if not col_existe(conn, "raw_partner", "industry_id"):
            conn.execute(text(
                "ALTER TABLE raw_partner ADD COLUMN industry_id INTEGER"
            ))
            print("  ✓ raw_partner.industry_id agregado")
        else:
            print("  · raw_partner.industry_id ya existe")

        # ── 2. Tablas nuevas de productos ──────────────────────────

        if not tabla_existe(conn, "raw_product_template"):
            conn.execute(text("""
                CREATE TABLE raw_product_template (
                    id              INTEGER PRIMARY KEY,
                    name            VARCHAR(256),
                    standard_price  FLOAT,
                    categ_id        INTEGER,
                    active          BOOLEAN,
                    company_id      INTEGER,
                    extracted_at    DATETIME
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_rpt_company_id "
                "ON raw_product_template(company_id)"
            ))
            print("  ✓ raw_product_template creada")
        else:
            print("  · raw_product_template ya existe")

        if not tabla_existe(conn, "raw_partner_industry"):
            conn.execute(text("""
                CREATE TABLE raw_partner_industry (
                    id           INTEGER PRIMARY KEY,
                    name         VARCHAR(128),
                    full_name    VARCHAR(256),
                    extracted_at DATETIME
                )
            """))
            print("  ✓ raw_partner_industry creada")
        else:
            print("  · raw_partner_industry ya existe")

        # ── 3. Tablas del agente supervisor ───────────────────────

        if not tabla_existe(conn, "visitas_vendedor"):
            conn.execute(text("""
                CREATE TABLE visitas_vendedor (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    vendedor     VARCHAR(128),
                    cliente      VARCHAR(256),
                    partner_id   INTEGER,
                    fecha        DATE,
                    tipo         VARCHAR(32),
                    resultado    VARCHAR(512),
                    compromiso   TEXT,
                    monto_pedido FLOAT,
                    created_at   DATETIME
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_visitas_vendedor "
                "ON visitas_vendedor(vendedor)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_visitas_fecha "
                "ON visitas_vendedor(fecha)"
            ))
            print("  ✓ visitas_vendedor creada")
        else:
            print("  · visitas_vendedor ya existe")

        if not tabla_existe(conn, "compromisos_vendedor"):
            conn.execute(text("""
                CREATE TABLE compromisos_vendedor (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    vendedor         VARCHAR(128),
                    cliente          VARCHAR(256),
                    partner_id       INTEGER,
                    descripcion      TEXT,
                    tipo             VARCHAR(32),
                    fecha_compromiso DATE,
                    estado           VARCHAR(16) DEFAULT 'pendiente',
                    resultado        TEXT,
                    created_at       DATETIME,
                    closed_at        DATETIME
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_compromisos_vendedor "
                "ON compromisos_vendedor(vendedor)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_compromisos_fecha "
                "ON compromisos_vendedor(fecha_compromiso)"
            ))
            print("  ✓ compromisos_vendedor creada")
        else:
            print("  · compromisos_vendedor ya existe")

        if not tabla_existe(conn, "cuota_mensual"):
            conn.execute(text("""
                CREATE TABLE cuota_mensual (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    vendedor        VARCHAR(128),
                    mes             VARCHAR(7),
                    gmv_mensual     FLOAT,
                    cuentas_activas INTEGER,
                    clientes_nuevos INTEGER,
                    cartera_max_pct FLOAT,
                    visitas_semana  INTEGER,
                    created_at      DATETIME
                )
            """))
            print("  ✓ cuota_mensual creada")
        else:
            print("  · cuota_mensual ya existe")

        if not tabla_existe(conn, "briefing_diario"):
            conn.execute(text("""
                CREATE TABLE briefing_diario (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha     DATETIME,
                    contenido TEXT,
                    mensajes  TEXT,
                    modelo    VARCHAR(64)
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_briefing_fecha "
                "ON briefing_diario(fecha)"
            ))
            print("  ✓ briefing_diario creada")
        else:
            print("  · briefing_diario ya existe")

        # ── 4. Tablas de sistema ───────────────────────────────────

        if not tabla_existe(conn, "llm_insights"):
            conn.execute(text("""
                CREATE TABLE llm_insights (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha     DATETIME,
                    tipo      VARCHAR(32),
                    contenido TEXT,
                    modelo    VARCHAR(64)
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_llm_insights_fecha "
                "ON llm_insights(fecha)"
            ))
            print("  ✓ llm_insights creada")
        else:
            print("  · llm_insights ya existe")

    print("\nMigración completada.")
    print("\nPróximo paso:")
    print("  python -m scripts.construir_modelo")


if __name__ == "__main__":
    main()
