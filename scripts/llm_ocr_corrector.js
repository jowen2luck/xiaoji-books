#!/usr/bin/env node
/**
 * llm_ocr_corrector.js — Use LLM to correct low-confidence OCR text
 *
 * Reads pages.jsonl (batch-local or global), finds records with confidence < threshold,
 * sends them to LongCat-2.0 API for correction, writes back corrected text.
 *
 * Features:
 * - Processes records in batches with rate limiting
 * - Uses adjacent pages for context
 * - Progress tracking (resume-safe via checkpoint file)
 * - Dry-run mode to preview without modifying files
 *
 * Usage:
 *   node scripts/llm_ocr_corrector.js [--threshold 0.85] [--dry-run] [--batch batch_002] [--global]
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');

const ROOT = path.resolve(__dirname, '..');
const BATCHES_DIR = path.join(ROOT, 'data', 'batches');
const EVIDENCE_DIR = path.join(ROOT, 'data', 'evidence');

// ── Config ──────────────────────────────────────────────────────────────────
const API_KEY = 'ak_2He1Ct7ZQ4Ib67y0Eh5ZM55y9PA8g';
const BASE_URL = 'https://api.longcat.chat/openai';
const MODEL = 'LongCat-2.0';
const DEFAULT_THRESHOLD = 0.85;
const MAX_TOKENS = 8192;
const RATE_LIMIT_MS = 200; // ms between API calls

// ── CLI args ────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
const DRY_RUN = args.includes('--dry-run');
const thresholdIdx = args.indexOf('--threshold');
const THRESHOLD = thresholdIdx >= 0 ? parseFloat(args[thresholdIdx + 1]) || DEFAULT_THRESHOLD : DEFAULT_THRESHOLD;
const BATCH_FILTER = args.includes('--batch') ? args[args.indexOf('--batch') + 1] : null;
const USE_GLOBAL = args.includes('--global');
const offsetIdx = args.indexOf('--offset');
const OFFSET = offsetIdx >= 0 ? parseInt(args[offsetIdx + 1]) || 0 : 0;
const limitIdx = args.indexOf('--limit');
const LIMIT = limitIdx >= 0 ? parseInt(args[limitIdx + 1]) || Infinity : Infinity;

// ── Helpers ─────────────────────────────────────────────────────────────────
function readJsonlSync(filePath) {
  const records = [];
  if (!fs.existsSync(filePath)) return records;
  for (const line of fs.readFileSync(filePath, 'utf8').split('\n')) {
    if (line.trim()) {
      try { records.push(JSON.parse(line)); } catch(e) { /* skip */ }
    }
  }
  return records;
}

function writeJsonlSync(filePath, records) {
  const content = records.map(r => JSON.stringify(r)).join('\n') + '\n';
  fs.writeFileSync(filePath, content, 'utf8');
}

function getAdjacentContext(records, pageIndex, bookId) {
  let prev = '', next = '';
  for (const r of records) {
    if (r.book_id === bookId) {
      if (r.page_index === pageIndex - 1 && r.text_normalized) {
        prev = r.text_normalized.slice(-200);
      }
      if (r.page_index === pageIndex + 1 && r.text_normalized) {
        next = r.text_normalized.slice(0, 200);
      }
    }
  }
  return { prev, next };
}

// ── LLM API call ────────────────────────────────────────────────────────────
function callLLM(prompt, retries = 3) {
  return new Promise((resolve, reject) => {
    let attempt = 0;
    let tokenLimit = MAX_TOKENS;
    function doRequest() {
      attempt++;
      const url = new URL(`${BASE_URL}/chat/completions`);
      const body = JSON.stringify({
        model: MODEL,
        messages: [{ role: 'user', content: prompt }],
        max_tokens: tokenLimit,
        temperature: 0.3,
      });

      const mod = url.protocol === 'https:' ? https : http;
      const req = mod.request({
        hostname: url.hostname,
        port: url.port,
        path: url.pathname,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${API_KEY}`,
          'Content-Length': Buffer.byteLength(body),
        },
        timeout: 90000,
      }, (res) => {
        let data = '';
        res.on('data', chunk => data += chunk);
        res.on('end', () => {
          if (res.statusCode === 429 || res.statusCode >= 500) {
            if (attempt < retries) {
              setTimeout(doRequest, 1000 * attempt);
              return;
            }
            reject(new Error(`API ${res.statusCode}: ${data.slice(0, 200)}`));
          } else if (res.statusCode !== 200) {
            reject(new Error(`API ${res.statusCode}: ${data.slice(0, 200)}`));
          } else {
            try {
              const parsed = JSON.parse(data);
              const msg = parsed.choices?.[0]?.message;
              const finishReason = parsed.choices?.[0]?.finish_reason;
              // Only accept 'content' field — reasoning_content is internal thinking, not the answer
              const content = msg?.content;
              if (content && content.trim()) {
                resolve(content.trim());
              } else if (attempt < retries) {
                if (finishReason === 'length') tokenLimit = Math.min(tokenLimit * 2, 16384);
                console.log(`    [retry ${attempt}/${retries}] Empty content, finish=${finishReason}, next_tokens=${tokenLimit}`);
                setTimeout(doRequest, 2000 * attempt);
              } else {
                console.log(`    [FAIL] finish=${finishReason}, has_reasoning=${!!msg?.reasoning_content}, tokens=${tokenLimit}`);
                reject(new Error(`Empty content (finish=${finishReason})`));
              }
            } catch(e) {
              if (attempt < retries) {
                setTimeout(doRequest, 1000);
              } else {
                reject(new Error(`JSON parse error: ${data.slice(0, 200)}`));
              }
            }
          }
        });
      });
      req.on('error', e => {
        if (attempt < retries) {
          setTimeout(doRequest, 1000 * attempt);
        } else {
          reject(e);
        }
      });
      req.on('timeout', () => {
        req.destroy();
        if (attempt < retries) {
          setTimeout(doRequest, 2000);
        } else {
          reject(new Error('timeout'));
        }
      });
      req.write(body);
      req.end();
    }
    doRequest();
  });
}

function buildPrompt(text, prevContext, nextContext) {
  return `你是一个中文OCR纠错专家。以下文本是从扫描版PDF通过OCR识别得到的，可能存在错字、漏字、断句错误、形近字混淆等问题。

请根据上下文语义进行纠错。只纠正明显的OCR错字，不要改变原文意思和风格。保留原文段落格式。如果某处无法确定，保持原样。

## 前一页末尾（供参考）：
${prevContext || '（无）'}

## 需要纠错的文本：
${text}

## 后一页开头（供参考）：
${nextContext || '（无）'}

## 要求：
1. 只输出纠错后的完整文本，不要任何解释或标记
2. 保留原文的段落结构和标点风格
3. 不要添加原文没有的内容
4. 如果原文没有明显错误，原样输出`;
}

// ── Main ────────────────────────────────────────────────────────────────────
async function main() {
  console.log('='.repeat(60));
  console.log('LLM OCR CORRECTION');
  console.log('='.repeat(60));
  console.log(`Threshold: ${THRESHOLD} | Dry-run: ${DRY_RUN} | Model: ${MODEL}`);

  // Collect target files
  const targets = [];
  if (USE_GLOBAL) {
    targets.push(path.join(EVIDENCE_DIR, 'pages.jsonl'));
  } else {
    const batchDirs = fs.readdirSync(BATCHES_DIR)
      .filter(d => d.startsWith('batch_'))
      .filter(d => !BATCH_FILTER || d === BATCH_FILTER)
      .map(d => path.join(BATCHES_DIR, d, 'pages.jsonl'))
      .filter(p => fs.existsSync(p));
    targets.push(...batchDirs);
  }

  console.log(`Target files: ${targets.length}`);

  let totalProcessed = 0;
  let totalCorrected = 0;
  let totalErrors = 0;
  let totalSkipped = 0;

  for (const targetFile of targets) {
    console.log(`\n--- ${path.relative(ROOT, targetFile)} ---`);
    const records = readJsonlSync(targetFile);

    // Build index by book for context lookup
    const bookIndex = {};
    for (const r of records) {
      if (!bookIndex[r.book_id]) bookIndex[r.book_id] = [];
      bookIndex[r.book_id].push(r);
    }

    // Find low-confidence OCR records
    const toFix = records.filter(r =>
      r.pipeline_stage === 'visual_ocr' &&
      r.confidence < THRESHOLD &&
      r.char_count > 20
    ).slice(OFFSET, OFFSET + LIMIT);

    console.log(`  Total records: ${records.length}, to correct: ${toFix.length}`);

    if (toFix.length === 0) continue;
    if (DRY_RUN) {
      for (const r of toFix.slice(0, 3)) {
        console.log(`  [DRY-RUN] Would correct: ${r.id} (conf=${r.confidence}, cc=${r.char_count})`);
        console.log(`    Preview: ${r.text_normalized.slice(0, 100)}...`);
      }
      if (toFix.length > 3) console.log(`  ... and ${toFix.length - 3} more.`);
      continue;
    }

    // Process each record
    const checkpointFile = targetFile + '.corrected.json';
    const failedFile = targetFile + '.failed.json';
    const corrected = new Set();
    const failed = new Set();
    if (fs.existsSync(checkpointFile)) {
      try {
        const cp = JSON.parse(fs.readFileSync(checkpointFile, 'utf8'));
        cp.forEach(id => corrected.add(id));
        console.log(`  Resuming: ${corrected.size} already corrected.`);
      } catch(e) {}
    }
    if (fs.existsSync(failedFile)) {
      try {
        const fp = JSON.parse(fs.readFileSync(failedFile, 'utf8'));
        fp.forEach(id => failed.add(id));
        if (failed.size > 0) console.log(`  Skipping ${failed.size} previously failed records.`);
      } catch(e) {}
    }

    for (let i = 0; i < toFix.length; i++) {
      const rec = toFix[i];
      if (corrected.has(rec.id)) { totalSkipped++; continue; }
      if (failed.has(rec.id)) { totalSkipped++; continue; }

      const bookRecords = bookIndex[rec.book_id] || [];
      const { prev, next } = getAdjacentContext(bookRecords, rec.page_index, rec.book_id);
      const prompt = buildPrompt(rec.text_normalized, prev, next);

      try {
        const correctedText = await callLLM(prompt);
        if (correctedText && correctedText.trim()) {
          rec.text_normalized = correctedText.trim();
          rec.char_count = correctedText.trim().length;
          rec.pipeline_stage = 'visual_ocr_llm_corrected';
          rec.correction_confidence = 0.95;
          totalCorrected++;
        }
        corrected.add(rec.id);
      } catch(e) {
        console.log(`  ERROR on ${rec.id}: ${e.message} (skipping)`);
        totalErrors++;
        failed.add(rec.id);
      }

      totalProcessed++;

      // Progress — save checkpoints and write file every 5 records
      if ((i + 1) % 5 === 0 || i === toFix.length - 1) {
        console.log(`  Progress: ${i + 1}/${toFix.length} (corrected=${totalCorrected}, errors=${totalErrors})`);
        fs.writeFileSync(checkpointFile, JSON.stringify([...corrected]), 'utf8');
        fs.writeFileSync(failedFile, JSON.stringify([...failed]), 'utf8');
        writeJsonlSync(targetFile, records);
      }

      // Rate limit
      await new Promise(r => setTimeout(r, RATE_LIMIT_MS));
    }

    // Write back (in case no corrections were made in this run, but some from before)
    writeJsonlSync(targetFile, records);
    console.log(`  Written: ${targetFile}`);
    // Clean up success checkpoint; KEEP failed file so we don't retry
    if (fs.existsSync(checkpointFile)) fs.unlinkSync(checkpointFile);
    if (fs.existsSync(failedFile)) {
      console.log(`  Failed records saved to: ${path.relative(ROOT, failedFile)} (${failed.size} records)`);
    }
  }

  console.log('\n' + '='.repeat(60));
  console.log('CORRECTION COMPLETE');
  console.log('='.repeat(60));
  console.log(`Processed: ${totalProcessed}`);
  console.log(`Corrected: ${totalCorrected}`);
  console.log(`Errors: ${totalErrors}`);
  console.log(`Skipped (already done): ${totalSkipped}`);
}

main().catch(e => { console.error(e); process.exit(1); });
