# QuoteTrack

App de escritorio para creación, gestión y seguimiento de **cotizaciones** y generación de **facturas**.

## Estado

Proyecto en fase inicial (scaffold). Pensado para desarrollarse con Claude Code.

## Stack

- Python 3.10+
- PySide6 (interfaz gráfica)
- SQLite (almacenamiento local, archivo `quotetrack.db`)
- PyInstaller (para compilar a `.exe` más adelante, igual que PlacaBasePro)

## Funcionalidad prevista

- [ ] **Cotizaciones**: crear, editar, listar, cambiar estado (borrador / enviada / aprobada / rechazada), buscar por cliente.
  - [x] Items de cotización: tabla editable (descripción, cantidad, precio), subtotal, ITBMS 7% y total automáticos. Solo se editan cotizaciones en `borrador`.
  - [x] Cambio de estado: borrador → enviada → aprobada / rechazada (para enviar se requiere al menos una línea)
  - [ ] Búsqueda y filtros
- [ ] **Facturas**: generar factura a partir de una cotización aprobada, numeración consecutiva, listado y seguimiento de pago (pendiente / pagada / vencida).
  - [x] Generar factura desde cotización aprobada (`FAC-AAAA-NNNN`, estado `pendiente`, una sola factura por cotización)
  - [ ] Seguimiento de pago
- [x] **Clientes**: catálogo básico de clientes (nombre, RUC/cédula, contacto).
- [ ] **Reportes**: exportar cotización o factura a PDF.

## Instalación (desarrollo)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Compilar a ejecutable portable

```bash
build_portable.bat
```

Deja el ejecutable en `dist\QuoteTrack\QuoteTrack.exe` y un `QuoteTrack_portable.zip` para compartir.
