@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv" (
    python -m venv .venv
)

call .venv\Scripts\activate.bat
pip install -r requirements.txt
pip install -r requirements-dev.txt
pip install pyinstaller

echo.
echo Ejecutando pruebas...
python -m pytest -q
if errorlevel 1 (
    echo.
    echo Las pruebas fallaron; no se genera el ejecutable.
    pause
    exit /b 1
)

pyinstaller --noconfirm --clean --windowed --name QuoteTrack --icon assets\icon.ico --add-data "assets;assets" main.py

echo.
echo Listo. Ejecutable en dist\QuoteTrack\QuoteTrack.exe
pause
