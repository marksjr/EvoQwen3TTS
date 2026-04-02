@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title Evo Qwen3TTS Installer
color 0B

cd /d "%~dp0"

set "PROJECT_DIR=%~dp0"
set "PORTABLE_PYTHON=%PROJECT_DIR%python\python.exe"
set "VENV_PYTHON=%PROJECT_DIR%venv\Scripts\python.exe"
set "PYTHON_CMD="
set "PIP_CMD="
set "USE_CPU=0"

goto :main

:check_required_file
if exist "%~1" exit /b 0
echo   [ERROR] Missing %~1
exit /b 1

:resolve_python
if exist "%PORTABLE_PYTHON%" (
    "%PORTABLE_PYTHON%" -c "import sys" >nul 2>&1
    if errorlevel 1 (
        echo   [WARNING] Portable Python exists but is not usable. Reinstalling...
    ) else (
        for /f "tokens=*" %%i in ('"%PORTABLE_PYTHON%" --version 2^>^&1') do echo   [OK] Portable Python found: %%i
        set "PYTHON_CMD=%PORTABLE_PYTHON%"
        call :ensure_pip
        exit /b %errorlevel%
    )
)

if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" -c "import sys" >nul 2>&1
    if errorlevel 1 (
        echo   [WARNING] Existing virtual environment is invalid. Recreating...
    ) else (
        for /f "tokens=*" %%i in ('"%VENV_PYTHON%" --version 2^>^&1') do echo   [OK] Existing virtual environment found: %%i
        set "PYTHON_CMD=%VENV_PYTHON%"
        set "PIP_CMD=%VENV_PYTHON% -m pip"
        exit /b 0
    )
)

python -c "import sys" >nul 2>&1
if errorlevel 1 goto :install_portable_python

for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo   [OK] System Python found: %%i
set "PYTHON_CMD=python"
set "PIP_CMD=python -m pip"
call :ensure_venv
exit /b %errorlevel%

:install_portable_python
echo   [INFO] Python not found. Installing portable Python 3.11...
if not exist "python" mkdir "python"

powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $ProgressPreference='SilentlyContinue'; $url='https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip'; $out='%PROJECT_DIR%python\python-embed.zip'; (New-Object Net.WebClient).DownloadFile($url,$out); Expand-Archive -LiteralPath $out -DestinationPath '%PROJECT_DIR%python' -Force; Remove-Item -LiteralPath $out -Force"
if errorlevel 1 (
    echo   [ERROR] Failed to download or extract portable Python.
    exit /b 1
)

if not exist "%PORTABLE_PYTHON%" (
    echo   [ERROR] Portable Python executable was not created.
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$pth = Get-ChildItem -LiteralPath '%PROJECT_DIR%python' -Filter 'python*._pth' | Select-Object -First 1; if ($null -ne $pth) { $content = Get-Content -LiteralPath $pth.FullName; $content = $content -replace '^#import site$', 'import site'; Set-Content -LiteralPath $pth.FullName -Value $content }"
if errorlevel 1 (
    echo   [ERROR] Failed to configure portable Python.
    exit /b 1
)

set "PYTHON_CMD=%PORTABLE_PYTHON%"
call :ensure_pip
if errorlevel 1 exit /b 1

for /f "tokens=*" %%i in ('"%PORTABLE_PYTHON%" --version 2^>^&1') do echo   [OK] Portable Python installed: %%i
exit /b 0

:ensure_pip
%PYTHON_CMD% -m pip --version >nul 2>&1
if not errorlevel 1 (
    set "PIP_CMD=%PYTHON_CMD% -m pip"
    echo   [OK] pip is available
    exit /b 0
)

echo   [INFO] pip not found. Installing pip...
if not exist "%PROJECT_DIR%python" mkdir "%PROJECT_DIR%python"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $ProgressPreference='SilentlyContinue'; (New-Object Net.WebClient).DownloadFile('https://bootstrap.pypa.io/get-pip.py', '%PROJECT_DIR%python\get-pip.py')"
if errorlevel 1 (
    echo   [ERROR] Failed to download get-pip.py.
    exit /b 1
)

%PYTHON_CMD% "%PROJECT_DIR%python\get-pip.py" --no-warn-script-location
if errorlevel 1 (
    echo   [ERROR] Failed to install pip.
    exit /b 1
)

%PYTHON_CMD% -m pip --version >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] pip is still unavailable after installation.
    exit /b 1
)

set "PIP_CMD=%PYTHON_CMD% -m pip"
echo   [OK] pip installed
exit /b 0

:ensure_venv
if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        echo   [OK] Virtual environment found
        set "PYTHON_CMD=%VENV_PYTHON%"
        set "PIP_CMD=%VENV_PYTHON% -m pip"
        exit /b 0
    )
)

echo   [INFO] Creating virtual environment...
%PYTHON_CMD% -m venv venv
if errorlevel 1 (
    echo   [ERROR] Failed to create the virtual environment.
    exit /b 1
)

if not exist "%VENV_PYTHON%" (
    echo   [ERROR] Virtual environment was not created correctly.
    exit /b 1
)

set "PYTHON_CMD=%VENV_PYTHON%"
set "PIP_CMD=%VENV_PYTHON% -m pip"
echo   [OK] Virtual environment ready
exit /b 0

:check_gpu
where nvidia-smi >nul 2>&1
if errorlevel 1 goto :no_gpu

for /f "tokens=*" %%i in ('nvidia-smi -L 2^>nul') do (
    echo   [OK] GPU found: %%i
    goto :gpu_done
)
echo   [WARNING] NVIDIA GPU tools were found, but the GPU name query failed.
goto :gpu_done

:no_gpu
echo   [INFO] NVIDIA not detected. Using CPU runtime.
set "USE_CPU=1"

:gpu_done
exit /b 0

:check_ffmpeg
where ffmpeg >nul 2>&1
if not errorlevel 1 (
    echo   [OK] ffmpeg found on PATH
    exit /b 0
)

if exist "%PROJECT_DIR%ffmpeg\ffmpeg.exe" (
    set "PATH=%PROJECT_DIR%ffmpeg;%PATH%"
    echo   [OK] Portable ffmpeg found in ffmpeg\
    exit /b 0
)

%PYTHON_CMD% -c "import imageio_ffmpeg; imageio_ffmpeg.get_ffmpeg_exe()" >nul 2>&1
if not errorlevel 1 (
    echo   [OK] ffmpeg helper already available via imageio-ffmpeg
    exit /b 0
)

echo   [INFO] Installing ffmpeg helper package...
%PIP_CMD% install imageio-ffmpeg --no-warn-script-location
if errorlevel 1 (
    echo   [ERROR] Failed to install ffmpeg helper package.
    exit /b 1
)

%PYTHON_CMD% -c "import imageio_ffmpeg; imageio_ffmpeg.get_ffmpeg_exe()" >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] ffmpeg helper package was installed but validation failed.
    exit /b 1
)

echo   [OK] ffmpeg helper installed
exit /b 0

:check_pytorch
if "%USE_CPU%"=="1" goto :check_pytorch_cpu

%PYTHON_CMD% -c "import torch; raise SystemExit(0 if torch.cuda.is_available() else 1)" >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%v in ('%PYTHON_CMD% -c "import torch; print(torch.__version__)" 2^>nul') do echo   [OK] PyTorch %%v with CUDA is already installed
    exit /b 0
)

echo   [INFO] Installing PyTorch with CUDA 12.6...
%PIP_CMD% install torch torchaudio --index-url https://download.pytorch.org/whl/cu126 --no-warn-script-location
if errorlevel 1 (
    echo   [ERROR] Failed to install PyTorch with CUDA support.
    exit /b 1
)

%PYTHON_CMD% -c "import torch; raise SystemExit(0 if torch.cuda.is_available() else 1)" >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] PyTorch was installed but CUDA validation failed.
    exit /b 1
)

for /f "tokens=*" %%v in ('%PYTHON_CMD% -c "import torch; print(torch.__version__)" 2^>nul') do echo   [OK] PyTorch %%v with CUDA is ready
exit /b 0

:check_pytorch_cpu
%PYTHON_CMD% -c "import torch" >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%v in ('%PYTHON_CMD% -c "import torch; print(torch.__version__)" 2^>nul') do echo   [OK] PyTorch %%v is already installed
    exit /b 0
)

echo   [INFO] Installing PyTorch for CPU...
%PIP_CMD% install torch torchaudio --index-url https://download.pytorch.org/whl/cpu --no-warn-script-location
if errorlevel 1 (
    echo   [ERROR] Failed to install PyTorch for CPU.
    exit /b 1
)

%PYTHON_CMD% -c "import torch" >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] PyTorch CPU installation completed but validation failed.
    exit /b 1
)

for /f "tokens=*" %%v in ('%PYTHON_CMD% -c "import torch; print(torch.__version__)" 2^>nul') do echo   [OK] PyTorch %%v is ready
exit /b 0

:check_dependencies
%PYTHON_CMD% -c "import fastapi, qwen_tts, whisper, soundfile, transformers, accelerate, huggingface_hub" >nul 2>&1
if not errorlevel 1 (
    echo   [OK] Dependencies are already installed
    exit /b 0
)

echo   [INFO] Installing project dependencies...
%PIP_CMD% install -r app\requirements.txt --no-warn-script-location
if errorlevel 1 (
    echo   [ERROR] Failed to install project dependencies.
    exit /b 1
)

%PYTHON_CMD% -c "import fastapi, qwen_tts, whisper, soundfile, transformers, accelerate, huggingface_hub" >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Dependencies were installed but validation failed.
    exit /b 1
)

echo   [OK] Dependencies installed
exit /b 0

:check_models
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

if "%HAS_06%"=="1" exit /b 0
if "%HAS_17%"=="1" exit /b 0

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
if "%MODEL_CHOICE%"=="4" exit /b 0

echo   [WARNING] Invalid option. Skipping model download.
exit /b 0

:download_model_06
echo.
echo   Downloading model 0.6B...
%PYTHON_CMD% app\download_models.py --model 0.6B --models-dir "%PROJECT_DIR%models"
if errorlevel 1 (
    echo   [ERROR] Failed to download model 0.6B.
    exit /b 1
)
exit /b 0

:download_model_17
echo.
echo   Downloading model 1.7B...
%PYTHON_CMD% app\download_models.py --model 1.7B --models-dir "%PROJECT_DIR%models"
if errorlevel 1 (
    echo   [ERROR] Failed to download model 1.7B.
    exit /b 1
)
exit /b 0

:download_model_all
echo.
echo   Downloading both models...
%PYTHON_CMD% app\download_models.py --model all --models-dir "%PROJECT_DIR%models"
if errorlevel 1 (
    echo   [ERROR] Failed to download one or more models.
    exit /b 1
)
exit /b 0

:main
echo.
echo ================================================
echo   Evo Qwen3TTS Portable Installer
echo ================================================
echo.

echo [0/6] Checking project files...
call :check_required_file "app\api.py"
call :check_required_file "app\index.html"
call :check_required_file "app\requirements.txt"
call :check_required_file "app\download_models.py"
if errorlevel 1 goto :error_exit
echo   [OK] Required app files found

echo.
echo [1/6] Checking Python...
call :resolve_python
if errorlevel 1 goto :error_exit

echo.
echo [2/6] Checking NVIDIA GPU / CUDA...
call :check_gpu
if errorlevel 1 goto :error_exit

echo.
echo [3/6] Checking ffmpeg...
call :check_ffmpeg
if errorlevel 1 goto :error_exit

echo.
echo [4/6] Checking PyTorch...
call :check_pytorch
if errorlevel 1 goto :error_exit

echo.
echo [5/6] Installing project dependencies...
call :check_dependencies
if errorlevel 1 goto :error_exit

echo.
echo [6/6] Checking local models...
call :check_models
if errorlevel 1 goto :error_exit

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
