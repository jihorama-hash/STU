@echo off
setlocal

for %%I in ("%~dp0\..\..") do set "REPOSITORY_ROOT=%%~fI"
set "REVIEW_VENV=%REPOSITORY_ROOT%\.venv-review"

where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python launcher was not found.
    echo Install 64-bit Python 3.11 or newer from https://www.python.org/downloads/windows/
    echo Enable the Python launcher during installation, then run this file again.
    pause
    exit /b 1
)

py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
    echo [ERROR] Python 3.11 or newer is required.
    pause
    exit /b 1
)

if not exist "%REVIEW_VENV%\Scripts\python.exe" (
    echo Creating the reviewer environment...
    py -3 -m venv "%REVIEW_VENV%"
    if errorlevel 1 goto :failed
)

echo Installing the two reviewer dependencies...
"%REVIEW_VENV%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
"%REVIEW_VENV%\Scripts\python.exe" -m pip install "numpy>=1.26,<3" "opencv-python-headless>=4.9,<5"
if errorlevel 1 goto :failed

echo.
echo Setup complete. Run run_blind_gt_review.bat next.
pause
exit /b 0

:failed
echo.
echo [ERROR] Setup failed. Review the messages above.
pause
exit /b 1
