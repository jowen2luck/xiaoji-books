/**
 * @file InquirySessionStore.js
 * @description 问答伴读会话状态机 (参考小鸡日记 InquirySessionStore)
 */

export default class InquirySessionStore {
  constructor() {
    this.sessions = new Map() // sessionId -> Session
  }

  /**
   * 创建新会话
   * @param {string} question
   * @param {Object} scope
   * @returns {Object} session
   */
  createSession(question, scope = {}) {
    const id = `session_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`
    const session = {
      id,
      initialQuestion: question,
      history: [
        { role: 'user', content: question, timestamp: new Date().toISOString() }
      ],
      scope: {
        type: scope.type || 'global',
        bookIds: scope.bookIds || [],
        categories: scope.categories || [],
        tags: scope.tags || []
      },
      evidencePackIds: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    }

    this.sessions.set(id, session)
    return session
  }

  /**
   * 追加消息与更新状态
   */
  addMessage(sessionId, message) {
    const session = this.sessions.get(sessionId)
    if (!session) throw new Error(`[InquirySessionStore] Session ${sessionId} not found`)

    session.history.push({
      ...message,
      timestamp: new Date().toISOString()
    })
    session.updatedAt = new Date().toISOString()
    return session
  }

  /**
   * 关联生成的证据包
   */
  addEvidencePack(sessionId, evidencePackId) {
    const session = this.sessions.get(sessionId)
    if (session && !session.evidencePackIds.includes(evidencePackId)) {
      session.evidencePackIds.push(evidencePackId)
      session.updatedAt = new Date().toISOString()
    }
  }

  /**
   * 获取会话
   */
  getSession(sessionId) {
    return this.sessions.get(sessionId) || null
  }

  /**
   * 获取所有会话列表
   */
  listSessions() {
    return Array.from(this.sessions.values()).sort(
      (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
    )
  }
}
