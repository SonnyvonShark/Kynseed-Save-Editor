@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 kynseed_save_editor.py
) else (
  python kynseed_save_editor.py
)
if errorlevel 1 pause
