# 图书助手 (Book Assistant) 平台使用与开发指南

> **设计基准**：深度对齐小鸡日记（`daily_log_vue`）的六边形分层架构与证据驱动认识论体系  
> **核心使命**：为读者提供单书/跨类问答、图书结构化分类标签管理、深度学术书评以及“恰到好处”的原文精准溯源伴读体验。

---

## 🌟 核心特性与架构亮点

### 1. 六边形领域驱动分层 (Hexagonal Architecture)
- **Domain 领域层** (`src/main/domain/`):
  - `contracts.js`: Zod 强类型数据契约 (`BookRecord`, `BookEvidenceRef`, `BookEvidencePack`, `InquiryPlan`, `ExplorationResult`)
  - `TagTaxonomy.js`: 多层级分类体系（主学科、主题标签、学术流派）与自动打标推断状态机
  - `QueryPlanner.js`: 智能查询规划器，根据自然语言问题自动推导单书/跨类 Scope 并编排检索操作 DAG
  - `InquirySessionStore.js`: 会话状态机与多轮问答伴读记忆管理
- **Infrastructure 基础设施层** (`src/main/infrastructure/`):
  - `BookCatalogRepository.js`: 基于 Node.js 22 内置 `node:sqlite`（零原生编译依赖），读写 67 本馆藏文献、25,000+ 段落、TOC 目录，以及动态分类标签的物理持久化
  - `BookSearchAdapter.js`: 基于 SQLite FTS5 trigram 中文分词的高性能检索适配器，具备多级停用词清洗与智能降级匹配 (AND $\to$ OR)
- **Application 应用服务层** (`src/main/application/`):
  - `BookService.js`: 书籍元数据、目录大纲与分类打标维护
  - `AnalysisService.js`: 执行查询计划，汇聚事实证据并计算定量指标
  - `InquiryService.js`: 问答编排中枢，协调规划器、分析服务与会话流转
  - `ReviewService.js`: 单书深度导读脑图与跨书学术观点对比矩阵
  - `AnswerComposer.js`: 认识论四层答案合成器，执行引用完整性校验 (Citation Integrity)
- **Agent 智能体层** (`src/main/agent/`):
  - `ToolRegistry.js`: 注册 5 大图书专属工具（检索证据、查阅大纲、拉取上下文、分类打标、生成书评）
  - `executor.js`: ReAct 思考与动作循环（Thought $\to$ Action $\to$ Observation）
- **Presentation 表现层** (`src/renderer/src/`):
  - 基于 Vue 3.5 + Naive UI + ECharts 构建的现代化沉浸式伴读客户端

---

## 📖 三大关键业务场景

### 1. 📚 书架与多维分类标签中心 (`BookShelf.vue`)
- **全库总览**：实时统计馆藏文献总数、累计总页数、分类分布。
- **多维筛选**：支持按"政治经济与社会主义"、"历史与人物传记"、"哲学与方法论"等分类标签快速过滤。
- **动态打标**：支持为任意书籍一键添加自定义主题标签（如 `#巴黎公社`、`#工人运动`、`#国际歌`）。
- **目录查看**：秒级预览书籍原始目录（TOC）或智能切片大纲。

### 2. 🤖 伴读研读工作台 (`ChatWorkbench.vue`)
- **灵活的 Scope 作用域**：
  - **全库宏观探索 (Global)**：跨越全部文献寻找宏观趋势与论断；
  - **主题分类 (Category)**：聚焦某一具体学术流派或学科文献；
  - **指定单书精读 (Single Book)**：锁定单本书籍（如《巴黎公社与国际歌史料集》）进行章节级深研；
  - **多书对照研读 (Multi Book)**：勾选多本书籍进行对照研读。
- **认识论四层分层呈现 (Epistemic Separation)**：
  - 💡 **核心观点解读**：基于事实提炼的逻辑洞见与时代命题解析；
  - 📑 **原文证据卡片**：直接列出精确物理锚点与摘录，支持"原文并行预览"与"查阅上下文"；
  - 📊 **定量计算指标**：覆盖书籍数、段落证据数；
  - 🔮 **深入研讨追问**：AI 自动生成的针对性延伸追问气泡。
- **思维链透明化**：每条回答附带可折叠的推理轨迹（检索步骤、命中的原典锚点），体现"不可变溯源"原则。

### 3. 🔍 原文并行预览与伴读抽屉 (`ParallelReader.vue` + `SourceDrawer.vue`)
- **左右对照阅读**：左侧 PDF 原版影印，右侧 OCR 提取文字，支持分割比例拖拽调整；
- **伴读提问面板**：右侧滑出式面板，仅基于当前页内容提问，支持快速提问标签；
- **"恰到好处"的原文伴读抽屉** (`SourceDrawer.vue`)：
  - 遵照用户核心要求：**当需要展示原文的时候在恰当的地方展示原文**！
  - 不在回答气泡中粗暴堆叠数千字，而是在正文中植入行内引用徽标（如 `[🔖 P.12]`）；
  - 点击徽标或证据卡片时，右侧平滑滑出**原文伴读抽屉**：
    - 标示书籍、精确印刷页码与相关度评分；
    - 醒目展现核心命中的原著段落（不可变 Ground Truth）；
    - **连贯上下文阅读窗 (Context Window)**：支持自由展开查看**前序段落**与**后续段落**，实现真正的原典学术考据，杜绝断章取义！

---

## 🚀 启动与运行

在项目根目录下执行：

```bash
# 1. 启动桌面端开发调试环境 (支持热重载 HMR)
npm run dev

# 2. 构建生产安装包 (Windows / Mac / Linux)
npm run build
```

---

## 🛡️ 架构合规与安全说明
1. **严格遵循最高安全红线**：全流程严禁未经批准的物理删除操作，现有 `data/catalog/catalog.db` 和 `fts5.db` 作为核心数字资产被安全保留并扩展。
2. **零编译轻量设计**：采用 Node.js 原生内置 SQLite，无需复杂 C++ 构建工具链，开箱即用。
