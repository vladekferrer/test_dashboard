COMPANY_ID = 2
from extraccion.odoo_client import OdooClient


PRODUCT_IDS = [193687, 193685, 194185, 194066, 193588, 193674]


def many2one_id(value):
    if isinstance(value, list) and value:
        return value[0]
    return None


def main():
    client = OdooClient()
    client.autenticar()

    print("=== USUARIO XML-RPC ===")
    user_data = client.models.execute_kw(
        client.db,
        client.uid,
        client.password,
        "res.users",
        "read",
        [[client.uid]],
        {
            "fields": ["id", "name", "company_id", "company_ids"],
        },
    )
    print(user_data)

    contexto_tbs = {
        "active_test": False,
        "force_company": COMPANY_ID,
        "allowed_company_ids": [COMPANY_ID],
        "company_id": COMPANY_ID,
    }

    print("\n=== PRODUCT.PRODUCT ===")
    productos = client.models.execute_kw(
        client.db,
        client.uid,
        client.password,
        "product.product",
        "read",
        [PRODUCT_IDS],
        {
            "fields": [
                "id",
                "display_name",
                "product_tmpl_id",
                "standard_price",
                "lst_price",
                "active",
            ],
            "context": contexto_tbs,
        },
    )

    for p in productos:
        print(
            p["id"],
            "|",
            p.get("display_name"),
            "| tmpl:",
            p.get("product_tmpl_id"),
            "| standard_price:",
            p.get("standard_price"),
            "| active:",
            p.get("active"),
        )

    template_ids = sorted(
        {
            many2one_id(p.get("product_tmpl_id"))
            for p in productos
            if many2one_id(p.get("product_tmpl_id"))
        }
    )

    print("\n=== PRODUCT.TEMPLATE CON CONTEXTO TBS ===")
    templates = client.models.execute_kw(
        client.db,
        client.uid,
        client.password,
        "product.template",
        "read",
        [template_ids],
        {
            "fields": [
                "id",
                "name",
                "standard_price",
                "list_price",
                "categ_id",
                "active",
                "company_id",
            ],
            "context": contexto_tbs,
        },
    )

    for t in templates:
        print(
            t["id"],
            "|",
            t.get("name"),
            "| standard_price:",
            t.get("standard_price"),
            "| company:",
            t.get("company_id"),
            "| active:",
            t.get("active"),
        )

    print("\n=== IR.PROPERTY PARA STANDARD_PRICE ===")

    res_ids = [f"product.template,{tid}" for tid in template_ids]

    propiedades = client.models.execute_kw(
        client.db,
        client.uid,
        client.password,
        "ir.property",
        "search_read",
        [
            [
                ("name", "=", "standard_price"),
                ("res_id", "in", res_ids),
                "|",
                ("company_id", "=", COMPANY_ID),
                ("company_id", "=", False),
            ]
        ],
        {
            "fields": [
                "id",
                "name",
                "res_id",
                "company_id",
                "value_float",
                "value_reference",
                "fields_id",
            ],
            "context": contexto_tbs,
        },
    )

    if not propiedades:
        print("No se encontraron propiedades standard_price en ir.property para estos templates.")
    else:
        for prop in propiedades:
            print(prop)


if __name__ == "__main__":
    main()