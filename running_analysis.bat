@echo off
echo Starting FIT file analysis...
echo.

for %%f in ("FIT Files\*.fit") do (
    echo Analyzing %%f...
    uv run python analyzer.py "%%f" --force
)

echo.
echo Analysis complete. All JSON files have been generated in the "Analyzed JSON Files" folder.
pause
