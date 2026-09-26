import { contextBridge, ipcRenderer } from 'electron'

const api = {
  // 图书相关
  listBooks: (filter) => ipcRenderer.invoke('books:list', filter),
  getBook: (bookId) => ipcRenderer.invoke('books:get', bookId),
  updateBookClassification: (payload) => ipcRenderer.invoke('books:update-classification', payload),
  getParagraphContext: (payload) => ipcRenderer.invoke('books:get-context', payload),
  getBookParagraphs: (payload) => ipcRenderer.invoke('books:paragraphs', payload),
  syncProcessedBooks: (opts) => ipcRenderer.invoke('books:sync-processed', opts),

  // 问答伴读
  askInquiry: (payload) => ipcRenderer.invoke('inquiry:ask', payload),
  getEvidencePack: (packId) => ipcRenderer.invoke('inquiry:get-evidence-pack', packId),
  // 会话管理
  listSessions: () => ipcRenderer.invoke('sessions:list'),
  getSession: (id) => ipcRenderer.invoke('sessions:get', id),
  createSession: (payload) => ipcRenderer.invoke('sessions:create', payload),
  renameSession: (payload) => ipcRenderer.invoke('sessions:rename', payload),
  deleteSession: (id) => ipcRenderer.invoke('sessions:delete', id),

  // 系统与外部打开
  openPath: (filePath) => ipcRenderer.invoke('shell:open-path', filePath),
  getPdfUrl: (filePath) => {
    if (!filePath) return ''
    const normalized = filePath.replace(/\\/g, '/')
    const clean = normalized.replace(/^\/+/, '')
    return `book-pdf:///${clean}`
  },

  // 读者长期画像与核心记忆 (Core Memory)
  getCoreMemory: () => ipcRenderer.invoke('core-memory:get'),
  updateCoreMemory: (payload) => ipcRenderer.invoke('core-memory:update', payload),

  // Agent 智能体 & 实时思维链推流
  runAgent: (payload) => ipcRenderer.invoke('agent:run', payload),
  onAgentEvent: (callback) => {
    const subscription = (_event, value) => callback(value)
    ipcRenderer.on('agent:event', subscription)
    return () => ipcRenderer.removeListener('agent:event', subscription)
  },
  onThoughtStep: (callback) => {
    ipcRenderer.removeAllListeners('agent:thought-step')
    const subscription = (_event, value) => callback(value)
    ipcRenderer.on('agent:thought-step', subscription)
    return () => ipcRenderer.removeListener('agent:thought-step', subscription)
  }
}

console.log('[Preload] Book Assistant preload script starting...')

if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld('api', api)
    console.log('[Preload] Successfully exposed window.api via contextBridge.')
  } catch (error) {
    console.error('[Preload] Failed to expose window.api via contextBridge:', error)
  }
} else {
  window.api = api
  console.log('[Preload] Successfully exposed window.api directly on window.')
}
