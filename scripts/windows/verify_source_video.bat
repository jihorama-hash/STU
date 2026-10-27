@echo off
setlocal

for %%I in ("%~dp0\..\..") do set "REPOSITORY_ROOT=%%~fI"
set "SOURCE_VIDEO=%REPOSITORY_ROOT%\data\raw\before\DJI_0482.MP4"
set "EXPECTED_SHA256=168c20eede240300371aff34a53d2617a4f1f5fe8b2dad37f16016c016c39cf0"

if not exist "%SOURCE_VIDEO%" (
    echo [ERROR] Source video is missing:
    echo %SOURCE_VIDEO%
    pause
    exit /b 1
)

echo Checking the DJI_0482.MP4 SHA-256. This can take a little while...
certutil -hashfile "%SOURCE_VIDEO%" SHA256 | findstr /i "%EXPECTED_SHA256%" >nul
if errorlevel 1 (
    echo [ERROR] The source video checksum does not match the approved R01 source.
    pause
    exit /b 1
)

echo Source video checksum: OK
pause
exit /b 0
