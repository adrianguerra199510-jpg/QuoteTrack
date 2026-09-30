@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv" (
    python -m venv .venv
)

call .venv\Scripts\activate.bat
pip install -r requirements.txt
pip install pyinstaller

pyinstaller --noconfirm --clean --windowed --name QuoteTrack main.py

echo.
echo Listo. Ejecutable en dist\QuoteTrack\QuoteTrack.exe
pause
