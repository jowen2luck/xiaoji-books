# 图书认知引擎 — 面向Agent的数据架构设计方案

```yaml
status: deprecated
deprecated_at: "2026-07-31"
superseded_by:
  - SKILL.md
  - REDESIGN.md
  - AIAE_INTEGRATION.md
reason: 已从"独立认知引擎"改为"AIAE 书籍领域 Provider"，参见新设计文档。
```

> ⚠️ **已废弃** (2026-07-31)
> 本文档是前一版"独立认知引擎"定位的架构设计，已被 AIAE 对齐的新设计取代。
> 仍可参考的部分：多尺度检索、引⽤可追溯、概念别名映射等思路。
> 新设计请参考 [SKILL.md](./SKILL.md) 和 [REDESIGN.md](./REDESIGN.md)。

> 版本: v2.0 | 生成时间: 2026-07-31
> 审查角色说明: Codex 因 OPENAI_API_KEY 未配置暂不可用，本文档基于 codex 角色定位（高质量架构审查者）由 AI 代理综合产出

---

## 一、当前方案 (IMPLEMENTATION_PLAN.md) 的核心缺陷

### 缺陷1: 只解决"存储"没解决"检索"
- 段落 JSONL + KO Schema 是静态结构
- 没有定义 Agent 如何从用户问题出发，穿过"概念→论断→证据→原文"的路径
- 等同于建了图书馆但没有目录卡片和检索系统

### 缺陷2: 粒度只有段落级，缺乏多尺度视图
- 一段话可能不足以让 Agent 理解完整论证
- 但整本书又太大无法一次性加载
- **缺少"章节摘要"这一中间层做导航**

### 缺陷3: 检索方式完全未定义
- 没说 embedding 什么（段落？章节？概念？）
- 没说何时用关键词、何时用向量、何时用图谱
- KO 的关系网络如何参与检索没有说明

### 缺陷4: Skill 的职责边界不清
- 如果 pdf/xlsx 等 Skill 各自为政，图书认知引擎的 Skill 能带来什么增量价值？
- 没有定义核心区别于"通用 RAG"的能力边界

---

## 二、核心设计原则

### 原则1: Agent 不需要"读完"一本书
给 Agent 一个**可导航的知识地图**，让它能：
1. 快速定位相关材料（检索层）
2. 按需加载细节（加载层）
3. 理解论证结构而非堆砌材料（推理层）

### 原则2: 出处不是装饰，是信用的根基
Agent 的每一个"观点陈述"必须有可验证的来源锚点：
- 锚点到具体页码段落
- 锚点到原文摘录
- Agent 回答时自动输出引用

### 原则3: 知识结构 > 原始文本
12.3GB 原始文本对 Agent 来说是噪声。真正有用的是：
- 概念网络（什么概念和什么概念有关）
- 论证图谱（谁支持/反对什么观点）
- 证据索引（哪个观点有什么原文证据）

---

## 三、修正后的四层数据架构

```
Layer 0  data/_kage/                          ← 原始文件（已完成，只读）
              ↓ pdf_tool.py + 自定义脚本
Layer 1  data/corpus/                          ← 结构化文本
  ├── books/{book_id}.json                     ← 书目元数据 + 目录
  ├── sections/{book_id}/{section_id}.json     ← ★新增: 章节级（含摘要）
  └── passages/{book_id}/{section_id}.jsonl    ← 段落级（带锚点）
              ↓ LLM 抽取 + 人工校验
Layer 2  knowledge/objects/                    ← Knowledge Objects
  ├── concepts.jsonl
  ├── claims.jsonl
  ├── persons.jsonl
  └── events.jsonl
              ↓ 关系抽取
Layer 3  knowledge/graph/                      ← 图谱索引
  ├── relations.jsonl                          ← KO 间关系边
  ├── evidence_index.jsonl                     ← 论断-证据映射
  └── concept_map.json                         ← ★新增: 概念别名/同义映射
              ↓ 向量化
Layer 4  knowledge/index/                      ← ★新增: 检索索引
  ├── passage_vectors.npy                      ← 段落 embedding
  ├── concept_vectors.npy                      ← 概念 embedding
  └── term_index.json                          ← 关键词倒排索引
```

### 关键变更说明

| 原方案 | 修正方案 | 原因 |
|--------|----------|------|
| 只有段落 JSONL | 增加章节级（含摘要） | 导航层：Agent 先看摘要决定是否需要细节 |
| 无 embedding 索引 | Layer 4 独立检索索引 | 检索与存储分离，可独立重建 |
| 无多粒度视图 | 章节/段落/句子三尺度 | 不同查询需要不同粒度 |
| 无概念映射表 | concept_map.json | "剩余价值"有不同语言/时期的表述 |

---

## 四、数据格式规范（修订版）

### 4.1 书目元数据 (corpus/books/{book_id}.json)

```json
{
  "book_id": "ref-book-me01a",
  "title": "马克思恩格斯全集 第一卷（上册）",
  "title_original": "Marx-Engels-Gesamtausgabe Band 1",
  "authors": [
    {"name": "马克思", "role": "author", "person_id": "ko-person-karl-marx"},
    {"name": "恩格斯", "role": "author", "person_id": "ko-person-friedrich-engels"}
  ],
  "compilers": ["中共中央马克思恩格斯列宁斯大林著作编译局"],
  "language": "zh",
  "category": "marx-engels",
  "domain": ["philosophy", "politics", "economics"],
  "volume": "1",
  "subtitle": "1833—1843年3月",
  "source": {
    "type": "pdf",
    "path": "data/_kage/www.marxists.org/chinese/pdf/marx-engels/me01a.pdf",
    "bytes": 2892000,
    "pages": 470,
    "has_bookmarks": false,
    "quality": "text_extractable"
  },
  "structure": {
    "total_sections": 12,
    "total_passages": 850,
    "depth": 3
  },
  "toc": [
    {
      "section_id": "me01a-sec-preface",
      "title": "前言",
      "page_start": 1,
      "page_end": 12,
      "level": 1,
      "children": []
    },
    {
      "section_id": "me01a-sec-part1",
      "title": "第一部分 博士论文和政论文章",
      "page_start": 13,
      "page_end": 470,
      "level": 1,
      "children": [
        {
          "section_id": "me01a-sec-part1-ch1",
          "title": "德谟克利特的自然哲学和伊壁鸠鲁的自然哲学的差别",
          "page_start": 13,
          "page_end": 102,
          "level": 2
        }
      ]
    }
  ],
  "provenance": {
    "created_at": "2026-07-31T00:00:00Z",
    "script": "scripts/pipeline/layer1_ocr/extract_book.py v1.0"
  }
}
```

### 4.2 章节级数据 (corpus/sections/{book_id}/{section_id}.json) ★新增

```json
{
  "section_id": "me01a-sec-part1-ch1",
  "book_id": "ref-book-me01a",
  "title": "德谟克利特的自然哲学和伊壁鸠鲁的自然哲学的差别",
  "part": "第一部分",
  "location": {
    "page_start": 13,
    "page_end": 102,
    "passage_count": 45
  },
  "summary": "本文是马克思的博士论文，通过比较德谟克利特与伊壁鸠鲁的自然哲学差异，论证了人的自由意志和独立性的哲学基础。马克思认为伊壁鸠鲁提出的原子偏斜运动打破了机械决定论，体现了自我意识的自由。",
  "key_concepts": [
    {"concept_id": "ko-concept-atom-declination", "name": "原子偏斜", "mentions": 12},
    {"concept_id": "ko-concept-free-will", "name": "自由意志", "mentions": 8},
    {"concept_id": "ko-concept-self-consciousness", "name": "自我意识", "mentions": 15}
  ],
  "argument_flow": [
    "提出问题：德谟克利特与伊壁鸠鲁的关系",
    "论证原子偏斜的哲学意义",
    "批判机械决定论",
    "得出自由是自我意识的内在属性"
  ],
  "passage_pids": ["me01a:p13:p1", "me01a:p13:p2"]
}
```

### 4.3 段落级 (corpus/passages/{book_id}/{section_id}.jsonl)

```jsonl
{"pid": "me01a:p13:h1", "type": "heading", "level": 2, "text": "德谟克利特的自然哲学和伊壁鸠鲁的自然哲学的差别", "section_id": "me01a-sec-part1-ch1", "page": 13, "ref": "me01a:p13"}
{"pid": "me01a:p14:p1", "type": "paragraph", "text": "本文的目的在于探讨......", "section_id": "me01a-sec-part1-ch1", "page": 14, "ref": "me01a:p14", "word_count": 200}
```

### 4.4 概念映射表 (graph/concept_map.json) ★新增

```json
{
  "ko-concept-surplus-value": {
    "canonical": "剩余价值",
    "aliases_zh": ["剩余价值", "额外价值", "盈余价值"],
    "aliases_en": ["Surplus Value", "Mehrwert"],
    "aliases_de": ["Mehrwert", "Mehrarbeit"],
    "definition_zh": "工人在剩余劳动时间里创造的、被资本家无偿占有的价值",
    "first_appearance": "《哲学的贫困》1847"
  },
  "ko-concept-atom-declination": {
    "canonical": "原子偏斜",
    "aliases_zh": ["原子偏斜", "原子脱离直线", "clinamen"],
    "aliases_en": ["declination of atoms", "clinamen", "swerve"]
  }
}
```

---

## 五、检索机制设计

### 5.1 三引擎协作检索

```
用户问题
    │
    ├──→ [引擎A: 概念匹配] ──→ KO 定位 ──→ 关系图谱遍历
    │     (精确/别名匹配)      找到相关概念     找到相关论断
    │
    ├──→ [引擎B: 向量检索] ──→ 语义相似度 top-k 段落
    │     (embedding cosine)    找到语义相关原文
    │
    └──→ [引擎C: 关键词检索] ─→ 精确关键词匹配 (人名/术语/事件)
          (BM25/倒排索引)
    │
    ▼
  [结果融合] ──→ Reciprocal Rank Fusion 去重+排序+关联
    │
    ▼
  [上下文组装] ─→ 载入选定段落的章节摘要 + 相邻段落 + 引用
    │
    ▼
  [Agent 生成] ─→ 引用原文 + 组织论证 + 输出出处
```

### 5.2 检索流程伪代码

```python
def retrieve_for_agent(query: str, context: dict) -> RetrievalResult:
    # 阶段1: 概念解析（精确）
    concepts = concept_map.lookup(query)
    related_claims = []
    for c in concepts:
        claims = graph.get_outgoing(c, relation_type="Supports")
        related_claims.extend(claims)
    
    # 阶段2: 向量检索（语义）
    query_vec = embed(query)
    passage_hits = passage_index.search(query_vec, top_k=20)
    
    # 阶段3: 关键词检索（精确）
    keyword_hits = term_index.search(query, top_k=10)
    
    # 阶段4: 融合排序
    merged = reciprocal_rank_fusion([related_claims, passage_hits, keyword_hits])
    
    # 阶段5: 上下文扩充（不是只返回匹配段落，而是加载所在章节）
    enriched = []
    for hit in merged.top(k=5):
        section = load_section(hit.pid)
        enriched.append({
            "section_summary": section.summary,
            "key_concepts": section.key_concepts,
            "passages": load_surrounding(hit.pid, window=2),
            "citations": graph.get_citations(hit.pid)
        })
    
    return RetrievalResult(
        context_blocks=enriched,
        concept_map=concepts,
        evidence_chain=build_evidence_chain(merged)
    )
```

### 5.3 不同查询类型的检索策略

| 查询类型 | 示例 | 主引擎 | 辅助引擎 |
|----------|------|--------|----------|
| 概念定义 | "什么是剩余价值" | 概念映射 | 向量检索 |
| 观点罗列 | "马克思如何论证自由意志" | KO 图谱 | 关键词检索 |
| 出处定位 | "原子偏斜在哪篇著作提到" | 关键词 | 概念映射 |
| 对比分析 | "李嘉图与马克思在地租理论上的区别" | 向量+图谱 | 全部 |
| 时间线 | "马克思主义辩证法的发展" | 图谱遍历 | 概念映射 |

---

## 六、BookKnowledgeSkill 接口设计

### 6.1 职责定义

| 职责 | 说明 |
|------|------|
| **统一检索入口** | 封装三引擎协作，Agent 不需要了解内部细节 |
| **引用生成** | 每个结果自带机器可读的引用锚点 |
| **概念导航** | 提供从概念出发的遍历能力 |
| **论证链还原** | 返回完整"主张→论据→原文"链 |
| **跨书对比** | 支持同一概念在不同著作中的对比 |

**不做的**（委托给其他 Skill）：
- PDF 解析 → `pdf` Skill
- 表格/数据处理 → `xlsx` Skill
- 浏览器操作 → `paw-browser` Skill
- 基础文本生成 → 基础 LLM 能力

### 6.2 Skill 伪代码接口

```python
class BookKnowledgeSkill:
    """
    图书认知引擎核心 Skill.
    为 Agent 提供对结构化图书知识的统一检索与导航能力。
    """
    
    def __init__(self, corpus_path: str, index_path: str):
        self.books = BookIndex(corpus_path)
        self.concept_map = ConceptMap(index_path)
        self.graph = KnowledgeGraph(index_path)
        self.passage_index = VectorIndex(index_path)
        self.term_index = TermIndex(index_path)
    
    def search(
        self,
        query: str,
        mode: Literal["auto", "concept", "semantic", "keyword"] = "auto",
        filters: dict = None,  # {"domain": "economics", "period": "1840s"}
        top_k: int = 10,
        context_window: int = 2
    ) -> SearchResult:
        """
        主检索入口，自动选择或融合多引擎结果。
        Returns:
            blocks: list[ContextBlock]   # 章节摘要 + 段落 + 锚点
            concepts: list[ConceptHit]    # 匹配的概念
            evidence_chain: list[Citation]  # 可引用的证据链
        """
        pass
    
    def get_concept(
        self,
        concept_id: str = None,
        concept_name: str = None
    ) -> ConceptDetail:
        """
        获取概念完整信息：定义 + 演化 + 相关概念 + 支撑论断 + 关键出处
        """
        pass
    
    def trace_argument(
        self,
        claim_id: str,
        depth: int = 3
    ) -> ArgumentChain:
        """
        追踪论证链：主张 → 论据 → 原文出处 → 反驳观点
        """
        pass
    
    def format_citation(
        self,
        ref: str,  # "me01a:p220-235"
        style: Literal["short", "full", "inline"] = "short"
    ) -> str:
        """
        格式化引用：
          short:  "《资本论》第1卷, p.220"
          full:   "马克思,《资本论》第一卷, 人民出版社, 2004, p.220-235"
          inline: "马克思指出:'...'（《资本论》第1卷, p.220）"
        """
        pass
    
    def compare_concepts(
        self,
        concept: str,
        books: list[str] = None
    ) -> ComparisonResult:
        """对比一个概念在不同著作/作者中的表述差异"""
        pass
    
    def get_passage(
        self,
        pid: str,
        with_context: bool = True
    ) -> Passage:
        """获取指定段落，可选带上下文"""
        pass
```

### 6.3 与其他 Skill 的协作

```
用户: "马克思在《资本论》里怎么定义剩余价值？"
    │
Agent (意图: 概念定义 + 出处定位)
    │
    ├──→ BookKnowledgeSkill.get_concept("剩余价值")
    │       → 概念定义 + 演化 + key_citations
    │
    ├──→ BookKnowledgeSkill.get_passage(pid="me044:xxx:p5", with_context=true)
    │       → 该段原文 + 前后段落
    │
    ├──→ pdf.render(book.source_path, page=220)  (仅当需要查看原PDF版面)
    │
    └──→ Agent 组织回答：
            "马克思在《资本论》第一卷中定义剩余价值为...（原文引用）
             出处: 《资本论》第一卷, 人民出版社, 2004, 第220-235页"
```

---

## 七、面向 Agent 的设计原则总结

### 7.1 与传统 RAG 的本质区别

| 传统 RAG | 本引擎 |
|----------|--------|
| 文本切片 → 向量化 | 多尺度结构 + 知识图谱 |
| 检索 top-k 相似文本 | 概念定位 → 论证链 → 原文 |
| 把原文喂给 LLM | 给 LLM 知识地图 + 按需加载 |
| 回答质量依赖检索精度 | 回答质量依赖知识结构完整性 |
| 出处是可选特征 | 出处是强制要求 |

### 7.2 让 Agent 理解"论证结构"

```
传统: "找到相关段落" → 多个段落拼在一起 → LLM总结

本引擎: "找到论证链" → Claim + Premises + Evidence

输出示例:
"马克思通过三个步骤论证自由意志:
 1. 【前提】伊壁鸠鲁提出原子偏斜运动 (博士论文 §30)
 2. 【推理】偏斜运动打破了机械决定论 (博士论文 §32)
 3. 【结论】因此自由是自我意识的内在属性 (博士论文 §75)
 这一观点后来在《资本论》中发展为..."
```

### 7.3 概念优先 vs 文本优先

Agent 的知识获取从**概念**出发，而非从**文本**出发：
- 文本优先：搜索字符串 → 返回匹配段 → 拼凑回答
- 概念优先：识别概念 → 找到定义/论断 → 追踪证据 → 组织回答

---

## 八、实施路径（修订版）

| 阶段 | 目标 | 投入 | 产出 |
|------|------|------|------|
| **P0** | 1本书(me01a)完整跑通所有层 | 1天 | 全部4层数据 |
| **P1** | Skill 接口 + 检索引擎 | 3天 | BookKnowledgeSkill v0.1 |
| **P2** | 批量 Layer1 文本提取 | 5天 | 全部图书 Layer1 |
| **P3** | 半自动 Layer2 KO 抽取 | 持续 | KO 逐步积累 |
| **P4** | 检索质量评测调优 | 2天 | 高质量检索 |

### P0 验收标准

```
1. 打开《马克思恩格斯全集第一卷》任意一页，5秒内返回原文
2. 搜索"原子偏斜"能定位到博士论文章节并返回上下文
3. Agent 回答"马克思如何论证自由意志"时:
   - 引用准确 (页码正确)
   - 论证结构清晰 (不是堆砌原文)
   - 标注了引用来源
4. 概念"剩余价值"能关联到多本书中的讨论
```

---

## 九、回答 codex 原始问题的最终结论

### Q1: 当前计划的关键缺陷？
→ 4项：缺检索层、缺章节摘要、缺概念映射、缺 Skill 接口

### Q2: Skill 应该有什么职责？
→ 知识检索统一入口 + 概念层导航 + 论证链还原 + 引用管理

### Q3: 数据解析范式？
→ 多尺度（章→段→句）+ 带锚点 + 带摘要 + 带论证结构（argument_flow）

### Q4: 存储方式？
→ JSON/JSONL 文件 + numpy mmap 向量；不引入外部向量数据库（12.3GB 规模可控）

### Q5: 检索方式？
→ 首选概念匹配 + 图谱遍历；辅助向量召回 + 关键词；融合用 RRF；后处理做上下文扩充

---

*本方案聚焦在审查层面（做什么），不涉及具体实现代码（怎么做）。*
