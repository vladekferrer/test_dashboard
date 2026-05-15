# TBS DESTILADOS — Base de conocimiento estrategico

> Este archivo contiene SOLO conocimiento estable: el modelo de negocio, los
> umbrales de alerta, la logica de la estrategia, el portafolio y el contexto
> de mercado. Cambia con decisiones estrategicas, no con la operacion.
>
> NO contiene perfiles de vendedores, porcentajes de GMV actuales, estados de
> hoteles ni cifras del mes. Esa informacion se inyecta en tiempo real desde la
> base de datos en la seccion "CONTEXTO ACTUAL" del prompt.

## Contexto del negocio

TBS DESTILADOS SAS es un subdistribuidor de licores premium en el canal HORECA
(hoteles, restaurantes, bares, clubes) en Cartagena, Colombia.
El portafolio se concentra en licores importados premium: whisky escoces y americano,
vinos, espumantes, gin, mezcal, tequila, ron premium, vodka y aperitivos.
Se excluye aguardiente y ron de bandera nacional por restricciones del monopolio
departamental de Bolivar.

El negocio es a credito (la gran mayoria de las ventas), relacional, y con
estacionalidad fuerte. El vendedor es el activo principal del negocio.

## Metricas clave y umbrales de alerta

| Metrica | Estado sano | Alerta amarilla | Alerta roja |
|---|---|---|---|
| GMV mensual (sin impuestos) | >$180M | $140-180M | <$140M |
| Cuentas activas | >=110 | 90-110 | <90 |
| Margen bruto | >20% | 17-20% | <17% |
| Cartera vencida >30d | <8% | 8-12% | >12% |
| Dias promedio cobro | <=45 dias | 46-55 dias | >55 dias |
| Dias sin pedido (cuenta top 30) | <=14 dias | 15-21 dias | >21 dias |

## Estrategia central: densificacion de los hoteles top

Existe un grupo de ~9 hoteles que concentra cerca del 39% del GMV recurrente.
La estrategia central NO es captar clientes nuevos, es vender mas categorias del
portafolio a los hoteles que ya compran.

La metrica es profundidad de portafolio: cuantas de las 8 categorias core del
portafolio TBS compra cada hotel. No se usa Share of Wallet porque TBS no conoce
el gasto total del hotel en licores; la profundidad de portafolio se mide exacto
con datos de Odoo y es igualmente accionable.

Las 8 categorias core del portafolio TBS:
Whisky, Vinos, Espumantes, Gin, Mezcal/Tequila, Ron, Vodka, Aperitivos.

La tactica de densificacion: identificar las categorias core que cada hotel NO
compra (white space), proponerlas al bartender o al area de A&B con curaduria y
storytelling, y medir la penetracion de categorias adicionales mes a mes.

La logica economica: si cada hotel top sube de 3-4 categorias a 5-6, el GMV
recurrente puede crecer de forma significativa sin sumar un solo cliente nuevo,
y el costo de lograrlo es mucho menor que el de captar cuentas nuevas.

> La lista concreta de hoteles objetivo, cuantas categorias tiene cada uno hoy y
> cuales son sus huecos viene en el contexto en vivo, no aqui.

## Portafolio y categorias

Prioridad alta (margen >15%, diferenciacion):
whisky single malt, mezcal artesanal, espumantes premium, gin de cocteleria,
vermouth y aperitivos, ron premium importado, vinos premium.

Prioridad media (volumen con margen moderado):
whisky estandar, vodka, tequila, vinos de entrada.

Excluir en Fase 1: aguardiente nacional (monopolio departamental),
cervezas (canal propio de las cerveceras), ron de bandera nacional (monopolio).

Los proveedores estan concentrados: unos pocos representan la mayor parte del
COGS, lo que abre una oportunidad de renegociar margen escalonado por volumen.

## Modelo de credito y cartera

La gran mayoria de las ventas son a credito, con un plazo promedio cercano a 45
dias. Esto genera una exposicion permanente en cartera que hay que vigilar.

Politica de credito:
- Cuentas nuevas: contado los 3 primeros pedidos
- Bares y discotecas: maximo 15-30 dias
- Restaurantes y hoteles boutique: 30 dias
- Hoteles cadena con orden de compra formal: 30-45 dias
- Stop de despacho: >30 dias sin pago
- Cobranza formal: >60 dias sin pago

## Contexto de mercado en Cartagena

Estacionalidad pronunciada: pico diciembre-marzo (temporada turistica),
valle mayo-septiembre (caida fuerte frente al pico).
El canal HORECA Caribe sigue siendo relacional: el vendedor es el activo
principal. WhatsApp es el canal digital de adopcion real, no los portales.
Competencia principal: Dislicores, Distribuidora Glasgow, Lehner Wines.
Diferenciadores de TBS: curaduria de portafolio premium, capacidad de pedido
urgente, servicio de bartender y activacion de marca.

## Indicadores de exito a 6 meses

- EBITDA positivo sostenido
- GMV mensual >$220M (sin impuestos)
- Cuentas activas >120
- Profundidad de portafolio promedio en los hoteles top >=5 categorias activas
- Cartera vencida <8%
- Cuentas huerfanas (sin vendedor) resueltas y recuperadas

El negocio tiene que llegar a EBITDA positivo sostenido antes de plantear
cualquier expansion geografica.
