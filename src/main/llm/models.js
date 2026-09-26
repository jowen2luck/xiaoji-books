/**
 * LLM 模型工厂
 * 支持 DashScope/OpenAI 兼容 API
 * 遵循 LangChain 1.0 BaseLanguageModel 规范
 */

import { ChatOpenAI } from '@langchain/openai'
import { bailianPoolManager, BAILIAN_AUTO_MODEL_ID } from './bailianPool.js'

// 定义不同 baseURL 对应的 API Key 环境变量映射
const API_KEY_MAP = {
  'https://dashscope.aliyuncs.com/compatible-mode/v1': 'DASHSCOPE_API_KEY_QWEN',
  'https://dashscope.aliyuncs.com/api/v1': 'DASHSCOPE_API_KEY',  // 新增：百炼 API 端点
  'https://llm-fxdsk6826w304s38.cn-beijing.maas.aliyuncs.com/compatible-mode/v1': 'DASHSCOPE_API_KEY',
  'https://uni-api.cstcloud.cn/v1': 'DASHSCOPE_API_KEY_SCTCLOUD',
  'https://api.openai.com/v1': 'OPENAI_API_KEY',
  'http://127.0.0.1:8045/v1': 'OPENAI_API_KEY',
  'https://api.longcat.chat/openai': 'LONGCAT_API_KEY',
  'https://api.longcat.chat/openai/v1': 'LONGCAT_API_KEY'
}

/**
 * 获取指定 baseURL 对应的 API Key
 * @param {string} baseURL - API 基础地址
 * @returns {string} - API Key
 */
function getAPIKeyForBaseURL(baseURL) {
  // 首先尝试从映射中获取对应的 API Key 环境变量名
  const envVar = API_KEY_MAP[baseURL]
  if (envVar && process.env[envVar]) {
    return process.env[envVar]
  }
  
  if (baseURL?.includes('dashscope') || baseURL?.includes('maas.aliyuncs.com')) {
    return process.env.DASHSCOPE_API_KEY || process.env.DASHSCOPE_API_KEY_QWEN || process.env.ANTI_DASHSCOPE_API_KEY || ''
  }

  // 如果没有找到特定的 API Key，则回退到默认的 API Key
  return process.env.DASHSCOPE_API_KEY || process.env.DASHSCOPE_API_KEY_QWEN || process.env.OPENAI_API_KEY || ''
}

/**
 * 创建兼容 OpenAI API 的聊天模型
 * @param {string} baseURL - API 基础地址
 * @param {string} model - 模型名称
 * @param {object} options - 额外配置
 * @returns {ChatOpenAI} - LangChain 标准聊天模型
 */
export function createChatModel(baseURL, model, options = {}) {
  let effectiveModel = model
  if (model === BAILIAN_AUTO_MODEL_ID || model === 'bailian-auto') {
    const current = bailianPoolManager.getCurrentModel()
    effectiveModel = current?.id || 'qwen3.7-flash-2026-07-15'
    console.log(`[createChatModel] 自动将 bailian-auto 解析为当前可用百炼模型: ${effectiveModel}`)
  }

  const apiKey = getAPIKeyForBaseURL(baseURL)
  
  console.log('[createChatModel] Configuration:', {
    baseURL,
    model: effectiveModel,
    originalModel: model,
    hasAPIKey: !!apiKey,
    apiKeyLength: apiKey?.length || 0
  })
  
  if (!apiKey) {
    throw new Error(`Missing API key for baseURL: ${baseURL}. Please set DASHSCOPE_API_KEY or DASHSCOPE_API_KEY_QWEN or OPENAI_API_KEY environment variable.`)
  }

  const config = {
    apiKey: apiKey,
    modelName: effectiveModel,
    temperature: options.temperature ?? 0.7,
    topP: options.top_p ?? 0.9,
    timeout: 60000,  // 增加到60秒
    maxRetries: 2,
  }
  
  // 根据 LangChain 版本选择正确的 baseURL 配置方式
  // 尝试多种配置方式以兼容不同版本
  if (baseURL && baseURL !== 'https://api.openai.com/v1') {
    // 方法1: 使用 configuration.baseURL
    config.configuration = {
      baseURL: baseURL
    }
    // 方法2: 同时设置 basePath (旧版本兼容)
    config.basePath = baseURL
  }
  
  console.log('[createChatModel] Final config:', JSON.stringify(config, null, 2))

  return new ChatOpenAI(config)
}

/**
 * 根据配置创建模型实例
 * @param {object} config - 模型配置
 * @returns {ChatOpenAI}
 */
export function initializeModel(config) {
  return createChatModel(
    config.selectedBaseURL || config.baseURL,
    config.selectedModel || config.model,
    {
      temperature: config.temperature,
      top_p: config.top_p,
      tools: config.tools,
    }
  )
}

/**
 * 从 API 响应解析工具调用
 * @param {object} response - API 响应对象
 * @returns {Array} - ToolCall 列表
 */
export function parseToolCalls(response) {
  if (!response) return []

  const toolCalls = []

  // 最优先处理 OpenAI 格式（choices 中的 tool_calls）
  // 这是采用直接 API 调用时的一般格式
  if (Array.isArray(response.choices)) {
    let hasChoicesWithToolCalls = false
    
    response.choices.forEach((choice, choiceIdx) => {
      const toolCallsInChoice = choice.message?.tool_calls || []
      if (toolCallsInChoice.length > 0) {
        hasChoicesWithToolCalls = true
        console.log(`[parseToolCalls] Choice ${choiceIdx} has ${toolCallsInChoice.length} tool calls`)
        toolCallsInChoice.forEach((call, callIdx) => {
          // 验证工具调用的有效性
          const toolName = call.function?.name || call.name
          const toolArgs = call.function?.arguments || call.arguments
          
          // 跳过无效的工具调用（缺少名称或参数）
          if (!toolName) {
            console.warn('[parseToolCalls] Skipping tool call with missing name:', call)
            return
          }
          
          // 验证参数不为空或只包含空对象
          let argsStr = typeof toolArgs === 'string' ? toolArgs : JSON.stringify(toolArgs || {})
          if (argsStr === '{}' && !toolArgs) {
            console.warn(`[parseToolCalls] Skipping tool call '${toolName}' with empty arguments`)
            return
          }
          
          // 标准化工具调用格式
          const standardized = {
            id: call.id || `${Date.now()}-${Math.random()}`,
            type: 'function',
            function: {
              name: toolName,
              // 确保 arguments 是字符串格式
              arguments: argsStr
            }
          }
          console.log(`[parseToolCalls] Added tool call: ${toolName} (choice ${choiceIdx}, call ${callIdx})`)
          toolCalls.push(standardized)
        })
      }
    })
    
    // 正常情况下，不应该有顶级 tool_calls
    // 如果已经从 choices 中找到了，就跳过顶级的
    if (hasChoicesWithToolCalls) {
      console.log('[parseToolCalls] Tool calls found in choices, skipping root level tool_calls')
      console.log(`[parseToolCalls] Total tool calls returned: ${toolCalls.length}`)
      return toolCalls
    }
  }

  // 也处理 LangChain 原生响应（顶级 tool_calls）
  if (Array.isArray(response.tool_calls)) {
    console.log(`[parseToolCalls] Found ${response.tool_calls.length} tool_calls at response root`)
    response.tool_calls.forEach((call, callIdx) => {
      // 验证工具调用的有效性
      const toolName = call.name || call.function?.name
      const toolArgs = call.arguments || call.function?.arguments
      
      // 跳过无效的工具调用（缺少名称或参数）
      if (!toolName) {
        console.warn('[parseToolCalls] Skipping tool call with missing name:', call)
        return
      }
      
      // 验证参数不为空或只包含空对象
      let argsStr = typeof toolArgs === 'string' ? toolArgs : JSON.stringify(toolArgs || {})
      if (argsStr === '{}' && !toolArgs) {
        console.warn(`[parseToolCalls] Skipping tool call '${toolName}' with empty arguments`)
        return
      }
      
      const standardized = {
        id: call.id || `${Date.now()}-${Math.random()}`,
        type: 'function',
        function: {
          name: toolName,
          arguments: argsStr
        }
      }
      console.log(`[parseToolCalls] Added tool call from root: ${toolName} (call ${callIdx})`)
      toolCalls.push(standardized)
    })
  }

  console.log(`[parseToolCalls] Total tool calls returned: ${toolCalls.length}`)
  return toolCalls
}

/**
 * 从响应获取文本内容
 * @param {object} response - API 响应
 * @returns {string} - 文本内容
 */
export function getTextContent(response) {
  if (typeof response === 'string') return response
  
  // LangChain AIMessage
  if (response.content) {
    return typeof response.content === 'string' 
      ? response.content 
      : response.content
  }

  // OpenAI 格式
  return response?.choices?.[0]?.message?.content || ''
}
