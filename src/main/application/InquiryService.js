/**
 * @file InquiryService.js
 * @description 图书问答与伴读会话编排服务 (整合意图路由、核心记忆与 ReAct 智能体执行)
 */

import { getSessionManager } from '../agent/sessionManager.js'
import { getCoreMemoryManager } from '../agent/memory/CoreMemoryManager.js'
import { AgentExecutor } from '../agent/executor.js'

export default class InquiryService {
  /**
   * @param {Object} options
   * @param {import('./BookService.js').default} options.bookService
   * @param {import('./AnalysisService.js').default} options.analysisService
   * @param {import('../agent/ToolRegistry.js').ToolRegistry} [options.toolRegistry]
   */
  constructor({ bookService, analysisService, toolRegistry } = {}) {
    this.bookService = bookService
    this.analysisService = analysisService
    this.sessionManager = getSessionManager()
    this.coreMemoryManager = getCoreMemoryManager()
    this.evidencePacks = new Map() // packId -> BookEvidencePack

    if (toolRegistry) {
      this.setToolRegistry(toolRegistry)
    }
  }

  setToolRegistry(toolRegistry) {
    this.toolRegistry = toolRegistry
    this.executor = new AgentExecutor({
      toolRegistry,
      bookService: this.bookService
    })
  }

  /**
   * 发起一次新的图书伴读问答 (具备意图路由、常驻记忆与多轮上下文)
   * @param {Object} params
   * @param {string} params.question 用户提问
   * @param {Object} [params.scope] 查询作用域
   * @param {string} [params.sessionId] 会话 ID
   * @param {Array} [params.history] 历史对话列表
   * @returns {Promise<Object>}
   */
  async ask({ question, scope = {}, sessionId = null, history = [], onThoughtStep = null }) {
    // 1. 获取或创建持久化会话
    let session = sessionId ? this.sessionManager.getSession(sessionId) : null
    if (!session) {
      session = this.sessionManager.createSession(question, scope)
    }

    // 记录用户消息
    this.sessionManager.appendMessage(session.id, {
      role: 'user',
      content: question,
      time: new Date().toISOString()
    })

    // 2. 调度集成意图路由与常驻记忆的 AgentExecutor
    if (this.executor) {
      if (typeof onThoughtStep === 'function') {
        this.executor.eventEmitter = onThoughtStep
      }
      let agentRes
      try {
        agentRes = await this.executor.run({
          query: question,
          scope,
          history: history && history.length > 0 ? history : (session.messages ? session.messages.slice(0, -1) : [])
        })
      } catch (err) {
        this.sessionManager.appendMessage(session.id, {
          role: 'assistant',
          content: `研读助手在处理提问时遇到异常: ${err.message}`,
          time: new Date().toISOString()
        })
        throw err
      }

      // 记录助手消息
      this.sessionManager.appendMessage(session.id, {
        role: 'assistant',
        content: agentRes.content,
        time: new Date().toISOString()
      })

      if (agentRes.evidencePack) {
        this.evidencePacks.set(agentRes.evidencePack.id, agentRes.evidencePack)
      }

      return {
        markdownAnswer: agentRes.content,
        computations: agentRes.computations || { relevantParagraphs: 0, distinctBooks: 0 },
        followUps: agentRes.followUps || [],
        evidencePack: agentRes.evidencePack || null,
        sessionId: session.id,
        intent: agentRes.intent,
        executionTrace: agentRes.executionTrace || []
      }
    }

    // 降级保护：若 executor 暂未挂载，返回保底回复
    return {
      markdownAnswer: `您好！我是图书伴读智能助手。正在为您初始化大模型引擎，请稍候再试。`,
      computations: { relevantParagraphs: 0, distinctBooks: 0 },
      followUps: [],
      evidencePack: null,
      sessionId: session.id
    }
  }

  getEvidencePack(packId) {
    return this.evidencePacks.get(packId) || null
  }

  listSessions() {
    return this.sessionManager.listSessions()
  }

  getSession(sessionId) {
    return this.sessionManager.getSession(sessionId)
  }

  createSession(question, scope = {}) {
    return this.sessionManager.createSession(question, scope)
  }

  renameSession(id, title) {
    return this.sessionManager.renameSession(id, title)
  }

  deleteSession(id) {
    return this.sessionManager.deleteSession(id)
  }
}
