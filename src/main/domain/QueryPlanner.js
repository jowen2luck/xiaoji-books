/**
 * @file QueryPlanner.js
 * @description 图书智能查询规划器 (参考小鸡日记 QueryPlanner)
 * 职责：分析用户问题意图、自动识别/演进 Scope（单书/跨类/全库），规划检索与分析操作 DAG
 */

export default class QueryPlanner {
  /**
   * 自动规划查询方案
   * @param {string} question 用户问题
   * @param {Object} currentScope 当前前端选择或会话中的 Scope
   * @param {Array} knownBooks 已知书目列表（辅助匹配书名）
   * @returns {Object} plan (符合 InquiryPlanSchema)
   */
  plan(question = '', currentScope = {}, knownBooks = []) {
    const normalizedQ = question.trim()
    const detectedScope = { ...currentScope }

    // 1. 尝试从提问文本中自动匹配书名 (例如 《巴黎公社》或 "国际歌")
    const matchedBook = knownBooks.find(b => {
      if (!b.title) return false
      return normalizedQ.includes(b.title) || normalizedQ.includes(`《${b.title}》`)
    })

    if (matchedBook && (!detectedScope.bookIds || detectedScope.bookIds.length === 0)) {
      detectedScope.type = 'single_book'
      detectedScope.bookIds = [matchedBook.id]
    }

    // 2. 判断是否是跨书对比意图
    const isComparison = /对比|区别|异同|不同之处|比较|关系/.test(normalizedQ)
    // 3. 判断是否是请求大纲或全书架构
    const isOutline = /目录|大纲|架构|脑图|章节|框架/.test(normalizedQ)
    // 4. 判断是否是深度书评解读
    const isReview = /书评|解读|核心观点|主旨|评价|思想体系/.test(normalizedQ)

    const operations = []
    let expectedOutput = 'qa_answer'

    if (isOutline) {
      expectedOutput = 'outline'
      operations.push({
        id: 'op_outline_1',
        type: 'extract_outline',
        input: { bookId: detectedScope.bookIds?.[0] || null },
        dependsOn: []
      })
    } else if (isComparison) {
      expectedOutput = 'comparison'
      operations.push({
        id: 'op_compare_1',
        type: 'cross_book_compare',
        input: { query: normalizedQ, scope: detectedScope },
        dependsOn: []
      })
    } else if (isReview) {
      expectedOutput = 'deep_review'
      operations.push({
        id: 'op_search_evidence',
        type: 'single_book_search',
        input: { query: normalizedQ, scope: detectedScope, limit: 10 },
        dependsOn: []
      })
    } else {
      expectedOutput = 'qa_answer'
      operations.push({
        id: 'op_search_evidence',
        type: 'single_book_search',
        input: { query: normalizedQ, scope: detectedScope, limit: 6 },
        dependsOn: []
      })
      operations.push({
        id: 'op_aggregate_metrics',
        type: 'aggregate_metrics',
        input: { query: normalizedQ },
        dependsOn: ['op_search_evidence']
      })
    }

    return {
      normalizedQuestion: normalizedQ,
      scope: {
        type: detectedScope.type || 'global',
        bookIds: detectedScope.bookIds || [],
        categories: detectedScope.categories || [],
        tags: detectedScope.tags || []
      },
      operations,
      expectedOutput
    }
  }
}
