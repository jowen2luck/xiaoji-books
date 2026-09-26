@echo off
chcp 65001 >nul
echo [Host] Shard 2 - 331 books (~119,740 pages)
echo.

set PROJECT=D:\Pcode\play\_skills\book-library-skill
cd /d %PROJECT%

echo Starting shard 2 in this window...
echo.

python scripts\pipeline\batch_ingest.py ^
  --manifest %PROJECT%\data\.shards\shard-2\manifest.jsonl ^
  --base-dir %PROJECT%\data\_kage\www.marxists.org ^
  --status-filter "ocr_required,partial_text" ^
  --output-dir %PROJECT%\data\evidence\shard2 ^
  --checkpoint %PROJECT%\data\shard2_checkpoint.jsonl ^
  --dpi 200

echo.
echo [Host] Shard 2 Finished!
pause
