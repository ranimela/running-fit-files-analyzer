@echo off
echo Fetching new running FIT files from Garmin Connect...
uv run python fetch_running_fits.py
echo.

echo Starting FIT file analysis...
echo.

for %%f in ("FIT Files\*.fit") do (
    uv run python analyzer.py "%%f"
)

echo.
echo Analysis complete. All JSON files have been generated in the "Analyzed JSON Files" folder.
pause
