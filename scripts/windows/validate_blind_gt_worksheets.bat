@echo off
setlocal

for %%I in ("%~dp0\..\..") do set "REPOSITORY_ROOT=%%~fI"
set "REVIEW_PYTHON=%REPOSITORY_ROOT%\.venv-review\Scripts\python.exe"

if not exist "%REVIEW_PYTHON%" (
    echo [ERROR] Run setup_blind_gt_review.bat first.
    pause
    exit /b 1
)

cd /d "%REPOSITORY_ROOT%"
"%REVIEW_PYTHON%" "%REPOSITORY_ROOT%\scripts\blind_gt_review_viewer.py" --validate-only
set "VALIDATION_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %VALIDATION_EXIT%
