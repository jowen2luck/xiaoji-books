# AIAE Integration Contract

> 版本: v1.0 | 生成时间: 2026-07-31  
> 上级设计: [SKILL.md](./SKILL.md) | [REDESIGN.md](./REDESIGN.md)  
> 本文档只描述四个接口契约（Evidence、Anchor、Repository、DiscoveryResult），作为 Book Provider 与 AIAE 主架构之间的正式合同。

---

## 0. 总体关系

### 0.1 三级 ID 体系

| 层级 | 字段 | 稳定性 | 说明 |
|------|------|--------|------|
| 文献层 | `book_id` | 永久稳定 | 逻辑文献标识，如 `book-me01a` |
| 文件实例层 | `artifact_id` | 绑定 SHA-256 | 当前文件内容的 hash，如 `sha256:a1b2c3...` |
| 路径元数据 | `source_path` | 可变 | 当前文件路径，仅作为可变元数据 |

**关键约束**: 文件重命名时 `book_id` 不变，只更新 `source_path`。已有文件名（如 `me01a`）作为 `aliases` 保留，但不作为唯一主键。

**背景**: 1458 个 PDF 中，61 个 stem 值重复（产生 279 个额外条目），文件名不能直接作为主键。

### 0.2 架构关系

```
BookAcquisitionAdapter
        ↓ 写入
AIAE Evidence Repository  ← BookEvidenceStore 是 Repository 的书籍实现
        ↓ 查询
BookDiscoveryProvider
        ↓ 返回 DiscoveryResult
AIAE Cross-source Discovery
        ↓ 组装 Context
AIAE Context Assembly
        ↓ 交付
Agent reasoning
```

**关键声明**: `BookEvidenceStore` 不是独立数据库，它是 AIAE Evidence Repository 契约的**书籍领域实现**。不存在两套 Ground Truth。AIAE Repository 定义统一契约（Evidence/Anchor/Store），Book Provider 提供书籍特有的实现细节。

---

## 1. Evidence 契约

### 1.1 定义

Evidence 是从 Source 中提取的**不可变原始事实单元**。它是 AIAE 系统核心数据的书籍领域实例化。

### 1.2 Evidence 类型

| type | 说明 | 来源 |
|------|------|------|
| `raw_page` | 单页提取文本 | PDF page → OCR/text extraction |
| `raw_paragraph` | 段落文本 | 页面文本 → 段落切分 |
| `source_toc` | 原始书签/目录 | PDF bookmarks 或页面文本中的目录 |
| `derived_catalog` | 派生目录结构 | 正则推断 / LLM 推断 |

### 1.3 Evidence Schema

```yaml
# 身份
id: str                    # 全局唯一标识，格式 ev://book/{book_id}/{type}/{local_id}
type: enum                 # raw_page | raw_paragraph | source_toc | derived_catalog

# 来源锚点（见 Anchor 契约）
anchor: EvidenceAnchor

# 内容
text_normalized: str       # 原文内容（不压缩、不替代）
text_raw: str | null       # 清洗前的原始提取文本（如有清洗）

# 元信息
extractor: str             # 提取器标识，如 "pdfplumber@0.11.10"
extractor_version: str     # 语义版本号
confidence: float          # 提取置信度 0-1
created_at: timestamp      # 首次写入时间

# 不变性
immutable: true            # 永远为 true，标记不可修改
```

### 1.4 约束

- Evidence 写入后**永远不做覆盖式修改**
- 重新提取产生新的 Evidence（新 id），旧版本保留
- `text_raw` 和 `text_normalized` 不能相互替代：清洗后的文本不能悄悄替代原始提取结果

---

## 2. Anchor 契约

### 2.1 定义

Anchor 是 Evidence 在原始 Source 中的**稳定位置标识**。它使任意 Evidence 结果能回到原始文件的精确位置。

### 2.2 为什么不使用 byte_range

PDF 原始文件的字节位置不能稳定对应文本位置（重新压缩、字体子集化、元数据修改都会改变字节偏移）。Anchor 必须使用与文本内容无关、与文件实例绑定的标识。

### 2.3 Anchor Schema

```yaml
# 文件实例标识
source_hash: str           # SHA-256 of raw file（绑定到具体文件实例）
artifact_id: str           # 原始文件引用，格式 art://book/{sha256[:16]}

# 位置（多尺度，至少填一项）
page_index: int            # 内部页码索引（0-based，PDF 内部页码）
printed_page: str | null   # 印刷页码（如 "Ⅳ", "220", "A-1"）
block_id: str | null       # 页面内块标识（文本块/表格/图片）
char_range: [int, int] | null  # 在页面文本内的字符偏移

# 视觉位置（可选，当有 layout 信息时）
layout_bbox: [float, float, float, float] | null  # [x0, y0, x1, y1] PDF 坐标系

# 提取上下文
extractor_version: str     # 提取器版本（影响 ID 映射稳定性）
```

### 2.4 页面号映射

PDF 常见的页面号问题：

- 前言用罗马数字（Ⅰ, Ⅱ, Ⅲ）
- 正文从 1 开始重新计数
- 附录用字母（A-1, A-2）
- 扫描件可能有封面页未编号

Anchor 通过 `page_index`（稳定的内部索引）+ `printed_page`（人类可读）双字段解决此映射问题。

### 2.5 约束

- Anchor 必须能从 Evidence 出发**单方向**回到原始文件
- 同一文件的不同提取版本可以有不同的 Anchor（extractor_version 不同）
- `source_hash` 变化意味着文件实例变化，所有 Anchor 失效

---

## 3. Repository 契约

### 3.1 定义

AIAE Evidence Repository 是系统中**唯一**的 Ground Truth 存储。`BookEvidenceStore` 是其书籍实现，维护书籍领域的 Evidence 读写。

### 3.2 所有权澄清

```
AIAE Evidence Repository（契约/接口）
    ├── BookEvidenceStore（本书 Provider 实现）
    ├── VideoEvidenceStore（视频 Provider 实现，未来）
    ├── DiaryEvidenceStore（日记 Provider 实现，未来）
    └── ...
```

不存在"Book Skill 自己的独立数据库"——所有 Evidence 在概念上属于 AIAE Repository，物理上由各自 Provider 管理。

### 3.3 Repository 接口

```python
class EvidenceRepository:
    """AIAE 统一 Evidence Repository 契约"""
    
    def store(self, evidence: Evidence) -> str:
        """写入 Evidence，返回唯一 id。写入后不可修改。"""
        ...
    
    def get(self, evidence_id: str) -> Evidence | None:
        """按 id 获取 Evidence"""
        ...
    
    def resolve_anchor(self, anchor: EvidenceAnchor) -> Evidence | None:
        """按 Anchor 定位 Evidence"""
        ...
    
    def list_by_source(self, source_hash: str) -> list[Evidence]:
        """列出某 Source 的所有 Evidence"""
        ...
    
    def store_evidence_set(self, evidences: list[Evidence]) -> str:
        """批量写入（原子性），返回 evidence_set_id"""
        ...
```

### 3.4 版本管理（reingest 语义）

重新提取不覆盖旧 Evidence。每次 ingest 产生：

```yaml
evidence_set_id: str       # 本次 ingest 的唯一标识
extractor_version: str     # 提取器版本
source_hash: str           # 提取时的文件 hash
ingested_at: timestamp     # 提取时间
evidence_ids: str[]        # 本次产生的所有 Evidence id
previous_set_id: str | null  # 上一版 evidence_set_id（如有）
```

旧的 Evidence 记录**永久保留**，Navigation 层选择绑定到最新版本。

### 3.5 约束

- Repository **不做删除**，只做追加
- 不同 `evidence_set_id` 的 Evidence 共存，通过版本链追踪
- Navigation 只引用当前版本的 Evidence（旧版本只在需要历史对比时使用）

---

## 4. DiscoveryResult 契约

### 4.1 定义

DiscoveryResult 是 Book Provider 返回给 AIAE Discovery 层的结果。它不是最终 Context，而是 Context 的**原材料**。

### 4.2 与 Context Assembly 的边界

```
BookDiscoveryProvider
    ↓ 返回 DiscoveryResult（本契约定义）
AIAE Discovery（跨源聚合、排序）
    ↓ 交给 Context Assembly
AIAE Context Assembly（组装最终 Context）
    ↓ 交付 Agent
```

**Book Provider 不负责最终 Context 格式**。它只提供：
- 哪些 Evidence 相关（evidence_refs）
- 这些 Evidence 的位置和元信息（anchors, metadata）
- 相关性得分（score, match_type）

Context 如何拼装（截断策略、引用格式、上下文窗口大小）由 AIAE Context Assembly 决定。

### 4.3 DiscoveryResult Schema

```yaml
# 查询元信息
query: str                 # 原始查询
provider: str              # "book-library-search"
provider_version: str      # Provider 版本

# 结果列表
results: list[DiscoveryHit]

# 聚合信息
total_candidates: int      # 总候选数（截断前）
search_time_ms: int        # 检索耗时
```

### 4.4 DiscoveryHit Schema

```yaml
# 核心引用
evidence_id: str           # Evidence 的 id
ref: str                   # 简洁引用标识，如 "me01a:p220:para3"

# 锚点
anchor: EvidenceAnchor     # 完整 Anchor（可回到原始页面）

# 相关性
score: float               # 相关性得分（归一化）
match_type: enum           # keyword | semantic | concept | fused

# 片段（用于展示，不作为证据本身）
snippet: str | null        # 高亮片段（View，可重建）
snippet_context: str | null  # 前后文本（View，可重建）

# 书目信息（冗余存根，避免额外查询）
book_title: str            # 书名
book_authors: str[]        # 作者
section_title: str | null  # 所在章节

# 溯源
provenance:
  generator: str           # 检索方法，如 "fts5+bge-small-zh"
  generator_version: str
  created_at: timestamp
```

### 4.5 跨书 vs 跨来源

| 类型 | 负责方 | 说明 |
|------|--------|------|
| 跨书发现 | Book Discovery Provider | 同一书籍集合内的跨书检索 |
| 跨来源发现 | AIAE Discovery | 跨 PDF/网页/视频/日记等来源的联合发现 |

Book Provider 不直接做跨来源聚合。它返回 DiscoveryResult 给 AIAE Discovery，由上层做跨源合并。

### 4.6 约束

- DiscoveryResult 是**临时视图**，不存储，不缓存为事实
- 结果中的 `snippet` 和 `snippet_context` 是 View，始终可以从 Evidence 重新生成
- `ref` 必须能解析到 Evidence + Anchor

---

## 5. 存储职责澄清

为避免 `navigation/embeddings.faiss` 和 `index/vectors.faiss` 的职责混淆：

| 目录 | 职责 | 内容 |
|------|------|------|
| `catalog/` | 结构化查询（SQLite） | books, sections, paragraphs 元数据 + FTS5 索引 |
| `navigation/` | 语义派生数据 | concept_map, summaries, alias_map |
| `index/` | 物理检索索引 | FAISS 向量索引（单一来源） |

**向量只存一份**：放在 `index/vectors.faiss`。`navigation/` 不保存向量副本。

---

## 6. 质量标准（可测量）

| 指标 | 定义 | 测量方法 | 阈值 |
|------|------|----------|------|
| 引用可验证率 | ref 能解析到固定页面 | 随机抽 100 个 ref，验证 text_hash 匹配 | ≥99.9% |
| 原文匹配率 | snippet 中的文本能在原始 Evidence 中找到 | 对 100 个搜索结果做子串匹配 | 100% |
| Navigation 重建一致性 | 删除 navigation/ 前后，DiscoveryResult 的 ref 列表一致 | 重建后对比 ref 集合 | 差异=0 |
| 删除降级能力 | 删除 navigation/index 后，FTS5 检索仍可用 | 仅依赖 catalog.db 做关键词检索 | 必须可用 |
| ingest 幂等性 | 重复 ingest 不产生重复 Evidence | 运行两次 ingest，对比 evidence_set_id 和 id 集合 | evidence_set_id 不同，但旧 Evidence 不被修改 |
| 版本切换一致性 | reingest 后 Navigation 绑定到新 evidence_set_id | 检查 Navigation 引用的 evidence_id 属于最新 set | 必须绑定最新 |
