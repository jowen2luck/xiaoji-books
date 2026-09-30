import fs from 'node:fs'
import path from 'node:path'
import { spawn } from 'node:child_process'
import BookIngestionPipeline from '../pipeline/BookIngestionPipeline.js'

export default class BookService {
  /**
   * @param {import('../infrastructure/persistence/BookCatalogRepository.js').default} repo 
   */
  constructor(repo) {
    this.repo = repo
    this._activeBackfills = new Set()
  }

  /**
   * 获取图书列表
   */
  async listBooks(filter = {}) {
    return this.repo.listBooks(filter)
  }

  /**
   * 检查单本图书当前的数据资产质量级别 (Tier 1/2 纯文本 vs Tier 3 全保真)
   */
  async getBookTierStatus(bookId) {
    const navDir = path.resolve(process.cwd(), 'data/evidence/navigation', bookId)
    const docMetaPath = path.join(navDir, 'doc_meta.json')
    if (fs.existsSync(docMetaPath)) {
      try {
        const meta = JSON.parse(fs.readFileSync(docMetaPath, 'utf8'))
        return {
          tier: 'Tier 3',
          tierName: 'Gold (全保真 4 点坐标与结构化版面)',
          ready: true,
          meta
        }
      } catch (e) {
        // ignore parse error
      }
    }
    const isBackfilling = this._activeBackfills.has(bookId)
    return {
      tier: 'Tier 1/2',
      tierName: 'Silver/Bronze (纯文本可用，待高保真回填)',
      ready: false,
      isBackfilling
    }
  }

  /**
   * 查阅触发按需回填 (Access-Triggered On-Demand Backfill)
   * 当用户点击阅读或调阅某本书原文时，若该书尚处 Tier 1/2，则在后台异步唤起精修流水线
   */
  triggerOnDemandBackfill(bookId) {
    if (!bookId || this._activeBackfills.has(bookId)) return

    // 如果已有 Tier 3 doc_meta.json 则无需重复回填
    const navDir = path.resolve(process.cwd(), 'data/evidence/navigation', bookId)
    if (fs.existsSync(path.join(navDir, 'doc_meta.json'))) return

    this._activeBackfills.add(bookId)
    console.log(`[BookService] User accessed book '${bookId}'. Triggering background on-demand precision backfill...`)

    const scriptPath = path.resolve(process.cwd(), 'scripts/pipeline/on_demand_backfill.py')
    try {
      const child = spawn('python', [scriptPath, '--book-id', bookId, '--json'], {
        cwd: process.cwd(),
        detached: true,
        stdio: ['ignore', 'pipe', 'pipe']
      })

      let stderr = ''
      child.stderr.on('data', d => { stderr += d.toString() })

      child.on('close', code => {
        this._activeBackfills.delete(bookId)
        if (code === 0) {
          console.log(`[BookService] On-demand backfill succeeded for '${bookId}'. Elevated to Tier 3.`)
        } else {
          console.warn(`[BookService] On-demand backfill failed for '${bookId}' (exit code ${code}): ${stderr.slice(-200)}`)
        }
      })

      child.unref()
    } catch (err) {
      this._activeBackfills.delete(bookId)
      console.warn(`[BookService] Failed to spawn on_demand_backfill for '${bookId}':`, err.message)
    }
  }

  /**
   * 从 navigation 目录直接读取 Tier 3 高保真段落（含 4 点物理 bbox 与多栏顺序）
   */
  _getNavigationParagraphs(bookId, offset = 0, limit = 50, pageIndex = null) {
    const navFile = path.resolve(process.cwd(), 'data/evidence/navigation', bookId, 'paragraphs_v2.jsonl')
    if (!fs.existsSync(navFile)) return null
    try {
      const content = fs.readFileSync(navFile, 'utf8')
      const lines = content.split('\n').filter(Boolean)
      const parsed = []
      for (const line of lines) {
        const item = JSON.parse(line)
        if (pageIndex !== null && pageIndex !== undefined && item.page_index !== pageIndex) {
          continue
        }
        parsed.push({
          id: item.id,
          bookId: item.book_id,
          pageIndex: item.page_index,
          printedPage: `P.${item.page_index + 1}`,
          paraIndex: item.para_index,
          text: (item.text || '').trim(),
          role: item.role,
          isHeading: item.is_heading,
          headingLevel: item.heading_level,
          headingCategory: item.heading_category,
          columnIdx: item.column_idx,
          isSpan: item.is_span,
          bbox: item.bbox,
          confidence: item.confidence
        })
      }
      const total = parsed.length
      const slice = parsed.slice(offset, offset + limit)
      return { total, paragraphs: slice, tier: 'Tier 3' }
    } catch (e) {
      console.warn(`[BookService] Error reading paragraphs_v2 for ${bookId}:`, e.message)
      return null
    }
  }

  /**
   * 获取单本图书详情
   */
  async getBookDetails(bookId) {
    const book = this.repo.getBookById(bookId)
    if (!book) return null
    const toc = this.repo.getBookTOC(bookId)
    const tierStatus = await this.getBookTierStatus(bookId)
    return {
      ...book,
      toc,
      tierStatus
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
    if (paragraphId && typeof paragraphId === 'string') {
      const bookId = paragraphId.split(':')[0]
      if (bookId) {
        this.triggerOnDemandBackfill(bookId)
      }
    }
    return this.repo.getParagraphContext(paragraphId, windowSize)
  }

  /**
   * 通读阅读器分页获取整本书或指定页的段落
   * 优先返回 Tier 3 高保真版面段落（带 bbox 坐标与通栏/分栏流向）；
   * 若尚在 Tier 1/2，则平滑降级提供纯文本并后台唤醒按需回填
   */
  async getBookParagraphs(bookId, offset = 0, limit = 50, pageIndex = null) {
    let actualOffset = offset
    let actualLimit = limit
    let actualPageIndex = pageIndex

    if (typeof offset === 'object' && offset !== null) {
      actualOffset = offset.offset || 0
      actualLimit = offset.limit || 50
      actualPageIndex = offset.pageIndex ?? null
    }

    // 1. 尝试从 Tier 3 高保真导航层获取
    const navResult = this._getNavigationParagraphs(bookId, actualOffset, actualLimit, actualPageIndex)
    if (navResult && navResult.paragraphs.length > 0) {
      return navResult
    }

    // 2. 尚处 Tier 1/2：触发按需后台回填，并即时回退返回 SQLite 存量纯文本
    this.triggerOnDemandBackfill(bookId)
    const dbResult = this.repo.listParagraphs(bookId, actualOffset, actualLimit, actualPageIndex)
    return {
      ...dbResult,
      tier: 'Tier 1/2'
    }
  }

  /**
   * 自动扫描并索引已处理好的书籍 (切片 + FTS 索引构建)
   */
  async syncProcessedBooks(opts = {}) {
    const pipeline = new BookIngestionPipeline({ dbPath: this.repo.dbPath })
    return pipeline.run(opts)
  }
}



