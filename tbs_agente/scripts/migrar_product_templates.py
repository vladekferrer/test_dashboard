"""
Migración única: agrega product_tmpl_id a raw_product
y crea la tabla raw_product_template.

Correr UNA sola vez:
    python -m scripts.migrar_product_templates
"""
from sqlalchemy import create_engine, text
from config import config


def main():
    engine = create_engine(config.DB_URL)

    with engine.begin() as conn:
        # 1. Agregar product_tmpl_id a raw_product si no existe
        cols = conn.execute(
            text("PRAGMA table_info(raw_product)")
        ).fetchall()
        col_names = {c[1] for c in cols}

        if "product_tmpl_id" not in col_names:
            conn.execute(text(
                "ALTER TABLE raw_product "
                "ADD COLUMN product_tmpl_id INTEGER"
            ))
            print("  ✓ Columna product_tmpl_id agregada a raw_product")
        else:
            print("  ✓ product_tmpl_id ya existe en raw_product")

        # 2. Crear raw_product_template
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS raw_product_template (
                id              INTEGER PRIMARY KEY,
                name            VARCHAR(256),
                standard_price  FLOAT,
                categ_id        INTEGER,
                active          BOOLEAN,
                company_id      INTEGER,
                extracted_at    DATETIME
            )
        """))
        print("  ✓ Tabla raw_product_template lista")

        # 3. Índices
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_raw_product_tmpl_id
            ON raw_product(product_tmpl_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_rpt_company_id
            ON raw_product_template(company_id)
        """))
        print("  ✓ Índices creados")

    print("\nMigración completada.")


if __name__ == "__main__":
    main()
