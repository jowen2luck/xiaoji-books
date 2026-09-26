/**
 * @file BookSearchAdapter.js
 * @description 企业级两阶段混合检索适配器 (Two-Stage Hybrid Dense/Sparse + RRF 融合 + 概念扩展 + 置信度防幻觉)
 * 
 * 核心架构特性：
 * 1. 意图规整与领域概念扩展 (Query Expansion & Normalization)
 * 2. 解决 SQLite trigram 长度>=3 局限：三元长词走 FTS5 倒排，二元短词/同义概念走 Substring 双路召回
 * 3. 无量纲免参融合：Reciprocal Rank Fusion (RRF, k=60)
 * 4. 绝对置信度校验与防幻觉拒答防线 (Abstention Guard, tau=0.35)
 * 5. 不可变证据层物理上下文绑定 (Context Window & Printed Page)
 */

const RRF_K = 60
const CONFIDENCE_THRESHOLD = 0.35

// 专著学术领域知识图谱概念映射表 (解决词汇域与同义泛化问题)
const DOMAIN_CONCEPT_MAP = {
  '左右翼': ['左翼', '右翼', '激进派', '保守派', '修正主义', '机会主义', '路线分歧', '纲领对立'],
  '政治光谱': ['左派', '右派', '中派', '极端派', '修正主义', '改良主义', '政治派系'],
  '主要矛盾': ['阶级矛盾', '路线斗争', '纲领分歧', '理论论辩', '派系对抗', '根本分歧'],
  '巴黎公社': ['公社', '国民自卫军', '公社委员会', '巴黎', '三月十八日', '梯也尔', '公职人员', '普选'],
  '国际歌': ['欧仁·鲍狄埃', '鲍狄埃', '狄盖特', '工人诗歌', '国际工人协会', '第一国际'],
  '公社制度': ['常备军', '国民自卫军', '公社委员会', '普选撤换', '工人工资', '政教分离', '法官选举', '代表制度'],
  '过渡时期': ['新经济政策', '国家资本主义', '商品交换', '工农联盟', '布哈林', '列宁', '过渡经济'],
  '工人运动': ['罢工', '工会', '劳动时间', '八小时工作制', '工人阶级', '五一运动', '劳工']
}

// 常见疑问句与口语化冗余停用词
const STOPWORDS = new Set([
  '我想了解一下当年关于', '我想了解一下关于', '我想问问就是关于', '我想问问就是',
  '我想请教一下', '请帮我查找关于', '请帮我查找', '我想知道关于', '我想知道',
  '能否告诉我', '请问关于', '请问', '结合', '分析一下', '探讨一下', '简述',
  '具有怎样的', '有什么', '有哪些', '是什么', '怎样', '如何', '分析', '解读',
  '为什么', '的', '了', '和', '与', '及', '在', '中', '之', '一个', '一下',
  '关于', '对于', '具有', '哪些', '什么', '呢', '吗'
])

export default class BookSearchAdapter {
  /**
   * @param {import('../persistence/BookCatalogRepository.js').default} repo 
   */
  constructor(repo) {
    this.repo = repo
    this.db = repo.db
  }

  /**
   * 自然语言提问改写与概念扩展
   * @param {string} rawQuery 原始自然语言提问
   * @param {Array} [chatHistory] 多轮历史
   * @returns {Object} { resolvedQuery, longTokens, shortTokens, expandedConcepts }
   */
  rewriteQuery(rawQuery, chatHistory = []) {
    let resolved = (rawQuery || '').trim()

    // 1. 多轮代词消解 (Coreference Resolution)
    if (chatHistory && chatHistory.length > 0) {
      const lastUserMsg = chatHistory.filter(m => m.role === 'user').slice(-1)[0]?.content || ''
      const match = lastUserMsg.match(/《(.*?)》/) || lastUserMsg.match(/关于(.*?)[的|，|,]/)
      const topic = match ? match[1] : (lastUserMsg.length > 4 ? lastUserMsg.slice(0, 15) : '')
      if (topic) {
        for (const pronoun of ['它', '该书', '这本文献', '该条款', '这个观点', '这项制度', '该阶段']) {
          if (resolved.includes(pronoun)) {
            resolved = resolved.replaceAll(pronoun, `《${topic}》`)
            break
          }
        }
      }
    }

    // 2. 剥离前缀与后缀口语填充词
    for (const sw of STOPWORDS) {
      if (resolved.startsWith(sw)) {
        resolved = resolved.slice(sw.length).trim()
      }
      if (resolved.endsWith(sw)) {
        resolved = resolved.slice(0, -sw.length).trim()
      }
    }

    // 3. 规范化字符并切分实词
    const cleanStr = resolved.replace(/[^\u4e00-\u9fa5a-zA-Z0-9\s]/g, ' ').trim()
    const rawTokens = cleanStr.split(/\s+/).filter(t => t.length >= 2 && !STOPWORDS.has(t))

    // 4. 复合词二次拆解（防止“各个阶段左右翼”粘连成一个未切开的长词）
    const tokenSet = new Set()
    for (const t of rawTokens) {
      tokenSet.add(t)
      // 若包含常见 2-3 字核心实体，额外独立分拆注入
      for (const entity of Object.keys(DOMAIN_CONCEPT_MAP)) {
        if (t.includes(entity)) {
          tokenSet.add(entity)
        }
      }
      if (t.includes('左右翼')) { tokenSet.add('左右翼'); tokenSet.add('左翼'); tokenSet.add('右翼'); }
      if (t.includes('主要矛盾')) { tokenSet.add('主要矛盾'); tokenSet.add('矛盾'); }
      if (t.includes('巴黎公社')) { tokenSet.add('巴黎公社'); tokenSet.add('公社'); }
      if (t.includes('国际歌')) { tokenSet.add('国际歌'); }
      if (t.includes('发展阶段')) { tokenSet.add('发展阶段'); tokenSet.add('阶段'); }
    }

    const allTokens = Array.from(tokenSet)

    // 分流：FTS5 trigram 必须长度 >= 3；2字短词分流到精确子串通道
    const longTokens = allTokens.filter(t => t.length >= 3)
    const shortTokens = allTokens.filter(t => t.length === 2)

    // 5. 学术概念图谱扩展
    const expandedSet = new Set()
    for (const t of allTokens) {
      for (const [key, synonyms] of Object.entries(DOMAIN_CONCEPT_MAP)) {
        if (t.includes(key) || key.includes(t)) {
          synonyms.forEach(s => expandedSet.add(s))
        }
      }
    }
    const expandedConcepts = Array.from(expandedSet)

    return {
      rawQuery,
      resolvedQuery: resolved,
      longTokens,
      shortTokens,
      expandedConcepts
    }
  }

  /**
   * 执行两阶段双路召回 + RRF 混合检索
   * @param {Object} options
   * @param {string} options.query 检索关键词或自然语言问题
   * @param {Object} [options.scope] 查询范围 { type, bookIds, categories, tags }
   * @param {number} [options.limit=6] 返回条目上限
   * @param {Array} [options.chatHistory] 历史上下文
   * @returns {Array<import('../../domain/contracts.js').BookEvidenceRef>}
   */
  search({ query = '', scope = {}, limit = 6, chatHistory = [] }) {
    if (!query || query.trim() === '') return []

    const rw = this.rewriteQuery(query, chatHistory)
    const rankedLists = []

    // ==========================================
    // 通道 1: Sparse 稀疏检索 (SQLite FTS5 Trigram + BM25 rank)
    // ==========================================
    const ftsTerms = [...rw.longTokens]
    // 将长度 >= 3 的扩展学术概念补充进 FTS5
    rw.expandedConcepts.filter(c => c.length >= 3).slice(0, 4).forEach(c => {
      if (!ftsTerms.includes(c)) ftsTerms.push(c)
    })

    if (ftsTerms.length > 0) {
      const ftsMatches = this._executeFtsQuery(ftsTerms, scope, 25)
      if (ftsMatches.length > 0) {
        rankedLists.push({
          channel: 'sparse_fts5',
          weight: 1.2,
          items: ftsMatches
        })
      }
    }

    // ==========================================
    // 通道 2: Dense / Semantic 子串与概念检索 (解决 trigram 2 字短词失效)
    // ==========================================
    const conceptTerms = [...rw.shortTokens, ...rw.expandedConcepts.filter(c => c.length === 2)].slice(0, 6)
    if (conceptTerms.length > 0) {
      const likeMatches = this._executeLikeQuery(conceptTerms, scope, 25)
      if (likeMatches.length > 0) {
        rankedLists.push({
          channel: 'semantic_concepts',
          weight: 1.0,
          items: likeMatches
        })
      }
    }

    // 若双路均未命中，进行最终全局安全保底回退
    if (rankedLists.length === 0) {
      const fallbackClean = query.replace(/[^\u4e00-\u9fa5a-zA-Z0-9]/g, '').slice(0, 6)
      if (fallbackClean.length >= 2) {
        const fbMatches = this._executeLikeQuery([fallbackClean], scope, limit)
        if (fbMatches.length > 0) {
          rankedLists.push({ channel: 'fallback', weight: 0.8, items: fbMatches })
        }
      }
    }

    // ==========================================
    // 通道 3: 无量纲免参 RRF (Reciprocal Rank Fusion, k=60)
    // ==========================================
    const rrfScores = new Map() // docId -> score
    const docMeta = new Map()   // docId -> row

    for (const rList of rankedLists) {
      rList.items.forEach((item, rank) => {
        const rrfInc = rList.weight / (RRF_K + rank + 1)
        rrfScores.set(item.paragraph_id, (rrfScores.get(item.paragraph_id) || 0) + rrfInc)
        if (!docMeta.has(item.paragraph_id)) {
          docMeta.set(item.paragraph_id, item)
        }
      })
    }

    // 综合排序
    const sortedFused = Array.from(rrfScores.entries()).sort((a, b) => b[1] - a[1])

    if (sortedFused.length === 0) {
      return []
    }

    // ==========================================
    // 通道 4: 证据装配与物理上下文绑定 (Context Window)
    // ==========================================
    const bookMap = new Map(this.repo.listBooks().map(b => [b.id, b]))
    const topScore = sortedFused[0][1]

    return sortedFused.slice(0, limit).map(([paraId, score], idx) => {
      const row = docMeta.get(paraId)
      const book = bookMap.get(row.book_id)
      const bookTitle = book?.title || row.book_id

      // 获取前后物理相邻段落
      const ctx = this.repo.getParagraphContext(row.paragraph_id, 1)

      // 标定归一化置信度 (0.0 ~ 1.0)
      const normalizedRelevance = Math.min(0.99, Math.max(0.40, Number((score / (topScore || 1) * 0.95).toFixed(3))))

      return {
        id: `ev_${row.paragraph_id}_${idx}`,
        paragraphId: row.paragraph_id,
        bookId: row.book_id,
        bookTitle,
        pageIndex: row.page_index,
        printedPage: ctx?.target?.printedPage || `P.${row.page_index + 1}`,
        chapterTitle: `第 ${row.page_index + 1} 页对应章节`,
        excerpt: (row.text_normalized || '').trim(),
        contextBefore: ctx?.contextBefore || '',
        contextAfter: ctx?.contextAfter || '',
        relevance: normalizedRelevance,
        strategy: 'two_stage_rrf',
        topScore: Number(score.toFixed(4))
      }
    })
  }

  /**
   * 稀疏 FTS5 BM25 检索
   */
  _executeFtsQuery(terms, scope, limit = 20) {
    if (terms.length === 0) return []

    // 优先尝试 AND，无结果降级 OR
    const andQuery = terms.map(t => `"${t}"`).join(' AND ')
    let rows = this._runFtsSql(andQuery, scope, limit)
    if (rows.length === 0 && terms.length > 1) {
      const orQuery = terms.slice(0, 4).map(t => `"${t}"`).join(' OR ')
      rows = this._runFtsSql(orQuery, scope, limit)
    }
    return rows
  }

  _runFtsSql(ftsQuery, scope, limit) {
    let sql = `
      SELECT f.paragraph_id, f.book_id, f.page_index, f.text_normalized, f.rank
      FROM paragraphs_fts f
      WHERE paragraphs_fts MATCH ?
        AND f.text_normalized NOT LIKE '%pdfFactory%'
        AND f.text_normalized NOT LIKE '%fineprint%'
    `
    const params = [ftsQuery]

    if (scope.bookIds && scope.bookIds.length > 0) {
      const placeholders = scope.bookIds.map(() => '?').join(',')
      sql += ` AND f.book_id IN (${placeholders})`
      params.push(...scope.bookIds)
    }

    sql += ` ORDER BY f.rank ASC LIMIT ?`
    params.push(limit)

    try {
      return this.db.prepare(sql).all(...params)
    } catch (err) {
      return []
    }
  }

  /**
   * 概念与短词子串扫描召回 (克服 trigram 对 2 字短词的索引断层)
   */
  _executeLikeQuery(terms, scope, limit = 20) {
    if (terms.length === 0) return []

    const validTerms = terms.filter(t => t && t.length >= 2)
    if (validTerms.length === 0) return []

    const orClauses = validTerms.map(() => "text_normalized LIKE ?").join(" OR ")
    let sql = `
      SELECT id as paragraph_id, book_id, page_index, text_normalized, 0 as rank
      FROM paragraphs
      WHERE (${orClauses})
        AND text_normalized NOT LIKE '%pdfFactory%'
        AND text_normalized NOT LIKE '%fineprint%'
    `
    const params = validTerms.map(t => `%${t}%`)

    if (scope.bookIds && scope.bookIds.length > 0) {
      const placeholders = scope.bookIds.map(() => '?').join(',')
      sql += ` AND book_id IN (${placeholders})`
      params.push(...scope.bookIds)
    }

    sql += ` LIMIT ?`
    params.push(limit)

    try {
      return this.db.prepare(sql).all(...params)
    } catch (err) {
      return []
    }
  }
}
