@echo off
chcp 65001 >nul 2>&1
title Evo Qwen3TTS Installer
color 0B

cd /d "%~dp0"

echo.
echo ================================================
echo   Evo Qwen3TTS Portable Installer
echo ================================================
echo.

echo [0/6] Checking project files...
if not exist "app\api.py" (
    echo   [ERROR] Missing app\api.py
    goto :error_exit
)
if not exist "app\index.html" (
    echo   [ERROR] Missing app\index.html
    goto :error_exit
)
if not exist "app\requirements.txt" (
    echo   [ERROR] Missing app\requirements.txt
    goto :error_exit
)
if not exist "app\download_models.py" (
    echo   [ERROR] Missing app\download_models.py
    goto :error_exit
)
echo   [OK] Required app files found

echo.
echo [1/6] Checking Python...
set "PYTHON_CMD="
set "PIP_CMD="
set "PORTABLE_PYTHON=%~dp0python\python.exe"

if exist "%PORTABLE_PYTHON%" (
    echo   [OK] Portable Python found in python\
    set "PYTHON_CMD=%PORTABLE_PYTHON%"
    set "PIP_CMD=%PORTABLE_PYTHON% -m pip"
    goto :python_ok
)

if exist "venv\Scripts\python.exe" (
    echo   [OK] Existing virtual environment found
    set "PYTHON_CMD=%~dp0venv\Scripts\python.exe"
    set "PIP_CMD=%~dp0venv\Scripts\python.exe -m pip"
    goto :python_ok
)

python -c "import sys" >nul 2>&1
if errorlevel 1 goto :install_portable_python

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set "PY_VER=%%i"
echo   [OK] System Python found: %PY_VER%
set "PYTHON_CMD=python"
set "PIP_CMD=python -m pip"
goto :create_venv

:install_portable_python
echo   [INFO] Python not found. Installing portable Python 3.11...
if not exist "python" mkdir python

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; ^
    $url = 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip'; ^
    $out = '%~dp0python\python-embed.zip'; ^
    (New-Object Net.WebClient).DownloadFile($url, $out); ^
    Expand-Archive -Path $out -DestinationPath '%~dp0python' -Force; ^
    Remove-Item $out -Force"

if not exist "%PORTABLE_PYTHON%" (
    echo   [ERROR] Failed to install portable Python.
    goto :error_exit
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$pth = Get-ChildItem '%~dp0python\python*._pth' | Select-Object -First 1; ^
    if ($pth) { ^
        $content = Get-Content $pth.FullName; ^
        $content = $content -replace '^#import site', 'import site'; ^
        Set-Content $pth.FullName $content ^
    }"

echo   Installing pip...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; ^
    (New-Object Net.WebClient).DownloadFile('https://bootstrap.pypa.io/get-pip.py', '%~dp0python\get-pip.py')"

"%PORTABLE_PYTHON%" "%~dp0python\get-pip.py" --no-warn-script-location >nul 2>&1
if %errorlevel% neq 0 (
    echo   [ERROR] Failed to install pip.
    goto :error_exit
)

set "PYTHON_CMD=%PORTABLE_PYTHON%"
set "PIP_CMD=%PORTABLE_PYTHON% -m pip"
echo   [OK] Portable Python installed
goto :python_ok

:create_venv
if exist "venv\Scripts\python.exe" goto :venv_exists

echo   Creating virtual environment...
%PYTHON_CMD% -m venv venv
if errorlevel 1 (
    echo   [ERROR] Failed to create the virtual environment.
    goto :error_exit
)

:venv_exists
set "PYTHON_CMD=%~dp0venv\Scripts\python.exe"
set "PIP_CMD=%~dp0venv\Scripts\python.exe -m pip"

:python_ok
echo.
echo [2/6] Checking NVIDIA GPU / CUDA...
set "USE_CPU=0"
where nvidia-smi >nul 2>&1
if errorlevel 1 goto :no_gpu

for /f "tokens=*" %%i in ('nvidia-smi --query-gpu=name --format=csv,noheader 2^>nul') do echo   [OK] GPU found: %%i
goto :gpu_check_done

:no_gpu
echo   [WARNING] nvidia-smi was not found.
echo   This project requires an NVIDIA GPU with CUDA support.
set /p "CONTINUE_ANYWAY=  Continue anyway to use CPU (will be much slower)? (Y/N): "
if /i not "%CONTINUE_ANYWAY%"=="Y" goto :error_exit
set "USE_CPU=1"

:gpu_check_done

echo.
echo [3/6] Checking ffmpeg...
where ffmpeg >nul 2>&1
if errorlevel 1 goto :install_ffmpeg_helper

echo   [OK] ffmpeg found
goto :ffmpeg_done

:install_ffmpeg_helper
if exist "%~dp0ffmpeg\ffmpeg.exe" (
    echo   [OK] Portable ffmpeg found in ffmpeg\
    set "PATH=%~dp0ffmpeg;%PATH%"
    goto :ffmpeg_done
)

echo   Installing ffmpeg helper package...
%PIP_CMD% install imageio-ffmpeg --no-warn-script-location -q
if errorlevel 1 (
    echo   [ERROR] Failed to install ffmpeg helper package.
    goto :error_exit
)
echo   [OK] ffmpeg helper installed

:ffmpeg_done

echo.
echo [4/6] Checking PyTorch...
if "%USE_CPU%"=="1" goto :install_pytorch_cpu

%PYTHON_CMD% -c "import torch; print(torch.cuda.is_available())" 2>nul | findstr "True" >nul 2>&1
if errorlevel 1 goto :install_pytorch_cuda

for /f "tokens=*" %%v in ('%PYTHON_CMD% -c "import torch; print(torch.__version__)" 2^>nul') do echo   [OK] PyTorch %%v with CUDA is already installed
goto :pytorch_done

:install_pytorch_cuda
echo   Installing PyTorch with CUDA 12.6...
%PIP_CMD% install torch torchaudio --index-url https://download.pytorch.org/whl/cu126 --no-warn-script-location -q
if errorlevel 1 (
    echo   [ERROR] Failed to install PyTorch.
    goto :error_exit
)
echo   [OK] PyTorch installed
goto :pytorch_done

:install_pytorch_cpu
%PYTHON_CMD% -c "import torch; print(torch.__version__)" 2>nul >nul
if errorlevel 1 goto :do_install_pytorch_cpu

for /f "tokens=*" %%v in ('%PYTHON_CMD% -c "import torch; print(torch.__version__)" 2^>nul') do echo   [OK] PyTorch %%v is already installed
goto :pytorch_done

:do_install_pytorch_cpu
echo   Installing PyTorch for CPU...
%PIP_CMD% install torch torchaudio --index-url https://download.pytorch.org/whl/cpu --no-warn-script-location -q
if errorlevel 1 (
    echo   [ERROR] Failed to install PyTorch.
    goto :error_exit
)
echo   [OK] PyTorch installed

:pytorch_done

echo.
echo [5/6] Installing project dependencies...
%PYTHON_CMD% -c "import fastapi; import qwen_tts; import whisper; import soundfile" 2>nul
if errorlevel 1 goto :install_deps

echo   [OK] Dependencies are already installed
goto :deps_done

:install_deps
%PIP_CMD% install -r app\requirements.txt --no-warn-script-location -q
if errorlevel 1 (
    echo   [ERROR] Failed to install project dependencies.
    goto :error_exit
)
echo   [OK] Dependencies installed

:deps_done

echo.
echo [6/6] Checking local models...
set "HAS_06=0"
set "HAS_17=0"
if exist "models\0.6B" (
    echo   [OK] Model 0.6B found
    set "HAS_06=1"
) else (
    echo   [WARNING] Model 0.6B not found in models\0.6B
)
if exist "models\1.7B" (
    echo   [OK] Model 1.7B found
    set "HAS_17=1"
) else (
    echo   [WARNING] Model 1.7B not found in models\1.7B
)

if "%HAS_06%"=="1" if "%HAS_17%"=="1" goto :install_done

echo.
echo   Evo Qwen3TTS still needs at least one model to generate audio.
echo   Choose what you want to do:
echo     [1] Download 0.6B now   - faster and lighter (recommended)
echo     [2] Download 1.7B now   - higher quality, heavier
echo     [3] Download both models
echo     [4] Skip for now
set /p "MODEL_CHOICE=  Select an option [1-4] (default: 1): "
if "%MODEL_CHOICE%"=="" set "MODEL_CHOICE=1"

if "%MODEL_CHOICE%"=="1" goto :download_model_06
if "%MODEL_CHOICE%"=="2" goto :download_model_17
if "%MODEL_CHOICE%"=="3" goto :download_model_all
if "%MODEL_CHOICE%"=="4" goto :install_done

echo   [WARNING] Invalid option. Skipping model download.
goto :install_done

:download_model_06
echo.
echo   Downloading model 0.6B...
%PYTHON_CMD% app\download_models.py --model 0.6B --models-dir "%~dp0models"
if %errorlevel% neq 0 (
    echo   [ERROR] Failed to download model 0.6B.
    goto :error_exit
)
goto :install_done

:download_model_17
echo.
echo   Downloading model 1.7B...
%PYTHON_CMD% app\download_models.py --model 1.7B --models-dir "%~dp0models"
if %errorlevel% neq 0 (
    echo   [ERROR] Failed to download model 1.7B.
    goto :error_exit
)
goto :install_done

:download_model_all
echo.
echo   Downloading both models...
%PYTHON_CMD% app\download_models.py --model all --models-dir "%~dp0models"
if %errorlevel% neq 0 (
    echo   [ERROR] Failed to download one or more models.
    goto :error_exit
)

:install_done

echo.
echo ================================================
echo   Installation completed successfully
echo   If no model was downloaded, audio generation will not work yet.
echo   You can run install.bat again later to download a model.
echo   Run start.bat to launch the system
echo ================================================
echo.
pause
exit /b 0

:error_exit
echo.
echo [ERROR] Installation stopped. Fix the issues above and try again.
echo.
pause
exit /b 1
