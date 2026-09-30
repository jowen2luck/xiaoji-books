# Book Evidence & Discovery Skill — 实施计划

> 版本: v2.0 (AIAE 对齐 + 决策确认版)  
> 生成时间: 2026-07-31  
> 上级设计: [SKILL.md](./SKILL.md) | [AIAE_INTEGRATION.md](./AIAE_INTEGRATION.md) | [REDESIGN.md](./REDESIGN.md)  
> 核心原则: **先 Ground Truth → 后 Navigation；Evidence 优先，检索第二批**  
> 关键数据: 1458 PDF | 12.3GB | ~87% 需要 OCR  
> 已确认决策: [参见下方 §0 决策记录](#0-决策记录)

---

## 0. 决策记录

> 这些决策已在 2026-07-31 由用户确认，作为本实施计划的基础约束。

### 0.1 OCR 比例与管线规划

实际普查结果 (M1 确认):

```text
总 PDF:          1458

text_extractable: 136  (9.3%)   — 直接提取
ocr_required:    1109  (76.1%)  — 纯扫描件，需 OCR
partial_text:     209  (14.3%)  — 混合，逐页判断
parser_error:       4  (0.3%)   — 解析异常
```

**M2c 完成 (2026-08-07)**: identity 加固 + Evidence 版本幂等 + catalog.db anchors 表。详见下方 M2b 状态。

工程规划按 **~90% OCR 负载** 设计 (1318/1458 = 90.4%)。

### 0.2 三级 ID 体系

| 层级 | 字段 | 稳定性 | 示例 |
|------|------|--------|------|
| 文献层 | `book_id` | 永久稳定 | `book-me01a` |
| 文件实例层 | `artifact_id` | 绑定 SHA-256 | `sha256:a1b2c3...` |
| 路径元数据 | `source_path` | 可变 | `chinese/pdf/marx-engels/me01a.pdf` |

文件重命名时 `book_id` 不变，只更新 `source_path`。

### 0.3 文本清洗边界

Ground Truth 层（`text_normalized`）允许:

- 去除明确识别的水印
- 全角数字/字母转半角
- 修复 CJK 字符间异常空格
- 去除首尾无意义空白
- 统一换行符

以下操作**只能在派生层**（不覆盖 Ground Truth）:

- 段落重排
- 断句补全
- 删除重复标题
- 页眉页脚去重
- LLM 修复错别字

### 0.4 目录推断

允许推断目录（`derived_catalog`），属于 Navigation，必须:

- 带 `confidence` 和 `source_refs`
- 记录生成器版本
- 可以删除后重建

推断优先级: PDF 书签 → 印刷目录页 → 正则规则 → LLM 兜底。

### 0.5 OCR 与版面分析引擎标准 (已升级生产标准)

最终选择: **RapidOCR + ONNX Runtime (CPU) + LayoutAnalyzer (自研版面切带与多级标题引擎)**。
详细规范与准则请参阅: [OCR_AND_LAYOUT_SPECIFICATION.md](../OCR_AND_LAYOUT_SPECIFICATION.md)。

- **选型与淘汰理由**:
  - 淘汰 `mobile_workshop` 方案：多设备 Tesseract 集群丢弃了原始 bbox 坐标；Paddle PP-Structure v2 / PicoDet / OrderPredictor 在 Windows CPU 下由于 oneDNN 冲突报错 `ConvertPirAttribute2RuntimeAttribute` 致命崩溃且路径写死。
  - 选择升级方案：RapidOCR 纯 CPU ONNX 秒级推理，稳定无崩溃，100% 保留 4 点物理 bbox；配合 `LayoutAnalyzer` 实现了通栏断点切带（彻底消除双栏标题穿透错乱）与 Level 1~4 多级标题结构化提取。
- **依赖链**: `rapidocr_onnxruntime` → `onnxruntime` → `opencv-python` + `pymupdf` (fitz 内存光栅化，无需 poppler 子进程)。

### 0.5b Embedding 模型

第一版: `bge-small-zh-v1.5`（中文优先、本地、离线）。模型接口抽象为可替换。

### 0.6 段落粒度

- **段落 = 主 Evidence**（按空行切分）
- **语义 chunk = Navigation / Vector Index**

语义 chunk 必须保存 `parent_passage_ids` + `start_offset` + `end_offset`。

### 0.7 处理顺序

先做 5-10 本跨类别样本，包含:

- 可直接提取文本的 PDF
- 纯扫描 PDF
- 混合型 PDF
- 有书签和无书签的 PDF
- 大文件和小文件

之后建立两条并行管线:

```text
可提取文本 → 文本规范化 → Evidence
扫描件     → OCR → Evidence
```

统一输出同一个 Evidence 契约。

### 0.8 存储合并

合并为单一 `catalog.db`:

```text
books
pages
paragraphs
toc_entries
anchors
metadata
paragraph_fts  -- FTS5 virtual table
```

向量索引单独: `index/vectors.faiss`。

---

## 一、实施原则

### 1.1 AIAE 合规

所有实施阶段必须通过 AIAE 宪法检查:

- [ ] 此操作恢复/增加信息，而非压缩信息?
- [ ] 原始 Evidence 不会被覆盖式修改?
- [ ] 没有调用 LLM 生成摘要替代原文?
- [ ] 新增来源不需要修改 Engine 核心代码?
- [ ] 变更可以被另一个实现零成本替换?

### 1.2 数据驱动决策

- 任何处理前先采样验证
- 每阶段产出必须可验证、可回滚
- 质量指标必须能用脚本测量

### 1.3 两管线统一

文本提取和 OCR 是两条**并行管线**，统一输出同一个 Evidence Schema，不产生两种 Evidence 类型。

---

## 二、里程碑路线图

```text
M0 基础设施 + 样本验证            ✅ 完成
  ↓
M1 稳定 ID / manifest 就绪       ✅ 完成 (验收 6/6 PASS)
  ↓
M2a E2E 样本管线                  ✅ 完成 (5 本 PASS)
  ↓
M2b 全量批量 OCR                  🔄 进行中 (~1458 本)
  ↓
M2c-prep Identity + Catalog 加固  ✅ 完成 (幂等+anchors+证据版本)
  ↓
M3 Anchor + Catalog 规模化验证    待启动
  ↓
M4 Navigation 生成               待启动
  ↓
M5 Embedding + 语义检索          待启动
```

---

## 三、M0: 基础设施 + 样本验证

### 3.1 目标

验证端到端流程在 5-10 本样本上的可行性，识别主要障碍。

### 3.2 样本选择

| 类别 | 样本数 | 特征 |
|------|--------|------|
| 中文马克思主义经典 | 2 | ME 全集、列宁选集 |
| 西方哲学 | 2 | 黑格尔、康德 |
| 可直接提取 | 2 | 文本型 PDF |
| 纯扫描 | 2 | 需 OCR |
| 混合 | 1 | 部分页面有文本 |
| 大文件 (>50MB) | 1 | 长文档处理 |

### 3.3 M0 任务清单

- [ ] 建立 `scripts/detect_text.py` — 分类 PDF 是否需要 OCR
- [ ] 建立 `scripts/classify_all.py` — 全量 1458 PDF 分类
- [x] 确认 OCR 引擎: RapidOCR + ONNX Runtime（PaddleOCR 已因 CPU 兼容性排除，见 §0.5）
- [ ] 验证 pypdf/pdfplumber 对样本中文 PDF 的提取质量
- [ ] 建立 `scripts/sample_pick.py` — 自动挑选跨类别样本
- [ ] 建立目录结构 `data/{raw,evidence,catalog,navigation,index}/`
- [ ] 实现基础 CLI 入口: `booklib detect`、`booklib ingest`
- [ ] 跑通 5-10 本样本的 detect → ingest → evidence 全流程

### 3.4 M0 验收标准

```text
[PASS] 5-10 本样本 detect 结果与人工判断一致
[PASS] 样本 OCR 后Evidence 包含完整 Anchor
[PASS] 样本 FTS5 检索能匹配关键词
[PASS] 样本 ref 能正确解析回原始页面
[PASS] 全部脚本有 --help、幂等、dry-run 模式
```

### 3.5 M0 запреmented（禁止事项）

- ❌ 不要在样本上生成 Embedding（M5 的事）
- ❌ 不要在 M0 做批量 ingest（1458 本）
- ❌ 不要为 OCR 质量优化（先确认管线可行）

---

## 四、M1: 稳定 ID / Manifest 就绪

### 4.1 目标

为 1458 PDF 建立稳定 ID 映射，确保文件重命名不会影响下游引用。

### 4.2 ID Schema

```yaml
# data/manifest.jsonl (每行一本书)
book_id: "book-me01a"           # 永久稳定的逻辑 ID
artifact_id: "sha256:a1b2c3..." # 当前文件内容 hash
source_path: "chinese/pdf/marx-engels/me01a.pdf"  # 可变
aliases: ["me01a"]              # 历史文件名
status: text_extractable | ocr_required | partial_text | parser_error
page_count: 220
detected_at: timestamp
detector_version: "detect_v1"
```

### 4.3 M1 任务清单

- [ ] 解析 `archive-index.json` 提取已有元数据
- [ ] 检测重复 stem（61 个重复，279 个额外条目），人工或自动区分
- [ ] 为每本书分配唯一 `book_id`（建议 `book-{stem}` 或 `book-{hash[:8]}`）
- [ ] 运行 Manifest 生成器 → 输出 `manifest.jsonl`
- [ ] 验证: 所有 1458 PDF 都有唯一 book_id
- [ ] 验证: SHA-256 计算正确（抽样 50 本）
- [ ] 分类统计各类型占比

### 4.4 分类状态机

```
PDF 文件
    ↓ 检测前 3 + 中 3 + 后 3 页
    ↓
┌─────────────────────────────────────┐
│ detect_text(pdf_path, sample_pages) │
└─────────────────────────────────────┘
    ↓
    ├─ ≥ 6 页有文本 → text_extractable
    ├─ 1-5 页有文本 → partial_text
    ├─ 0 页有文本   → ocr_required
    └─ 解析异常     → parser_error
```

### 4.5 M1 硬性验收标准

```text
[PASS] manifest.jsonl 含 1458 行，无重复 book_id
[PASS] book_id 唯一数 = 1458
[PASS] artifact_id 非空（1458/1458）
[PASS] 每条 detection 都能映射到 manifest（1458/1458）
[PASS] 重命名 source_path 后 book_id 不变（test_rename_stability.py 验证）
[PASS] 旧的 me02 Evidence 引用仍然可解析（verify_m1_acceptance.py 验证）
```

验收脚本: `scripts/verify/verify_m1_acceptance.py`（全自动 6 项检查）

---

## 五、M2: 两条并行 Evidence 管线

### 5.1 目标

基于 M1 的分类结果，建立文本提取和 OCR 两条管线，统一输出 Evidence。

### 5.2 管线架构

```
manifest.jsonl
    ↓ 按 status 分发
    ↓
┌────────────────┐    ┌────────────────┐
│ TextExtract    │    │ OcrPipeline    │
│ Pipeline       │    │                │
│ (text_extract  │    │ (ocr_required  │
│  + partial)    │    │  + parser_err) │
└───────┬────────┘    └───────┬────────┘
        │                      │
        ↓                      ↓
┌─────────────────────────────────────┐
│ Evidence Normalizer (统一契约)       │
│ - text_raw ← 原始提取               │
│ - text_normalized ← 机械修复后      │
│ - normalization_version             │
│ - (不碰: 重排/断句/LLM修复)         │
└─────────────────────────────────────┘
        ↓
┌─────────────────────────────────────┐
│ Anchor Builder                      │
│ - source_hash, artifact_id          │
│ - page_index, printed_page          │
│ - char_range, layout_bbox           │
└─────────────────────────────────────┘
        ↓
   evidence/*.jsonl  (统一输出)
```

### 5.3 TextExtract Pipeline

**输入**: `status = text_extractable OR partial_text`

**步骤**:
1. pypdf/pdfplumber 逐页提取文本
2. 记录原始文本到 `text_raw`
3. 记录 page_layout（字符位置、字体）
4. 规范化: 全角转半角、空格修复、换行统一 → `text_normalized`
5. 按空行切分段落
6. 为每段落生成 Anchor

**特殊处理**: `partial_text` 的书——某些页 OCR、某些页直接提取，逐页判断。

### 5.4 OcrPipeline (生产版规范)

**输入**: `status = ocr_required OR parser_error`

**步骤**:
1. PyMuPDF (fitz) 内存光栅化 (200 DPI 起点，纯扫描件 300 DPI，无需子进程)
2. RapidOCR 识别（中文+英文模型，ONNX Runtime 纯 CPU 推理），保留物理 4 点 bbox 坐标
3. `LayoutAnalyzer` 结构化处理：
   - 过滤与分离顶部重复页眉与边沿页码
   - 通栏大标题断点切带（Span-Block Banding）
   - 自适应多栏检测与人类阅读顺序重排（左栏自顶向下 -> 右栏自顶向下）
   - 多级标题层级（Level 1~4）与类别分类
4. 后处理与分层记录:
   - Ground Truth 写入 `blocks.jsonl`，保留物理真实检测坐标
   - Navigation 写入 `page_structure.jsonl`、`paragraphs_v2.jsonl`（带重排顺序、标题绑定与分栏元信息）

### 5.5 Normalizer 规则明细

```python
NORMALIZATION_RULES = [
    "fullwidth_to_halfwidth",     # 全角数字字母转半角
    "cjk_spacing_fix",             # 修复中文字符间多余空格
    "strip_head_tail_whitespace",  # 去除首尾空白
    "unify_newlines",             # 统一为 \n
    "remove_watermark",           # 去除明确的水印文本（需规则配置）
]

# 不可用于 Ground Truth 层:
NOT_ALLOWED = [
    "paragraph_reorder",
    "sentence_repair",
    "remove_duplicate_headers",
    "llm_typo_fix",
]
```

### 5.6 M2 任务清单

- [ ] 实现 `scripts/pipeline/text_extract.py`
- [ ] 实现 `scripts/pipeline/ocr_extract.py`
- [ ] 实现 `scripts/pipeline/normalizer.py`（严格限制清洗规则）
- [ ] 实现 `scripts/pipeline/anchor_builder.py`
- [ ] 在 M0 样本上运行两条管线，对比输出
- [ ] 验证: text_raw ≠ text_normalized 时没有信息丢失
- [ ] 验证: 抽样 100 本书，Evidence 含完整 Anchor
- [ ] 实现断点续传（大规模批量 ingest 需要）

### 5.7 M2 验收标准

```text
[PASS] text_extractable 管线处理 187 本书无报错
[PASS] OCR 管线处理 5 本样本识别准确率 > 95%（人工抽检）
[PASS] 所有 Evidence 行含 text_raw + text_normalized + normalization_version
[PASS] 所有 Evidence 行含 source_hash + artifact_id + page_index 非空
[PASS] 重复 ingest 不修改已有 Evidence（只生成新 evidence_set_id）
[PASS] 抽样 30 本重命名源文件再 ingest，book_id 不变
```

---

## 六、M3: Anchor + Catalog 单 SQLite

### 6.1 目标

建立单一 `catalog.db`，存储所有结构化查询所需数据 + FTS5 全文索引。

### 6.2 SQLite Schema

```sql
-- 书目
CREATE TABLE books (
    book_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    source_path TEXT,
    title TEXT,
    authors TEXT,           -- JSON array
    language TEXT,
    page_count INTEGER,
    status TEXT,            -- text_extractable | ocr_required | ...
    ingested_at TEXT,
    evidence_set_id TEXT
);

-- 页面
CREATE TABLE pages (
    id TEXT PRIMARY KEY,    -- {book_id}:p{page_index}
    book_id TEXT NOT NULL,
    page_index INTEGER,
    printed_page TEXT,
    artifact_id TEXT,
    text_raw TEXT,
    text_normalized TEXT,
    normalization_version TEXT,
    confidence REAL,
    FOREIGN KEY (book_id) REFERENCES books(book_id)
);

-- 段落
CREATE TABLE paragraphs (
    id TEXT PRIMARY KEY,    -- {book_id}:p{page_index}:para{local_id}
    book_id TEXT NOT NULL,
    page_id TEXT,
    page_index INTEGER,
    printed_page TEXT,
    para_index INTEGER,
    text_raw TEXT,
    text_normalized TEXT,
    normalization_version TEXT,
    char_start INTEGER,
    char_end INTEGER,
    confidence REAL,
    FOREIGN KEY (book_id) REFERENCES books(book_id),
    FOREIGN KEY (page_id) REFERENCES pages(id)
);

-- 目录条目（source_toc）
CREATE TABLE toc_source (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    page_index INTEGER,
    printed_page TEXT,
    title TEXT,
    level INTEGER,
    parent_id TEXT,
    FOREIGN KEY (book_id) REFERENCES books(book_id)
);

-- 派生目录（derived_catalog）
CREATE TABLE toc_derived (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    page_index INTEGER,
    printed_page TEXT,
    title TEXT,
    level INTEGER,
    parent_id TEXT,
    confidence REAL NOT NULL,
    provenance TEXT,        -- JSON: generator + version + input_refs
    FOREIGN KEY (book_id) REFERENCES books(book_id)
);

-- Anchor 索引
CREATE TABLE anchors (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    page_index INTEGER,
    printed_page TEXT,
    block_id TEXT,
    char_start INTEGER,
    char_end INTEGER,
    layout_bbox TEXT,       -- JSON [x0,y0,x1,y1]
    extractor_version TEXT,
    evidence_id TEXT,
    FOREIGN KEY (book_id) REFERENCES books(book_id)
);

-- FTS5 全文索引
CREATE VIRTUAL TABLE paragraphs_fts USING fts5(
    text_normalized,
    content='paragraphs',
    content_rowid='rowid',
    tokenize='unicode61'    -- 对 CJK 可用 trigram
);
```

### 6.3 M3 任务清单

- [ ] 实现 `scripts/catalog/init.py` — 创建 catalog.db 表结构
- [ ] 实现 `scripts/catalog/ingest_summary.py` — 从 manifest 写 books 表
- [ ] 实现 `scripts/catalog/ingest_pages.py` — 从 evidence 写 pages + paragraphs
- [ ] 实现 `scripts/catalog/ingest_anchors.py` — 写 anchors 表
- [ ] 实现 `scripts/catalog/fts_sync.py` — 同步 paragraphs → paragraphs_fts
- [ ] 实现 `scripts/catalog/toc_extract.py` — 提取 source_toc
- [ ] 在 M0 样本上生成 catalog.db，验证 FTS5 查询正常
- [ ] 验证: trigram tokenizer 对中文查询有合理召回

### 6.4 M3 验收标准

```text
[PASS] catalog.db 包含全部 1458 条 books 记录
[PASS] paragraphs_fts 与 paragraphs 表数据一致
[PASS] FTS5 中文关键词查询返回相关段落
[PASS] anchors 表命中抽样 50 条都能定位到正确页面
[PASS] SQLite 文件可被 DuckDB 读取（导出路径预留）
[PASS] toc_source 和 toc_derived 分表存储，不混合
```

---

## 七、M4: Navigation 生成

### 7.1 目标

从 Evidence 生成 Navigation（可删除重建），包括 derived_catalog、摘要、语义 chunk。

### 7.2 Navigation 资产清单

| 目录 | 文件 | 输入依赖 | 是否可删 |
|------|------|----------|----------|
| navigation/ | derived_catalog.jsonl | pages.text + source_toc | ✅ |
| navigation/ | summaries.jsonl | paragraphs.text | ✅ |
| navigation/ | concept_map.json | NER + aliases | ✅ |
| navigation/ | semantic_chunks.jsonl | paragraphs.text + 切分规则 | ✅ |

### 7.3 语义 chunk 规则

```yaml
id: "sc-{paragraph_id}-{chunk_index}"
parent_paragraphs: ["{paragraph_id}"]  # 必须回溯到 Evidence
start_offset: 0                        # 段落内字符偏移
end_offset: 280
chunk_text: "..."                      # 仅用于 embedding input
overlap: 50                            # 块重叠字符数
splitter_v1: "ruler_v1"               # 切分器版本
```

### 7.4 derived_catalog 生成优先级

```text
1. PDF 书签 (pypdf 提取)
2. 印刷目录页（识别"目录"/"CONTENTS"页，提取结构化文本）
3. 正则规则（"第X章/节/部分"、"X.X.X"、罗马数字前缀）
4. LLM 兜底（整书结构推断，标记低 confidence）
```

### 7.5 M4 任务清单

- [ ] 实现 `scripts/navigation/toc_extract_bookmarks.py`
- [ ] 实现 `scripts/navigation/toc_extract_pages.py`
- [ ] 实现 `scripts/navigation/toc_regex_rules.py`
- [ ] 实现 `scripts/navigation/toc_llm_fallback.py`（可选）
- [ ] 实现 `scripts/navigation/chunk_splitter.py`
- [ ] 实现 `scripts/navigation/summary_generator.py`（LLM，带 provenance）
- [ ] 实现 `scripts/navigation/concept_map_builder.py`
- [ ] 实现 `scripts/navigation/full_rebuild.py` 一键重建
- [ ] 在 M0 样本上验证 derived_catalog 质量
- [ ] 验证: 删除 navigation/ 后重建，结果一致（在容差内）

### 7.6 M4 验收标准

```text
[PASS] 全部 1458 本书有 derived_catalog（或标记为不可推断）
[PASS] derived_catalog 每条目有 confidence + provenance
[PASS] 抽样 20 本，derived_catalog 与人工目录对比 F1 > 0.85
[PASS] semantic_chunks 每条含 parent_paragraphs + 偏移量
[PASS] 删除 navigation/ 后重建，paragraph_ids 完全一致
[PASS] 重建 summary 与原 summary 有 generator_version 追踪
```

---

## 八、M5: Embedding + 语义检索

### 8.1 目标

基于 semantic_chunks 生成 Embedding，建立 FAISS 索引。

### 8.2 模型与接口

```yaml
current_embedding_model: "bge-small-zh-v1.5"
vector_dimension: 512
interface: EmbeddingModel (可替换)
future_candidates:
  - bge-m3 (多语言)
  - text-embedding-3-small (API)
```

### 8.3 FAISS 索引设计

```text
index/
└── vectors.faiss              # 唯一向量存储
    + vectors_map.jsonl        # vector_id → semantic_chunk_id 映射
```

必须保留映射文件，FAISS 内部 ID 不能直接关联 Evidence。

### 8.4 M5 任务清单

- [ ] 实现 `scripts/embedding/model.py` — EmbeddingModel 抽象
- [ ] 实现 `scripts/embedding/generate.py` — 批量生成向量
- [ ] 实现 `scripts/embedding/faiss_index.py` — 索引构建和查询
- [ ] 实现 `scripts/search/hybrid.py` — 三引擎检索 + RRF
- [ ] 验证: 向量检索返回结果 snippet 与 Evidence 原文匹配
- [ ] 验证: 检索结果 ref 能正确解析
- [ ] 性能基准: 1458 本书检索延迟 < 200ms

### 8.5 M5 验收标准

```text
[PASS] FAISS 索引与 semantic_chunks 数量一致
[PASS] vectors_map.jsonl 与 FAISS 内部 ID 一一对应
[PASS] 语义检索结果能解析为 Evidence + Anchor
[PASS] 混合检索（keyword + semantic + concept）RRF 合并正确
[PASS] 删除 index/ 前 FTS5 检索仍然可用（降级模式）
[PASS] embedding 模型可在配置中切换，不改核心代码
```

---

## 九、质量保障

### 9.1 阶段质量门禁

每个 Mi 完成后必须执行:

```bash
python -m scripts.verify --milestone M{i} --report verify-M{i}.md
```

### 9.2 全量质量检查清单

```text
[ ] 引用可验证率 ≥99.9%
[ ] 原文精确匹配率 100%
[ ] Navigation 重建一致性（ref 集合差异=0）
[ ] 删除降级能力（无 index/ 时 FTS5 可用）
[ ] ingest 幂等性（旧 Evidence 不变）
[ ] reingest 版本链（Navigation 绑定最新）
[ ] Anchor 完整性 100%
[ ] 目录不混合（derived_catalog 必须有 confidence）
```

### 9.3 禁止事项（全阶段通用）

❌ Ground Truth 重排段落  
❌ Ground Truth 删除重复标题/页眉  
❌ Ground Truth LLM 修复错别字  
❌ derived_catalog 不带 confidence  
❌ 语义 chunk 没有 parent_paragraphs  
❌ byte_range 替代 Anchor  

---

## 十、目录结构（目标态）

```
book-library-skill/
├── SKILL.md                      # 职责规范（权威）
├── REDESIGN.md                   # 迁移说明
├── AIAE_INTEGRATION.md           # 接口契约（权威）
├── IMPLEMENTATION_PLAN.md        # 本文档（权威）
├── ARCHITECTURE_DESIGN_v2.md     # 历史已废弃
├── README.md
├── data/
│   ├── manifest.jsonl            # 三级 ID 注册中心
│   ├── raw/                      # 永久原始文件 (immutable)
│   │   ├── pdf/
│   │   ├── chm/
│   │   └── djvu/
│   ├── evidence/                 # Ground Truth (immutable)
│   │   ├── books.jsonl
│   │   ├── pages.jsonl
│   │   ├── paragraphs.jsonl
│   │   └── anchors.jsonl
│   ├── catalog/                  # 单 SQLite（可重建）
│   │   └── catalog.db
│   ├── navigation/               # 语义派生（可删除）
│   │   ├── derived_catalog.jsonl
│   │   ├── summaries.jsonl
│   │   ├── concept_map.json
│   │   └── semantic_chunks.jsonl
│   └── index/                    # 物理索引
│       ├── vectors.faiss
│       └── vectors_map.jsonl
├── scripts/
│   ├── detect/                   # 文本可提取性检测
│   ├── pipeline/                 # 两条并行管线
│   │   ├── text_extract.py
│   │   ├── ocr_extract.py
│   │   ├── normalizer.py
│   │   └── anchor_builder.py
│   ├── catalog/                  # SQLite 操作
│   ├── navigation/               # 派生数据生成
│   ├── embedding/                # 向量模型
│   ├── search/                   # 检索服务
│   └── verify/                   # 质量验证
└── docs/
    └── decisions/                # 决策记录（ADR）
        └── 2026-07-31-eight-decisions.md
```

---

## 十一、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| RapidOCR 中文准确率低于 95% | 中 | 高 | M0 已验证，备选 PaddleOCR（需配 mkldnn 关闭） |
| 个别 PDF 加密或损坏 | 低 | 低 | 标记为 parser_error，跳过并记录 |
| 三级 ID 分配冲突 | 低 | 中 | SHA-256 辅助去重 |
| SQLite 写入性能瓶颈 | 低 | 中 | 批量事务 + WAL 模式 |
| Embedding 模型未来切换 | 高 | 低 | 接口抽象，不在代码中硬编码模型 |
| 1458 本 ingest 耗时过长 | 中 | 中 | 断点续传 + 分批处理 + 并行 worker |

---

## 十二、引用关系

```
[权威设计文档]
  SKILL.md              ← 职责规范
  AIAE_INTEGRATION.md   ← 接口契约
  IMPLEMENTATION_PLAN.md ← 本文档

[上级架构]
  D:\Pcode\play\_agents\summary\core_idea\
    核心理念.md
    架构设计.md
    设计宪法.md

[废弃文档]
  ARCHITECTURE_DESIGN_v2.md (status: deprecated)
    → superseded_by: SKILL.md
```
