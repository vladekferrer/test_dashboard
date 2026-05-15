# TBS Dashboard - Día 1: Extracción Odoo

## Lo que hace este código

Conecta a tu Odoo 14, extrae 18 meses de datos (órdenes, líneas, clientes,
productos, vendedores, facturas) y los guarda en una base SQLite local
lista para análisis.

Este es el **Día 1** del MVP de 3 días. El Día 2 construye el modelo
analítico y la API; el Día 3 agrega el dashboard HTML y la integración
con Claude.

## Requisitos previos

- Python 3.10 o superior
- Acceso administrativo a Odoo 14 (URL, base de datos, usuario, API key)
- 5–15 minutos de tiempo de extracción dependiendo del volumen

## Setup paso a paso

### 1. Crear entorno virtual e instalar dependencias

```bash
cd tbs_dashboard
python3 -m venv venv

# Linux/Mac:
source venv/bin/activate

# Windows:
venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configurar credenciales

```bash
cp .env.example .env
```

Edita `.env` con tus valores reales:

```
ODOO_URL=https://tbs.odoo.com         # tu URL real
ODOO_DB=tbs_production                # nombre de la base de Odoo
ODOO_USERNAME=admin@tbs.com           # usuario con permisos de lectura
ODOO_PASSWORD=tu_api_key              # API key, NO la contraseña humana
EXTRACT_FROM_DATE=2024-07-01          # fecha de corte para histórico
```

**Importante sobre la API key**: en Odoo 14 ve a tu usuario, pestaña
"Account Security", "New API Key". No uses tu contraseña personal.

### 3. Ejecutar extracción inicial

```bash
python -m scripts.extraer_inicial
```

Verás logs en pantalla. La extracción completa típicamente toma entre
3 y 15 minutos dependiendo del volumen.

Output esperado al final:

```
============================================================
COMPLETADO en 487.3s
Total registros: 12453
Modelos OK:      7
Modelos fallo:   0
============================================================
```

### 4. Validar la extracción

```bash
python -m scripts.validar
```

Este script compara los conteos en Odoo contra los conteos en la base
local. Si algo no coincide te dice qué.

### 5. Inspeccionar la base SQLite

```bash
# Si tienes sqlite3 instalado:
sqlite3 tbs.db

# Comandos útiles dentro de sqlite3:
.tables                    # ver todas las tablas
.schema raw_sale_order     # ver el schema de una tabla
SELECT COUNT(*) FROM raw_sale_order;
SELECT name, amount_total FROM raw_sale_order ORDER BY date_order DESC LIMIT 10;
```

Alternativamente puedes abrir `tbs.db` con [DB Browser for SQLite](https://sqlitebrowser.org/)
para verlo gráficamente.

## Configurar extracción incremental (cron)

Una vez que la extracción inicial funcione, configura el cron job para
mantener los datos frescos.

### Linux/Mac (crontab):

```bash
crontab -e
```

Agrega esta línea (cambia la ruta absoluta a tu instalación):

```
0 */4 * * * cd /home/usuario/tbs_dashboard && /home/usuario/tbs_dashboard/venv/bin/python -m scripts.extraer_incremental >> logs/cron.log 2>&1
```

### Windows (Task Scheduler):

1. Abre "Task Scheduler"
2. "Create Basic Task"
3. Trigger: cada 4 horas
4. Action: Start a program
5. Program: `C:\ruta\tbs_dashboard\venv\Scripts\python.exe`
6. Arguments: `-m scripts.extraer_incremental`
7. Start in: `C:\ruta\tbs_dashboard`

## Estructura de la base SQLite

Tablas crudas (espejo de Odoo):
- `raw_sale_order` — órdenes de venta
- `raw_sale_order_line` — líneas de orden con SKU
- `raw_account_move` — facturas y notas crédito
- `raw_partner` — clientes
- `raw_product` — productos/SKU
- `raw_user` — vendedores
- `raw_product_category` — categorías de producto

Tablas analíticas (se llenan en Día 2):
- `dim_cliente`, `dim_vendedor`, `dim_producto`
- `fct_orden`, `fct_orden_linea`, `fct_cartera`

Bitácora:
- `log_extraccion` — registro de cada corrida

## Solución de problemas

### "Autenticacion fallida"
- Verifica que `ODOO_DB` sea exactamente el nombre de la base (mayúsculas/minúsculas importan)
- Confirma que la API key sea de un usuario con acceso de lectura
- Prueba la URL en el navegador para confirmar que el servidor responde

### "No se puede contactar Odoo"
- Verifica conectividad: `curl https://tu-empresa.odoo.com`
- Si Odoo está detrás de VPN, conéctate primero
- Revisa que no haya firewall bloqueando XML-RPC (puertos 80/443)

### Extracción muy lenta
- Normal en primera corrida con histórico grande
- Reduce `EXTRACT_FROM_DATE` para traer menos histórico
- El timeout default de Odoo es 60s; bloques de 500 registros respetan esto

### "fallaron N modelos"
- Revisa `logs/extraccion_*.log` para detalles
- Generalmente es un campo que cambió en tu instalación de Odoo
- Re-ejecuta: la extracción es idempotente

## Próximos pasos

Una vez que tengas la extracción funcionando y validada:

- **Día 2**: ejecutar el script de construcción del modelo analítico
  (`python -m scripts.construir_modelo`) y arrancar la API
- **Día 3**: levantar el dashboard HTML y conectar la integración Claude

Estos están en los archivos siguientes del proyecto.
