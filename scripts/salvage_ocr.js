#!/usr/bin/env node
/**
 * salvage_ocr.js — Merge stranded OCR chunks back into pages.jsonl
 *
 * Problem: overnight_autopilot.py writes OCR results to ocr_chunks/ but
 * the merge step was interrupted, so batch-local pages.jsonl only has
 * triage records (char_count=0 for scanned PDFs).
 *
 * This script:
 *   1. Reads all ocr_chunk*.jsonl and res_chunk*.json from batch dirs
 *   2. Builds a lookup: book_id:page_index -> ocr_record
 *   3. Re-reads batch-local pages.jsonl, replaces records that have OCR
 *   4. Overwrites batch-local pages.jsonl with merged result
 *   5. Appends new OCR records to global data/evidence/pages.jsonl
 *   6. Reports stats
 */

const fs = require('fs');
const path = require('path');
const readline = require('readline');

const ROOT = path.resolve(__dirname, '..');
const BATCHES_DIR = path.join(ROOT, 'data', 'batches');
const EVIDENCE_DIR = path.join(ROOT, 'data', 'evidence');
const GLOBAL_PAGES = path.join(EVIDENCE_DIR, 'pages.jsonl');

function readJsonlSync(filePath) {
  const records = [];
  if (!fs.existsSync(filePath)) return records;
  const content = fs.readFileSync(filePath, 'utf8');
  for (const line of content.split('\n')) {
    if (line.trim()) {
      try { records.push(JSON.parse(line)); } catch(e) { /* skip */ }
    }
  }
  return records;
}

function readResChunkJson(filePath) {
  // res_chunk files are JSON arrays (from remote tesseract)
  if (!fs.existsSync(filePath)) return [];
  try {
    const data = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    return Array.isArray(data) ? data : [];
  } catch(e) { return []; }
}

async function main() {
  console.log('='.repeat(60));
  console.log('OCR SALVAGE — Merge stranded OCR chunks into pages.jsonl');
  console.log('='.repeat(60));

  const batchDirs = fs.readdirSync(BATCHES_DIR)
    .filter(d => d.startsWith('batch_'))
    .map(d => path.join(BATCHES_DIR, d))
    .filter(d => fs.statSync(d).isDirectory());

  console.log(`Found ${batchDirs.length} batch directories.\n`);

  // Track what's already in global to avoid duplicates
  const globalExisting = new Set();
  if (fs.existsSync(GLOBAL_PAGES)) {
    const globalRecords = readJsonlSync(GLOBAL_PAGES);
    for (const r of globalRecords) {
      globalExisting.add(`${r.book_id}:p${r.page_index}`);
    }
  }
  console.log(`Global evidence/pages.jsonl: ${globalExisting.size} existing records.`);

  let totalOcrRecords = 0;
  let totalMergedIntoBatch = 0;
  let totalAppendedToGlobal = 0;
  let totalSkipped = 0;

  const newGlobalRecords = [];

  for (const batchDir of batchDirs.sort()) {
    const batchName = path.basename(batchDir);
    const chunksDir = path.join(batchDir, 'ocr_chunks');
    const localPagesFile = path.join(batchDir, 'pages.jsonl');

    if (!fs.existsSync(chunksDir) || !fs.existsSync(localPagesFile)) {
      console.log(`\n[${batchName}] No chunks dir or pages.jsonl, skipping.`);
      continue;
    }

    console.log(`\n--- Processing ${batchName} ---`);

    // 1. Read all OCR chunk files
    const chunkFiles = fs.readdirSync(chunksDir)
      .filter(f => f.startsWith('ocr_chunk') || f.startsWith('res_chunk'))
      .sort();

    const ocrLookup = new Map(); // key: "book_id:page_index" -> record

    for (const cf of chunkFiles) {
      const cfPath = path.join(chunksDir, cf);
      if (cf.startsWith('ocr_chunk')) {
        // JSONL format
        const records = readJsonlSync(cfPath);
        for (const r of records) {
          const key = `${r.book_id}:p${r.page_index}`;
          // Keep the one with higher confidence / more text
          const existing = ocrLookup.get(key);
          if (!existing || (r.char_count > existing.char_count)) {
            ocrLookup.set(key, r);
          }
        }
      } else if (cf.startsWith('res_chunk')) {
        // JSON array format (remote tesseract results)
        const items = readResChunkJson(cfPath);
        for (const item of items) {
          // res_chunk items may not have book_id, extract from filename
          const m = cf.match(/book-(\w+)-p/);
          const bookId = m ? `book-${m[1]}` : null;
          if (!bookId) continue;
          const key = `${bookId}:p${item.page_index}`;
          const rec = {
            id: `${bookId}:p${item.page_index}`,
            book_id: bookId,
            page_index: item.page_index,
            text_normalized: item.text_normalized || '',
            classification: item.char_count >= 30 ? 'visual_ocr_extracted' : 'visual_ocr_low_text',
            char_count: item.char_count || 0,
            confidence: item.confidence || 0.75,
            extractor: 'tesseract@5.5.3',
            pipeline_stage: 'visual_ocr',
            source_file: cf,
          };
          const existing = ocrLookup.get(key);
          if (!existing || (rec.char_count > existing.char_count)) {
            ocrLookup.set(key, rec);
          }
        }
      }
    }

    console.log(`  OCR chunks read: ${chunkFiles.length} files, ${ocrLookup.size} unique pages with OCR.`);

    // 2. Read existing local pages.jsonl
    const localRecords = readJsonlSync(localPagesFile);
    console.log(`  Local pages.jsonl: ${localRecords.length} records.`);

    // 3. Merge: replace records where OCR is available
    let merged = 0;
    const mergedRecords = [];
    const seen = new Set();

    for (const rec of localRecords) {
      const key = `${rec.book_id}:p${rec.page_index}`;
      if (seen.has(key)) continue; // dedup
      seen.add(key);

      const ocr = ocrLookup.get(key);
      if (ocr && ocr.char_count > 0 && rec.char_count === 0) {
        mergedRecords.push(ocr);
        merged++;
      } else {
        mergedRecords.push(rec);
      }
    }

    // 4. Write merged batch-local pages.jsonl (backup first)
    const backupPath = localPagesFile + '.bak';
    if (!fs.existsSync(backupPath)) {
      fs.copyFileSync(localPagesFile, backupPath);
    }
    const out = mergedRecords.map(r => JSON.stringify(r)).join('\n') + '\n';
    fs.writeFileSync(localPagesFile, out, 'utf8');
    console.log(`  Merged into local pages.jsonl: ${merged} records updated.`);

    // 5. Collect new records for global evidence
    for (const rec of mergedRecords) {
      const key = `${rec.book_id}:p${rec.page_index}`;
      if (!globalExisting.has(key) && rec.char_count > 0) {
        newGlobalRecords.push(rec);
        globalExisting.add(key); // prevent dup across batches
      }
    }

    totalOcrRecords += ocrLookup.size;
    totalMergedIntoBatch += merged;
  }

  // 6. Append to global evidence
  if (newGlobalRecords.length > 0) {
    const appendStr = newGlobalRecords.map(r => JSON.stringify(r)).join('\n') + '\n';
    fs.appendFileSync(GLOBAL_PAGES, appendStr, 'utf8');
    totalAppendedToGlobal = newGlobalRecords.length;
  }

  console.log('\n' + '='.repeat(60));
  console.log('SALVAGE COMPLETE');
  console.log('='.repeat(60));
  console.log(`Total OCR pages found in chunks: ${totalOcrRecords}`);
  console.log(`Merged into batch-local pages.jsonl: ${totalMergedIntoBatch}`);
  console.log(`Appended to global evidence/pages.jsonl: ${totalAppendedToGlobal}`);
  console.log(`Skipped (already in global): ${totalSkipped}`);
}

main().catch(e => { console.error(e); process.exit(1); });
