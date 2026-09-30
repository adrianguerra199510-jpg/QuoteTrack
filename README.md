# QuoteTrack

App de escritorio para creación, gestión y seguimiento de **cotizaciones** y generación de **facturas**.

## Estado

Funcionalidad principal implementada (ver lista abajo). El formato visual de los PDF es básico y se afinará después.

## Stack

- Python 3.10+
- PySide6 (interfaz gráfica)
- SQLite (almacenamiento local, archivo `quotetrack.db`)
- PyInstaller (para compilar a `.exe` más adelante, igual que PlacaBasePro)

## Funcionalidad

- [x] **Cotizaciones**: crear, editar, listar, cambiar estado (borrador / enviada / aprobada / rechazada), buscar por cliente.
  - [x] Items de cotización: tabla editable (descripción, cantidad, precio), subtotal, ITBMS 7% y total automáticos. Solo se editan cotizaciones en `borrador`.
  - [x] Cambio de estado: borrador → enviada → aprobada / rechazada (para enviar se requiere al menos una línea)
  - [x] Notas / Términos y condiciones: texto multilínea bajo los items, plantilla por defecto editable en la pestaña Configuración (con «Restaurar plantilla original») e insertable con «Insertar plantilla»; se copia a la factura (editable con «Editar notas») y se imprime en el PDF bajo el total
  - [x] Proyecto por cotización; descripciones multilínea y precios con formato `B/. 23,551.60`
  - [x] Búsqueda y filtros: por cliente o número y por estado, en Cotizaciones y Facturas
- [x] **Facturas**: generar factura a partir de una cotización aprobada, numeración consecutiva, listado y seguimiento de pago (pendiente / pagada / vencida).
  - [x] Generar factura desde cotización aprobada (`FAC-AAAA-NNNN`, estado `pendiente`, una sola factura por cotización)
  - [x] Seguimiento de pago: marcar como pagada (con fecha de pago) o vencida; filas vencidas en rojo y pagadas en verde
- [x] **Configuración**: datos de la empresa para el PDF, tasa de ITBMS (0 = exento), mostrar estado en el PDF y plantilla de notas.
- [x] **Clientes**: catálogo básico de clientes (nombre, RUC/cédula, contacto).
- [x] **Reportes**: exportar cotización o factura a PDF (botón "Exportar PDF" en ambas pestañas, con reportlab; el estado no se imprime salvo activar «Mostrar estado en el PDF» en Configuración; encabezado con empresa/subtítulo/correo configurables).

## Instalación (desarrollo)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Pruebas

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Datos de ejemplo

`python scripts/ejemplo_curio.py` crea la cotización de ejemplo «Torres Curio A y B» (no se ejecuta sola ni toca cotizaciones existentes).

## Compilar a ejecutable portable

```bash
build_portable.bat
```

Deja el ejecutable en `dist\QuoteTrack\QuoteTrack.exe` y un `QuoteTrack_portable.zip` para compartir.
