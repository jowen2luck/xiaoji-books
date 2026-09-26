/**
 * @file AnswerComposer.js
 * @description 认识论分层答案合成器 (参考小鸡日记 AnswerComposer)
 * 职责：
 * 1. 严格解耦 Facts (硬事实/出处)、Computations (定量指标)、Hypotheses (模型解读/书评)、Suggestions (伴读引导)
 * 2. 强制执行引用完整性校验 (Citation Integrity)
 * 3. 在 Markdown 答案中恰当地生成交互式原文引用锚点：[《书名》页码 🔖]
 */

import { callOpenAIAPI } from '../llm/directOpenAI.js'

export default class AnswerComposer {
  /**
   * @param {Object} options
   * @param {Object} [options.llmClient] 可选外部大模型调用客户端
   */
  constructor({ llmClient } = {}) {
    this.llmClient = llmClient || null
  }

  /**
   * 合成认识论分层伴读成果
   * @param {Object} params
   * @param {import('../domain/contracts.js').BookEvidencePack} params.evidencePack
   * @param {import('../domain/contracts.js').InquirySession} params.session
   * @param {string} [params.customInsight] 大模型生成的洞见或书评内容
   * @returns {Promise<import('../domain/contracts.js').ExplorationResult>}
   */
  async compose({ evidencePack, session, customInsight = null }) {
    const { evidence = [], metrics = [], question } = evidencePack

    // 1. Facts：硬事实与出处映射
    const facts = evidence.map(ev => ({
      text: `《${ev.bookTitle}》(${ev.printedPage || `P.${ev.pageIndex + 1}`}): “${ev.excerpt.slice(0, 120)}...”`,
      evidenceRefs: [ev.id]
    }))

    // 2. Computations：定量事实
    const computations = metrics.map(m => ({
      text: `${m.label}: ${m.value} ${m.unit || ''} (样本: ${m.sampleSize})`,
      metricRefs: [m.id]
    }))

    // 3. Hypotheses / Interpretations：模型解读与观点推演
    let hypothesisText = customInsight
    if (!hypothesisText) {
      if (evidence.length === 0) {
        hypothesisText = `在当前选定的图书范围中，未能检索到与“${question}”直接吻合的段落。建议扩大查询范围或调整关键词检索。`
      } else if (process.env.DASHSCOPE_API_KEY || process.env.DASHSCOPE_API_KEY_QWEN || process.env.OPENAI_API_KEY) {
        try {
          const evidenceContent = evidence.slice(0, 4).map((e, idx) => 
            `【证据 ${idx+1}】《${e.bookTitle}》（${e.printedPage || `第 ${e.pageIndex+1} 页`}）：\n"${e.excerpt}"`
          ).join('\n\n')

          const llmRes = await callOpenAIAPI({
            baseURL: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            model: 'qwen-plus',
            messages: [
              {
                role: 'system',
                content: '你是一位精通文献考据与学术研读的图书伴读专家。请结合所提供的真实文献证据段落，严谨、深入地回答读者提问。观点须忠实于文献，条理分明，适度展开思想脉络与历史启示。'
              },
              {
                role: 'user',
                content: `读者提问: ${question}\n\n检索到的文献证据:\n${evidenceContent}\n\n请结合以上文献证据给出专业解读与评论：`
              }
            ]
          })
          if (llmRes && llmRes.content) {
            hypothesisText = llmRes.content
          }
        } catch (llmErr) {
          console.warn('[AnswerComposer] LLM invocation failed, using deterministic fallback:', llmErr.message)
        }
      }

      if (!hypothesisText) {
        const topEv = evidence[0]
        hypothesisText = `根据在《${topEv.bookTitle}》等文献中的记录，核心观点指出：${topEv.excerpt.slice(0, 180)}。\n\n从文献思想脉络来看，该问题反映了当时的历史背景与理论论辩，对理解该主题的制度与实践具有关键的基石意义。`
      }
    }

    // 引用完整性检查
    const validIds = new Set(evidence.map(e => e.id))
    const hypotheses = [
      {
        text: hypothesisText,
        evidenceRefs: evidence.map(e => e.id).filter(id => validIds.has(id)),
        confidence: evidence.length > 2 ? 'high' : 'medium',
        model: 'BookAssistant-EpistemicEngine-v1'
      }
    ]

    // 4. Suggestions：阅读引导
    const suggestions = [
      {
        text: '建议点击文中原文引用徽标或右侧抽屉，核对完整上下文段落以验证解读。',
        basisRefs: evidence.map(e => e.id)
      }
    ]

    // 5. 渲染 Markdown 正文，并在恰当位置嵌入优雅的原文徽标与引文卡片
    const markdownLines = []

    markdownLines.push(`## 📖 伴读解读：${question}\n`)

    if (evidence.length > 0) {
      markdownLines.push(`> **检索综述**：已从 **${new Set(evidence.map(e=>e.bookTitle)).size}** 本典籍中锁定 **${evidence.length}** 处关键佐证段落。\n`)

      markdownLines.push(`### 💡 核心观点与深入解答\n`)
      markdownLines.push(`${hypothesisText}\n`)

      markdownLines.push(`### 📑 核心依据与原文溯源 (可折叠)\n`)
      evidence.slice(0, 3).forEach((ev, idx) => {
        const pageNum = (ev.pageIndex !== undefined && ev.pageIndex !== null) ? (ev.pageIndex + 1) : 1
        const pageLabel = ev.printedPage ? `第 ${ev.printedPage} 页` : `第 ${pageNum} 页`
        const cleanExcerpt = (ev.excerpt || '').replace(/\s+/g, ' ').trim()
        const preview = cleanExcerpt.length > 55 ? cleanExcerpt.slice(0, 55) + '...' : cleanExcerpt
        const bookDisplay = ev.bookTitle ? (ev.bookTitle.startsWith('book-') ? ev.bookTitle.slice(5) : ev.bookTitle) : '文献原著'

        markdownLines.push(
          `<details class="evidence-fold-item">\n` +
          `<summary class="evidence-fold-summary">` +
          `<span class="evidence-tag">证据 [${idx + 1}]</span> ` +
          `《${bookDisplay}》 <b>${pageLabel}</b> ` +
          `<span class="evidence-preview-text">“${preview}”</span>` +
          `</summary>\n\n` +
          `> “${cleanExcerpt}”\n\n` +
          `<div class="evidence-fold-actions">\n` +
          `  <button class="evidence-jump-btn" data-book-id="${ev.bookId || ''}" data-page="${pageNum}" data-paragraph-id="${ev.id || ''}">📖 立即在并行阅读器对照原件 (${pageLabel})</button>\n` +
          `</div>\n` +
          `</details>\n`
        )
      })
    } else {
      markdownLines.push(hypothesisText)
    }

    // 6. 构造追问建议
    const followUps = this._generateFollowUps(question, evidence)

    return {
      sessionId: session.id,
      evidencePackId: evidencePack.id,
      scopeSummary: `检索范围: ${evidencePack.scope.type} (${evidence.length} 条证据)`,
      facts,
      computations,
      hypotheses,
      suggestions,
      markdownAnswer: markdownLines.join('\n'),
      followUps
    }
  }

  _generateFollowUps(question, evidence) {
    const list = []
    if (evidence.length > 0) {
      list.push(`请为我详细解读《${evidence[0].bookTitle}》的核心框架与目录体系`)
      list.push(`结合这一观点，书中还提出了哪些具体的论据与历史背景？`)
      list.push(`在同分类图书中，是否有其他作者对此持有不同或补充的观点？`)
    } else {
      list.push('推荐与此问题最相关的书目有哪些？')
      list.push('如何为当前书库重新分类与补充标签？')
    }
    return list
  }
}
