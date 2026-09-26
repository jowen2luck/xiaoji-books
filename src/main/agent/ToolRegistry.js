/**
 * @file ToolRegistry.js
 * @description 图书助手智能体动态工具注册中心 (参考小鸡日记 ToolRegistry)
 */

export class ToolRegistry {
  /**
   * @param {Object} services
   * @param {import('../application/BookService.js').default} services.bookService
   * @param {import('../application/InquiryService.js').default} services.inquiryService
   * @param {import('../application/ReviewService.js').default} services.reviewService
   */
  constructor(services) {
    this.services = services
    this.tools = new Map()
    this._registerDefaultTools()
  }

  _registerDefaultTools() {
    // 1. 检索图书证据
    this.register({
      name: 'search_book_evidence',
      description: '在指定书目或指定分类范围中检索精准段落，获取带页码的证据包',
      parameters: {
        query: { type: 'string', description: '检索词或问题' },
        bookIds: { type: 'array', items: { type: 'string' }, description: '限定的书籍ID列表(可选)' },
        limit: { type: 'number', description: '返回证据条目上限，默认5' }
      },
      handler: async (args) => {
        const { query, bookIds, limit = 6 } = args
        const scope = { type: bookIds?.length ? 'single_book' : 'global', bookIds }
        const evidence = this.services.analysisService.searchAdapter.search({
          query,
          scope,
          limit
        })

        const uniqueBooks = new Set(evidence.map(e => e.bookTitle))
        const metrics = [
          {
            id: `m_ev_${Date.now()}`,
            label: '检索相关段落证据数',
            value: evidence.length,
            unit: '段',
            sampleSize: evidence.length
          },
          {
            id: `m_bk_${Date.now()}`,
            label: '覆盖权威书籍数',
            value: uniqueBooks.size,
            unit: '本',
            sampleSize: uniqueBooks.size
          }
        ]

        const evidencePack = {
          id: `pack_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
          question: query,
          scope,
          evidence,
          metrics,
          generatedAt: new Date().toISOString()
        }

        return {
          evidencePack,
          evidenceCount: evidence.length,
          evidenceList: evidence.map(e => ({
            id: e.id,
            bookTitle: e.bookTitle,
            page: e.printedPage,
            excerpt: e.excerpt
          }))
        }
      }
    })

    // 2. 查看图书目录大纲
    this.register({
      name: 'get_book_outline',
      description: '获取指定书籍的目录大纲、章节以及全书页数',
      parameters: {
        bookId: { type: 'string', description: '书籍ID' }
      },
      handler: async (args) => {
        const details = await this.services.bookService.getBookDetails(args.bookId)
        if (!details) return { error: '书籍不存在' }
        return {
          title: details.title,
          category: details.primaryCategory,
          pageCount: details.pageCount,
          toc: details.toc
        }
      }
    })

    // 3. 原文上下文溯源 (用于抽屉伴读)
    this.register({
      name: 'fetch_original_context',
      description: '依据证据引用ID获取前后指定段落的完整上下文原文，避免断章取义',
      parameters: {
        paragraphId: { type: 'string', description: '段落ID' },
        windowSize: { type: 'number', description: '前后各取几段，默认2' }
      },
      handler: async (args) => {
        return this.services.bookService.getContextForEvidence(args.paragraphId, args.windowSize || 2)
      }
    })

    // 4. 为图书分类打标签
    this.register({
      name: 'tag_and_classify_book',
      description: '更新或补充某本书的分类和主题标签',
      parameters: {
        bookId: { type: 'string', description: '书籍ID' },
        category: { type: 'string', description: '主分类' },
        tags: { type: 'array', items: { type: 'string' }, description: '主题标签列表' }
      },
      handler: async (args) => {
        await this.services.bookService.updateClassification(args.bookId, {
          primaryCategory: args.category,
          tags: args.tags
        })
        return { success: true, message: `已成功更新《${args.bookId}》分类为 ${args.category}` }
      }
    })

    // 5. 生成学术书评与导读报告
    this.register({
      name: 'generate_book_review',
      description: '为指定图书生成包含核心论旨、导读大纲与批判性评论的深度书评',
      parameters: {
        bookId: { type: 'string', description: '书籍ID' }
      },
      handler: async (args) => {
        return this.services.reviewService.generateBookReview(args.bookId)
      }
    })
  }

  register(toolDef) {
    this.tools.set(toolDef.name, toolDef)
  }

  getTool(name) {
    return this.tools.get(name) || null
  }

  getToolDefinitions() {
    return Array.from(this.tools.values()).map(t => ({
      name: t.name,
      description: t.description,
      parameters: t.parameters
    }))
  }

  async execute(name, args) {
    const tool = this.getTool(name)
    if (!tool) throw new Error(`Tool ${name} not found`)
    return tool.handler(args)
  }
}
