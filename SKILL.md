---
name: book-library-skill
description: "Book Evidence & Discovery Skill — 面向书籍类来源的 Acquisition Adapter 和 Discovery Provider。负责 PDF/CHM/DJVU 等书籍文件的获取、结构恢复（章节/页/段落/锚点）、不可变 Evidence 保存、以及书籍领域检索与引用定位。本 Skill 不生成理论论证，不下结论；推理与总结由 Agent 完成。"
---

# Book Evidence & Discovery Skill

> 定位: AIAE (Agent Information Access Engine) 的书籍领域 Provider  
> 上层架构: Acquisition → Evidence Repository → Discovery → Context Assembly  
> 核心原则: Information Preservation — 只组织信息，不压缩信息

## 一、项目定位

Book Evidence & Discovery Skill 是 AIAE 的**书籍领域适配器**，负责：

1. **Acquisition**: PDF/CHM/DJVU → 结构化 Evidence（章节、页面、段落、锚点）
2. **Repository**: 不可变存储原始文本 + 可追溯的来源锚点
3. **Discovery**: 书籍内检索、概念别名映射、跨书证据发现
4. **Delivery**: 返回证据链 + 引用锚点，供 Agent 组织回答

**不负责**：
- 理论推理、辩证分析、最终结论（Agent 的职责）
- 替代原文的摘要压缩（违反 Information Preservation）
- 独立的 Reasoning Graph（属于 AIAE Navigation 层）

## 二、AIAE 四层映射

> **Repository 所有权声明**: `BookEvidenceStore` 不是独立数据库。它是 AIAE `Evidence Repository` 契约的**书籍领域实现**。不存在两套 Ground Truth。AIAE 定义统一契约（store/get/resolve_anchor），Book Provider 提供书籍特有的 Extract + Anchor 细节。

```
AIAE Layer              Book Skill 对应
═══════════════════════════════════════════════════════════════
Acquisition             Book Acquisition Adapter
                        PDF → Text + Layout + Anchors
                        CHM → HTML + TOC
                        DJVU → Text + Images

Evidence Repository     Book Evidence Store（Repository 的书籍实现）
                        - 原始文件 (immutable, hashed, source_hash)
                        - 提取文本 (immutable, versioned by evidence_set_id)
                        - 页面锚点 (page_index + printed_page + layout_bbox)
                        - 段落切片 (paragraph + ref + anchor)

Discovery               Book Discovery Provider
                        - 关键词检索 (SQLite FTS5)
                        - 语义检索 (FAISS in index/)
                        - 概念别名导航 (navigation/concept_map)
                        - 跨书证据发现（仅书籍内，跨来源由 AIAE 负责）

Context Assembly        View Generator (仅限输出格式化)
                        - 引用格式化（format_citation）
                        - 证据链输出（EvidenceSet / DiscoveryResult）
                        - 最终 Context 组装由 AIAE 负责，不在本 Skill 范围内
```

## 三、Ground Truth vs Navigation 分离

> AIAE 宪法第一条: 保持 Ground Truth 不变，允许构建 Navigation Layer。

### 3.1 Ground Truth（永久保留，不可变）

| 内容 | 说明 |
|------|------|
| 原始文件 | PDF/CHM/DJVU 原件，带 SHA-256 |
| 提取文本 | 逐页/逐段提取的原文（含版本和来源） |
| Evidence Anchor | 原始文件中的稳定位置标识（页面/块/坐标） |
| 目录结构 | source_toc（原始书签）与 derived_catalog（推断）严格区分 |
| 出版信息 | 书名、作者、版本、ISBN、出版年 |

每条 Evidence 记录必须包含完整 Anchor（PDF 的字节偏移不能稳定对应文本位置，因此不使用 byte_range）：

```yaml
# 身份
id: str                    # 全局唯一标识
type: enum                 # raw_page | raw_paragraph | source_toc | derived_catalog

# 来源锚点
source_hash: str           # SHA-256 of raw file（绑定到具体文件实例）
artifact_id: str           # 原始文件引用，格式 art://book/{sha256[:16]}
page_index: int            # 内部页码索引（0-based）
printed_page: str | null   # 印刷页码（如 "Ⅳ", "220", "A-1"）
block_id: str | null       # 页面内块标识
char_range: [int, int] | null  # 页面文本内字符偏移
layout_bbox: [x0, y0, x1, y1] | null  # PDF 坐标系视觉位置

# 内容
text_raw: str | null       # 原始提取文本（清洗前，immutable）
text_normalized: str       # 机械修复后的版本（normalization_version 追踪）

# 提取元信息
extractor: str             # 提取器标识，如 "pdfplumber@0.11.10"
extractor_version: str     # 语义版本号
normalization_version: str # 清洗规则版本（如 "norm_v1"）
confidence: float          # 提取置信度 0-1
created_at: timestamp      # 首次写入时间

# 版本管理
evidence_set_id: str       # 所属 ingest 批次
previous_set_id: str | null  # 上一版（reingest 时填写）
```

### 3.1.1 source_toc vs derived_catalog

| 类型 | 来源 | 约束 |
|------|------|------|
| `source_toc` | PDF bookmarks / 页面印刷的目录页 | 直接来自源文件事实，无需 confidence |
| `derived_catalog` | 正则推断（`^第.+章`） / LLM 推断的结构化目录 | 必须带 `confidence` 和 `provenance` |

两类目录分开存储，不允许混合。引用时必须区分"书中原有目录如此"vs"我们推断的目录如此"。

### 3.1.2 文本清洗规则（text_raw vs text_normalized）

每条 Evidence 包含两个版本:

| 字段 | 说明 | 可变性 |
|------|------|--------|
| `text_raw` | 原始提取/OCR 输出，不做任何修改 | 写入后不变 |
| `text_normalized` | 机械修复后的版本 | 跟随 normalization_version |

**允许的机械修复**（仅限以下 5 项）:

| 规则 | 说明 |
|------|------|
| `fullwidth_to_halfwidth` | 全角数字/字母转半角（`０→0`，`Ａ→A`） |
| `cjk_spacing_fix` | 修复 CJK 字符间多余空格（`马 克 思→马克思`） |
| `strip_head_tail_whitespace` | 去除段落首尾无意义空白 |
| `unify_newlines` | 统一换行符为 `\n` |
| `remove_watermark` | 去除明确识别的水印文本（需规则配置） |

**禁止覆盖 Ground Truth 的操作**（只能在派生层）:

| 禁止操作 | 说明 |
|----------|------|
| 段落重排 | 属于 Interpretation |
| 断句补全 | 属于 Interpretation |
| 删除重复标题/页眉页脚 | 丢失源文件事实 |
| LLM 修复错别字 | 属于 Interpretation |
| 任何改变段落顺序的操作 | 破坏 printed_page 绑定 |

以上禁止操作可在 Navigation 层生成派生字段（`paragraph_derived`、`semantic_chunk`、`page_header_detected`），并保留 `input_refs` 和生成器版本。

### 3.2 Navigation（可重建，可删除）

| 内容 | 说明 | 重建依赖 |
|------|------|---------|
| 章节摘要 | LLM 生成的章节概述 | 原始文本 + prompt |
| 概念别名 | 多语言/同义概念映射 | LLM + 领域词典 |
| 论断候选 | 从文本提取的 Claim 候选 | NER + LLM |
| 论证流 | 章节内的论证结构假设 | LLM analysis |
| Embedding | 段落/章节向量 | embedding model |
| 关系图 | 概念/论断间关系 | 全量 Navigation |
| 倒排索引 | 关键词检索索引 | 原始文本 |

每条 Navigation 记录必须包含 provenance：

```yaml
input_refs: str[]       # 基于哪些 Ground Truth
generator: str          # 生成脚本/model
version: str            # generator 版本
confidence: float       # 生成置信度
created_at: timestamp
```

### 3.3 关键约束

- **Navigation 可以全部删除，从 Ground Truth 重新生成**
- **Ground Truth 永远不做覆盖式修改**
- **Discovery 优先查询 Navigation，但结果必须能回溯到 Ground Truth**

## 四、存储策略

### 4.1 存储组合

| 数据类型 | 存储方式 | 说明 |
|----------|----------|------|
| 原始文件 | 文件系统 + hash 索引 | immutable, 永久保留 |
| Evidence & Anchor | JSONL 文件 | 可审计, 可导出 |
| 目录 & 元数据 | SQLite / DuckDB | 结构化查询 |
| 关键词检索 | SQLite FTS5 | 全文检索 |
| 向量检索 | FAISS / hnswlib | 语义检索 (可重建) |
| Navigation | JSONL + 关系文件 | 可删除重建 |

### 4.2 存储职责澄清（避免重复）

```text
data/
├── raw/                    # 永久不可变
│   ├── pdf/                # 原始 PDF
│   ├── chm/                # 原始 CHM
│   └── djvu/               # 原始 DJVU
├── evidence/               # 永久不可变（Ground Truth）
│   ├── books.jsonl         # 书目元数据
│   ├── pages.jsonl         # 页面证据
│   └── paragraphs.jsonl    # 段落证据
├── catalog/                # 结构化查询（SQLite，可重建）
│   └── catalog.db          # books + sections + paragraphs + FTS5
├── navigation/             # 语义派生数据（可删除重建）
│   ├── concept_map.json    # 概念别名映射
│   ├── summaries.jsonl     # 章节摘要（带 provenance）
│   └── claim_candidates.jsonl  # 论断候选（带 confidence）
└── index/                  # 物理检索索引（可删除重建）
    └── vectors.faiss       # FAISS 向量索引（单一来源）

**合并约束**: 向量只存一份（`index/vectors.faiss`），`navigation/` 不保存向量副本。FTS5 合并到 `catalog.db` 的 `paragraphs_fts` 虚拟表中，不单独维护 `fts.db`。`navigation/` 只保存概念别名、摘要等语义派生数据；`index/` 仅保存向量物理索引。

### 4.3 Retention Policy

| 层级 | 生命周期 | 重建成本 |
|------|----------|----------|
| Raw | 永久 | 重新获取原件 |
| Evidence | 永久 | 重新 OCR/提取 |
| Catalog | 长期 | 从 Evidence 重建 |
| Navigation | 可删除 | LLM 重新生成 |
| Index | 可删除 | 从 Evidence 重建 |

## 五、核心 Skill 接口

### 5.1 Acquisition

```python
class BookAcquisitionAdapter:
    """将各种书籍格式转换为统一 Evidence"""
    
    def ingest(self, file_path: str) -> BookIngestionResult:
        """
        接收 PDF/CHM/DJVU 文件，产生:
        - evidence_set_id: 本次 ingest 唯一标识
        - source_hash: 文件 SHA-256
        - extractor_version: 提取器版本
        - raw_file_ref: 原始文件引用
        - pages: 逐页提取文本 + Anchor
        - source_toc: 从书签/页面提取的原始目录
        - derived_catalog: 推断的目录结构（带 confidence + provenance）
        - metadata: 书目信息
        """
        pass
    
    def reingest(self, book_id: str) -> BookIngestionResult:
        """
        从原始文件重新生成 Evidence。
        
        不可变语义:
        - 生成新的 evidence_set_id + extractor_version + source_hash
        - 旧 Evidence 记录永久保留，不做覆盖
        - Navigation 重新绑定到新 evidence_set_id
        - 旧版本通过 previous_set_id 链接
        """
        pass
```

### 5.2 Repository

```python
class BookEvidenceStore:
    """不可变 Evidence 存储"""
    
    def store_evidence(self, evidence: Evidence) -> str:
        """存储 Evidence，返回唯一 ID"""
        pass
    
    def get_evidence(self, evidence_id: str) -> Evidence:
        """获取 Evidence"""
        pass
    
    def get_page(self, book_id: str, page: int) -> PageEvidence:
        """获取指定页面的 Evidence"""
        pass
    
    def get_paragraph(self, ref: str) -> ParagraphEvidence:
        """通过锚点引用获取段落（如 "me01a:p220"）"""
        pass
    
    def resolve_citation(self, citation: str) -> ParagraphEvidence:
        """解析人类可读引用（如 "资本论第一卷220页"）"""
        pass
```

### 5.3 Discovery

```python
class BookDiscoveryProvider:
    """书籍领域检索
    
    职责边界:
    - 跨书发现: 本 Provider 负责（同一书籍集合内的跨书检索）
    - 跨来源发现: 不属于本 Provider（由 AIAE Discovery 层负责，跨 PDF/网页/视频/日记等）
    """
    
    def search(
        self,
        query: str,
        mode: Literal["keyword", "semantic", "concept"] = "auto",
        book_ids: list[str] = None,  # 限定书籍范围
        filters: dict = None,        # 时间、作者、分类等
        top_k: int = 10
    ) -> DiscoveryResult:
        """
        检索返回 DiscoveryResult:
        - evidence_refs: 原始 Evidence 引用列表（回到 Ground Truth）
        - anchors: 完整 Anchor 信息（可定位原始页面）
        - snippets: 高亮片段（View，可重建，不作为证据）
        - score + match_type: 相关性信息
        
        注意: DiscoveryResult 是 Context 的原材料，不是最终 Context。
        最终 Context 的组装（截断、排序、拼接策略）由 AIAE Context Assembly 决定。
        """
        pass
    
    def navigate_concept(
        self,
        concept: str
    ) -> ConceptNavigation:
        """
        通过概念别名导航（仅在 navigation/concept_map 范围内）:
        - canonical_name
        - aliases (多语言/同义)
        - related_passages (含锚点引用)
        - cross_book_refs: 跨书引用（仅书籍集合内）
        """
        pass
    
    def trace_evidence(
        self,
        passage_ref: str
    ) -> EvidenceChain:
        """
        追踪证据来源链（不是论证链）:
        - 该段落来自哪本书的哪一页（Anchor）
        - 上下文段落（前后段落 ref）
        - 同一概念的其他出处（ref 列表）
        """
        pass
    
    def format_citation(self, ref: str, style: str = "short") -> str:
        """格式化引用: 'me01a:p220' → '《资本论》第1卷, p.220'
        这是输出 View，可重建，不属于 Ground Truth。
        """
        pass
```

### 5.4 Navigation 生成

```python
class BookNavigationBuilder:
    """从 Ground Truth 生成 Navigation（可重建）"""
    
    def generate_summary(self, section_id: str) -> Summary:
        """生成章节摘要（带 generator 版本和 confidence）"""
        pass
    
    def extract_concepts(
        self,
        book_id: str = None
    ) -> list[ConceptCandidate]:
        """提取概念候选（不生成最终定义）"""
        pass
    
    def build_embedding(self, target: str = "passages") -> EmbeddingIndex:
        """构建向量索引"""
        pass
    
    def rebuild_all(self, book_id: str = None):
        """删除并重建所有 Navigation"""
        pass
```

## 六、与其他组件的协作

```
BookAcquisitionAdapter
        ↓ 写入
BookEvidenceStore = AIAE Evidence Repository 的书籍实现
        ↓ 查询
BookDiscoveryProvider（书籍内跨书检索）
        ↓ 返回 DiscoveryResult
AIAE Cross-source Discovery（跨来源聚合）
        ↓ 组装
AIAE Context Assembly
        ↓ 交付
Agent reasoning
```

**数据流**：
1. 本 Skill 的 Acquisition 层将 PDF 转换为 Evidence
2. Evidence 通过 AIAE Evidence Repository 契约存储（BookEvidenceStore 是其实现）
3. 本 Skill 的 Discovery 层做**书籍内检索**，返回 DiscoveryResult
4. AIAE Discovery 层聚合多个 Provider（书籍、视频、网页等），做**跨来源发现**
5. Context Assembly 组装最终 Context，交给 Agent 做推理

**职责分界**：
- 跨书发现：Book Provider 范围内（同一集合内的多本书）
- 跨来源发现：AIAE Discovery 层职责（跨 PDF/网页/视频/日记等）

## 七、实施优先级

| 阶段 | 目标 | 产出 |
|------|------|------|
| **P0** | 原始文件不可变存储 + hash 索引 | raw/ 目录 + manifest |
| **P1** | PDF 文本提取 + 页面锚点 Evidence | evidence/pages.jsonl |
| **P2** | 目录解析 + 段落结构恢复 | evidence/paragraphs.jsonl |
| **P3** | SQLite Catalog + FTS5 检索 | catalog.db |
| **P4** | Navigation 生成（摘要、概念候选） | navigation/ |
| **P5** | 向量索引 + 语义检索 | vectors.faiss |

## 八、禁止事项

- ❌ 不生成替代原文的 Summary（仅作为 Navigation 辅助）
- ❌ 不做理论判断或辩证结论（Engine Never Concludes）
- ❌ 不使用 LLM 生成的标签替代原始文本
- ❌ 不修改已写入的 Ground Truth
- ❌ 不独立于 AIAE 声称"认知能力"

## 九、质量标准（可测量）

| 指标 | 定义 | 测量方法 | 阈值 |
|------|------|----------|------|
| 引用可验证率 | ref 能解析到固定页面 | 随机抽 100 个 ref，验证 text_hash 匹配原始文本 | ≥99.9% |
| 原文精确匹配 | snippet 中的文本能在原始 Evidence 中找到 | 对 100 个搜索结果做子串匹配 | 100% |
| Navigation 重建一致性 | 删除 navigation/ 前后，ref 集合不变 | 重建后对比结果 ref 列表 | 差异=0 |
| 索引降级能力 | 删除 navigation/index 后，FTS5 检索仍可用 | 仅依赖 catalog.db 做关键词检索 | 必须可用 |
| ingest 幂等性 | 重复 ingest 不修改旧 Evidence | 运行两次 ingest，对比 evidence_set_id | 新 set_id，旧 Evidence 不变 |
| reingest 版本链 | reingest 后 Navigation 绑定到最新 evidence_set_id | 检查 Navigation 引用的 evidence_id | 必须绑定最新版本 |
| Anchor 完整性 | 所有 Evidence 记录含完整 Anchor | 查询 evidence 中 source_hash + page_index 非空率 | 100% |
| 目录区分 | source_toc 与 derived_catalog 不混合 | 检查 type 字段，derived_catalog 必须有 confidence | 100% 符合 |
