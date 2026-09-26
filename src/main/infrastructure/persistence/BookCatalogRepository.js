/**
 * @file BookCatalogRepository.js
 * @description 图书目录与段落存储仓储层 (基于 Node.js 22 内置 node:sqlite)
 */

import { DatabaseSync } from 'node:sqlite'
import path from 'node:path'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { inferCategoryAndTags } from '../../domain/TagTaxonomy.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default class BookCatalogRepository {
  constructor(dbPath = null) {
    const resolvedPath = this._resolveDatabasePath(dbPath)
    console.log('[BookCatalogRepository] Connecting to SQLite catalog at:', resolvedPath)
    this.dbPath = resolvedPath
    this.db = new DatabaseSync(resolvedPath)
    this._ensureSchemaExtensions()
  }

  _resolveDatabasePath(customPath) {
    if (customPath && fs.existsSync(customPath)) return customPath

    const candidates = [
      process.env.BOOK_CATALOG_DB,
      path.resolve(process.cwd(), 'data/catalog/catalog.db'),
      path.resolve(__dirname, '../../../../data/catalog/catalog.db'),
      path.resolve(__dirname, '../../../data/catalog/catalog.db'),
      path.resolve(__dirname, '../../data/catalog/catalog.db'),
      'd:/Pcode/play/_skills/book-library-skill/data/catalog/catalog.db'
    ].filter(Boolean)

    for (const c of candidates) {
      if (fs.existsSync(c)) {
        const stat = fs.statSync(c)
        if (stat.size > 1000) {
          return c
        }
      }
    }

    // 默认回退
    return path.resolve(process.cwd(), 'data/catalog/catalog.db')
  }

  /**
   * 扩展表结构，平滑支持分类 (primary_category) 与标签 (tags)
   */
  _ensureSchemaExtensions() {
    try {
      const cols = this.db.prepare("PRAGMA table_info(books)").all().map(c => c.name)
      if (!cols.includes('primary_category')) {
        this.db.exec("ALTER TABLE books ADD COLUMN primary_category TEXT DEFAULT '未分类'")
      }
      if (!cols.includes('tags')) {
        this.db.exec("ALTER TABLE books ADD COLUMN tags TEXT DEFAULT '[]'")
      }
      if (!cols.includes('brief_summary')) {
        this.db.exec("ALTER TABLE books ADD COLUMN brief_summary TEXT DEFAULT ''")
      }
    } catch (err) {
      console.warn('[BookCatalogRepository] Schema extension warning:', err.message)
    }
  }

  /**
   * 获取所有图书列表（并规范化友好书名和标签）
   * 自动过滤未真正进行 OCR、仅有 pdfFactory 试用版虚拟打印机水印的伪提取书籍
   */
  listBooks({ category = null, tag = null, search = null, onlyProcessed = true } = {}) {
    let sql = "SELECT * FROM books WHERE 1=1"
    const params = []

    if (category && category !== '全部' && category !== 'all') {
      sql += " AND primary_category = ?"
      params.push(category)
    }

    const rows = this.db.prepare(sql).all(...params)

    // 统计每本书具有真正实质内容（非纯试用版水印）的有效段落数
    const validCountMap = new Map()
    try {
      const validRows = this.db.prepare(`
        SELECT book_id, COUNT(*) as c 
        FROM paragraphs 
        WHERE text_normalized NOT LIKE '%pdfFactory%' AND text_normalized NOT LIKE '%fineprint%'
        GROUP BY book_id
      `).all()
      validRows.forEach(r => validCountMap.set(r.book_id, r.c))
    } catch (e) {
      console.warn('[BookCatalogRepository] Error querying valid paragraphs count:', e.message)
    }

    return rows.map(row => {
      // 友好书名推断
      let title = row.title
      if (!title || title.trim() === '') {
        const basename = path.basename(row.source_path || row.book_id || '', '.pdf')
        title = basename.replace(/[-_]/g, ' ')
        // 常见名录中文化翻译
        if (title.includes('internationale parisco')) title = '巴黎公社与国际歌史料集'
        else if (title.includes('internationale')) title = '国际歌纪念文献'
        else if (title.includes('poem of pottier')) title = '鲍狄埃诗集选'
        else if (title.includes('pottier bio1')) title = '欧仁·鲍狄埃生平传记'
        else if (title.includes('053103')) title = '布哈林文选：过渡时期经济学'
      }

      let tags = []
      try {
        tags = JSON.parse(row.tags || '[]')
      } catch {
        tags = []
      }

      let primaryCategory = row.primary_category || '未分类'

      // 如果尚未打标，进行规则自动打标
      if (primaryCategory === '未分类' || tags.length === 0) {
        const inference = inferCategoryAndTags({ title, sourcePath: row.source_path, bookId: row.book_id })
        if (primaryCategory === '未分类') primaryCategory = inference.primaryCategory
        if (tags.length === 0) tags = inference.suggestedTags
      }

      const validParagraphsCount = validCountMap.get(row.book_id) || 0

      return {
        id: row.book_id,
        artifactId: row.artifact_id,
        sourcePath: row.source_path,
        title,
        authors: row.authors ? [row.authors] : ['国际共运与革命史料编委会'],
        language: row.language || 'zh',
        pageCount: row.page_count || 0,
        primaryCategory,
        tags,
        status: row.status || 'active',
        validParagraphsCount,
        ingestedAt: row.ingestedAt || '2026-09-01'
      }
    }).filter(b => {
      // 严格遵循：未处理生书/纯水印伪提取书先不纳入系统展示
      if (onlyProcessed && b.validParagraphsCount === 0) return false
      if (tag && !b.tags.includes(tag)) return false
      if (search && !b.title.toLowerCase().includes(search.toLowerCase())) return false
      return true
    })
  }

  /**
   * 根据 ID 获取单本图书详情
   */
  getBookById(bookId) {
    const list = this.listBooks()
    return list.find(b => b.id === bookId) || null
  }

  /**
   * 更新图书分类与标签
   */
  updateBookClassification(bookId, { primaryCategory, tags, briefSummary }) {
    let sql = "UPDATE books SET "
    const sets = []
    const params = []

    if (primaryCategory !== undefined) {
      sets.push("primary_category = ?")
      params.push(primaryCategory)
    }
    if (tags !== undefined) {
      sets.push("tags = ?")
      params.push(JSON.stringify(tags))
    }
    if (briefSummary !== undefined) {
      sets.push("brief_summary = ?")
      params.push(briefSummary)
    }

    if (sets.length === 0) return true

    sql += sets.join(", ") + " WHERE book_id = ?"
    params.push(bookId)

    this.db.prepare(sql).run(...params)
    return true
  }

  /**
   * 获取某本书籍的目录结构 (TOC)
   */
  getBookTOC(bookId) {
    const sourceToc = this.db.prepare("SELECT * FROM toc_source WHERE book_id = ? ORDER BY page_index ASC").all(bookId)
    if (sourceToc && sourceToc.length > 0) {
      return sourceToc.map(t => ({
        id: t.id,
        title: t.title,
        pageIndex: t.page_index,
        printedPage: t.printed_page,
        level: t.level || 1,
        type: 'source'
      }))
    }
    const derivedToc = this.db.prepare("SELECT * FROM toc_derived WHERE book_id = ? ORDER BY page_index ASC").all(bookId)
    return (derivedToc || []).map(t => ({
      id: t.id,
      title: t.title,
      pageIndex: t.page_index,
      printedPage: t.printed_page,
      level: t.level || 1,
      type: 'derived'
    }))
  }

  /**
   * 获取指定段落及其周围上下文窗口 (Context Window: 前后各 N 个段落)
   * 用于“恰到好处的原文呈现抽屉”
   */
  getParagraphContext(paragraphId, windowSize = 2) {
    const target = this.db.prepare("SELECT * FROM paragraphs WHERE id = ?").get(paragraphId)
    if (!target) return null

    const bookId = target.book_id
    const paraIndex = target.para_index || 0

    // 取前 N 段（自动过滤 pdfFactory 水印杂音）
    const beforeParas = this.db.prepare(`
      SELECT text_normalized, para_index, printed_page 
      FROM paragraphs 
      WHERE book_id = ? AND para_index < ? AND para_index >= ?
        AND text_normalized NOT LIKE '%pdfFactory%' AND text_normalized NOT LIKE '%fineprint%'
      ORDER BY para_index ASC
    `).all(bookId, paraIndex, Math.max(0, paraIndex - windowSize))

    // 取后 N 段（自动过滤 pdfFactory 水印杂音）
    const afterParas = this.db.prepare(`
      SELECT text_normalized, para_index, printed_page 
      FROM paragraphs 
      WHERE book_id = ? AND para_index > ? AND para_index <= ?
        AND text_normalized NOT LIKE '%pdfFactory%' AND text_normalized NOT LIKE '%fineprint%'
      ORDER BY para_index ASC
    `).all(bookId, paraIndex, paraIndex + windowSize)

    return {
      target: {
        id: target.id,
        bookId: target.book_id,
        pageIndex: target.page_index,
        printedPage: target.printed_page,
        paraIndex: target.para_index,
        text: target.text_normalized || target.text_raw
      },
      contextBefore: beforeParas.map(p => p.text_normalized).join('\n\n'),
      contextAfter: afterParas.map(p => p.text_normalized).join('\n\n')
    }
  }

  /**
   * 通读阅读器连续分页或单页流式获取段落
   * 自动过滤 pdfFactory 等试用版虚拟打印机残留的水印杂音段落
   * @param {string} bookId
   * @param {number} offset
   * @param {number} limit
   * @param {number|null} [pageIndex] 可选指定页码 (0-indexed)
   */
  listParagraphs(bookId, offset = 0, limit = 50, pageIndex = null) {
    let countSql = `
      SELECT COUNT(*) as c 
      FROM paragraphs 
      WHERE book_id = ? 
        AND text_normalized NOT LIKE '%pdfFactory%' 
        AND text_normalized NOT LIKE '%fineprint%'
    `
    const countParams = [bookId]

    let selectSql = `
      SELECT id, book_id, page_index, printed_page, para_index, text_normalized, text_raw
      FROM paragraphs
      WHERE book_id = ? 
        AND text_normalized NOT LIKE '%pdfFactory%' 
        AND text_normalized NOT LIKE '%fineprint%'
    `
    const selectParams = [bookId]

    if (pageIndex !== null && pageIndex !== undefined) {
      countSql += ` AND page_index = ?`
      countParams.push(pageIndex)
      selectSql += ` AND page_index = ?`
      selectParams.push(pageIndex)
    }

    selectSql += ` ORDER BY page_index ASC, para_index ASC LIMIT ? OFFSET ?`
    selectParams.push(limit, offset)

    const total = this.db.prepare(countSql).get(...countParams)?.c || 0
    const rows = this.db.prepare(selectSql).all(...selectParams)

    return {
      total,
      paragraphs: rows.map(r => ({
        id: r.id,
        bookId: r.book_id,
        pageIndex: r.page_index,
        printedPage: r.printed_page || `P.${r.page_index + 1}`,
        paraIndex: r.para_index,
        text: (r.text_normalized || r.text_raw || '').trim()
      }))
    }
  }
}

