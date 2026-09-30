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

- **Cotizaciones**: crear, editar, listar, cambiar estado (borrador / enviada / aprobada / rechazada), buscar por cliente.
- **Facturas**: generar factura a partir de una cotización aprobada, numeración consecutiva, listado y seguimiento de pago (pendiente / pagada / vencida).
- **Clientes**: catálogo básico de clientes (nombre, RUC/cédula, contacto).
- **Reportes**: exportar cotización o factura a PDF.

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
