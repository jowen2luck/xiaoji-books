# Book Evidence & Discovery Skill

> 面向书籍类来源的 Acquisition Adapter 和 Discovery Provider

## 定位

本 Skill 是 [AIAE](https://github.com/DeusData/)（Agent Information Access Engine）的**书籍领域 Provider**，负责：

- **Acquisition**: PDF/CHM/DJVU → 结构化 Evidence
- **Repository**: 不可变存储原始文本 + 可追溯的来源锚点
- **Discovery**: 书籍内检索、概念别名映射、跨书证据发现
- **Delivery**: 返回证据链 + 引用锚点，供 Agent 组织回答

## 核心原则

遵循 AIAE 设计宪法：

1. **Information Preservation** — 只组织信息，不压缩信息
2. **Ground Truth / Navigation 分离** — 原始文本永久保留，摘要/标签可重建
3. **Engine Never Concludes** — 只返回证据和引用，不下理论结论
4. **Source is Replaceable** — Acquisition 层与 Repository 层解耦

## 目录结构

```
data/
├── raw/               # 永久不可变: 原始 PDF/CHM/DJVU + hash
├── evidence/          # 永久不可变: 页面/段落/目录 Evidence (JSONL)
├── catalog/           # 可重建: SQLite 目录与元数据
├── navigation/        # 可删除重建: 摘要/概念/关系
└── index/             # 可重建: FTS5 + 向量索引
```

## 与其他组件的关系

```
PDF/CHM/DJVU
    ↓
BookAcquisitionAdapter (本 Skill)
    ↓
AIAE Evidence Repository (统一存储)
    ↓
BookDiscoveryProvider (本 Skill) ←→ Cross-source Discovery (AIAE)
    ↓
Context Assembly
    ↓
Agent (推理、总结、回答)
```

## AIAE 四层映射

| AIAE 层 | 本 Skill 实现 |
|---------|-------------|
| Acquisition | BookAcquisitionAdapter |
| Evidence Repository | BookEvidenceStore (immutable) |
| Discovery | BookDiscoveryProvider (keyword + semantic + concept) |
| Context Assembly | 引用格式化 + 证据链输出 |

## 实施优先级

| 阶段 | 目标 |
|------|------|
| **P0** | 原始文件不可变存储 + hash 索引 |
| **P1** | PDF 文本提取 + 页面锚点 Evidence |
| **P2** | 目录解析 + 段落结构恢复 |
| **P3** | SQLite Catalog + FTS5 检索 |
| **P4** | Navigation 生成（摘要、概念候选） |
| **P5** | 向量索引 + 语义检索 |

## 设计、使用与评测文档

- [BOOK_ASSISTANT_GUIDE.md](./docs/BOOK_ASSISTANT_GUIDE.md) — **图书助手 (Book Assistant) 客户端使用与架构指南**
- [BENCHMARK_REPORT.md](./docs/BENCHMARK_REPORT.md) — **企业级知识库问答对比评测与量化报告（Baseline vs 简历版本实现）**
- [SKILL.md](./SKILL.md) — Skill 详细规范（接口、约束、宪法遵守）
- [REDESIGN.md](./docs/architecture/REDESIGN.md) — 重构记录（为什么从"认知引擎"改为"Provider"）

## 历史架构文档（仅供参考）

- [ARCHITECTURE_DESIGN_v2.md](./docs/architecture/ARCHITECTURE_DESIGN_v2.md) — 旧版架构（已废弃，部分思路可参考）
- [IMPLEMENTATION_PLAN.md](./docs/architecture/IMPLEMENTATION_PLAN.md) — 旧版实施计划（已废弃）
- [AIAE_INTEGRATION.md](./docs/architecture/AIAE_INTEGRATION.md) — AIAE 契约规范
- [STATUS.md](./docs/architecture/STATUS.md) — 历史里程碑状态跟踪
- [verify-M0.md](./docs/verify-M0.md) — M0 产物验证报告

## 许可证

原始文献版权归各自作者所有，本工具仅做结构化处理和检索。
