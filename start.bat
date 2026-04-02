@echo off
chcp 65001 >nul 2>&1
title Evo Qwen3TTS Server
color 0A

cd /d "%~dp0"

echo.
echo ================================================
echo   Evo Qwen3TTS Server Startup
echo ================================================
echo.

set "PYTHON_CMD="

if exist "python\python.exe" (
    set "PYTHON_CMD=%~dp0python\python.exe"
    echo   Using portable Python
    goto :found
)

if exist "venv\Scripts\python.exe" (
    set "PYTHON_CMD=%~dp0venv\Scripts\python.exe"
    echo   Using virtual environment Python
    goto :found
)

where python >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python"
    echo   Using system Python
    goto :found
)

echo   [ERROR] Python was not found.
echo   Run install.bat first.
echo.
pause
exit /b 1

:found
%PYTHON_CMD% -c "import fastapi; import qwen_tts" 2>nul
if %errorlevel% neq 0 (
    echo   [ERROR] Dependencies are not installed.
    echo   Run install.bat first.
    echo.
    pause
    exit /b 1
)

set "HAS_06=0"
set "HAS_17=0"
if exist "models\0.6B" set "HAS_06=1"
if exist "models\1.7B" set "HAS_17=1"

if "%HAS_06%"=="0" if "%HAS_17%"=="0" (
    echo   [ERROR] No model was found in the models folder.
    echo.
    echo   Evo Qwen3TTS needs at least one model to generate audio.
    echo   The easiest fix is to run install.bat and choose a model download option.
    echo.
    set /p "OPEN_INSTALL=  Open install.bat now? (Y/N): "
    if /i "%OPEN_INSTALL%"=="Y" (
        start "" "%~dp0install.bat"
    )
    echo.
    pause
    exit /b 1
)

if exist "%~dp0ffmpeg\ffmpeg.exe" set "PATH=%~dp0ffmpeg;%PATH%"

echo   Starting API on port 5050...
echo   The web interface will open automatically.
echo   System docs: http://localhost:5050/docs.html
echo   API docs: http://localhost:5050/api-docs
echo.
echo   To stop the server, close this window.
echo.

start "" cmd /c "timeout /t 6 /nobreak >nul && start http://localhost:5050"
%PYTHON_CMD% app\api.py

pause
