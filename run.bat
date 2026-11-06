@echo off
cd /d "%~dp0"
if "%~1"=="" (python src\main.py --config config.xml) else (python src\main.py --config "%~1")
