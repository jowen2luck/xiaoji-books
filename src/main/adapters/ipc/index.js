/**
 * @file index.js
 * @description 注册所有 IPC 通道
 */

import { registerBookHandlers } from './bookHandler.js'
import { registerInquiryHandlers } from './inquiryHandler.js'
import { registerReviewHandlers } from './reviewHandler.js'
import { registerAgentHandlers } from '../../agent/ipcHandlers.js'

export function registerAllIPCHandlers() {
  registerBookHandlers()
  registerInquiryHandlers()
  registerReviewHandlers()
  registerAgentHandlers()
}
