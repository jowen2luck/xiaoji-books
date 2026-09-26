/**
 * @file contracts.js
 * @description 规范化领域数据契约 (Domain Data Contracts for Book Assistant)
 * 参考小鸡日记 domain/contracts.js，引入认识论四层分层模型与强类型校验
 */

import { z } from 'zod'

// ===================== 1. 书目与元数据契约 =====================

export const BookRecordSchema = z.object({
  id: z.string(),
  artifactId: z.string().optional(),
  sourcePath: z.string().optional(),
  title: z.string(),
  authors: z.array(z.string()).default([]),
  language: z.string().default('zh'),
  pageCount: z.number().default(0),
  primaryCategory: z.string().default('未分类'),
  tags: z.array(z.string()).default([]),
  status: z.string().default('active'),
  ingestedAt: z.string().optional(),
  sourceHash: z.string().optional()
})

// ===================== 2. 原文证据与计算指标契约 =====================

/**
 * 原文证据引用 (BookEvidenceRef)
 * 必须包含稳定的物理锚点：书目ID、章节、内部页码、印刷页码、行/段落标识、原文摘录
 */
export const BookEvidenceRefSchema = z.object({
  id: z.string(),                  // 全局唯一标识，如 ev_bookid_p12_para0
  bookId: z.string(),              // 关联书目
  bookTitle: z.string(),           // 书名
  pageIndex: z.number(),           // 内部 0-based 页码
  printedPage: z.string().nullable().optional(), // 纸质书印刷页码 (如 "第 45 页" 或 "iv")
  chapterTitle: z.string().optional(), // 所属章节标题
  excerpt: z.string(),             // 精确原文摘录 (Ground Truth，不做篡改)
  contextBefore: z.string().optional(), // 前序段落上下文 (用于伴读抽屉)
  contextAfter: z.string().optional(),  // 后续段落上下文 (用于伴读抽屉)
  relevance: z.number().default(1.0)    // 相关度评分 (0-1)
})

/**
 * 确定性计算指标 (ComputedMetric)
 */
export const ComputedMetricSchema = z.object({
  id: z.string(),
  label: z.string(),
  value: z.union([z.number(), z.string(), z.null()]),
  unit: z.string().optional(),
  operation: z.string(), // count / frequency / coverage
  sampleSize: z.number(),
  bookIds: z.array(z.string()).optional()
})

/**
 * 证据包 (BookEvidencePack)
 * 汇聚一次问答或分析过程检索到的所有证据、指标与查询范围
 */
export const BookEvidencePackSchema = z.object({
  id: z.string(),
  schemaVersion: z.string().default('1.0'),
  question: z.string(),
  scope: z.object({
    type: z.enum(['single_book', 'category', 'multi_books', 'global']),
    bookIds: z.array(z.string()).optional(),
    categories: z.array(z.string()).optional(),
    tags: z.array(z.string()).optional()
  }),
  evidence: z.array(BookEvidenceRefSchema).default([]),
  metrics: z.array(ComputedMetricSchema).default([]),
  limitations: z.array(z.object({
    code: z.string(),
    message: z.string(),
    severity: z.enum(['info', 'warning'])
  })).default([]),
  generatedAt: z.string()
})

// ===================== 3. 查询计划契约 (InquiryPlan) =====================

export const InquiryPlanSchema = z.object({
  normalizedQuestion: z.string(),
  scope: z.object({
    type: z.enum(['single_book', 'category', 'multi_books', 'global']),
    bookIds: z.array(z.string()).optional(),
    categories: z.array(z.string()).optional(),
    tags: z.array(z.string()).optional()
  }),
  operations: z.array(z.object({
    id: z.string(),
    type: z.enum(['single_book_search', 'cross_book_compare', 'aggregate_metrics', 'extract_outline']),
    input: z.record(z.unknown()),
    dependsOn: z.array(z.string()).default([])
  })),
  expectedOutput: z.enum(['qa_answer', 'deep_review', 'outline', 'comparison']).default('qa_answer')
})

// ===================== 4. 认识论输出契约 (ExplorationResult) =====================

export const ExplorationResultSchema = z.object({
  sessionId: z.string(),
  evidencePackId: z.string(),
  scopeSummary: z.string(),
  // 认识论分层
  facts: z.array(z.object({
    text: z.string(),
    evidenceRefs: z.array(z.string())
  })),
  computations: z.array(z.object({
    text: z.string(),
    metricRefs: z.array(z.string())
  })),
  hypotheses: z.array(z.object({
    text: z.string(),
    evidenceRefs: z.array(z.string()),
    confidence: z.enum(['high', 'medium', 'low']),
    model: z.string()
  })),
  suggestions: z.array(z.object({
    text: z.string(),
    basisRefs: z.array(z.string()).optional()
  })),
  markdownAnswer: z.string(),
  followUps: z.array(z.string()).default([])
})

// ===================== 5. 运行时验证辅助函数 =====================

export function safeParseBookRecord(data) {
  const result = BookRecordSchema.safeParse(data)
  if (!result.success) {
    console.error('[Contracts] BookRecord validation failed:', result.error.message)
    return { success: false, errors: result.error.issues }
  }
  return { success: true, data: result.data }
}

export function safeParseEvidencePack(data) {
  const result = BookEvidencePackSchema.safeParse(data)
  if (!result.success) {
    console.error('[Contracts] BookEvidencePack validation failed:', result.error.message)
    return { success: false, errors: result.error.issues }
  }
  return { success: true, data: result.data }
}

export function safeParseInquiryPlan(data) {
  const result = InquiryPlanSchema.safeParse(data)
  if (!result.success) {
    console.error('[Contracts] InquiryPlan validation failed:', result.error.message)
    return { success: false, errors: result.error.issues }
  }
  return { success: true, data: result.data }
}
