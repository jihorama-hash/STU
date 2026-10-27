@echo off
setlocal

for %%I in ("%~dp0\..\..") do set "REPOSITORY_ROOT=%%~fI"
set "REVIEW_PYTHON=%REPOSITORY_ROOT%\.venv-review\Scripts\python.exe"
set "REVIEW_APP=%REPOSITORY_ROOT%\apps\demo\blind_gt_review.py"
set "SOURCE_VIDEO=%REPOSITORY_ROOT%\data\raw\before\DJI_0482.MP4"

if not exist "%REVIEW_PYTHON%" (
    echo [ERROR] Reviewer environment is missing.
    echo Run setup_blind_gt_review.bat first.
    pause
    exit /b 1
)

if not exist "%SOURCE_VIDEO%" (
    echo [ERROR] Source video is missing:
    echo %SOURCE_VIDEO%
    echo Copy DJI_0482.MP4 to data\raw\before and try again.
    pause
    exit /b 1
)

cd /d "%REPOSITORY_ROOT%"
echo Starting the blind-GT reviewer at http://127.0.0.1:8502
echo Keep this window open. Press Ctrl+C here to stop the reviewer.
"%REVIEW_PYTHON%" "%REVIEW_APP%" --open-browser

if errorlevel 1 (
    echo.
    echo [ERROR] The reviewer stopped with an error.
    pause
    exit /b 1
)
exit /b 0
