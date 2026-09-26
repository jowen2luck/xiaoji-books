# Book Skill 重构记录

> 日期: 2026-07-31  
> 触发: 二哥指导 + AIAE 架构对齐  
> 核心改变: 从"独立认知引擎"改为"AIAE 书籍领域 Provider"

---

## 一、原定位的问题

原方案将 book-library-skill 定位为"马克思主义认知引擎"，存在以下问题：

1. **职责越界**: 设置 Reasoning Graph、生成理论结论，与"Engine Never Concludes"原则冲突
2. **架构平行**: 五层设计（Layer 0-4）与 AIAE 四层架构平行竞争，而非作为其领域 Provider
3. **概念混淆**: 把 Navigation（摘要、概念定义）当作 Ground Truth，违反 Information Preservation 原则
4. **只存储不检索**: 关注数据格式但缺乏明确的检索与引用机制

## 二、新定位

> **Book Evidence & Discovery Skill**  
> 面向书籍类来源的 Acquisition Adapter 和 Discovery Provider。

### 职责边界

| 属于本 Skill | 不属于本 Skill |
|-------------|---------------|
| PDF/CHM/DJVU → Evidence 转换 | 理论推理、辩证分析 |
| 不可变存储文本 + 锚点 | 替代原文的 Summary |
| 书籍内检索（关键词/语义/概念） | 跨来源发现（AIAE 负责） |
| 引用定位 + 格式化 | 论证组织 / 最终结论 |
| 段落上下文加载 | 价值判断 |

## 三、AIAE 对齐

### 四层映射

| AIAE 层 | Book Skill 实现 | 关键澄清 |
|---------|----------------|---------|
| Acquisition | BookAcquisitionAdapter (PDF → Evidence + Anchor) | 生成 evidence_set_id, source_hash |
| Evidence Repository | **BookEvidenceStore = Repository 的书籍实现** | 不是独立数据库，是契约实现 |
| Discovery | BookDiscoveryProvider (keyword + semantic + concept) | 只做书籍内发现，跨来源归 AIAE |
| Context Assembly | View Generator（仅 format_citation） | 最终 Context 组装在 AIAE |

### Ground Truth vs Navigation

```
Ground Truth (永久, 不可变)
├── 原始文件 (PDF/CHM/DJVU, source_hash)
├── 提取文本 (immutable, evidence_set_id 版本化)
│   ├── text_raw (清洗前)
│   └── text (清洗后)
├── 来源锚点 (Anchor: page_index + printed_page + layout_bbox + ...)
├── source_toc (原始书签/页面印刷目录)
└── 出版信息 (书名/作者/ISBN/出版年)

Navigation (可删除, 可重建)
├── derived_catalog (推断目录, 带 confidence + provenance)
├── 章节摘要 (LLM-generated, with provenance)
├── 概念别名映射 (multi-lang synonyms)
├── Embedding 向量 (FAISS — 只存 index/ 一份)
├── 关系图 (概念共现)
└── FTS 倒排索引
```

**关键区分**: `source_toc`（源文件事实）与 `derived_catalog`（推断产物）严格分开存储，不允许混合。

### 宪法遵守

| AIAE 宪法 | 本 Skill 响应 |
|-----------|--------------|
| Information Preservation | Ground Truth 永不修改，只追加 |
| Evidence is Immutable | paragraphs.jsonl 只写不改 |
| Engine Never Concludes | 只返回证据链+锚点，不下结论 |
| The Source is Replaceable | Acquisition 层与 Repository 解耦 |
| Views are Ephemeral | 引用格式化是 View，可重建 |
| Context is Task-dependent | 不预组装固定 Context |

## 四、目录结构变更

```
旧结构:                    新结构:
data/                      data/
├── _kage/                 ├── raw/              ← 原始文件 (immutable)
│   └── www.marxists...    │   ├── pdf/
├── archive/               │   ├── chm/
├── chinese/               │   └── djvu/
└── corpus/                ├── evidence/         ← Ground Truth
    ├── books/             │   ├── books.jsonl
    ├── paragraphs/        │   ├── pages.jsonl
    └── (空)               │   └── paragraphs.jsonl
                           ├── catalog/          ← SQLite + FTS5（可重建）
                           │   └── catalog.db
                           ├── navigation/       ← 语义派生（可删除重建）
                           │   ├── concept_map.json
                           │   ├── summaries.jsonl
                           │   └── claim_candidates.jsonl
                           └── index/            ← 物理索引（单一来源）
                               └── vectors.faiss  ← 只存此处（FTS5 合并到 catalog.db）
```

**关键变化**: `navigation/embeddings.faiss` 已删除，向量只在 `index/vectors.faiss` 存一份，避免谁是事实谁是缓存的混淆。

## 五、存储策略

| 数据类型 | 存储 | 理由 |
|----------|------|------|
| 原始文件 | 文件系统 + hash | 永久保留, 可追溯 |
| Evidence | JSONL | 可审计, 可版本控制 |
| 元数据/目录 | SQLite | 结构化查询 |
| 关键词检索 | SQLite FTS5 | 高效全文检索 |
| 向量 | FAISS | 可重建, 无需外部依赖 |
| Navigation | JSONL + 关系文件 | 可删除, 可重建 |

## 六、Skill 接口变更

### 旧接口 (v2 方案)
```python
trace_argument(claim_id)  → 带推理的论证链
get_concept(concept_id)   → 生成概念定义
compare_concepts(concept) → 生成跨书对比结论
```

### 新接口 (对齐 AIAE)
```python
trace_evidence(passage_ref) → 来源链 + 上下文
navigate_concept(concept)  → 别名导航 + 证据引用
format_citation(ref)       → 引用格式化 (View)
search(query, mode)        → 检索 (keyword/semantic/concept)
```

**关键变化**: 不再有"生成结论"的方法，只有"导航到证据"的方法。

## 七、实施路径调整

### 原计划 (v2)
- P0: 1天跑通全部四层（含 LLM 概念抽取、关系抽取）
- 质量风险过高
- Navigation 与 Ground Truth 混在一起

### 新计划 (对齐 AIAE)
- P0: 不可变存储 + hash 索引（Ground Truth 基础）
- P1: PDF 文本提取 + 页面锚点（Evidence）
- P2: 目录解析 + 段落结构（结构化 Evidence）
- P3: SQLite Catalog + FTS5（Discovery 基础）
- P4: Navigation 生成（摘要、概念候选，可选）
- P5: 向量索引 + 语义检索（高级 Discovery）

**原则**: 先确保 Ground Truth 可靠，再增加 Navigation 能力。Navigation 可延期，Ground Truth 必须优先。

## 八、关于 summary/nostalgia 的处理

原文中 `argument_flow` 等 Navigation 内容：
- **保留存在权**: 作为 Navigation 可以存在
- **必须标注**: generator、version、confidence、input_refs
- **不可混入 Ground Truth**: 与原始文本分开存储
- **可全部删除**: 删除后不影响检索和引用能力

## 九、原 v2 文档保留原因

`ARCHITECTURE_DESIGN_v2.md` 保留作为历史文档：
- 其中关于"多尺度检索"和"概念导航"的思路仍有参考价值
- 存储格式设计（段落 JSONL）可以继续使用
- "引用可追溯"的核心目标不变
- 只是需要放置在 Navigation 层，而非作为核心

## 十、总结

| 维度 | 旧定位 | 新定位 |
|------|--------|--------|
| 角色 | 独立认知引擎 | AIAE 书籍 Provider |
| 目标 | 让 Agent 获得理论思考 | 让 Agent 可靠访问书籍证据 |
| 核心资产 | Concept/Claim/Reasoning | Evidence/Anchor/Citation |
| 输出 | 理论结论 | 证据链 + 引用锚点 |
| 约束 | Information Preservation | AIAE 宪法全量遵守 |
