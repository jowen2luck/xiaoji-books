/**
 * @file PreCallMiddleware.js
 * @description 图书伴读前置中间件与意图路由 (移植自小鸡日记 PreCallMiddleware 范式)
 * 职责：
 * 1. 毫秒级闲聊与问候识别 (Fast-path Bypass)，彻底解决“输入你好搜不到段落”的僵硬问题
 * 2. 意图分诊：闲聊/书目发现推荐/大纲速览/学术书评/深度证据研读
 * 3. 注入动态书库概貌与核心记忆
 */

export class PreCallMiddleware {
  constructor() {
    this.casualRegex = /^(你好|您好|hi|hello|hey|嗨|在吗|在不|在么|早上好|中午好|晚上好|早安|晚安|测试|你是谁|介绍一下你自己)(呀|啊|哦|吧|嘛)?[!！~。?？\s]*$/i
  }

  /**
   * 极简问候与闲聊旁路检测
   * @param {string} query
   * @returns {boolean}
   */
  isCasualGreeting(query) {
    if (!query || typeof query !== 'string') return false
    return this.casualRegex.test(query.trim())
  }

  /**
   * 意图深度分诊
   * @param {string} query
   * @param {Object} scope
   * @param {Array} books
   * @returns {{ intent: 'casual'|'catalog_recommend'|'outline'|'review'|'deep_inquiry', matchedBook?: Object }}
   */
  classifyIntent(query, scope = {}, books = []) {
    const q = (query || '').trim()

    // 1. 纯问候闲聊旁路
    if (this.isCasualGreeting(q)) {
      return { intent: 'casual' }
    }

    // 2. 匹配具体书目
    let matchedBook = null
    if (scope.bookIds && scope.bookIds.length > 0) {
      matchedBook = books.find(b => b.id === scope.bookIds[0])
    }
    if (!matchedBook) {
      // 尝试从用户问题中根据书名识别（如 《美国工人运动史》 或 美国工人运动史）
      const bookMatch = q.match(/《([^》]+)》/)
      if (bookMatch) {
        matchedBook = books.find(b => b.title && b.title.includes(bookMatch[1]))
      }
    }

    // 3. 大纲目录意图
    if (/(大纲|目录|章节|框架|体系结构|包含哪些篇章)/.test(q)) {
      return { intent: 'outline', matchedBook }
    }

    // 4. 深度学术书评/命题导读意图
    if (/(书评|深度解读|导读|核心论旨|评价|学术价值|时代背景)/.test(q) && matchedBook) {
      return { intent: 'review', matchedBook }
    }

    // 5. 馆藏推荐与书库发现意图（非查具体段落，而是查有什么书）
    if (/(有哪些书|推荐.*书|馆藏|什么书|哪些文献|看看书库|有哪些资料)/.test(q)) {
      return { intent: 'catalog_recommend' }
    }

    // 6. 默认进入深度原典证据研读
    return { intent: 'deep_inquiry', matchedBook }
  }

  /**
   * 增强 System Prompt
   */
  augmentSystemPrompt({ coreMemoryBlock = '', booksSummary = '', currentBook = null } = {}) {
    let prompt = `你是一位学识深厚、富有思想洞察力的近现代思想史与学术典籍专属伴读助手。
你与读者是长期的学术对话伙伴。

你的核心原则：
1. 【亲和而有深度的学伴】：对于问候、打招呼或日常请教，以温暖、知性、学者风范的口吻交流，主动结合读者的研读重心给出方向指引。切勿机械化输出“未找到段落”等生硬机器术语。
2. 【证据支撑与学术诚信】：在讨论具体书籍或历史学术论点时，坚持“论从史出”，以真实原著证据为基石，结合历史唯物主义与现代学术视角进行辩证分析。
3. 【恰当引导】：当读者的问题较宽泛时，结合当前书库的优质馆藏主动推荐切入点。
`

    if (coreMemoryBlock) {
      prompt += `\n\n${coreMemoryBlock}`
    }

    if (currentBook) {
      prompt += `\n\n【当前聚焦精读书籍】：《${currentBook.title}》（分类：${currentBook.primaryCategory}，共 ${currentBook.pageCount} 页）`
    } else if (booksSummary) {
      prompt += `\n\n【馆藏典籍速览】当前书库收录了以下重点权威著作：\n${booksSummary}`
    }

    return prompt
  }
}

export const globalPreCallMiddleware = new PreCallMiddleware()
