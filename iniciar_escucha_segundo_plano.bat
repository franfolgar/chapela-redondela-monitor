@echo off
title Bot Agenda Chapela y Redondela - Escucha en vivo
cd /d "%~dp0"
echo ========================================================
echo Bot de Telegram activo y escuchando en tiempo real.
echo Cada vez que un amigo pulse /start, le respondera al instante.
echo Puedes dejar esta ventana minimizada.
echo ========================================================
python monitor.py --listen
pause
