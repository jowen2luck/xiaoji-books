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
import { ref, computed, watch } from 'vue'
import { useMessage } from 'naive-ui'

const props = defineProps({
  show: { type: Boolean, default: false },
  evidence: { type: Object, default: null }
})

const emit = defineEmits(['update:show'])

const message = useMessage()

const visible = computed({
  get: () => props.show,
  set: (v) => emit('update:show', v)
})

const loading = ref(false)
const currentEvidence = ref(null)
const contextData = ref(null)
const drawerTitle = ref('📖 原文伴读与证据溯源')
const showBefore = ref(false)
const showAfter = ref(false)

watch(() => props.show, (v) => {
  if (v && props.evidence) open(props.evidence)
})

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
  color: var(--color-ink-faint);
}
.drawer-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.meta-alert {
  border-radius: var(--radius-lg) !important;
}
.meta-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.meta-sub {
  font-size: 11px;
  color: var(--color-ink-muted);
}
.target-evidence-card {
  background: var(--color-accent-soft);
  border: 1px solid #fde68a;
  border-left: 3px solid var(--color-accent);
  border-radius: var(--radius-md);
  padding: 18px 20px;
  box-shadow: var(--shadow-sm);
}
.card-badge {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-accent);
  margin-bottom: 10px;
  letter-spacing: 0.3px;
}
.target-text {
  margin: 0;
  font-family: var(--font-display);
  font-size: 15px;
  line-height: 1.8;
  color: var(--color-ink);
  white-space: pre-wrap;
}
.context-section {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  overflow: hidden;
}
.context-header {
  padding: 8px 14px;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-ink-soft);
  cursor: pointer;
  user-select: none;
  transition: color 0.15s;
}
.context-header:hover {
  color: var(--color-accent);
}
.context-content {
  padding: 12px 14px;
  font-size: 13px;
  line-height: 1.65;
  color: var(--color-ink-muted);
  border-top: 1px solid var(--color-border);
  white-space: pre-wrap;
}
.drawer-footer-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
</style>
