@echo off
TITLE Quant Trader System Launcher
color 0A

echo ===================================================
echo     INICIANDO QUANT TRADER SYSTEM (BOT + DASH)     
echo ===================================================
echo.
echo [!] NOTA: Se configuro el servidor en el puerto 5174 
echo     para evitar conflictos con el puerto 8000.
echo.
echo Abriendo navegador en el Dashboard...
start http://127.0.0.1:5174/dashboard/
echo.
echo Presiona Ctrl+C en esta ventana para cerrar el sistema completo.
echo.

python launcher.py
pause
