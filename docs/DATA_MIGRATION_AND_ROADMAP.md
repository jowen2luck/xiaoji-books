# 藏书数据资产治理与后续 OCR/版面分析推进规划 (Data Migration & Processing Roadmap)

> **版本**: v1.0 (2026-09)  
> **目标**: 针对已处理存量（无 bbox / 纯文本）与未处理增量（约 733 本），实施科学、低算力开销、高数据保真度的平滑升级路线。

---

## 一、当前全量数据资产现状盘点

根据 `data/manifest.jsonl`（共 **1,458 本**）与两工作区的实测统计：

| 数据资产类别 | 数量 | 现状特征 | 核心痛点与风险 |
| :--- | :--- | :--- | :--- |
| **群组 1：存量纯文本数据**<br>(`mobile_workshop/corpus/*.jsonl`) | **725 本** | 包含每页纯文本，文本识别质量尚可，可用于基础全文搜索。 | ❌ **无物理 bbox 坐标**，多栏排版可能存在左右行交错，无层级标题元数据。 |
| **群组 2：存量带坐标数据**<br>(`book-library-skill/data/evidence/shard1~4`) | **62 本** | 包含 250MB+ 的 `blocks.jsonl`，保留了原始 4 点物理 bbox。 | 🟡 尚未全量套用最新的 `LayoutAnalyzer` 通栏切带和多级标题。 |
| **群组 3：未处理增量书籍**<br>(待采集提取) | **约 733 本** | 纯 PDF 原始文件（包含 1109 本 `ocr_required` 中的剩余大部分及 `partial_text`）。 | ⏳ 尚未进行 OCR 提取。 |

---

## 二、后续推进总体战略：分级渐进与按需回填 (Tiered Governance & On-Demand Backfill)

> **核心原则**：**算力最小化、业务零中断、查阅触发价值驱动、永久保真。**  
> 坚决放弃无差别的“夜间全量跑批回填”——对未被翻阅的数百本冷门书籍盲目消耗数十小时 GPU/CPU 算力不可操作且缺乏价值。  
> 采用“**用户查阅行为作为天然价值过滤器**”：当用户真正调阅、精读某本书的原文时，后台自动触发高精度懒加载回填（Lazy Precision Backfill），实现“看哪本、精修哪本”。

```
                                1,458 本全库目标
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        ▼                             ▼                             ▼
【第一步：增量未处理】           【第二步：存量有坐标】           【第三步：存量无坐标】
       约 695 本                     40 本 (Shards 1-4)               701 本
        │                             │                             │
        ▼                             ▼                             ▼
 原生执行新标准 OCR            【已完成】免重新 OCR，离线重构      查阅触发·按需懒加载回填：
 (RapidOCR + LayoutAnalyzer)   (block_structure.py)          1. 首屏瞬时返回存量纯文本 (零等待)
 产出完整 4 点 bbox +          已一键重建 40 本书的 64,820     2. 后台异步唤起 on_demand_backfill.py
 多栏重排 + 多级标题           段落高保真 paragraphs_v2      3. 精修完成平滑升迁至 Tier 3 (Gold)
```

---

## 三、四大具体推进步骤与实施方案

### 阶段一：增量未处理书籍（约 733 本）—— 原生标准提取

- **执行策略**：直接执行全新升级的 [`scripts/pipeline/ocr_extract.py`](file:///D:/Pcode/play/_skills/book-library-skill/scripts/pipeline/ocr_extract.py)。
- **核心流程**：
  1. 扫描未处理清单：
     ```bash
     python scripts/pipeline/batch_ingest.py --status-filter ocr_required,partial_text
     ```
  2. 原生启动 `analyze_layout=True` 与 `return_blocks=True`；
  3. 一步到位产出：
     - `blocks.jsonl`：永久不可变的物理真实 4 点坐标事实。
     - `text_normalized`：按通栏断点切带（Span-Banding）和双栏顺序重排后的正文。
     - `page_structure.jsonl`：包含分栏、通栏状态、页眉页码过滤。
     - `headings`：Level 1~4 多级标题树。

---

### 阶段二：存量有坐标书籍（40 本已完成）—— 零算力离线重构

- **执行策略**：利用现有 250MB+ 的 `shard1~4/blocks.jsonl`，**无需重新调用 RapidOCR**，直接纯数学/算法重构。
- **执行结果【已全量完成】**：
  运行离线重构脚本：
  ```bash
  python scripts/pipeline/block_structure.py
  ```
  - **实测耗时**：约 25 秒
  - **处理成果**：全量重构 40 本核心书籍、15,772 页、64,820 个段落、18,179 条 OCR 质量标记；
  - **产出成果**：每一本书生成了带 Level 1~4 多级标题与通栏切带双栏重排的 `navigation/<book_id>/paragraphs_v2.jsonl`、`page_structure.jsonl` 与 `doc_meta.json`，无缝升迁为 **Tier 3 (Gold)**。

---

### 阶段三：存量无坐标书籍（约 701 本）—— 查阅触发·按需懒加载回填 (Access-Triggered On-Demand Backfill)

针对没有保留物理 bbox 的 701 本书，**坚决摒弃夜间无差别批量重跑（算力浪费大、冷门书利用率低、可操作性差）**，全面转向**“用户查阅行为驱动”的高保真按需回填**：

#### 1. 核心业务哲学与设计原则
- **用户查阅行为即最高效的“价值过滤器”**：全库 1,458 本书中，大量书籍为低频或冷门文献。只有当读者真正检索调阅、翻开该书、或者提出伴读问答时，才表明该书具备当下阅读研究价值。
- **渐进增强（Progressive Enhancement）交互体验**：
  - **T0（首屏瞬时响应，零等待）**：用户打开书籍时，前端立即拉取已存入 SQLite/Corpus 的 Tier 1/2 纯文本，毫秒级呈现实体文字，阅读体验零卡顿、零阻塞。
  - **T1（后台静默唤醒）**：系统在 `BookService.getBookParagraphs()` 或 `getContextForEvidence()` 时自动捕获查阅动作。若检测到该书无 Tier 3 坐标元数据，自动派发后台轻量任务：
    ```bash
    python scripts/pipeline/on_demand_backfill.py --book-id <book_id>
    ```
  - **T2（无感平滑升迁）**：后台 `RapidOCR + LayoutAnalyzer` 在十数秒内完成通栏切带、双栏重排与 4 点 bbox 提取后，生成 `navigation/<book_id>/paragraphs_v2.jsonl` 与 `doc_meta.json`。该书永久升迁为 Tier 3（Gold）。后续阅读翻页或再次访问直接享受影印坐标高亮与多级大纲！

#### 2. 工具与接口支撑体系
- **按需回填 CLI 引擎**：[`scripts/pipeline/on_demand_backfill.py`](file:///D:/Pcode/play/_skills/book-library-skill/scripts/pipeline/on_demand_backfill.py)
  - 自动通过 `manifest.jsonl` 探测 PDF 物理路径。
  - 具备幂等性：已处于 Tier 3 的书籍耗时 0.0 秒直接返回。
  - 实测验证：对《国际歌》选集（`book-internationale`，5 页）执行回填，19.4 秒内一步到位生成 213 个带 4 点坐标 block 与 57 个双栏重排段落，无缝完成 Tier 3 认证。
- **应用层服务深度集成**：
  - [`src/main/application/BookService.js`](file:///D:/Pcode/play/_skills/book-library-skill/src/main/application/BookService.js)：内置 `triggerOnDemandBackfill(bookId)` 守护集，防止重复并发触发；优先读取 `paragraphs_v2.jsonl`，降级回退 SQLite。
  - [`src/main/adapters/ipc/bookHandler.js`](file:///D:/Pcode/play/_skills/book-library-skill/src/main/adapters/ipc/bookHandler.js)：新增 `books:tier-status` 与 `books:trigger-backfill` IPC 通道，前端阅读器与书架可实时获知图书 Tier 等级。

---

## 四、数据分级标准与元数据健康度模型 (Data Tiers)

建立统一的数据质量分级标准，允许数据在不同生命周期共存：

| 级别 | 定义 | 元数据完备度 | 适用场景 |
| :--- | :--- | :--- | :--- |
| **Tier 3 (Gold 标准)** | **全保真结构化版面** | 包含 4 点物理 bbox + 通栏切带多栏重排 + Level 1~4 标题 + 段落绑定。 | 左右影印阅读器点选高亮、复杂问答、精准引用。 |
| **Tier 2 (Silver 过渡)** | **文本级结构化** | 仅纯文本 + 正则推断章节标题，无物理 bbox。 | 关键词搜索 (FTS5)、章节浏览、大模型上下文注入。 |
| **Tier 1 (Bronze 原始)** | **扁平文本流** | 仅页面纯文本，无结构化元信息。 | 基础关键字命中。 |
| **Tier 0 (Pending)** | **待处理原始文件** | 仅 PDF 文件及 Hash。 | 待提取队列。 |

---

## 五、实施落地步骤总结（执行现状）

1. **第 1 步（资产清点与架构统一）**【✅ 已完成】:
   - 全库 1,458 本书划分 4 大资产阶梯，规范多栏重排与通栏切带标准规范 [`docs/OCR_AND_LAYOUT_SPECIFICATION.md`](file:///D:/Pcode/play/_skills/book-library-skill/docs/OCR_AND_LAYOUT_SPECIFICATION.md)。
2. **第 2 步（存量带坐标离线重构）**【✅ 已完成】:
   - 运行升级版 `block_structure.py`，0 GPU 算力消耗下完成 40 本书（15,772 页，64,820 段落）的 Tier 3 重建。
3. **第 3 步（按需懒加载回填机制上线）**【✅ 已完成】:
   - 编写并验证 `scripts/pipeline/on_demand_backfill.py`。
   - 接入 Electron 后端应用层 `BookService.js` 与 IPC 通道，实现“用户查阅原文触发回填，首屏纯文本零等待，后台静默升级 Tier 3”。
4. **第 4 步（增量生书原生高保真提取）**【⏳ 推进中】:
   - 针对剩余未处理增量书籍，按批次执行 `batch_ingest.py` / `ocr_extract.py`，直接产出 Tier 3 标准数据资产。
