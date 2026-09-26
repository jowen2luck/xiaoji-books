/**
 * @file ipcHandlers.js
 * @description 智能体 ReAct 工作台 IPC 通道
 */

import { ipcMain } from 'electron'
import { getServices } from '../application/index.js'
import { AgentExecutor } from './executor.js'

export function registerAgentHandlers() {
  const { toolRegistry } = getServices()

  ipcMain.handle('agent:run', async (event, { query, scope }) => {
    try {
      const executor = new AgentExecutor({
        toolRegistry,
        eventEmitter: ({ type, data }) => {
          // 向发送请求的前端窗口推流事件 (thought, action, observation)
          if (!event.sender.isDestroyed()) {
            event.sender.send('agent:event', { type, data })
          }
        }
      })

      const res = await executor.run({ query, scope })
      return { success: true, data: res }
    } catch (err) {
      return { success: false, error: err.message }
    }
  })
}
