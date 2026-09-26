/**
 * @file bookHandler.js
 * @description 图书信息与标签分类 IPC 通道
 */

import { ipcMain } from 'electron'
import { getServices } from '../../application/index.js'

export function registerBookHandlers() {
  const { bookService } = getServices()

  // 1. 获取图书列表
  ipcMain.handle('books:list', async (_event, filter) => {
    try {
      return { success: true, data: await bookService.listBooks(filter) }
    } catch (err) {
      return { success: false, error: err.message }
    }
  })

  // 2. 获取图书详情
  ipcMain.handle('books:get', async (_event, bookId) => {
    try {
      return { success: true, data: await bookService.getBookDetails(bookId) }
    } catch (err) {
      return { success: false, error: err.message }
    }
  })

  // 3. 更新图书分类与标签
  ipcMain.handle('books:update-classification', async (_event, { bookId, category, tags, briefSummary }) => {
    try {
      await bookService.updateClassification(bookId, { primaryCategory: category, tags, briefSummary })
      return { success: true }
    } catch (err) {
      return { success: false, error: err.message }
    }
  })

  // 4. 获取段落上下文（伴读抽屉）
  ipcMain.handle('books:get-context', async (_event, { paragraphId, windowSize }) => {
    try {
      return { success: true, data: await bookService.getContextForEvidence(paragraphId, windowSize) }
    } catch (err) {
      return { success: false, error: err.message }
    }
  })

  // 5. 通读阅读器流式分页段落 (支持指定页码过滤)
  ipcMain.handle('books:paragraphs', async (_event, { bookId, offset, limit, pageIndex }) => {
    try {
      return { success: true, data: await bookService.getBookParagraphs(bookId, offset, limit, pageIndex) }
    } catch (err) {
      return { success: false, error: err.message }
    }
  })

  // 6. 增量扫描并索引已处理好的书籍
  ipcMain.handle('books:sync-processed', async (_event, opts) => {
    try {
      const stats = await bookService.syncProcessedBooks(opts)
      return { success: true, data: stats }
    } catch (err) {
      return { success: false, error: err.message }
    }
  })
}
