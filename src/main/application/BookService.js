/**
 * @file BookService.js
 * @description 图书核心应用服务 (负责书籍元数据、目录大纲、分类与标签管理)
 */

import BookIngestionPipeline from '../pipeline/BookIngestionPipeline.js'

export default class BookService {
  /**
   * @param {import('../infrastructure/persistence/BookCatalogRepository.js').default} repo 
   */
  constructor(repo) {
    this.repo = repo
  }

  /**
   * 获取图书列表
   */
  async listBooks(filter = {}) {
    return this.repo.listBooks(filter)
  }

  /**
   * 获取单本图书详情
   */
  async getBookDetails(bookId) {
    const book = this.repo.getBookById(bookId)
    if (!book) return null
    const toc = this.repo.getBookTOC(bookId)
    return {
      ...book,
      toc
    }
  }

  /**
   * 为图书更新分类与标签
   */
  async updateClassification(bookId, { primaryCategory, tags, briefSummary }) {
    return this.repo.updateBookClassification(bookId, { primaryCategory, tags, briefSummary })
  }

  /**
   * 获取某段落的完整上下文（用于伴读抽屉展示原文）
   */
  async getContextForEvidence(paragraphId, windowSize = 2) {
    return this.repo.getParagraphContext(paragraphId, windowSize)
  }

  /**
   * 通读阅读器分页获取整本书或指定页的段落
   */
  async getBookParagraphs(bookId, offset = 0, limit = 50, pageIndex = null) {
    if (typeof offset === 'object' && offset !== null) {
      const opts = offset
      return this.repo.listParagraphs(bookId, opts.offset || 0, opts.limit || 50, opts.pageIndex ?? null)
    }
    return this.repo.listParagraphs(bookId, offset, limit, pageIndex)
  }

  /**
   * 自动扫描并索引已处理好的书籍 (切片 + FTS 索引构建)
   */
  async syncProcessedBooks(opts = {}) {
    const pipeline = new BookIngestionPipeline({ dbPath: this.repo.dbPath })
    return pipeline.run(opts)
  }
}


