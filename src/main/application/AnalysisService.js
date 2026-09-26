/**
 * @file AnalysisService.js
 * @description 图书分析与证据装配服务 (参考小鸡日记 AnalysisService)
 * 职责：执行查询计划中的操作，检索证据、聚合统计指标，输出结构化 BookEvidencePack
 */

export default class AnalysisService {
  /**
   * @param {Object} options
   * @param {import('../infrastructure/retrieval/BookSearchAdapter.js').default} options.searchAdapter
   * @param {import('./BookService.js').default} options.bookService
   */
  constructor({ searchAdapter, bookService }) {
    this.searchAdapter = searchAdapter
    this.bookService = bookService
  }

  /**
   * 执行查询计划，生成证据包 (BookEvidencePack)
   * @param {import('../domain/contracts.js').InquiryPlan} plan
   * @returns {Promise<import('../domain/contracts.js').BookEvidencePack>}
   */
  async execute(plan) {
    const { normalizedQuestion, scope, operations } = plan

    let allEvidence = []
    const metrics = []

    for (const op of operations) {
      if (op.type === 'single_book_search' || op.type === 'cross_book_compare') {
        const query = op.input.query || normalizedQuestion
        const opScope = op.input.scope || scope
        const limit = op.input.limit || 6

        const results = this.searchAdapter.search({
          query,
          scope: opScope,
          limit
        })
        allEvidence.push(...results)
      } else if (op.type === 'aggregate_metrics') {
        // 计算定量事实：涉及书目数量、段落命中总数
        const uniqueBooks = new Set(allEvidence.map(e => e.bookId))
        metrics.push({
          id: `metric_evidence_count_${Date.now()}`,
          label: '检索相关段落证据数',
          value: allEvidence.length,
          unit: '段',
          operation: 'count',
          sampleSize: allEvidence.length,
          bookIds: Array.from(uniqueBooks)
        })

        metrics.push({
          id: `metric_books_covered_${Date.now()}`,
          label: '覆盖权威书籍数',
          value: uniqueBooks.size,
          unit: '本',
          operation: 'count',
          sampleSize: uniqueBooks.size,
          bookIds: Array.from(uniqueBooks)
        })
      }
    }

    // 去重
    const seen = new Set()
    allEvidence = allEvidence.filter(e => {
      if (seen.has(e.id)) return false
      seen.add(e.id)
      return true
    })

    const pack = {
      id: `pack_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`,
      schemaVersion: '1.0',
      question: normalizedQuestion,
      scope,
      evidence: allEvidence,
      references: allEvidence.map(e => ({
        ...e,
        snippet: e.excerpt,
        text: e.excerpt
      })),
      metrics,
      limitations: allEvidence.length === 0 ? [
        { code: 'NO_EVIDENCE_FOUND', message: '在指定书目范围内未检索到高相关度段落', severity: 'warning' }
      ] : [],
      generatedAt: new Date().toISOString()
    }

    return pack
  }
}
