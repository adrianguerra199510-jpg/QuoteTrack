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
  - [x] Notas / Términos y condiciones: texto multilínea bajo los items, plantilla por defecto editable (botones «Insertar plantilla» / «Editar plantilla…»); se copia a la factura y se imprime en el PDF bajo el total
  - [x] Búsqueda y filtros: por cliente o número y por estado, en Cotizaciones y Facturas
- [x] **Facturas**: generar factura a partir de una cotización aprobada, numeración consecutiva, listado y seguimiento de pago (pendiente / pagada / vencida).
  - [x] Generar factura desde cotización aprobada (`FAC-AAAA-NNNN`, estado `pendiente`, una sola factura por cotización)
  - [x] Seguimiento de pago: marcar como pagada (con fecha de pago) o vencida; filas vencidas en rojo y pagadas en verde
- [x] **Clientes**: catálogo básico de clientes (nombre, RUC/cédula, contacto).
- [x] **Reportes**: exportar cotización o factura a PDF (botón "Exportar PDF" en ambas pestañas, con reportlab; el estado «borrador» no se imprime salvo que se marque la opción).

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

## Compilar a ejecutable portable

```bash
build_portable.bat
```

Deja el ejecutable en `dist\QuoteTrack\QuoteTrack.exe` y un `QuoteTrack_portable.zip` para compartir.
