/**
 * @file executor.js
 * @description 图书伴读智能体 ReAct 执行引擎 (完整复刻小鸡日记路由、记忆与 Agent 范式)
 */

import { globalPreCallMiddleware } from './middleware/PreCallMiddleware.js'
import { getCoreMemoryManager } from './memory/CoreMemoryManager.js'
import { callOpenAIAPI } from '../llm/directOpenAI.js'
import AnswerComposer from '../application/AnswerComposer.js'

export class AgentExecutor {
  /**
   * @param {Object} options
   * @param {import('./ToolRegistry.js').ToolRegistry} options.toolRegistry
   * @param {import('../application/BookService.js').default} options.bookService
   * @param {Function} [options.eventEmitter]
   */
  constructor({ toolRegistry, bookService, eventEmitter }) {
    this.toolRegistry = toolRegistry
    this.bookService = bookService
    this.coreMemoryManager = getCoreMemoryManager()
    this.eventEmitter = eventEmitter || (() => {})
    this.answerComposer = new AnswerComposer()
  }

  emit(type, data) {
    const msgText = typeof data === 'string' ? data : (data.message || data.thought || data.summary || data.content || '')
    const step = {
      type,
      message: msgText,
      thought: msgText,
      content: msgText,
      action: data?.tool ? `调用工具: ${data.tool}` : msgText,
      observation: data?.observation || data?.summary || '',
      tool: data?.tool,
      time: new Date().toLocaleTimeString('zh-CN', { hour12: false })
    }
    if (this.currentTrace) {
      this.currentTrace.push(step)
    }
    try {
      this.eventEmitter(step)
    } catch (e) {
      console.error('[AgentExecutor] Emit error:', e)
    }
  }

  /**
   * 智能路由与 ReAct 推理执行
   * @param {Object} params
   * @param {string} params.query 用户问题
   * @param {Object} [params.scope] 查询作用域
   * @param {Array} [params.history] 历史会话消息
   * @returns {Promise<Object>}
   */
  async run({ query, scope = {}, history = [] }) {
    this.currentTrace = []
    const q = (query || '').trim()
    const books = await this.bookService.listBooks()

    // 1. 意图分诊与前置中间件嗅探
    const classification = globalPreCallMiddleware.classifyIntent(q, scope, books)
    this.emit('thought', { message: `意图分诊分析：“${q.slice(0, 20)}...” -> 判定为 [${classification.intent}]` })
    const coreMemoryPrompt = this.coreMemoryManager.getPromptBlock()

    // 书库权威馆藏摘录（供 LLM 整体把握书目体系）
    const sampleBooksStr = books.slice(0, 15).map(b => `《${b.title}》(${b.primaryCategory}, ${b.pageCount}页)`).join('、')
    const currentBook = classification.matchedBook || (scope.bookIds?.[0] ? books.find(b => b.id === scope.bookIds[0]) : null)

    const systemPrompt = globalPreCallMiddleware.augmentSystemPrompt({
      coreMemoryBlock: coreMemoryPrompt,
      booksSummary: sampleBooksStr,
      currentBook
    })

    console.log(`[AgentExecutor] Classified intent for "${q}":`, classification.intent)

    // ==========================================
    // 路径 A: 闲聊/问候旁路 (Fast-path Bypass)
    // ==========================================
    if (classification.intent === 'casual') {
      this.emit('thought', { message: '检测到日常问候与研读交流，以专属伴读导师身份直接对话...' })

      const promptMessages = [
        { role: 'system', content: systemPrompt },
        ...history.slice(-4), // 保留最近几轮多轮上下文
        { role: 'user', content: q }
      ]

      try {
        const resp = await callOpenAIAPI({
          model: 'qwen-plus',
          messages: promptMessages,
          temperature: 0.7
        })

        const reply = resp.content || resp.choices?.[0]?.message?.content || '你好！我是你的专属典籍研读助手。今天想一同研读哪部经典著作？'

        return this._wrapResult({
          success: true,
          content: reply,
          intent: 'casual',
          computations: [{ text: '研读模式: 专属伴读导师直连交流' }],
          followUps: [
            '推荐几部馆藏的核心工人运动著作',
            '如何利用大纲与原文抽屉精读单本书？'
          ],
          evidencePack: { id: `ev_casual_${Date.now()}`, evidence: [] }
        })
      } catch (err) {
        console.warn('[AgentExecutor] LLM casual call error, fallback:', err.message)
        return this._wrapResult({
          success: true,
          content: `你好！我是你的专属近现代思想史与学术典籍伴读助手。\n\n当前馆藏已整理入库 **${books.length}** 部权威专著与珍贵文献（涵盖工人运动、政治哲学与国际共运档案）。\n\n你可以随时指定某本书进行**章节精读**、**观点考证**或**学术书评导读**，请问今天想从哪一部著作开始探讨？`,
          intent: 'casual',
          computations: [{ text: '研读模式: 专属伴读导师直连交流' }],
          followUps: ['查看馆藏重点书目推荐', '如何为书籍自定义标签？']
        })
      }
    }

    // ==========================================
    // 路径 B: 馆藏发现与书目推荐
    // ==========================================
    if (classification.intent === 'catalog_recommend') {
      this.emit('thought', { message: '检索馆藏图书分类体系与权威典籍推荐...' })

      const promptMessages = [
        {
          role: 'system',
          content: `${systemPrompt}\n\n【任务指令】：用户正在寻求书目推荐。请根据馆藏现有图书列表（已提供在上方系统提示词中），结合读者的研读重心，以专业学者的眼光推荐 3-5 部最值得深入精读的书目，说明推荐理由与建议阅读切入点。`
        },
        ...history.slice(-2),
        { role: 'user', content: q }
      ]

      const resp = await callOpenAIAPI({
        model: 'qwen-plus',
        messages: promptMessages,
        temperature: 0.6
      })

      const reply = resp.content || resp.choices?.[0]?.message?.content || ''

      return this._wrapResult({
        success: true,
        content: reply,
        intent: 'catalog_recommend',
        computations: [{ text: `馆藏入库典籍: ${books.length} 部` }],
        followUps: ['研读《美国工人运动史》的核心大纲', '对比不同专著的研究视角']
      })
    }

    // ==========================================
    // 路径 C: 大纲架构速览
    // ==========================================
    if (classification.intent === 'outline' && currentBook) {
      this.emit('thought', { message: `提取《${currentBook.title}》目录大纲与结构体系...` })
      this.emit('action', { tool: 'get_book_outline', args: { bookId: currentBook.id } })

      const outline = await this.toolRegistry.execute('get_book_outline', { bookId: currentBook.id })

      this.emit('observation', { tool: 'get_book_outline', summary: `成功解析 ${outline.toc?.length || outline.pageCount} 个章节锚点。` })

      let content = `### 📚 《${outline.title}》大纲结构与章节全览\n\n` +
        `**学科分类**：${outline.category} | **文献体量**：共 ${outline.pageCount} 页\n\n`

      if (outline.toc && outline.toc.length > 0) {
        content += outline.toc.map(t => `- **${t.title}** (第 ${t.pageIndex + 1} 页)`).join('\n')
      } else {
        content += `*(该文献原始扫描件未嵌入标准书签，系统已自动按 ${outline.pageCount} 个分页与段落完成连续切片)*\n\n` +
          `你可以直接点击左下角 **“原典通读阅读器”** 连续滚动阅读全文，或选中文本即时呼出 AI 划词解读。`
      }

      return this._wrapResult({
        success: true,
        content,
        intent: 'outline',
        computations: [
          { text: `章节大纲锚点: ${outline.toc?.length || outline.pageCount} 处` },
          { text: `全书文献体量: ${outline.pageCount} 页` }
        ],
        followUps: [`解读《${outline.title}》的核心思想与时代背景`, `查阅本书第一章的原典细节`]
      })
    }

    // ==========================================
    // 路径 D: 学术书评与深度导读
    // ==========================================
    if (classification.intent === 'review' && currentBook) {
      this.emit('thought', { message: `正在为《${currentBook.title}》生成学术级深度导读与批判性书评...` })
      this.emit('action', { tool: 'generate_book_review', args: { bookId: currentBook.id } })

      const review = await this.toolRegistry.execute('generate_book_review', { bookId: currentBook.id })

      this.emit('observation', { tool: 'generate_book_review', summary: '成功完成核心论旨抽取与现代反思合成。' })

      const content = `## 📝 《${review.bookTitle}》深度导读与学术书评\n\n` +
        `### 一、核心论旨与时代命题\n${review.coreThesis}\n\n` +
        `### 二、全书架构导读\n${review.structureSummary}\n\n` +
        `### 三、学术价值与现代反思\n${review.critique}\n\n` +
        `### 四、原典核心锚点证据\n` +
        review.anchors.slice(0, 3).map((a, i) => `**[${i+1}] ${a.page}**：“${a.excerpt}”`).join('\n\n')

      return this._wrapResult({
        success: true,
        content,
        intent: 'review',
        computations: [
          { text: `核心原典锚点: ${review.anchors?.length || 0} 处` },
          { text: '分析维度: 学术导读与批判性反思' }
        ],
        followUps: [`查阅此书在现代视角下的主要争议`, `对比同类著作的学术观点`]
      })
    }

    // ==========================================
    // 路径 E: 深度段落证据研读 (两阶段双路召回 + RRF 融合 + 认识论合成)
    // ==========================================
    const searchAdapter = this.toolRegistry?.services?.analysisService?.searchAdapter
    const rw = searchAdapter?.rewriteQuery ? searchAdapter.rewriteQuery(q, history) : null

    if (rw && (rw.longTokens?.length > 0 || rw.shortTokens?.length > 0)) {
      const entityStr = [...(rw.longTokens || []), ...(rw.shortTokens || [])].slice(0, 4).join(', ')
      const expStr = (rw.expandedConcepts || []).slice(0, 3).join(', ')
      this.emit('thought', {
        message: `Query 改写与概念扩展：已提取核心实体 [${entityStr}]${expStr ? `，扩展关联学术概念 [${expStr}]` : ''}`
      })
    } else {
      this.emit('thought', { message: `启动两阶段双路召回，检索“${q}”的核心史料证据...` })
    }

    this.emit('action', {
      tool: 'search_book_evidence',
      args: { query: q, bookIds: scope.bookIds || [] },
      message: '正在启动 FTS5 BM25 稀疏通道与概念扩展双路召回 (RRF 融合)...'
    })

    const searchResult = await this.toolRegistry.execute('search_book_evidence', {
      query: q,
      bookIds: scope.bookIds || []
    })

    const evidenceList = searchResult.evidencePack?.evidence || []
    this.emit('observation', {
      tool: 'search_book_evidence',
      summary: `双路 RRF 融合检索完成，精准锁定 ${evidenceList.length} 条高置信度原典段落证据。`
    })

    // 如果命中证据，直接使用 AnswerComposer 执行认识论四层合成
    if (evidenceList.length > 0) {
      this.emit('synthesize', { message: `已锁定 ${evidenceList.length} 处原典段落，正在结合文献证据与读者研读重心进行深度认识论合成...` })

      const evidenceContent = evidenceList.slice(0, 5).map((e, idx) =>
        `【原典证据 ${idx + 1}】《${e.bookTitle}》（${e.printedPage || `第 ${e.pageIndex + 1} 页`}）：\n"${e.excerpt}"`
      ).join('\n\n')

      const promptMessages = [
        {
          role: 'system',
          content: `${systemPrompt}\n\n【学术考证与研读任务】：读者提出研讨问题：“${q}”。\n系统已从本地馆藏中检索出以下高度相关的真实原典段落：\n\n${evidenceContent}\n\n【回答规范】：\n1. 必须忠实于上述真实原典证据，并结合近现代思想史的理论脉络，严谨深入地给出解答；\n2. 观点条理清晰，兼具历史唯物主义深度与文献互证；\n3. 适度指出这些文献证据所反映的历史时代局限与现实理论启示。`
        },
        ...history.slice(-2),
        { role: 'user', content: q }
      ]

      let customInsight = ''
      try {
        const resp = await callOpenAIAPI({
          model: 'qwen-plus',
          messages: promptMessages,
          temperature: 0.6
        })
        customInsight = resp.content || resp.choices?.[0]?.message?.content || ''
      } catch (err) {
        console.warn('[AgentExecutor] LLM synthesis failed, fallback to evidence excerpts:', err.message)
      }

      const composed = await this.answerComposer.compose({
        evidencePack: searchResult.evidencePack,
        session: { id: `session_${Date.now()}` },
        customInsight: customInsight || null
      })

      this.emit('synthesize', { message: '完成认识论事实、指标与观点合成。' })

      return this._wrapResult({
        success: true,
        content: composed.markdownAnswer,
        computations: composed.computations,
        followUps: composed.followUps,
        evidencePack: searchResult.evidencePack,
        intent: 'deep_inquiry'
      })
    }

    // 如果字面未搜到精准段落，不抛生硬报错模版，而是由 LLM 结合常识与学术知识进行启发式解答！
    this.emit('thought', { message: '本地未直接检索到完全吻合的原著段落，正在基于学术常识进行背景推演与研读启发...' })

    const promptMessages = [
      {
        role: 'system',
        content: `${systemPrompt}\n\n【任务说明】：读者提问：“${q}”。但在本地书库已入库段落中暂未搜索到直接字面吻合的段落。请你发挥学术导师的学养，以富有深度和诚实的口吻先解答该问题的理论背景与关键脉络；随后客观说明“当前本地馆藏中未找到相关直接段落”，并建议读者可以尝试哪些更具体的专有名词或查阅哪些关联图书。`
      },
      ...history.slice(-2),
      { role: 'user', content: q }
    ]

    try {
      const resp = await callOpenAIAPI({
        model: 'qwen-plus',
        messages: promptMessages,
        temperature: 0.6
      })
      const naturalReply = resp.content || resp.choices?.[0]?.message?.content || ''
      this.emit('synthesize', { message: '完成历史唯物主义与思想史脉络的启发式解答。' })

      return this._wrapResult({
        success: true,
        content: naturalReply,
        computations: [
          { text: '本地馆藏直接相关段落: 0 段' },
          { text: '解答模式: 思想史背景启发式研读' }
        ],
        followUps: [
          '推荐与该主题最相关的专著有哪些？',
          '尝试换用核心专有名词重新检索'
        ],
        evidencePack: { id: `ev_heuristic_${Date.now()}`, evidence: [] },
        intent: 'heuristic_answer'
      })
    } catch (llmErr) {
      return this._wrapResult({
        success: true,
        content: `### 📖 伴读研讨：“${q}”\n\n关于您提出的议题，在当前选定的图书切片中暂未检索到完全吻合的原始字面段落。建议使用更具体的历史事件名（如“八小时工作制”、“芝加哥干草市场”）、著作人名或扩大检索范围。`,
        computations: [
          { text: '本地馆藏直接相关段落: 0 段' },
          { text: '解答模式: 保底指引' }
        ],
        followUps: ['推荐与此问题最相关的书目有哪些？'],
        evidencePack: { id: `ev_empty_${Date.now()}`, evidence: [] }
      })
    }
  }

  _wrapResult(res) {
    return {
      ...res,
      executionTrace: [...(this.currentTrace || [])]
    }
  }
}
