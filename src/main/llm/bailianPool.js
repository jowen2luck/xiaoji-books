/**
 * 百炼（DashScope）模型聚合与自动顺延池管理器
 * 
 * 核心能力：
 * 1. 维护百炼候选模型列表，严格按到期时间升序排列（先到期先用）
 * 2. 自动根据系统时间检查并标记过期模型（expired）
 * 3. 监控调用错误（如 429、402、欠费、配额用尽、模型不存在），自动标记废弃（deprecated）
 * 4. 废弃状态持久化至本地 JSON 文件，避免重启后重复请求失效模型
 * 5. 支持统一虚拟模型代号 'bailian-auto'，调用失败时在请求内无缝顺延至下一个候选模型
 */

import fs from 'node:fs'
import path from 'node:path'

/** 统一百炼聚合模型代号 */
export const BAILIAN_AUTO_MODEL_ID = 'bailian-auto'

/**
 * 百炼模型候选池（按到期时间升序排序）
 */
export const BAILIAN_MODELS_POOL = [
  { id: 'qwen3.7-flash-2026-07-15', name: 'Qwen 3.7 Flash (0715)', expireDate: '2026-10-23', type: 'llm', quota: '1M', daysLeft: 30 },
  { id: 'qwen3.7-flash', name: 'Qwen 3.7 Flash', expireDate: '2026-10-23', type: 'llm', quota: '1M', daysLeft: 30 },
  { id: 'deepseek-v4-flash-0731', name: 'DeepSeek V4 Flash (0731)', expireDate: '2026-10-31', type: 'llm', quota: '1M', daysLeft: 38 },
  { id: 'qwen3.8-max', name: 'Qwen 3.8 Max', expireDate: '2026-11-01', type: 'llm', quota: '1M', daysLeft: 39 },
  { id: 'qwen3.8-2.4t-a95b', name: 'Qwen 3.8 2.4T A95B', expireDate: '2026-11-12', type: 'llm', quota: '1M', daysLeft: 50 },
  { id: 'deepseek-v4-pro-0813', name: 'DeepSeek V4 Pro (0813)', expireDate: '2026-11-13', type: 'llm', quota: '1M', daysLeft: 51 },
  { id: 'qwen3.8-27b', name: 'Qwen 3.8 27B', expireDate: '2026-11-17', type: 'llm', quota: '1M', daysLeft: 55 },
  { id: 'kimi-k3', name: 'Kimi K3', expireDate: '2026-11-17', type: 'llm', quota: '1M', daysLeft: 55 },
  { id: 'glm-5.3', name: 'GLM 5.3', expireDate: '2026-11-23', type: 'llm', quota: '1M', daysLeft: 61 },
  { id: 'qwen3.8-flash', name: 'Qwen 3.8 Flash', expireDate: '2026-11-25', type: 'llm', quota: '1M', daysLeft: 63 },
  { id: 'qwen3.8-max-0902', name: 'Qwen 3.8 Max (0902)', expireDate: '2026-12-01', type: 'llm', quota: '1M', daysLeft: 69 },
  { id: 'deepseek-v4.1-flash', name: 'DeepSeek V4.1 Flash', expireDate: '2026-12-13', type: 'llm', quota: '1M', daysLeft: 81 },
  { id: 'qwen-mt-uni', name: 'Qwen MT Uni (多模态)', expireDate: '2026-12-15', type: 'multimodal', quota: '1M', daysLeft: 83 },
  { id: 'qwen3.8-omni-flash', name: 'Qwen 3.8 Omni Flash (多模态)', expireDate: '2026-12-17', type: 'multimodal', quota: '1M', daysLeft: 85 },
  { id: 'qwen3.8-omni-flash-realtime', name: 'Qwen 3.8 Omni Flash Realtime (多模态)', expireDate: '2026-12-21', type: 'multimodal', quota: '1M', daysLeft: 89 },
]

export class BailianPoolManager {
  constructor() {
    this.statusFilePath = null
    this.customDataDir = null
    this.state = {
      deprecated: {} // { [modelId]: { reason, message, deprecatedAt } }
    }
    this.initialized = false
  }

  setCustomDataDir(dir) {
    this.customDataDir = dir
    this.statusFilePath = null
    this.initialized = false
  }

  resolveStatusFilePath() {
    if (this.customDataDir) {
      return path.join(this.customDataDir, 'bailian_pool_status.json')
    }
    try {
      // 优先探测 Electron userData 目录
      let electron
      try {
        electron = globalThis.require ? globalThis.require('electron') : null
      } catch {}
      if (electron?.app?.getPath) {
        return path.join(electron.app.getPath('userData'), 'bailian_pool_status.json')
      }
    } catch {}

    return path.join(process.cwd(), 'bailian_pool_status.json')
  }

  ensureInitialized() {
    if (this.initialized) return
    this.statusFilePath = this.resolveStatusFilePath()
    this.loadState()
    this.initialized = true
  }

  loadState() {
    try {
      if (fs.existsSync(this.statusFilePath)) {
        const raw = fs.readFileSync(this.statusFilePath, 'utf-8')
        const parsed = JSON.parse(raw)
        if (parsed && typeof parsed.deprecated === 'object') {
          this.state.deprecated = parsed.deprecated
          console.log(`[BailianPool] Loaded status: ${Object.keys(this.state.deprecated).length} models deprecated`)
          return
        }
      }
    } catch (e) {
      console.warn('[BailianPool] Failed to load status file:', e.message)
    }
    this.state = { deprecated: {} }
  }

  saveState() {
    try {
      this.ensureInitialized()
      const dir = path.dirname(this.statusFilePath)
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true })
      }
      const tempPath = this.statusFilePath + '.tmp'
      fs.writeFileSync(tempPath, JSON.stringify(this.state, null, 2), 'utf-8')
      fs.renameSync(tempPath, this.statusFilePath)
    } catch (e) {
      console.error('[BailianPool] Failed to save status file:', e.message)
    }
  }

  /**
   * 检查模型是否已超过到期日（按到期日当天 23:59:59 结束）
   */
  isExpired(model, now = new Date()) {
    if (!model?.expireDate) return false
    const expireTime = new Date(`${model.expireDate}T23:59:59.999+08:00`).getTime()
    return now.getTime() > expireTime
  }

  /**
   * 检查并自动标记所有已过期的模型
   */
  checkAndDeprecateExpired(now = new Date()) {
    this.ensureInitialized()
    let changed = false
    for (const model of BAILIAN_MODELS_POOL) {
      if (this.isExpired(model, now) && !this.state.deprecated[model.id]) {
        this.markDeprecated(
          model.id,
          'expired',
          `模型已于 ${model.expireDate} 到期（系统时间: ${now.toISOString()}）`,
          false
        )
        changed = true
      }
    }
    if (changed) {
      this.saveState()
    }
  }

  /**
   * 标记某个模型废弃并记录原因
   */
  markDeprecated(modelId, reason, message, shouldSave = true) {
    this.ensureInitialized()
    this.state.deprecated[modelId] = {
      reason,
      message: String(message || ''),
      deprecatedAt: new Date().toISOString()
    }
    console.warn(`[BailianPool] ⚠️ 模型 ${modelId} 已标记废弃 [原因: ${reason}] - ${message}`)
    if (shouldSave) {
      this.saveState()
    }
  }

  /**
   * 判断错误是否属于应该将该模型废弃并顺延的类型
   * 涵盖：429 配额用尽、402 欠费/需要付费、模型不存在/已下线等
   */
  isDeprecatableError(error, statusCode) {
    if (!error && !statusCode) return false

    const code = Number(statusCode || error?.status || error?.statusCode || 0)
    const msg = String(error?.message || error || '').toLowerCase()

    // 状态码判断
    if (code === 402) return true
    if (code === 404 && (msg.includes('model') || msg.includes('not found') || msg.includes('exist'))) return true

    // 错误关键词精准识别
    const deprecatePatterns = [
      'allocationquotaexceeded',
      'throttling.allocationquota',
      'insufficient_quota',
      'quota exceeded',
      'quota_exhausted',
      'exceeded your current quota',
      'free quota has been used up',
      'arrearage',
      'payment required',
      'insufficient balance',
      'account has insufficient balance',
      'modelnotfound',
      'model not found',
      'model does not exist',
      'does not exist',
      'model is offline',
      'model has been deprecated',
      'modelnotaccessible',
      'not exist',
      '429',
      '欠费',
      '配额',
      '额度',
      '已用尽',
      '模型不存在',
      '模型已下线'
    ]

    return deprecatePatterns.some(pattern => msg.includes(pattern))
  }

  /**
   * 获取当前可用的候选模型队列（未过期且未被标记废弃，按到期时间升序）
   */
  getActiveCandidates({ type, now = new Date() } = {}) {
    this.checkAndDeprecateExpired(now)

    let candidates = BAILIAN_MODELS_POOL.filter(m => !this.state.deprecated[m.id])

    if (type) {
      const typeFiltered = candidates.filter(m => m.type === type)
      if (typeFiltered.length > 0) {
        candidates = typeFiltered
      }
    }

    // 保证按 expireDate 升序排序（临近过期的优先使用）
    candidates.sort((a, b) => new Date(a.expireDate).getTime() - new Date(b.expireDate).getTime())

    return candidates
  }

  /**
   * 获取当前顺延队首模型
   */
  getCurrentModel(options) {
    const candidates = this.getActiveCandidates(options)
    return candidates[0] || null
  }

  /**
   * 重置模型池（清空所有废弃标记）
   */
  resetPool() {
    this.ensureInitialized()
    this.state.deprecated = {}
    this.saveState()
    console.log('[BailianPool] 🔄 模型池状态已重置，所有未过期模型已重新启用')
  }

  /**
   * 获取模型池运行状态摘要
   */
  getPoolSummary() {
    this.ensureInitialized()
    const active = this.getActiveCandidates()
    const deprecatedKeys = Object.keys(this.state.deprecated)
    return {
      total: BAILIAN_MODELS_POOL.length,
      activeCount: active.length,
      deprecatedCount: deprecatedKeys.length,
      currentModel: active[0] || null,
      activeModels: active,
      deprecatedList: deprecatedKeys.map(id => ({
        id,
        ...this.state.deprecated[id]
      }))
    }
  }
}

// 导出全局单例
export const bailianPoolManager = new BailianPoolManager()
