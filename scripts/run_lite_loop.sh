#!/bin/bash
# run_lite_loop.sh — 循环运行 lite 纠错直到完成
# 用法: bash scripts/run_lite_loop.sh [batch_001|batch_002|all]

set +e  # 不因错误退出

BATCH="${1:-batch_002}"
MAX_ITERATIONS=100  # 安全上限

echo "========================================"
echo "LLM OCR Lite Correction Loop"
echo "Batch: $BATCH"
echo "========================================"

for i in $(seq 1 $MAX_ITERATIONS); do
  echo ""
  echo "--- Iteration $i ---"

  # 运行一批
  node scripts/llm_ocr_corrector_lite.js --batch "$BATCH" --lite-threshold 0.8 --combine 1 --limit 20

  # 检查是否完成
  REMAINING=$(node -e "
    const fs = require('fs');
    try {
      const records = JSON.parse('[' + fs.readFileSync('data/batches/$BATCH/pages.jsonl','utf8').split('\n').filter(l=>l.trim()).join(',') + ']');
      let cp = []; let fp = [];
      try { cp = JSON.parse(fs.readFileSync('data/batches/$BATCH/pages.jsonl.lite_corrected.json','utf8')); } catch(e) {}
      try { fp = JSON.parse(fs.readFileSync('data/batches/$BATCH/pages.jsonl.lite_failed.json','utf8')); } catch(e) {}
      const done = new Set([...cp, ...fp]);
      const remaining = records.filter(r => r.pipeline_stage === 'visual_ocr' && r.confidence < 0.8 && r.char_count > 20 && !done.has(r.id)).length;
      console.log(remaining);
    } catch(e) { console.log('0'); }
  " 2>/dev/null || echo "1")

  echo "Remaining: $REMAINING"

  if [ "$REMAINING" -le 0 ]; then
    echo "DONE! All records processed."
    break
  fi

  # 暂停，避免 API 过载
  echo "Pausing 5s before next iteration..."
  sleep 5
done

echo ""
echo "========================================"
echo "Final stats:"
echo "Corrected: $(cat data/batches/$BATCH/pages.jsonl.lite_corrected.json 2>/dev/null | tr ',' '\n' | grep -c '"book' 2>/dev/null || echo 0)"
echo "Failed: $(cat data/batches/$BATCH/pages.jsonl.lite_failed.json 2>/dev/null | tr ',' '\n' | grep -c '"book' 2>/dev/null || echo 0)"
echo "In file: $(grep -c 'visual_ocr_llm_corrected' data/batches/$BATCH/pages.jsonl 2>/dev/null || echo 0)"
