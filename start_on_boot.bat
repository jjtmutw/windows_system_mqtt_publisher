@echo off
setlocal

rem Windows System MQTT Publisher startup script.
rem Put a shortcut to this file in shell:startup, or run it from Task Scheduler.

cd /d "%~dp0"

set "MQTT_HOST=broker.emqx.io"
set "MQTT_PORT=1883"
set "MQTT_USERNAME="
set "MQTT_PASSWORD="
set "MQTT_TOPIC=jj/windows/system/status"
set "DASHBOARD_PORT=8088"

set "PYTHON_EXE=python"
if exist "%~dp0.venv\Scripts\python.exe" (
  set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
)

rem Start LibreHardwareMonitor if the WMI-capable copy exists.
set "LHM_EXE=C:\tmp\LibreHardwareMonitor-v0.9.4\LibreHardwareMonitor.exe"
if exist "%LHM_EXE%" (
  tasklist /FI "IMAGENAME eq LibreHardwareMonitor.exe" 2>NUL | find /I "LibreHardwareMonitor.exe" >NUL
  if errorlevel 1 (
    start "LibreHardwareMonitor" /min "%LHM_EXE%"
  )
)

rem Start MQTT publisher in a minimized console.
start "Windows System MQTT Publisher" /min "%PYTHON_EXE%" "%~dp0app.py"

rem Start dashboard web server for mobile browser access.
rem start "Windows System Dashboard HTTP" /min "%PYTHON_EXE%" -m http.server %DASHBOARD_PORT% --bind 0.0.0.0

endlocal
