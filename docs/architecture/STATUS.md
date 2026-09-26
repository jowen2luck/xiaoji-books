# AIAE Book Evidence Engine — 当前状态

> 更新: 2026-08-08 06:10
> 阶段: **M2b 全量 OCR 运行中** + M5/M6 代码层完成

---

## 一、当前进度（M2b 全量 OCR）

### 整体进度: ~90/1458 books（~6.2%）

| 类别 | 数量 | 状态 | 实际完成 |
|------|------|------|----------|
| text_extractable | 136 | ✅ 完成 | 136/136 |
| partial_text | 209 | 🔄 进行中 | ~130/209 |
| ocr_required | 1109 | ⏳ 主体未动 | ~0/1109 |
| parser_error | 4 | ⏳ 未开始 | 0/4 |

### 批次运行状态

- **最后更新**: 2026-08-08（活跃运行中）
- **已完成 book_ids**: 90（从 checkpoint 计算）
- **CPU 时间**: 全部 6 个 Python 进程在跑（累计 3000-3600s CPU）
- **速率**: ~33 books/hr（小书 + 中书的 mix）
- **Catalog 加载**: 后台运行中（re-insert 10k+ paragraphs）

**Catalog.db 当前状态:**
- books: 67（正在被 catalog load 更新 → 预期 90+）
- pages: 25,054
- paragraphs: 25,022
- paragraphs_fts: 25,384
- anchors: 25,022
- evidence_sets: 67

---

## 二、完成的技术资产（M0-M6 代码层）

### M0-M2b: Ingest + Evidence 存储
- `scripts/pipeline/batch_ingest.py` — 串行批处理 + checkpoint/resume + skip logic 修复
- `scripts/pipeline/batch_parallel.py` — 4 worker 并行（shard + merge）
- `scripts/pipeline/run_m2b_full.py` — orchestrator
- `scripts/pipeline/anchor_builder.py` — Evidence 锚点构建
- `scripts/catalog/init_db.py` — schema
- `scripts/catalog/load_catalog.py` — 幂等加载 SQLite+FTS5

### M3: 规模化验证
- `scripts/verify/verify_m3_scale.py` — 6 项一致性检查（anchor 1:1、FTS5 覆盖、evidence_set_id、char_range 等）

### M4: Navigation
- `scripts/navigation/derived_catalog.py` — TOC 推断（带 confidence）
- `scripts/navigation/semantic_chunks.py` — 500-char chunks
- `scripts/navigation/full_rebuild.py` — orchestrator

### M5: Embedding + Search
- `scripts/embedding/model.py` — EmbeddingModel 抽象层
- `scripts/embedding/faiss_index.py` — FAISS index 构建+查询
- `scripts/search/hybrid.py` — FTS5 + Vector RRF 融合

### M6: AIAE 查询引擎（Skill 入口）
- `scripts/query/engine.py` — 主查询引擎 + Engine Never Concludes
- 返回 snippet + provenance（book_id, artifact_id, page_index, char_range, layout_bbox, source_hash）

---

## 三、Catalog.db Schema

```
books              (book_id PK, artifact_id, source_path, evidence_set_id, source_hash, ...)
pages              (id PK, book_id FK, page_index, text_raw, text_normalized, evidence_set_id)
paragraphs         (id PK, book_id FK, page_id FK, char_start, char_end, evidence_set_id)
paragraphs_fts     (paragraph_id, book_id, page_index, text_normalized)  — FTS5 trigram
anchors            (id PK, book_id, artifact_id, page_index, block_id, char_start, char_end, layout_bbox, evidence_set_id)
evidence_sets      (evidence_set_id PK, book_id, artifact_id, extractor_sig, ...)
toc_source         (book extracted TOC)
toc_derived        (inferred TOC, confidence, provenance — derived layer)
```

---

## 四、运行批次指南

```powershell
cd D:\Pcode\play\_skills\book-library-skill

# 1. text_extractable (剩余 ~70 本) — PID 32672
python scripts/pipeline/batch_ingest.py `
  --status-filter text_extractable `
  --checkpoint data/batch_checkpoint.jsonl `
  --output-dir data/evidence

# 2. 并行 partial_text + ocr_required — PID 23408 (4 workers)
python scripts/pipeline/batch_parallel.py --workers 4 `
  --status-filter partial_text,ocr_required `
  --shards-dir data/.parallel_shards

# 3. 全部完成后 → merge → catalog load → verify
python scripts/pipeline/batch_parallel.py --merge
python scripts/catalog/load_catalog.py --evidence data/evidence/ --db data/catalog/catalog.db
python scripts/verify/verify_m3_scale.py --verbose

# 4. 查询测试
python scripts/query/engine.py --query "马克思主义" --topk 3
```

---

## 五、关键约束（宪法级）

### 证据不可变
- Engine 只追加新版本 Evidence（新 evidence_set_id），旧 Evidence 永不覆写
- 严禁覆盖原文或使用替代性 Summary
- Ground Truth (`text_normalized`) 仅做机械修复（去水印、全角转半角、CJK 异常空格）

### Engine Never Concludes
- `scripts/query/engine.py` 返回 Evidence + 锚点
- 禁止"总结"、"我认为"、"综上所述" — 只返原文
- `engine_never_concludes: true` 是硬编码 invariant

### ID 体系
- `book_id` 永久稳定; `artifact_id` = SHA-256 内容哈希; `source_path` 可变
- `evidence_set_id = sha256[:16](book_id, artifact_id, extractor_sig:norm_v1)` 

---

## 六、验收协议

### M2b Done（全部 1458 本 OCR 完成）
- [x] text_extractable 136/136
- [~] partial_text ~130/209
- [ ] ocr_required 0/1109
- [ ] parser_error 0/4
- [ ] catalog.db 入库完成（全部 paragraph + FTS5）
- [ ] anchors 覆盖率 = 100%

### M6 Done（AIAE Skill 上线）
- [x] engine.py 查询引擎（FTS5 + LIKE fallback）
- [x] Provenance 锚点全字段返回
- [x] Engine Never Concludes invariant
- [ ] M3 verify_m3_scale.py 通过
- [ ] Hybrid search（FTS5 + FAISS RRF）联动
- [ ] Skill trigger 注册（CatPaw skill 定义）

---

## 七、环境

- **Python**: `C:\Users\31239\.meituan-catpaw\runtimes\python\versions\3.12.13\python.exe`
- **OCR**: RapidOCR + ONNX Runtime
- **WORKSPACE**: `D:\Pcode\play\_skills\book-library-skill`
