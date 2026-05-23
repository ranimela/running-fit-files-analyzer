@echo off
:: Change working directory to the directory of this batch file
cd /d "%~dp0"

echo Current directory set to: %CD%

:: Locate the uv executable
where uv >nul 2>nul
if %errorlevel% equ 0 (
    set UV_CMD=uv
) else (
    if exist "%USERPROFILE%\.local\bin\uv.exe" (
        set UV_CMD="%USERPROFILE%\.local\bin\uv.exe"
    ) else (
        echo Error: uv executable not found. Please ensure uv is installed or add it to PATH.
        if "%~1" neq "/scheduled" pause
        exit /b 1
    )
)

echo Fetching new running FIT files from Garmin Connect...
%UV_CMD% run python fetch_running_fits.py
echo.

echo Starting FIT file analysis...
echo.

for %%f in ("FIT Files\*.fit") do (
    %UV_CMD% run python analyzer.py "%%f"
)

echo.
echo Analysis complete. All JSON files have been generated in the "Analyzed JSON Files" folder.

:: Only pause if not running via Scheduler
if "%~1" neq "/scheduled" (
    pause
)
