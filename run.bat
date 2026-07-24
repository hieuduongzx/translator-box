@echo off
cd /d "%~dp0"

if not exist "python-app\main.py" (
    echo Khong tim thay python-app\main.py.
    pause
    exit /b 1
)

set "PYW=%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"

start "" "%PYW%" "python-app\main.py"
exit /b
