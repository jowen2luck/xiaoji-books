@echo off
chcp 65001 >nul
echo [Notebook] Shard 4 - 329 books (~119,739 pages)
echo.

set SHARE=\\192.168.1.171\booklib
set PROJECT=%SHARE%

where py >nul 2>&1 && set PYCMD=py -3
if not defined PYCMD (
    where python >nul 2>&1 && set PYCMD=python
)
if not defined PYCMD (
    echo ERROR: Python not found. Run notebook_setup.bat first.
    pause
    exit /b 1
)

net use Z: %SHARE% /persistent:no >nul 2>&1
echo Starting shard 4...
echo.

cd /d %PROJECT%

%PYCMD% scripts\pipeline\batch_ingest.py ^
  --manifest %PROJECT%\data\.shards\shard-4\manifest.jsonl ^
  --base-dir %PROJECT%\data\_kage\www.marxists.org ^
  --status-filter "ocr_required,partial_text" ^
  --output-dir %PROJECT%\data\evidence\shard4 ^
  --checkpoint %PROJECT%\data\shard4_checkpoint.jsonl ^
  --dpi 200

echo.
echo [Notebook] Shard 4 Finished!
pause
