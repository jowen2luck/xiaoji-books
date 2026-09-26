/**
 * @file sessionManager.js
 * @description 图书伴读会话管理器 (移植自小鸡日记 SessionManager)
 * 职责：
 * 1. 维护多话题会话生命周期
 * 2. 存储多轮对话历史 (messages) 与思维链记录 (reacts)
 * 3. 本地持久化保存与恢复
 */

import fs from 'node:fs'
import path from 'node:path'

export class SessionManager {
  constructor({ storagePath = '' } = {}) {
    this.storagePath = storagePath || path.resolve(process.cwd(), 'data/sessions.json')
    this.sessions = []
    this._load()
  }

  _load() {
    try {
      if (this.storagePath && fs.existsSync(this.storagePath)) {
        const raw = fs.readFileSync(this.storagePath, 'utf-8')
        if (raw && raw.trim()) {
          const parsed = JSON.parse(raw)
          if (Array.isArray(parsed) && parsed.length > 0) {
            this.sessions = parsed
            return
          }
        }
      }
    } catch (e) {
      console.warn('[SessionManager] Failed to load sessions:', e.message)
    }

    // 默认创建一个初始会话
    this.sessions = [this._createDefaultSession()]
    this._save()
  }

  _save() {
    if (!this.storagePath) return
    try {
      const dir = path.dirname(this.storagePath)
      if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true })
      fs.writeFileSync(this.storagePath, JSON.stringify(this.sessions, null, 2), 'utf-8')
    } catch (e) {
      console.warn('[SessionManager] Failed to save sessions:', e.message)
    }
  }

  _createDefaultSession() {
    const now = new Date().toISOString()
    return {
      id: `sess_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`,
      title: '研读新对话',
      createdAt: now,
      updatedAt: now,
      messages: [],
      scope: { type: 'global' }
    }
  }

  listSessions() {
    return this.sessions.map(s => ({
      id: s.id,
      title: s.title || '研读新对话',
      createdAt: s.createdAt,
      updatedAt: s.updatedAt,
      messageCount: s.messages ? s.messages.length : 0,
      scope: s.scope
    })).sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())
  }

  getSession(id) {
    let sess = this.sessions.find(s => s.id === id)
    if (!sess) sess = this.sessions[0]
    return sess
  }

  createSession({ title, id, scope } = {}) {
    const now = new Date().toISOString()
    const newSession = {
      id: id || `sess_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`,
      title: title || '研读新对话',
      createdAt: now,
      updatedAt: now,
      messages: [],
      scope: scope || { type: 'global' }
    }
    this.sessions.unshift(newSession)
    this._save()
    return newSession
  }

  appendMessage(sessionId, message) {
    let sess = this.sessions.find(s => s.id === sessionId)
    if (!sess) {
      sess = this.createSession({ id: sessionId })
    }
    if (!Array.isArray(sess.messages)) sess.messages = []

    sess.messages.push({
      ...message,
      time: message.time || new Date().toISOString()
    })
    sess.updatedAt = new Date().toISOString()

    // 自动更新会话标题
    if (sess.title === '研读新对话' && sess.messages.length >= 2) {
      const firstUserMsg = sess.messages.find(m => m.role === 'user')?.content || ''
      if (firstUserMsg) {
        sess.title = firstUserMsg.slice(0, 16) + (firstUserMsg.length > 16 ? '...' : '')
      }
    }

    this._save()
    return sess
  }

  renameSession(id, title) {
    const sess = this.sessions.find(s => s.id === id)
    if (sess) {
      sess.title = (title || '').trim() || '研读对话'
      sess.updatedAt = new Date().toISOString()
      this._save()
      return true
    }
    return false
  }

  deleteSession(id) {
    const idx = this.sessions.findIndex(s => s.id === id)
    if (idx >= 0) {
      this.sessions.splice(idx, 1)
      if (this.sessions.length === 0) {
        this.sessions.push(this._createDefaultSession())
      }
      this._save()
      return true
    }
    return false
  }
}

let globalSessionManagerInstance = null
export function getSessionManager() {
  if (!globalSessionManagerInstance) {
    globalSessionManagerInstance = new SessionManager()
  }
  return globalSessionManagerInstance
}
