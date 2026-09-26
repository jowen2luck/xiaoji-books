/**
 * @file BookIngestionPipeline.js
 * @description 已处理书籍自动化切片与全量索引入库管道
 * 
 * 核心设计原则：
 * 1. 【只关注已处理书籍】：未经过 OCR/提取的生 PDF 坚决不纳入系统
 * 2. 【多级源自动发现】：扫描 data/batches/*, data/evidence/, data/.parallel_shards/*
 * 3. 【智能切片与页码绑定】：保持物理页码 printed_page 与 page_index
 * 4. 【书名智能提取】：从 OCR 文本前序页面（版权页/扉页）自动识别真实书名
 * 5. 【全文索引同步】：事务写入 SQLite 并同步构建 FTS5 trigram 索引
 */

import fs from 'node:fs'
import path from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { inferCategoryAndTags } from '../domain/TagTaxonomy.js'

export default class BookIngestionPipeline {
  /**
   * @param {Object} options
   * @param {string} [options.dbPath] SQLite 数据库路径
   * @param {string} [options.dataRoot] 数据根目录
   */
  constructor({ dbPath, dataRoot } = {}) {
    this.dataRoot = dataRoot || path.resolve(process.cwd(), 'data')
    this.dbPath = dbPath || path.resolve(this.dataRoot, 'catalog/catalog.db')
    this.db = new DatabaseSync(this.dbPath)
  }

  /**
   * 自动扫描并增量导入所有已处理好的书籍
   * @param {Object} opts
   * @param {boolean} [opts.force=false] 是否强制重新切片已有书籍
   * @returns {Promise<Object>} 导入统计报表
   */
  async run({ force = false } = {}) {
    console.log('[IngestionPipeline] Starting scan for processed books in:', this.dataRoot)

    // 1. 获取现有已入库书籍
    const existingBookIds = new Set(
      this.db.prepare("SELECT book_id FROM books").all().map(b => b.book_id)
    )

    // 2. 收集候选数据目录
    const candidateDirs = this._discoverProcessedDirs()
    console.log(`[IngestionPipeline] Found ${candidateDirs.length} candidate processed directories.`)

    const stats = {
      scannedDirs: candidateDirs.length,
      discoveredBooks: 0,
      newlyIngested: 0,
      totalParagraphsIndexed: 0,
      skippedUntreated: 0,
      errors: []
    }

    for (const dir of candidateDirs) {
      try {
        const result = this._processDirectory(dir, existingBookIds, force)
        stats.discoveredBooks += result.discovered
        stats.newlyIngested += result.ingested
        stats.totalParagraphsIndexed += result.paragraphs
        stats.skippedUntreated += result.skippedUntreated
      } catch (err) {
        console.error(`[IngestionPipeline] Error processing ${dir}:`, err.message)
        stats.errors.push({ dir, error: err.message })
      }
    }

    console.log('[IngestionPipeline] Ingestion completed. Stats:', stats)
    return stats
  }

  /**
   * 发现包含已提取文件的批次目录
   */
  _discoverProcessedDirs() {
    const dirs = []

    // 1. 检查 data/evidence
    const evidenceDir = path.resolve(this.dataRoot, 'evidence')
    if (fs.existsSync(evidenceDir)) dirs.push(evidenceDir)

    // 2. 检查 data/batches
    const batchesDir = path.resolve(this.dataRoot, 'batches')
    if (fs.existsSync(batchesDir)) {
      const sub = fs.readdirSync(batchesDir, { withFileTypes: true })
      for (const s of sub) {
        if (s.isDirectory()) dirs.push(path.join(batchesDir, s.name))
      }
    }

    // 3. 检查 data/.parallel_shards
    const shardsDir = path.resolve(this.dataRoot, '.parallel_shards')
    if (fs.existsSync(shardsDir)) {
      const sub = fs.readdirSync(shardsDir, { withFileTypes: true })
      for (const s of sub) {
        if (s.isDirectory()) dirs.push(path.join(shardsDir, s.name))
      }
    }

    return dirs
  }

  /**
   * 处理单个目录
   */
  _processDirectory(dir, existingBookIds, force) {
    const booksFile = path.join(dir, 'books.jsonl')
    const pagesFile = path.join(dir, 'pages.jsonl')
    const parasFile = path.join(dir, 'paragraphs.jsonl')

    let discovered = 0
    let ingested = 0
    let paragraphsCount = 0
    let skippedUntreated = 0

    // 只有具有 pages.jsonl 或 paragraphs.jsonl 的才证明已经过 OCR 提取处理！
    if (!fs.existsSync(pagesFile) && !fs.existsSync(parasFile)) {
      return { discovered: 0, ingested: 0, paragraphs: 0, skippedUntreated: 0 }
    }

    // 读取段落或页面索引
    const bookParagraphsMap = new Map() // book_id -> Paragraph[]
    const bookPagesMap = new Map()       // book_id -> Page[]

    if (fs.existsSync(parasFile)) {
      const lines = fs.readFileSync(parasFile, 'utf-8').split('\n')
      for (const line of lines) {
        if (!line.trim()) continue
        try {
          const item = JSON.parse(line)
          const bId = item.book_id
          if (!bId) continue
          if (!bookParagraphsMap.has(bId)) bookParagraphsMap.set(bId, [])
          bookParagraphsMap.get(bId).push(item)
        } catch {}
      }
    }

    if (fs.existsSync(pagesFile)) {
      const lines = fs.readFileSync(pagesFile, 'utf-8').split('\n')
      for (const line of lines) {
        if (!line.trim()) continue
        try {
          const item = JSON.parse(line)
          const bId = item.book_id
          if (!bId) continue
          if (!bookPagesMap.has(bId)) bookPagesMap.set(bId, [])
          bookPagesMap.get(bId).push(item)
        } catch {}
      }
    }

    // 读取元数据 books.jsonl
    const bookMetaMap = new Map()
    if (fs.existsSync(booksFile)) {
      const lines = fs.readFileSync(booksFile, 'utf-8').split('\n')
      for (const line of lines) {
        if (!line.trim()) continue
        try {
          const item = JSON.parse(line)
          if (item.book_id) bookMetaMap.set(item.book_id, item)
        } catch {}
      }
    }

    // 扫描所有具有实际提取内容的书籍
    const candidateBookIds = new Set([...bookParagraphsMap.keys(), ...bookPagesMap.keys()])

    for (const bId of candidateBookIds) {
      discovered++

      // 若已经入库且不强制覆盖，则跳过
      if (existingBookIds.has(bId) && !force) {
        continue
      }

      const meta = bookMetaMap.get(bId) || {}
      const paras = bookParagraphsMap.get(bId) || []
      const pages = bookPagesMap.get(bId) || []

      // 智能切片：如果只有 pages 没有 paragraphs，从 pages 智能切片
      let finalParas = paras
      if (finalParas.length === 0 && pages.length > 0) {
        finalParas = this._slicePagesToParagraphs(bId, pages)
      }

      // 过滤 pdfFactory 试用版虚拟打印机等水印杂音段落
      finalParas = finalParas.filter(p => {
        const text = (p.text_normalized || p.text_raw || '').trim()
        return text && !text.includes('pdfFactory') && !text.includes('fineprint.com')
      })

      // 如果过滤后完全没有任何实际文字（说明是扫描件但未做 OCR，仅提取到了水印），坚决不纳入系统
      if (finalParas.length === 0) {
        skippedUntreated++
        continue
      }

      // 书名智能识别与提取
      const refinedTitle = this._extractRefinedTitle(bId, meta, pages, finalParas)

      // 写入数据库与构建 FTS5 索引
      this._saveBookAndIndex({
        bookId: bId,
        title: refinedTitle,
        meta,
        pages,
        paragraphs: finalParas
      })

      existingBookIds.add(bId)
      ingested++
      paragraphsCount += finalParas.length
    }

    return {
      discovered,
      ingested,
      paragraphs: paragraphsCount,
      skippedUntreated
    }
  }

  /**
   * 将页面长文本智能切分成自然语义段落
   */
  _slicePagesToParagraphs(bookId, pages) {
    const paragraphs = []
    for (const page of pages) {
      const rawText = page.text_normalized || page.text_raw || ''
      if (!rawText.trim()) continue

      // 按空行切分
      const blocks = rawText.split(/\n\s*\n/).map(b => b.trim()).filter(Boolean)
      let paraIdx = 0

      for (const block of blocks) {
        if (block.length < 2) continue

        // 若单段超过 800 字，按句号适当断句切片
        if (block.length > 800) {
          const subSentences = block.split(/(?<=[。！？\n])/)
          let currentChunk = ''
          for (const s of subSentences) {
            if ((currentChunk + s).length > 500 && currentChunk) {
              paragraphs.push({
                id: `${bookId}:p${page.page_index}:para${paraIdx++}`,
                book_id: bookId,
                page_id: `${bookId}:p${page.page_index}`,
                page_index: page.page_index,
                printed_page: page.printed_page || `P.${page.page_index + 1}`,
                para_index: paraIdx,
                text_normalized: currentChunk.trim()
              })
              currentChunk = s
            } else {
              currentChunk += s
            }
          }
          if (currentChunk.trim()) {
            paragraphs.push({
              id: `${bookId}:p${page.page_index}:para${paraIdx++}`,
              book_id: bookId,
              page_id: `${bookId}:p${page.page_index}`,
              page_index: page.page_index,
              printed_page: page.printed_page || `P.${page.page_index + 1}`,
              para_index: paraIdx,
              text_normalized: currentChunk.trim()
            })
          }
        } else {
          paragraphs.push({
            id: `${bookId}:p${page.page_index}:para${paraIdx++}`,
            book_id: bookId,
            page_id: `${bookId}:p${page.page_index}`,
            page_index: page.page_index,
            printed_page: page.printed_page || `P.${page.page_index + 1}`,
            para_index: paraIdx,
            text_normalized: block
          })
        }
      }
    }
    return paragraphs
  }

  /**
   * 从封面/扉页/段落文本中智能提炼书名
   */
  _extractRefinedTitle(bookId, meta, pages, paragraphs) {
    if (meta.title && !meta.title.startsWith('book-') && !/^\d{6,}/.test(meta.title)) {
      return meta.title
    }

    // 从前 5 个段落文本中匹配特征: "书名=xxx" 或 《xxx》
    const earlyText = paragraphs.slice(0, 8).map(p => p.text_normalized || '').join('\n')
    
    // 匹配: 书名=美国工人运动史
    const titleEqualMatch = earlyText.match(/书名\s*[:=]\s*([^\r\n]+)/)
    if (titleEqualMatch && titleEqualMatch[1].trim()) {
      return titleEqualMatch[1].trim().replace(/[《》]/g, '')
    }

    // 匹配书名号
    const bookTitleMarkMatch = earlyText.match(/《([^》\r\n]{2,30})》/)
    if (bookTitleMarkMatch && bookTitleMarkMatch[1].trim()) {
      return bookTitleMarkMatch[1].trim()
    }

    // 从 source_path 或 book_id 优雅清洗
    const sourcePath = meta.source_path || bookId
    const base = path.basename(sourcePath, path.extname(sourcePath)).replace(/[-_]/g, ' ')
    if (base.includes('internationale parisco')) return '巴黎公社与国际歌史料集'
    if (base.includes('internationale')) return '国际歌纪念文献'
    if (base.includes('poem of pottier')) return '鲍狄埃诗集选'
    if (base.includes('pottier bio1')) return '欧仁·鲍狄埃生平传记'
    if (base.includes('053103')) return '布哈林文选：过渡时期经济学'
    if (base.includes('20190715a')) return '美国工人运动史'

    return base || bookId
  }

  /**
   * 事务性保存图书、段落并构建 FTS5 trigram 索引
   */
  _saveBookAndIndex({ bookId, title, meta, pages, paragraphs }) {
    const pageCount = meta.page_count || meta.total_pages || (pages.length > 0 ? pages.length : 1)
    const inference = inferCategoryAndTags({ title, sourcePath: meta.source_path || '', bookId })

    // 1. 插入 books 表
    this.db.prepare(`
      INSERT OR REPLACE INTO books (
        book_id, artifact_id, source_path, title, authors, language,
        page_count, status, ingested_at, evidence_set_id, source_hash,
        primary_category, tags
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      bookId,
      meta.artifact_id || `art://${bookId}`,
      meta.source_path || '',
      title,
      meta.authors || '史料编纂组',
      'zh',
      pageCount,
      'processed',
      new Date().toISOString(),
      meta.evidence_set_id || `es-${Date.now()}`,
      meta.source_hash || '',
      inference.primaryCategory,
      JSON.stringify(inference.suggestedTags)
    )

    // 2. 批量写入 pages 表、paragraphs 表与 paragraphs_fts 虚拟表
    const insertPage = this.db.prepare(`
      INSERT OR REPLACE INTO pages (
        id, book_id, artifact_id, evidence_set_id, page_index, printed_page,
        text_raw, text_normalized, normalization_version, confidence, char_count
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `)

    const insertPara = this.db.prepare(`
      INSERT OR REPLACE INTO paragraphs (
        id, book_id, artifact_id, evidence_set_id, page_id,
        page_index, printed_page, para_index, text_normalized, text_raw
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `)

    const insertFts = this.db.prepare(`
      INSERT INTO paragraphs_fts (paragraph_id, book_id, page_index, text_normalized)
      VALUES (?, ?, ?, ?)
    `)

    this.db.exec("PRAGMA foreign_keys = OFF")
    this.db.exec("BEGIN TRANSACTION")
    try {
      // 写入 pages
      for (const pg of pages) {
        const pId = pg.id || `${bookId}:p${pg.page_index || 0}`
        insertPage.run(
          pId,
          bookId,
          meta.artifact_id || '',
          meta.evidence_set_id || '',
          pg.page_index || 0,
          pg.printed_page || `P.${(pg.page_index || 0) + 1}`,
          pg.text_raw || pg.text_normalized || '',
          pg.text_normalized || pg.text_raw || '',
          pg.normalization_version || 'v1',
          pg.confidence || 0.95,
          (pg.text_normalized || '').length
        )
      }

      // 先清理可能存在的旧 FTS 条目
      try {
        this.db.prepare("DELETE FROM paragraphs_fts WHERE book_id = ?").run(bookId)
      } catch {}

      for (const p of paragraphs) {
        const text = (p.text_normalized || p.text_raw || '').trim()
        if (!text) continue

        const pId = p.id || `${bookId}:p${p.page_index || 0}:para${p.para_index || 0}`
        const pIndex = p.page_index || 0
        const printed = p.printed_page || `P.${pIndex + 1}`

        insertPara.run(
          pId,
          bookId,
          meta.artifact_id || '',
          meta.evidence_set_id || '',
          p.page_id || `${bookId}:p${pIndex}`,
          pIndex,
          printed,
          p.para_index || 0,
          text,
          p.text_raw || text
        )

        insertFts.run(
          pId,
          bookId,
          pIndex,
          text
        )
      }
      this.db.exec("COMMIT")
      console.log(`[IngestionPipeline] Successfully indexed 《${title}》 (${bookId}) with ${paragraphs.length} paragraphs.`)
    } catch (e) {
      this.db.exec("ROLLBACK")
      throw e
    }
  }
}
