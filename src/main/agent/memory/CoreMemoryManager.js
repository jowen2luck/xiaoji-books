/**
 * @file CoreMemoryManager.js
 * @description 图书伴读常驻画像与长期记忆管理器 (复用小鸡日记 CoreMemory 范式)
 * 职责：
 * 1. 维护读者的研读重心、感兴趣学术领域、阅读偏好及学伴助手准则
 * 2. 生成紧凑格式常驻于 System Prompt，让大模型持久保有上下文
 * 3. 支持在对话过程中动态更新记忆
 */

import fs from 'node:fs'
import path from 'node:path'

const DEFAULT_BOOK_CORE_MEMORY = {
  reader_profile: '严谨专注的学术研读者，注重史料扎实度、思想脉络与历史唯物主义分析视角。',
  research_focus: '近期重点研读国际共运史、欧美早期工人运动、马克思主义哲学流派与历史档案文献。',
  reading_preferences: '偏好论点鲜明、观点交锋深入、带有精确页码证据佐证的学术研读与批判性反思，拒绝空洞模版。',
  assistant_persona: '你是一位知识渊博、文风优雅的近现代思想史与学术典籍伴读导师，善于引导读者抽丝剥茧、融会贯通。'
}

export const VALID_SECTIONS = [
  'reader_profile',
  'research_focus',
  'reading_preferences',
  'assistant_persona'
]

export class CoreMemoryManager {
  constructor({ storagePath = '' } = {}) {
    this.storagePath = storagePath || path.resolve(process.cwd(), 'data/core-memory.json')
    this.memory = { ...DEFAULT_BOOK_CORE_MEMORY }
    this._load()
  }

  _load() {
    try {
      if (this.storagePath && fs.existsSync(this.storagePath)) {
        const raw = fs.readFileSync(this.storagePath, 'utf-8')
        if (raw && raw.trim()) {
          const parsed = JSON.parse(raw)
          if (parsed && typeof parsed === 'object') {
            this.memory = { ...DEFAULT_BOOK_CORE_MEMORY, ...parsed }
            return
          }
        }
      }
    } catch (e) {
      console.warn('[CoreMemoryManager] Failed to load memory file:', e.message)
    }
    this._save()
  }

  _save() {
    if (!this.storagePath) return
    try {
      const dir = path.dirname(this.storagePath)
      if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true })
      fs.writeFileSync(this.storagePath, JSON.stringify(this.memory, null, 2), 'utf-8')
    } catch (e) {
      console.warn('[CoreMemoryManager] Failed to save memory file:', e.message)
    }
  }

  getMemory() {
    return { ...this.memory }
  }

  updateSection(section, content) {
    if (!VALID_SECTIONS.includes(section)) return false
    this.memory[section] = String(content || '').trim()
    this._save()
    return true
  }

  getPromptBlock() {
    const lines = [
      `- 读者画像 (reader_profile)：${this.memory.reader_profile}`,
      `- 当前研读重心 (research_focus)：${this.memory.research_focus}`,
      `- 阅读偏好 (reading_preferences)：${this.memory.reading_preferences}`,
      `- 伴读人设准则 (assistant_persona)：${this.memory.assistant_persona}`
    ]

    return `
<core_memory>
【读者长期画像与研读伴读记忆 (Core Memory)】
${lines.join('\n')}
(提示：此为用户的长期研读记忆。请在所有回答中自然融入此人设与学术品味，体现长效陪伴感)
</core_memory>
`.trim()
  }
}

let globalCoreMemoryInstance = null
export function getCoreMemoryManager() {
  if (!globalCoreMemoryInstance) {
    globalCoreMemoryInstance = new CoreMemoryManager()
  }
  return globalCoreMemoryInstance
}
