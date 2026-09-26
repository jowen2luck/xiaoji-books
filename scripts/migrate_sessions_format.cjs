const fs = require('node:fs')
const path = require('node:path')

const sessionPath = path.resolve(__dirname, '../data/sessions.json')
const sessions = JSON.parse(fs.readFileSync(sessionPath, 'utf8'))

const regex = /\*\*证据 \[(\d+)\]\*\* 来自 《([^》]+)》 \*\*([^*]+)\*\*：\s*\n> “([\s\S]*?)”(?:\s*\n\*\([^)]+\)\*)?/g

let count = 0
for (const sess of sessions) {
  if (!Array.isArray(sess.messages)) continue
  for (const m of sess.messages) {
    if (m.role === 'assistant' && typeof m.content === 'string') {
      const newContent = m.content.replace(regex, (_match, idx, book, page, excerpt) => {
        count++
        const cleanExcerpt = excerpt.replace(/\s+/g, ' ').trim()
        const preview = cleanExcerpt.length > 55 ? cleanExcerpt.slice(0, 55) + '...' : cleanExcerpt
        const pageClean = page.replace(/\D/g, '') || page
        const bookClean = book.startsWith('book-') ? book.slice(5) : book
        const bookId = book.startsWith('book-') ? book : `book-${book}`

        return `<details class="evidence-fold-item">
<summary class="evidence-fold-summary">
  <span class="evidence-tag">证据 [${idx}]</span>
  《${bookClean}》 <b>第 ${pageClean} 页</b>
  <span class="evidence-preview-text">“${preview}”</span>
</summary>

> “${cleanExcerpt}”

<div class="evidence-fold-actions">
  <button class="evidence-jump-btn" data-book-id="${bookId}" data-page="${pageClean}">📖 立即在并行阅读器对照原件 (第 ${pageClean} 页)</button>
</div>
</details>`
      })
      m.content = newContent
    }
  }
}

console.log('Total evidence blocks transformed:', count)
fs.writeFileSync(sessionPath, JSON.stringify(sessions, null, 2), 'utf8')
console.log('Saved data/sessions.json successfully.')
