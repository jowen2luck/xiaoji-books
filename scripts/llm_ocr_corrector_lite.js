#!/usr/bin/env node
/**
 * llm_ocr_corrector_lite.js — Token-optimized LLM OCR correction
 *
 * Saves ~65% tokens vs the full version by:
 *   1. No adjacent page context
 *   2. Shorter prompt
 *   3. Truncating text to MAX_CHARS (default 600)
 *   4. Only processing records with confidence < --lite-threshold (default 0.75)
 *   5. Combining multiple short records per API call
 *
 * Usage:
 *   node scripts/llm_ocr_corrector_lite.js [--batch batch_002] [--dry-run]
 *     [--threshold 0.85] [--lite-threshold 0.75] [--max-chars 600] [--combine 3]
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');

const ROOT = path.resolve(__dirname, '..');
const BATCHES_DIR = path.join(ROOT, 'data', 'batches');
const EVIDENCE_DIR = path.join(ROOT, 'data', 'evidence');

// ── Config ──────────────────────────────────────────────────────────────────
const API_KEY = 'ak_2hZ1Qk9e22SE1f876m76y2yT3j71s';
const BASE_URL = 'https://api.longcat.chat/openai';
const MODEL = 'LongCat-2.0';
const DEFAULT_THRESHOLD = 0.85;
const LITE_THRESHOLD = 0.75; // Skip records above this (less urgent)
const MAX_TOKENS = 8192;
const RATE_LIMIT_MS = 200;
const MAX_CHARS = 600; // Truncate text to this many chars
const COMBINE = 3; // Combine up to N records per API call

// ── CLI args ────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
const DRY_RUN = args.includes('--dry-run');
const thresholdIdx = args.indexOf('--threshold');
const THRESHOLD = thresholdIdx >= 0 ? parseFloat(args[thresholdIdx + 1]) || DEFAULT_THRESHOLD : DEFAULT_THRESHOLD;
const liteIdx = args.indexOf('--lite-threshold');
const LITE_T = liteIdx >= 0 ? parseFloat(args[liteIdx + 1]) || LITE_THRESHOLD : LITE_THRESHOLD;
const charsIdx = args.indexOf('--max-chars');
const MAX_C = charsIdx >= 0 ? parseInt(args[charsIdx + 1]) || MAX_CHARS : MAX_CHARS;
const combineIdx = args.indexOf('--combine');
const COMB = combineIdx >= 0 ? parseInt(args[combineIdx + 1]) || COMBINE : COMBINE;
const offsetIdx = args.indexOf('--offset');
const OFFSET = offsetIdx >= 0 ? parseInt(args[offsetIdx + 1]) || 0 : 0;
const limitIdx = args.indexOf('--limit');
const LIMIT = limitIdx >= 0 ? parseInt(args[limitIdx + 1]) || Infinity : Infinity;
const BATCH_FILTER = args.includes('--batch') ? args[args.indexOf('--batch') + 1] : null;
const USE_GLOBAL = args.includes('--global');

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
        temperature: 0,
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
        timeout: 180000,
      }, (res) => {
        let data = '';
        res.on('data', chunk => data += chunk);
        res.on('end', () => {
          if (res.statusCode === 429 || res.statusCode >= 500) {
            if (attempt < retries) {
              setTimeout(doRequest, 2000 * attempt);
              return;
            }
            reject(new Error(`API ${res.statusCode}: ${data.slice(0, 150)}`));
          } else if (res.statusCode === 402) {
            reject(new Error('QUOTA_EXHAUSTED'));
          } else if (res.statusCode !== 200) {
            reject(new Error(`API ${res.statusCode}: ${data.slice(0, 150)}`));
          } else {
            try {
              const parsed = JSON.parse(data);
              const msg = parsed.choices?.[0]?.message;
              const finishReason = parsed.choices?.[0]?.finish_reason;
              const content = msg?.content;
              if (content && content.trim()) {
                resolve(content.trim());
              } else if (finishReason === 'length' && attempt < retries) {
                tokenLimit = Math.min(tokenLimit * 2, 16384);
                setTimeout(doRequest, 1000);
              } else if (attempt < retries) {
                setTimeout(doRequest, 2000 * attempt);
              } else {
                reject(new Error(`Empty (finish=${finishReason})`));
              }
            } catch(e) {
              if (attempt < retries) {
                setTimeout(doRequest, 1000);
              } else {
                reject(new Error('JSON parse error'));
              }
            }
          }
        });
      });
      req.on('error', e => {
        if (attempt < retries) { setTimeout(doRequest, 2000 * attempt); }
        else { reject(e); }
      });
      req.on('timeout', () => {
        req.destroy();
        if (attempt < retries) { setTimeout(doRequest, 2000); }
        else { reject(new Error('timeout')); }
      });
      req.write(body);
      req.end();
    }
    doRequest();
  });
}

// — Short prompt (no context, no examples) —
function buildPrompt(text) {
  return `纠正以下OCR文本的错字、漏字、断句错误。只输出纠正后的文本，不解释。

${text}`;
}

// — Combined prompt for multiple short records —
function buildCombinedPrompt(items) {
  let p = `纠正以下${items.length}段OCR文本的错字和断句错误。每段用[START]和[END]标记。输出时保持相同格式，只输出纠正后的文本。\n\n`;
  for (const item of items) {
    p += `[START id=${item.id}]\n${item.text}\n[END]\n\n`;
  }
  return p;
}

function parseCombinedResponse(resp, items) {
  const results = {};
  for (const item of items) {
    const startTag = `[START id=${item.id}]`;
    const endTag = `[END]`;
    const si = resp.indexOf(startTag);
    const ei = resp.indexOf(endTag, si + startTag.length);
    if (si >= 0 && ei > si) {
      results[item.id] = resp.slice(si + startTag.length, ei).trim();
    }
  }
  return results;
}

// ── Main ────────────────────────────────────────────────────────────────────
async function main() {
  console.log('='.repeat(60));
  console.log('LLM OCR CORRECTION (LITE — token optimized)');
  console.log('='.repeat(60));
  console.log(`Threshold: ${THRESHOLD} | Lite-cutoff: ${LITE_T} | MaxChars: ${MAX_C} | Combine: ${COMB}`);

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

  let totalProcessed = 0, totalCorrected = 0, totalErrors = 0, totalSkipped = 0;

  for (const targetFile of targets) {
    console.log(`\n--- ${path.relative(ROOT, targetFile)} ---`);
    const records = readJsonlSync(targetFile);

    // Find low-confidence OCR records, only process the worst ones (< LITE_T)
    const toFix = records.filter(r =>
      r.pipeline_stage === 'visual_ocr' &&
      r.confidence < LITE_T &&
      r.char_count > 20
    ).slice(OFFSET, OFFSET + LIMIT);

    console.log(`  Total records: ${records.length}, to correct (conf < ${LITE_T}): ${toFix.length}`);

    if (toFix.length === 0) { console.log('  Nothing to do.'); continue; }

    if (DRY_RUN) {
      for (const r of toFix.slice(0, 5)) {
        console.log(`  [DRY-RUN] ${r.id} (conf=${r.confidence}, cc=${r.char_count})`);
      }
      if (toFix.length > 5) console.log(`  ... and ${toFix.length - 5} more.`);
      continue;
    }

    // Checkpoint
    const checkpointFile = targetFile + '.lite_corrected.json';
    const failedFile = targetFile + '.lite_failed.json';
    const corrected = new Set();
    const failed = new Set();
    if (fs.existsSync(checkpointFile)) {
      try { JSON.parse(fs.readFileSync(checkpointFile, 'utf8')).forEach(id => corrected.add(id)); } catch(e) {}
    }
    if (fs.existsSync(failedFile)) {
      try { JSON.parse(fs.readFileSync(failedFile, 'utf8')).forEach(id => failed.add(id)); } catch(e) {}
    }
    console.log(`  Resuming: ${corrected.size} done, ${failed.size} failed.`);

    // Truncate texts — auto-shrink per-record when combining to fit token budget
    const perRecChars = Math.max(150, Math.floor(MAX_C / COMBINE));
    const items = toFix.map(r => ({
      id: r.id,
      rec: r,
      text: (r.text_normalized || '').slice(0, perRecChars),
    }));

    // Process in combined batches
    let i = 0;
    while (i < items.length) {
      // Skip already done
      while (i < items.length && (corrected.has(items[i].id) || failed.has(items[i].id))) {
        i++;
        totalSkipped++;
      }
      if (i >= items.length) break;

      // Gather up to COMB unprocessed items
      const batch = [];
      let j = i;
      while (j < items.length && batch.length < COMB) {
        if (!corrected.has(items[j].id) && !failed.has(items[j].id)) {
          batch.push(items[j]);
        }
        j++;
      }

      if (batch.length === 0) { i = j; continue; }

      let resp;
      try {
        if (batch.length === 1) {
          resp = await callLLM(buildPrompt(batch[0].text));
          if (resp) {
            batch[0].rec.text_normalized = resp + (batch[0].rec.text_normalized.length > MAX_C ? batch[0].rec.text_normalized.slice(MAX_C) : '');
            batch[0].rec.char_count = batch[0].rec.text_normalized.length;
            batch[0].rec.pipeline_stage = 'visual_ocr_llm_corrected';
            batch[0].rec.correction_confidence = 0.92;
            totalCorrected++;
          }
          corrected.add(batch[0].id);
        } else {
          const prompt = buildCombinedPrompt(batch);
          resp = await callLLM(prompt);
          if (resp) {
            const parsed = parseCombinedResponse(resp, batch);
            for (const item of batch) {
              if (parsed[item.id]) {
                item.rec.text_normalized = parsed[item.id] + (item.rec.text_normalized.length > MAX_C ? item.rec.text_normalized.slice(MAX_C) : '');
                item.rec.char_count = item.rec.text_normalized.length;
                item.rec.pipeline_stage = 'visual_ocr_llm_corrected';
                item.rec.correction_confidence = 0.92;
                totalCorrected++;
                corrected.add(item.id);
              } else {
                failed.add(item.id);
                totalErrors++;
              }
            }
          } else {
            for (const item of batch) { failed.add(item.id); totalErrors++; }
          }
        }
      } catch(e) {
        if (e.message === 'QUOTA_EXHAUSTED') {
          console.log('  QUOTA EXHAUSTED — stopping.');
          // Save progress
          fs.writeFileSync(checkpointFile, JSON.stringify([...corrected]), 'utf8');
          fs.writeFileSync(failedFile, JSON.stringify([...failed]), 'utf8');
          writeJsonlSync(targetFile, records);
          process.exit(2);
        }
        for (const item of batch) {
          console.log(`  ERROR ${item.id}: ${e.message}`);
          failed.add(item.id);
          totalErrors++;
        }
      }

      totalProcessed += batch.length;
      i = j;

      // Save every 5 batches
      if (totalProcessed % 10 === 0) {
        console.log(`  Progress: ${totalProcessed}/${toFix.length} (corrected=${totalCorrected}, errors=${totalErrors})`);
        fs.writeFileSync(checkpointFile, JSON.stringify([...corrected]), 'utf8');
        fs.writeFileSync(failedFile, JSON.stringify([...failed]), 'utf8');
        writeJsonlSync(targetFile, records);
      }

      await new Promise(r => setTimeout(r, RATE_LIMIT_MS));
    }

    // Final write
    writeJsonlSync(targetFile, records);
    fs.writeFileSync(checkpointFile, JSON.stringify([...corrected]), 'utf8');
    fs.writeFileSync(failedFile, JSON.stringify([...failed]), 'utf8');
    console.log(`  Written. Corrected=${totalCorrected}, Errors=${totalErrors}`);
  }

  console.log('\n' + '='.repeat(60));
  console.log('LITE CORRECTION COMPLETE');
  console.log('='.repeat(60));
  console.log(`Processed: ${totalProcessed} | Corrected: ${totalCorrected} | Errors: ${totalErrors} | Skipped: ${totalSkipped}`);
}

main().catch(e => { console.error(e); process.exit(1); });
