/**
 * @file TagTaxonomy.js
 * @description 图书助手分类与多维标签体系 (Categorization & Tag Taxonomy)
 */

export const DEFAULT_CATEGORIES = [
  { id: 'cat_marxism_socialism', name: '政治经济与社会主义', description: '马克思主义经典、巴黎公社、国际共运历史文献' },
  { id: 'cat_history_biography', name: '历史与人物传记', description: '历史人物生平、革命史料、编年史册' },
  { id: 'cat_philosophy', name: '哲学与方法论', description: '辩证唯物主义、批判理论、认识论' },
  { id: 'cat_economics', name: '理论与应用经济学', description: '政治经济学批判、资本理论、发展战略' },
  { id: 'cat_literature_poetry', name: '文学诗歌与纪实', description: '革命诗篇、工人文学、散文纪实' },
  { id: 'cat_uncategorized', name: '未分类', description: '等待智能标注或人工归类的书籍' }
]

export const PRESET_TAGS = [
  '巴黎公社', '国际歌', '工人运动', '十月革命', '列宁主义',
  '布哈林', '鲍狄埃', '法兰西内战', '唯物史观', '政治经济学',
  '阶级斗争', '帝国主义论', '经典原著', '重要传记', '文献汇编'
]

/**
 * 自动根据书名、路径或文本关键词推断候选分类与标签
 * @param {Object} bookMeta 
 * @returns {{ primaryCategory: string, suggestedTags: string[] }}
 */
export function inferCategoryAndTags(bookMeta = {}) {
  const { title = '', sourcePath = '', bookId = '' } = bookMeta
  const targetStr = `${title} ${sourcePath} ${bookId}`.toLowerCase()

  const suggestedTags = []
  let primaryCategory = '未分类'

  if (targetStr.includes('internationale') || targetStr.includes('国际歌')) {
    suggestedTags.push('国际歌', '巴黎公社', '工人运动')
    primaryCategory = '政治经济与社会主义'
  }
  if (targetStr.includes('parisco') || targetStr.includes('巴黎公社')) {
    suggestedTags.push('巴黎公社', '工人运动')
    primaryCategory = '政治经济与社会主义'
  }
  if (targetStr.includes('pottier') || targetStr.includes('鲍狄埃')) {
    suggestedTags.push('鲍狄埃', '人物传记', '文学诗歌与纪实')
    if (primaryCategory === '未分类') primaryCategory = '历史与人物传记'
  }
  if (targetStr.includes('bukharin') || targetStr.includes('布哈林')) {
    suggestedTags.push('布哈林', '政治经济学')
    primaryCategory = '政治经济与社会主义'
  }
  if (targetStr.includes('poem') || targetStr.includes('诗')) {
    suggestedTags.push('文学诗歌与纪实')
  }

  // 默认兜底
  if (primaryCategory === '未分类' && targetStr.includes('chinese')) {
    primaryCategory = '政治经济与社会主义'
    suggestedTags.push('文献汇编')
  }

  return {
    primaryCategory,
    suggestedTags: Array.from(new Set(suggestedTags))
  }
}
