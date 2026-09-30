/**
 * @file inquiryHandler.js
 * @description 问答伴读 IPC 通道
 */

import { ipcMain } from 'electron'
import { getServices } from '../../application/index.js'

export function registerInquiryHandlers() {
  const { inquiryService } = getServices()

  // 发起伴读提问（支持意图路由、多轮历史、核心记忆与思维链实时推流）
  ipcMain.handle('inquiry:ask', async (event, { question, scope, history, sessionId }) => {
    try {
      const onThoughtStep = (step) => {
        if (event.sender && !event.sender.isDestroyed()) {
          event.sender.send('agent:thought-step', step)
        }
      }
      const result = await inquiryService.ask({ question, scope, history, sessionId, onThoughtStep })
      return { success: true, data: result }
    } catch (err) {
      console.error('[InquiryHandler] Error:', err)
      return { success: false, error: err.message }
    }
  })

  // 获取证据包详情
  ipcMain.handle('inquiry:get-evidence-pack', async (_event, packId) => {
    try {
      const pack = inquiryService.getEvidencePack(packId)
      return { success: true, data: pack }
    } catch (err) {
      return { success: false, error: err.message }
    }
  })

  // 获取会话列表与单会话
  ipcMain.handle('sessions:list', async () => {
    try {
      return { success: true, data: inquiryService.listSessions() }
    } catch (err) {
      return { success: false, error: err.message }
    }
  })
  ipcMain.handle('sessions:get', async (_event, id) => {
    try {
      return { success: true, data: inquiryService.getSession(id) }
    } catch (err) {
      return { success: false, error: err.message }
    }
  })
  ipcMain.handle('sessions:create', async (_event, payload) => {
    try {
      const question = payload?.question || '新会话'
      const scope = payload?.scope || {}
      return { success: true, data: inquiryService.createSession(question, scope) }
    } catch (err) {
      return { success: false, error: err.message }
    }
  })
  ipcMain.handle('sessions:rename', async (_event, { id, title }) => {
    try {
      const ok = inquiryService.renameSession(id, title)
      return { success: ok }
    } catch (err) {
      return { success: false, error: err.message }
    }
  })
  ipcMain.handle('sessions:delete', async (_event, id) => {
    try {
      const ok = inquiryService.deleteSession(id)
      return { success: ok }
    } catch (err) {
      return { success: false, error: err.message }
    }
  })

  // 常驻画像与阅读记忆 (Core Memory)
  ipcMain.handle('core-memory:get', async () => {
    try {
      const { getCoreMemoryManager } = await import('../../agent/memory/CoreMemoryManager.js')
      return { success: true, data: getCoreMemoryManager().getMemory() }
    } catch (err) {
      return { success: false, error: err.message }
    }
  })
  ipcMain.handle('core-memory:update', async (_event, { section, content }) => {
    try {
      const { getCoreMemoryManager } = await import('../../agent/memory/CoreMemoryManager.js')
      const ok = getCoreMemoryManager().updateSection(section, content)
      return { success: ok }
    } catch (err) {
      return { success: false, error: err.message }
    }
  })
}
