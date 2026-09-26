/**
 * @file reviewHandler.js
 * @description 深度书评与解读工坊 IPC 通道
 */

import { ipcMain } from 'electron'
import { getServices } from '../../application/index.js'

export function registerReviewHandlers() {
  const { reviewService } = getServices()

  // 单书深度解读
  ipcMain.handle('review:generate', async (_event, bookId) => {
    try {
      const report = await reviewService.generateBookReview(bookId)
      return { success: true, data: report }
    } catch (err) {
      return { success: false, error: err.message }
    }
  })

  // 多书对比
  ipcMain.handle('review:compare', async (_event, { topic, bookIds }) => {
    try {
      const comparison = await reviewService.compareBooks(topic, bookIds)
      return { success: true, data: comparison }
    } catch (err) {
      return { success: false, error: err.message }
    }
  })
}
