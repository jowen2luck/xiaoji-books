<template>
  <n-drawer v-model:show="visible" :width="560" placement="right">
    <n-drawer-content :title="drawerTitle" closable>
      <div v-if="loading" class="loading-box">
        <n-spin size="medium" />
        <span style="margin-left: 10px; color: #666;">正在精确检索不可变原书物理锚点...</span>
      </div>

      <div v-else-if="currentEvidence" class="drawer-body">
        <!-- 顶部元信息标牌 -->
        <n-alert type="info" :bordered="false" class="meta-alert">
          <div class="meta-row">
            <span class="meta-item">📚 书目：<strong>《{{ currentEvidence.bookTitle }}》</strong></span>
            <span class="meta-item">📑 页码：<n-tag size="small" type="primary">{{ currentEvidence.printedPage || `P.${currentEvidence.pageIndex + 1}` }}</n-tag></span>
          </div>
          <div class="meta-row" style="margin-top: 6px;">
            <span class="meta-sub">相关度评分：{{ ((currentEvidence.relevance || 1) * 100).toFixed(0) }}%</span>
            <span class="meta-sub">章节对应：{{ currentEvidence.chapterTitle || '正文节选' }}</span>
          </div>
        </n-alert>

        <!-- 前置上下文（按需展开/收起） -->
        <div v-if="contextData?.contextBefore" class="context-section">
          <div class="context-header" @click="showBefore = !showBefore">
            <span>{{ showBefore ? '▼ 收起前序段落' : '▶ 展开前序段落（阅读连贯上下文）' }}</span>
          </div>
          <div v-if="showBefore" class="context-content before">
            {{ contextData.contextBefore }}
          </div>
        </div>

        <!-- 核心命中的原文证据（视觉高亮卡片） -->
        <div class="target-evidence-card">
          <div class="card-badge">📌 核心依据原文（不可变 Ground Truth）</div>
          <blockquote class="target-text">
            “{{ currentEvidence.excerpt }}”
          </blockquote>
        </div>

        <!-- 后置上下文（按需展开/收起） -->
        <div v-if="contextData?.contextAfter" class="context-section">
          <div class="context-header" @click="showAfter = !showAfter">
            <span>{{ showAfter ? '▼ 收起后续段落' : '▶ 展开后续段落（阅读连贯上下文）' }}</span>
          </div>
          <div v-if="showAfter" class="context-content after">
            {{ contextData.contextAfter }}
          </div>
        </div>

        <!-- 底部考据操作 -->
        <div class="drawer-footer-actions">
          <n-button size="small" @click="copyText(currentEvidence.excerpt)">
            📋 复制本段原文
          </n-button>
          <n-button size="small" secondary @click="expandAllContext">
            📖 展开全部上下文
          </n-button>
        </div>
      </div>

      <div v-else class="empty-box">
        暂无选中的原文证据。点击问答中的 [🔖 P.xx] 即可调出本抽屉。
      </div>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup>
import { ref } from 'vue'
import { useMessage } from 'naive-ui'

const message = useMessage()

const visible = ref(false)
const loading = ref(false)
const currentEvidence = ref(null)
const contextData = ref(null)
const drawerTitle = ref('📖 原文伴读与证据溯源')
const showBefore = ref(false)
const showAfter = ref(false)

/**
 * 打开抽屉并加载完整上下文
 */
async function open(evidence) {
  currentEvidence.value = evidence
  drawerTitle.value = `📖 原文伴读：《${evidence.bookTitle}》`
  visible.value = true
  showBefore.value = false
  showAfter.value = false

  // 从 evidence.id 解析段落ID并拉取扩展上下文
  try {
    loading.value = true
    const paraId = evidence.id.replace(/^ev_/, '').replace(/_\d+$/, '')
    if (window.api?.getParagraphContext) {
      const res = await window.api.getParagraphContext({ paragraphId: paraId, windowSize: 2 })
      if (res.success && res.data) {
        contextData.value = res.data
      } else {
        contextData.value = {
          contextBefore: evidence.contextBefore || '',
          contextAfter: evidence.contextAfter || ''
        }
      }
    } else {
      contextData.value = {
        contextBefore: evidence.contextBefore || '',
        contextAfter: evidence.contextAfter || ''
      }
    }
  } catch (err) {
    console.error('Failed to fetch context:', err)
  } finally {
    loading.value = false
  }
}

function expandAllContext() {
  showBefore.value = true
  showAfter.value = true
}

function copyText(text) {
  navigator.clipboard.writeText(text)
  message.success('已复制原文到剪贴板')
}

defineExpose({ open })
</script>

<style scoped>
.loading-box, .empty-box {
  padding: 40px;
  text-align: center;
  color: #888;
}
.drawer-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.meta-alert {
  border-radius: 8px;
}
.meta-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.meta-sub {
  font-size: 12px;
  color: #718096;
}
.target-evidence-card {
  background: #fffdf5;
  border: 1px solid #f6e05e;
  border-left: 4px solid #d69e2e;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 2px 6px rgba(0,0,0,0.03);
}
.card-badge {
  font-size: 12px;
  font-weight: 600;
  color: #b7791f;
  margin-bottom: 8px;
}
.target-text {
  margin: 0;
  font-size: 14px;
  line-height: 1.7;
  color: #2d3748;
  white-space: pre-wrap;
}
.context-section {
  border: 1px dashed #cbd5e0;
  border-radius: 6px;
  background: #f7fafc;
}
.context-header {
  padding: 8px 12px;
  font-size: 12px;
  color: #4a5568;
  cursor: pointer;
  user-select: none;
}
.context-header:hover {
  color: #2b6cb0;
}
.context-content {
  padding: 10px 14px;
  font-size: 13px;
  line-height: 1.6;
  color: #718096;
  border-top: 1px solid #edf2f7;
  white-space: pre-wrap;
}
.drawer-footer-actions {
  display: flex;
  gap: 10px;
  margin-top: 10px;
}
</style>
