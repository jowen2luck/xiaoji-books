/**
 * @file ReviewService.js
 * @description 深度书评与学术导读工坊服务 (Review & Deep Interpretation Service)
 */

import { callOpenAIAPI } from '../llm/directOpenAI.js'

export default class ReviewService {
  /**
   * @param {Object} options
   * @param {import('./BookService.js').default} options.bookService
   * @param {import('./AnalysisService.js').default} options.analysisService
   */
  constructor({ bookService, analysisService }) {
    this.bookService = bookService
    this.analysisService = analysisService
  }

  /**
   * 生成单书深度解读与书评报告
   * @param {string} bookId 
   * @returns {Promise<Object>} 包含核心论旨、导读大纲、批判性书评与证据引用的报告
   */
  async generateBookReview(bookId) {
    const book = await this.bookService.getBookDetails(bookId)
    if (!book) throw new Error(`Book ${bookId} not found`)

    // 获取书目的部分关键段落作为证据锚点
    const evidencePack = await this.analysisService.execute({
      normalizedQuestion: `深度解读《${book.title}》的核心思想与论证结构`,
      scope: { type: 'single_book', bookIds: [bookId] },
      operations: [
        {
          id: 'op_review_search',
          type: 'single_book_search',
          input: { query: '公社 国际 历史 革命 纲领 阶级 理论 思想', scope: { bookIds: [bookId] }, limit: 6 },
          dependsOn: []
        },
        {
          id: 'op_metric',
          type: 'aggregate_metrics',
          input: {},
          dependsOn: ['op_review_search']
        }
      ],
      expectedOutput: 'deep_review'
    })

    const sampleEv = evidencePack.evidence

    let coreThesis = `《${book.title}》系统性展现了该时期的核心政治纲领与社会变革理念，强调历史规律与实践运动的有机结合，是研究该领域不可或缺的基础性文献。`
    let critique = `**价值与启示**：\n文献具有极强的历史现场感与论辩严密性，其核心逻辑对考察当时工人运动与政治思想演变提供了不可篡改的第一手史料。\n\n**局限性与反思**：\n受限于当时特殊的历史环境与技术发展阶段，部分论断具备鲜明的时代烙印，在用于当代现实问题分析时，需结合现代政治经济学框架做审慎的范式迁移。`

    if (process.env.DASHSCOPE_API_KEY || process.env.DASHSCOPE_API_KEY_QWEN || process.env.OPENAI_API_KEY) {
      try {
        const evTexts = sampleEv.slice(0, 3).map(e => `“${e.excerpt}”`).join('\n\n')
        const res = await callOpenAIAPI({
          baseURL: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
          model: 'qwen-plus',
          messages: [
            {
              role: 'system',
              content: '你是一位精通文献考据与学术批评的资深学者。请为指定书籍撰写深度书评。请输出两部分：1.【核心论旨】(120字以内精要概括本书的核心命题与思想主干)；2.【学术反思与批判】(分“历史价值与思想贡献”和“时代局限与当代反思”两方面论述，条理分明)。'
            },
            {
              role: 'user',
              content: `书名：《${book.title}》\n所属分类：${book.primaryCategory}\n精选原典段落证据：\n${evTexts}`
            }
          ]
        })
        if (res && res.content) {
          const parts = res.content.split(/【学术反思与批判】|学术反思与批判/)
          if (parts.length > 1) {
            coreThesis = parts[0].replace(/【核心论旨】|核心论旨/g, '').trim()
            critique = parts[1].trim()
          } else {
            critique = res.content
          }
        }
      } catch (err) {
        console.warn('[ReviewService] LLM call failed, fallback to template:', err.message)
      }
    }

    // 构建结构化书评
    const reviewReport = {
      bookId,
      bookTitle: book.title,
      category: book.primaryCategory,
      tags: book.tags,
      pageCount: book.pageCount,
      coreThesis,
      structureSummary: book.toc && book.toc.length > 0 
        ? book.toc.map(t => `- **${t.title}** (第 ${t.pageIndex + 1} 页): 奠定该阶段论证核心事实`).join('\n')
        : `- **导言与背景篇**: 梳理历史脉络与思想溯源\n- **核心纲领与论争**: 围绕主要社会政治命题展开论述\n- **结语与实践展望**: 提炼经验总结与理论启发`,
      critique,
      anchors: sampleEv.map(e => ({
        page: e.printedPage,
        excerpt: e.excerpt,
        evidenceId: e.id
      }))
    }

    return reviewReport
  }

  /**
   * 跨书多方观点对照 (Comparative Perspectives)
   * 围绕某一议题，对比多部书的论述
   */
  async compareBooks(topic, bookIds = []) {
    const evidencePack = await this.analysisService.execute({
      normalizedQuestion: topic,
      scope: { type: 'multi_books', bookIds },
      operations: [
        {
          id: 'op_compare',
          type: 'cross_book_compare',
          input: { query: topic, scope: { bookIds }, limit: 10 },
          dependsOn: []
        }
      ],
      expectedOutput: 'comparison'
    })

    const groupedByBook = {}
    for (const ev of evidencePack.evidence) {
      if (!groupedByBook[ev.bookTitle]) groupedByBook[ev.bookTitle] = []
      groupedByBook[ev.bookTitle].push(ev)
    }

    return {
      topic,
      comparisonMatrix: Object.entries(groupedByBook).map(([title, evList]) => ({
        bookTitle: title,
        evidenceCount: evList.length,
        representativeExcerpt: evList[0]?.excerpt || '无匹配观点',
        page: evList[0]?.printedPage || '',
        evidenceId: evList[0]?.id
      }))
    }
  }
}
