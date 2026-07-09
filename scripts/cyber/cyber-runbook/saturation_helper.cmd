@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
where py.exe >nul 2>nul
if not errorlevel 1 (
  py -3 "%SCRIPT_DIR%saturation_helper.py" %*
  exit /b %ERRORLEVEL%
)
python "%SCRIPT_DIR%saturation_helper.py" %*
exit /b %ERRORLEVEL%
