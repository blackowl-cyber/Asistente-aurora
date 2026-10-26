@echo off
REM Inicia el servidor y el agente de Aurora en esta PC, cada uno en su ventana.
REM Ejecutalo desde la carpeta del proyecto (donde esta el archivo .env).
cd /d "%~dp0.."
start "Aurora - servidor" cmd /k ".venv\Scripts\aurora-servidor.exe"
timeout /t 3 /nobreak >nul
start "Aurora - agente de PC" cmd /k ".venv\Scripts\aurora-agente.exe"
