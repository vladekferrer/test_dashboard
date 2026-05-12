"""
Validacion de la extraccion.

Corre despues de extraer_inicial.py para verificar que los datos
extraidos hagan sentido. Compara totales de Odoo contra SQLite.

Uso:
    python -m scripts.validar
"""
import sys
from sqlalchemy import create_engine, text
from config import config
from extraccion.odoo_client import OdooClient


def main():
    print("=" * 60)
    print("VALIDACION DE EXTRACCION TBS")
    print("=" * 60)

    cliente = OdooClient()
    cliente.autenticar()
    engine = create_engine(config.DB_URL)

    chequeos = [
        ("sale.order",       [["date_order", ">=", config.EXTRACT_FROM_DATE]],
         "raw_sale_order"),
        ("sale.order.line",  [["create_date", ">=", config.EXTRACT_FROM_DATE]],
         "raw_sale_order_line"),
        ("res.partner",      [["customer_rank", ">", 0]],
         "raw_partner"),
        ("product.product",  [["active", "in", [True, False]]],
         "raw_product"),
        ("res.users",        [],
         "raw_user"),
        ("account.move",     [["move_type", "in", ["out_invoice", "out_refund"]],
                              ["invoice_date", ">=", config.EXTRACT_FROM_DATE]],
         "raw_account_move"),
    ]

    print(f"\n{'Modelo':<25} {'Odoo':>12} {'SQLite':>12} {'Diff':>10} {'Estado':>10}")
    print("-" * 71)

    total_diff = 0
    for modelo_odoo, dominio, tabla_local in chequeos:
        odoo_count = cliente.contar(modelo_odoo, dominio)
        with engine.connect() as conn:
            local_count = conn.execute(text(f"SELECT COUNT(*) FROM {tabla_local}")).scalar()
        diff = odoo_count - local_count
        total_diff += abs(diff)
        estado = "OK" if diff == 0 else ("WARN" if abs(diff) < 5 else "ERROR")
        print(f"{modelo_odoo:<25} {odoo_count:>12} {local_count:>12} {diff:>10} {estado:>10}")

    print("-" * 71)

    print("\nValidaciones de coherencia:")
    with engine.connect() as conn:
        ordenes_sin_cliente = conn.execute(text(
            "SELECT COUNT(*) FROM raw_sale_order WHERE partner_id IS NULL"
        )).scalar()
        print(f"  Ordenes sin cliente:        {ordenes_sin_cliente}")

        ordenes_sin_vendedor = conn.execute(text(
            "SELECT COUNT(*) FROM raw_sale_order WHERE user_id IS NULL"
        )).scalar()
        print(f"  Ordenes sin vendedor:       {ordenes_sin_vendedor}")

        lineas_sin_orden = conn.execute(text(
            "SELECT COUNT(*) FROM raw_sale_order_line "
            "WHERE order_id NOT IN (SELECT id FROM raw_sale_order)"
        )).scalar()
        print(f"  Lineas sin orden padre:     {lineas_sin_orden}")

        suma_total = conn.execute(text(
            "SELECT SUM(amount_total) FROM raw_sale_order WHERE state IN ('sale','done')"
        )).scalar() or 0
        print(f"  Suma total ordenes (state=sale/done): ${suma_total:,.0f}")

    print("\n" + "=" * 60)
    if total_diff == 0:
        print("VALIDACION OK - los conteos coinciden")
        sys.exit(0)
    elif total_diff < 50:
        print(f"VALIDACION CON ADVERTENCIAS - diferencia total: {total_diff}")
        sys.exit(0)
    else:
        print(f"VALIDACION FALLO - diferencia total: {total_diff}")
        print("Revisa logs/extraccion_*.log y considera reextraccion.")
        sys.exit(1)


if __name__ == "__main__":
    main()
