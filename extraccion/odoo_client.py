"""
Cliente XML-RPC para Odoo 14.
Maneja autenticacion y consultas a los modelos de Odoo.

Documentacion oficial:
https://www.odoo.com/documentation/14.0/developer/api/external_api.html
"""
import xmlrpc.client
import logging
from typing import List, Dict, Any, Optional
from config import config

logger = logging.getLogger(__name__)


class OdooClient:
    """
    Cliente para Odoo 14. Implementa autenticacion una sola vez
    y reutiliza el UID para todas las consultas.
    """

    def __init__(self):
        config.validate()
        self.url = config.ODOO_URL
        self.db = config.ODOO_DB
        self.username = config.ODOO_USERNAME
        self.password = config.ODOO_PASSWORD
        self.uid: Optional[int] = None
        self.models = None

    def autenticar(self) -> int:
        """
        Autentica contra Odoo y guarda el UID en memoria.
        Retorna el UID. Si falla, lanza excepcion.
        """
        if self.uid is not None:
            return self.uid

        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        try:
            version = common.version()
            logger.info(f"Conectado a Odoo version: {version.get('server_version')}")
        except Exception as e:
            raise RuntimeError(f"No se puede contactar Odoo en {self.url}: {e}")

        uid = common.authenticate(self.db, self.username, self.password, {})
        if not uid:
            raise RuntimeError(
                f"Autenticacion fallida. Revisa ODOO_DB, ODOO_USERNAME y ODOO_PASSWORD."
            )

        self.uid = uid
        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")
        logger.info(f"Autenticado como UID={uid}")
        return uid

    def buscar_y_leer(
        self,
        modelo: str,
        dominio: List[Any],
        campos: List[str],
        limite: Optional[int] = None,
        offset: int = 0,
        orden: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Wrapper sobre 'search_read' de Odoo.

        modelo:  nombre del modelo Odoo, ej. 'sale.order'
        dominio: filtro Odoo, ej. [['state', '=', 'sale']]
        campos:  lista de campos a leer
        limite:  opcional, max registros (None = todos)
        offset:  opcional, paginacion
        orden:   opcional, ej. 'date_order desc'
        """
        if self.uid is None:
            self.autenticar()

        kwargs = {"fields": campos, "offset": offset}
        if limite is not None:
            kwargs["limit"] = limite
        if orden:
            kwargs["order"] = orden

        try:
            return self.models.execute_kw(
                self.db, self.uid, self.password,
                modelo, "search_read",
                [dominio], kwargs,
            )
        except xmlrpc.client.Fault as e:
            logger.error(f"Error consultando {modelo}: {e.faultString}")
            raise

    def contar(self, modelo: str, dominio: List[Any]) -> int:
        if self.uid is None:
            self.autenticar()
        return self.models.execute_kw(
            self.db, self.uid, self.password,
            modelo, "search_count", [dominio]
        )

    def buscar_y_leer_paginado(
        self,
        modelo: str,
        dominio: List[Any],
        campos: List[str],
        tamano_pagina: int = 500,
    ):
        """
        Generator que itera por bloques. Util para extracciones grandes
        sin saturar memoria ni timeouts del servidor Odoo.

        Uso:
            for bloque in cliente.buscar_y_leer_paginado('sale.order', [...], [...]):
                procesar(bloque)
        """
        offset = 0
        total = self.contar(modelo, dominio)
        logger.info(f"{modelo}: {total} registros a extraer en bloques de {tamano_pagina}")

        while offset < total:
            bloque = self.buscar_y_leer(
                modelo, dominio, campos,
                limite=tamano_pagina, offset=offset
            )
            if not bloque:
                break
            yield bloque
            offset += len(bloque)
            logger.info(f"{modelo}: {offset}/{total} extraidos ({offset*100//total}%)")
