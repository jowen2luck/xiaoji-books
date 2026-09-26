<template>
  <div class="chat-workbench">
    <!-- 顶部工作台状态与作用域控制栏 -->
    <div class="workbench-header">
      <div class="header-left">
        <div class="session-title-box">
          <span class="title-text" :title="sessionTitle">{{ sessionTitle }}</span>
          <n-button
            quaternary
            circle
            size="tiny"
            class="rename-trigger-btn"
            @click="$emit('start-rename-session')"
            title="重命名对话"
          >
            <template #icon><n-icon size="13"><CreateOutline /></n-icon></template>
          </n-button>
        </div>

        <n-divider vertical style="margin: 0 8px;" />

        <!-- 紧凑伴读 Scope 范围切换器 -->
        <div class="scope-compact-selector">
          <span class="scope-prefix-label">伴读范围：</span>
          <n-radio-group v-model:value="scopeType" size="tiny" @update:value="onScopeChange">
            <n-radio-button value="global">全库探索</n-radio-button>
            <n-radio-button value="category">分类流派</n-radio-button>
            <n-radio-button value="single_book">指定单书</n-radio-button>
          </n-radio-group>

          <n-select
            v-if="scopeType === 'category'"
            v-model:value="selectedCategory"
            :options="categoryOptions"
            placeholder="选择主题学科"
            size="tiny"
            style="width: 170px; margin-left: 8px;"
          />

          <n-select
            v-if="scopeType === 'single_book'"
            v-model:value="selectedBookId"
            :options="bookOptions"
            filterable
            placeholder="选择精读书籍"
            size="tiny"
            style="width: 220px; margin-left: 8px;"
          />
        </div>
      </div>

      <div class="header-right">
        <!-- 快捷进入原文并行预览 -->
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button
              size="small"
              secondary
              type="primary"
              class="reader-shortcut-btn"
              @click="handleOpenParallelReader"
            >
              <template #icon><n-icon><BookOutline /></n-icon></template>
              原文并行预览
            </n-button>
          </template>
          进入原书影印与提取文字的左右对照阅读器
        </n-tooltip>

        <!-- 思维链开关 -->
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button
              quaternary
              circle
              size="small"
              :type="showTracePanel ? 'primary' : 'default'"
              @click="showTracePanel = !showTracePanel"
            >
              <template #icon><n-icon size="16"><SparklesOutline /></n-icon></template>
            </n-button>
          </template>
          {{ showTracePanel ? '收起右侧思维链轨迹' : '展开右侧思维链轨迹' }}
        </n-tooltip>

        <!-- 清空对话 -->
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button quaternary circle size="small" @click="confirmClearHistory">
              <template #icon><n-icon size="16"><RefreshOutline /></n-icon></template>
            </n-button>
          </template>
          清空当前会话消息
        </n-tooltip>
      </div>
    </div>

    <!-- 主对话体与右侧思维链分栏 -->
    <div class="workbench-main-body">
      <!-- 聊天对话主视窗 -->
      <div class="chat-viewport">
        <div class="messages-container" ref="chatScrollRef">
          <!-- 小鸡书友欢迎 Hero Card (空消息状态) -->
          <div v-if="messages.length === 0" class="hero-welcome-card">
            <div class="hero-avatar-box">
              <span class="hero-avatar-emoji">🐥</span>
              <span class="hero-online-dot"></span>
            </div>
            <h2 class="hero-title">你好呀！我是小鸡书友 🐥</h2>
            <p class="hero-subtitle">
              你的智能文献考据与学术研读伴侣。基于不可变原著存证与认知四层分层模型，随时为你抽丝剥茧、溯源求证～
            </p>

            <div class="prompt-chips-grid">
              <div
                v-for="(chip, idx) in promptChips"
                :key="idx"
                class="prompt-chip-card"
                @click="applyPromptChip(chip.query)"
              >
                <span class="chip-icon">{{ chip.icon }}</span>
                <div class="chip-text-group">
                  <span class="chip-label">{{ chip.label }}</span>
                  <span class="chip-desc">{{ chip.query }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 消息气泡流 -->
          <div v-for="(msg, idx) in messages" :key="idx" class="message-row" :class="msg.role">
            <!-- 用户气泡 -->
            <div v-if="msg.role === 'user'" class="user-bubble">
              <div class="bubble-header user-header">
                <span class="user-name">我</span>
              </div>
              <div class="bubble-content user-content">
                {{ msg.content }}
              </div>
            </div>

            <!-- 助手气泡 -->
            <div v-else class="assistant-bubble">
              <div class="bubble-header assistant-header">
                <span class="assistant-avatar">🐥</span>
                <span class="assistant-name">小鸡书友</span>
                <span class="assistant-badge">不可变溯源</span>
              </div>

              <div class="bubble-content assistant-content">
                <!-- 实时/历史思维链折叠卡片 -->
                <div v-if="msg.executionTrace && msg.executionTrace.length > 0" class="trace-fold-card">
                  <div class="trace-fold-header" @click="msg._showTrace = !msg._showTrace">
                    <span class="trace-fold-title">
                      <n-icon size="14"><SparklesOutline /></n-icon>
                      思考过程 (共 {{ msg.executionTrace.length }} 步推理动作)
                    </span>
                    <span class="trace-fold-toggle">{{ msg._showTrace ? '收起 ▴' : '展开 ▾' }}</span>
                  </div>
                  <div v-if="msg._showTrace" class="trace-steps-body">
                    <div v-for="(step, sIdx) in msg.executionTrace" :key="sIdx" class="trace-step-item">
                      <div class="step-num">{{ sIdx + 1 }}</div>
                      <div class="step-info">
                        <div class="step-type-badge">{{ step.type || '推理' }}</div>
                        <div class="step-content">{{ step.thought || step.message || step.content || step.action }}</div>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- Markdown 正文回答 -->
                <div
                  class="markdown-body"
                  v-html="renderMarkdown(msg.content)"
                  @click="handleInlineCitationClick($event, msg.evidencePack)"
                ></div>

                <!-- 认识论定量计算指标 -->
                <div v-if="msg.computations && msg.computations.length > 0" class="metric-ribbon">
                  <div v-for="c in msg.computations" :key="c.text" class="metric-badge">
                    📊 {{ c.text }}
                  </div>
                </div>

                <!-- 核心事实证据卡片列表 (带一键进入并行对照阅读) -->
                <div v-if="msg.evidencePack && ((msg.evidencePack.references && msg.evidencePack.references.length > 0) || (msg.evidencePack.evidence && msg.evidencePack.evidence.length > 0))" class="evidence-pack-section">
                  <div class="evidence-section-title">
                    <span>📑 本轮回答引用的原典依据 ({{ (msg.evidencePack.references || msg.evidencePack.evidence).length }} 处)</span>
                  </div>
                  <div class="evidence-cards-scroll">
                    <div
                      v-for="(refItem, rIdx) in (msg.evidencePack.references || msg.evidencePack.evidence || []).slice(0, 4)"
                      :key="rIdx"
                      class="evidence-card"
                    >
                      <div class="evidence-card-header">
                        <span class="evidence-book-title" :title="refItem.bookTitle">
                          《{{ refItem.bookTitle || '文献' }}》
                        </span>
                        <span class="evidence-page-tag">
                          {{ refItem.printedPage || `P.${(refItem.pageIndex || 0) + 1}` }}
                        </span>
                      </div>
                      <div class="evidence-card-body">
                        "{{ refItem.snippet || refItem.excerpt || refItem.text || '引文摘录...' }}"
                      </div>
                      <div class="evidence-card-footer">
                        <n-button
                          size="tiny"
                          type="primary"
                          secondary
                          @click="openParallelForEvidence(refItem)"
                        >
                          📖 原文并行预览 ({{ refItem.printedPage || `P.${(refItem.pageIndex || 0) + 1}` }})
                        </n-button>
                        <n-button
                          size="tiny"
                          quaternary
                          @click="openSourceDrawer(refItem)"
                        >
                          🔍 查阅上下文
                        </n-button>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- 深入研讨追问建议 -->
                <div v-if="msg.followUps && msg.followUps.length > 0" class="follow-up-bar">
                  <span class="follow-title">🔮 深入研讨追问：</span>
                  <div class="follow-chips">
                    <n-tag
                      v-for="fu in msg.followUps"
                      :key="fu"
                      size="small"
                      round
                      type="warning"
                      clickable
                      @click="sendQuickQuestion(fu)"
                    >
                      {{ fu }}
                    </n-tag>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 助手实时思考/推流中状态 -->
          <div v-if="loading" class="assistant-bubble thinking-bubble">
            <div class="bubble-header assistant-header">
              <span class="assistant-avatar">🐥</span>
              <span class="assistant-name">小鸡书友</span>
              <span class="assistant-badge thinking">思考中...</span>
            </div>
            <div class="thinking-content">
              <n-spin size="small" />
              <span class="thinking-text">{{ currentThoughtText || '正在检索不可变原典证据，编排学术逻辑...' }}</span>
            </div>
          </div>
        </div>

        <!-- 底部输入操作栏 -->
        <div class="chat-input-bar">
          <div class="input-container">
            <n-input
              v-model:value="inputText"
              type="textarea"
              placeholder="向小鸡提问文献要点、作者观点、或是要求对比不同流派的论述... (Enter 发送, Shift+Enter 换行)"
              :autosize="{ minRows: 2, maxRows: 6 }"
              :disabled="loading"
              @keydown="handleKeyDown"
              class="message-textarea"
            />
            <div class="input-actions-row">
              <div class="input-scope-indicator">
                <span class="indicator-dot"></span>
                <span class="indicator-label">{{ currentScopeDisplay }}</span>
              </div>
              <n-button
                type="primary"
                :loading="loading"
                :disabled="!inputText.trim()"
                @click="handleSubmit"
                class="send-btn"
              >
                <template #icon><n-icon><SendOutline /></n-icon></template>
                发送研读
              </n-button>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧思维链轨迹面板 (可收起) -->
      <div v-if="showTracePanel" class="trace-side-panel">
        <div class="trace-panel-header">
          <div class="panel-title">
            <n-icon size="16"><SparklesOutline /></n-icon>
            <span>思维链推理全景</span>
          </div>
          <n-button quaternary circle size="tiny" @click="showTracePanel = false">✕</n-button>
        </div>
        <div class="trace-panel-content">
          <div v-if="activeExecutionTrace.length === 0" class="empty-trace">
            暂无当前轮次的推理轨迹
          </div>
          <div v-else class="trace-timeline">
            <div v-for="(step, idx) in activeExecutionTrace" :key="idx" class="timeline-step">
              <div class="timeline-dot"></div>
              <div class="timeline-card">
                <div class="timeline-title-row">
                  <span class="step-type">{{ step.type || '推导' }}</span>
                  <span class="step-time">步骤 {{ idx + 1 }}</span>
                </div>
                <div class="timeline-desc">{{ step.thought || step.message || step.content || step.action }}</div>
                <div v-if="step.observation" class="timeline-obs">
                  <span class="obs-tag">观察存证:</span>
                  <span>{{ step.observation }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 原文上下文伴读抽屉 -->
    <SourceDrawer
      v-model:show="showDrawer"
      :evidence="activeDrawerEvidence"
      @view-in-parallel="openParallelForEvidence"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { useMessage } from 'naive-ui'
import { marked } from 'marked'
import {
  CreateOutline,
  BookOutline,
  SparklesOutline,
  RefreshOutline,
  SendOutline
} from '@vicons/ionicons5'
import SourceDrawer from './SourceDrawer.vue'

const props = defineProps({
  currentSessionId: { type: String, default: '' },
  currentSessionTitle: { type: String, default: '研读新对话' }
})

const emit = defineEmits([
  'start-rename-session',
  'session-updated',
  'open-parallel-reader'
])

const message = useMessage()

// 状态
const messages = ref([])
const inputText = ref('')
const loading = ref(false)
const currentThoughtText = ref('')
const chatScrollRef = ref(null)

const scopeType = ref('global') // 'global', 'category', 'single_book'
const selectedCategory = ref(null)
const selectedBookId = ref(null)

const books = ref([])
const showTracePanel = ref(false)
const activeExecutionTrace = ref([])

// 抽屉
const showDrawer = ref(false)
const activeDrawerEvidence = ref(null)

// 欢迎卡片推荐提示词
const promptChips = ref([
  {
    icon: '🚩',
    label: '国际歌与巴黎公社',
    query: '请结合馆藏史料，分析《国际歌》创作的历史背景以及巴黎公社在文献中的核心论述。'
  },
  {
    icon: '🏛️',
    label: '《国家与革命》论析',
    query: '《国家与革命》的核心要义是什么？列宁是如何论述国家消亡与无产阶级专政的？'
  },
  {
    icon: '⚖️',
    label: '学术流派观点对比',
    query: '对比布哈林与普列汉诺夫在唯物史观与经济政策上的学术分歧与代表性引文。'
  },
  {
    icon: '🔍',
    label: '无产阶级专政考据',
    query: '跨文献检索马克思、恩格斯、列宁对“无产阶级专政”概念的定义与原文论据。'
  }
])

// 计算属性
const sessionTitle = computed(() => props.currentSessionTitle || '研读对话')

const categoryOptions = [
  { label: '政治经济与社会主义', value: '政治经济与社会主义' },
  { label: '历史与人物传记', value: '历史与人物传记' },
  { label: '哲学与方法论', value: '哲学与方法论' },
  { label: '文化与社会研究', value: '文化与社会研究' }
]

const bookOptions = computed(() => {
  return books.value.map(b => ({
    label: `《${b.title}》 (${b.primaryCategory || '文献'})`,
    value: b.id
  }))
})

const currentScopeDisplay = computed(() => {
  if (scopeType.value === 'global') return '全库 67 本馆藏宏观探索'
  if (scopeType.value === 'category') return `分类：${selectedCategory.value || '未选择'}`
  const b = books.value.find(item => item.id === selectedBookId.value)
  return `单书：${b ? `《${b.title}》` : '未选择书籍'}`
})

// 监听会话切换
watch(() => props.currentSessionId, async (newId) => {
  if (newId) {
    await loadSessionData(newId)
  }
}, { immediate: true })

onMounted(async () => {
  await loadBooks()

  // 监听后端推送的实时思维步骤
  if (window.api?.onThoughtStep) {
    window.api.onThoughtStep((step) => {
      if (step) {
        currentThoughtText.value = step.thought || step.content || '正在考据研读中...'
        activeExecutionTrace.value.push(step)
      }
    })
  }
})

async function loadBooks() {
  if (window.api?.listBooks) {
    const res = await window.api.listBooks()
    if (res.success && Array.isArray(res.data)) {
      books.value = res.data
    }
  }
}

async function loadSessionData(sessionId) {
  if (!window.api?.getSession) return
  try {
    const res = await window.api.getSession(sessionId)
    if (res.success && res.data) {
      const sess = res.data
      messages.value = (sess.messages || []).map(m => ({
        ...m,
        _showTrace: false
      }))
      if (sess.scope) {
        scopeType.value = sess.scope.type || 'global'
        selectedCategory.value = sess.scope.category || null
        selectedBookId.value = sess.scope.bookId || null
      }
      scrollToBottom()
    }
  } catch (err) {
    console.warn('Failed to load session:', err)
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (chatScrollRef.value) {
      chatScrollRef.value.scrollTop = chatScrollRef.value.scrollHeight
    }
  })
}

function handleKeyDown(e) {
  if (e.isComposing || e.keyCode === 229) return
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSubmit()
  }
}

function applyPromptChip(query) {
  inputText.value = query
  handleSubmit()
}

function sendQuickQuestion(q) {
  inputText.value = q
  handleSubmit()
}

async function handleSubmit() {
  const query = inputText.value.trim()
  if (!query || loading.value) return

  const userMsg = {
    role: 'user',
    content: query,
    time: new Date().toISOString()
  }
  messages.value.push(userMsg)
  inputText.value = ''
  loading.value = true
  currentThoughtText.value = '正在检索原典存证...'
  activeExecutionTrace.value = []
  scrollToBottom()

  // 构建当前 Scope
  const currentScope = {
    type: scopeType.value,
    category: scopeType.value === 'category' ? selectedCategory.value : undefined,
    bookId: scopeType.value === 'single_book' ? selectedBookId.value : undefined
  }

  try {
    const history = messages.value.slice(-6).map(m => ({
      role: m.role,
      content: m.content
    }))

    const res = await window.api.askInquiry({
      question: query,
      scope: currentScope,
      sessionId: props.currentSessionId,
      history
    })

    if (res.success && res.data) {
      const d = res.data
      const assistantMsg = {
        role: 'assistant',
        content: d.markdownAnswer,
        computations: d.computations ? formatComputations(d.computations) : [],
        followUps: d.followUps || [],
        evidencePack: d.evidencePack,
        executionTrace: d.executionTrace || activeExecutionTrace.value,
        _showTrace: false,
        time: new Date().toISOString()
      }
      messages.value.push(assistantMsg)
      activeExecutionTrace.value = assistantMsg.executionTrace || []
      emit('session-updated', d.sessionId)
    } else {
      messages.value.push({
        role: 'assistant',
        content: '研读解析出现异常: ' + (res.error || '未知错误'),
        time: new Date().toISOString()
      })
    }
  } catch (err) {
    messages.value.push({
      role: 'assistant',
      content: '网络或服务调用异常: ' + err.message,
      time: new Date().toISOString()
    })
  } finally {
    loading.value = false
    currentThoughtText.value = ''
    scrollToBottom()
  }
}

function formatComputations(comp) {
  const list = []
  if (comp.relevantParagraphs) {
    list.push({ text: `命中核心物理证据: ${comp.relevantParagraphs} 处` })
  }
  if (comp.distinctBooks) {
    list.push({ text: `跨越典籍: ${comp.distinctBooks} 部` })
  }
  return list
}

function renderMarkdown(content) {
  if (!content) return ''
  try {
    return marked.parse(content)
  } catch {
    return content
  }
}

function handleInlineCitationClick(event, evidencePack) {
  const jumpBtn = event.target.closest('.evidence-jump-btn')
  if (jumpBtn) {
    const bookId = jumpBtn.getAttribute('data-book-id')
    const page = parseInt(jumpBtn.getAttribute('data-page')) || 1
    const paragraphId = jumpBtn.getAttribute('data-paragraph-id') || null
    if (bookId) {
      emit('open-parallel-reader', { bookId, page, paragraphId })
      return
    }
  }

  const badge = event.target.closest('.citation-badge')
  if (badge) {
    const citeId = badge.getAttribute('data-cite-id')
    const refItem = evidencePack?.references?.find(r => r.id === citeId || `[${r.printedPage}]` === citeId)
    if (refItem) {
      openParallelForEvidence(refItem)
    }
  }
}

function openSourceDrawer(refItem) {
  activeDrawerEvidence.value = refItem
  showDrawer.value = true
}

function openParallelForEvidence(refItem) {
  emit('open-parallel-reader', {
    bookId: refItem.bookId,
    page: (refItem.pageIndex !== undefined ? refItem.pageIndex + 1 : (parseInt(refItem.printedPage?.replace(/\D/g, '')) || 1)),
    paragraphId: refItem.id || refItem.paragraphId
  })
}

function handleOpenParallelReader() {
  emit('open-parallel-reader', {
    bookId: selectedBookId.value || (books.value[0]?.id) || null,
    page: 1
  })
}

function confirmClearHistory() {
  messages.value = []
  message.info('当前视图历史已清空')
}

function onScopeChange(type) {
  if (type === 'category' && !selectedCategory.value) {
    selectedCategory.value = categoryOptions[0].value
  }
  if (type === 'single_book' && !selectedBookId.value && books.value.length > 0) {
    selectedBookId.value = books.value[0].id
  }
}

function setTargetBook(book) {
  scopeType.value = 'single_book'
  selectedBookId.value = book.id
}

function askDirectQuestion({ question, scope }) {
  if (scope) {
    scopeType.value = scope.type || 'global'
    if (scope.bookId) selectedBookId.value = scope.bookId
    if (scope.category) selectedCategory.value = scope.category
  }
  inputText.value = question
  handleSubmit()
}

defineExpose({
  setTargetBook,
  askDirectQuestion
})
</script>

<style scoped>
.chat-workbench {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  background: #f8fafc;
  overflow: hidden;
}

/* 顶部状态与作用域控制 */
.workbench-header {
  height: 52px;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  flex-shrink: 0;
  z-index: 5;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}

.session-title-box {
  display: flex;
  align-items: center;
  gap: 6px;
}

.title-text {
  font-size: 14px;
  font-weight: 700;
  color: #1e293b;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scope-compact-selector {
  display: flex;
  align-items: center;
}

.scope-prefix-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
  margin-right: 6px;
  white-space: nowrap;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.reader-shortcut-btn {
  font-weight: 600;
}

/* 主视窗分栏 */
.workbench-main-body {
  display: flex;
  flex: 1;
  height: calc(100% - 52px);
  overflow: hidden;
}

.chat-viewport {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  position: relative;
}

.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* Hero 欢迎卡片 */
.hero-welcome-card {
  max-width: 700px;
  margin: 20px auto 0;
  text-align: center;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 32px 28px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.03);
}

.hero-avatar-box {
  position: relative;
  display: inline-block;
  margin-bottom: 12px;
}

.hero-avatar-emoji {
  font-size: 48px;
}

.hero-online-dot {
  position: absolute;
  bottom: 4px;
  right: 2px;
  width: 12px;
  height: 12px;
  background: #10b981;
  border: 2px solid #ffffff;
  border-radius: 50%;
}

.hero-title {
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 8px;
}

.hero-subtitle {
  font-size: 13px;
  line-height: 1.6;
  color: #64748b;
  margin-bottom: 24px;
}

.prompt-chips-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  text-align: left;
}

.prompt-chip-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.prompt-chip-card:hover {
  background: #fffdfa;
  border-color: #f59e0b;
  transform: translateY(-1px);
  box-shadow: 0 4px 10px rgba(245, 158, 11, 0.08);
}

.chip-icon {
  font-size: 20px;
  flex-shrink: 0;
}

.chip-label {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  display: block;
  margin-bottom: 2px;
}

.chip-desc {
  font-size: 12px;
  color: #64748b;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 消息行 */
.message-row {
  display: flex;
  flex-direction: column;
  max-width: 860px;
  width: 100%;
  margin: 0 auto;
}

.message-row.user {
  align-items: flex-end;
}

.user-bubble {
  background: #2563eb;
  color: #ffffff;
  border-radius: 16px 16px 4px 16px;
  padding: 12px 18px;
  max-width: 80%;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.15);
}

.user-header {
  font-size: 11px;
  opacity: 0.8;
  margin-bottom: 4px;
  text-align: right;
}

.user-content {
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.assistant-bubble {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 16px 16px 16px 4px;
  padding: 18px 20px;
  max-width: 90%;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
}

.assistant-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.assistant-avatar {
  font-size: 18px;
}

.assistant-name {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.assistant-badge {
  font-size: 10px;
  background: #ecfdf5;
  color: #059669;
  border: 1px solid #a7f3d0;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.assistant-badge.thinking {
  background: #fef3c7;
  color: #b45309;
  border-color: #fde68a;
}

/* 思维链折叠卡片 */
.trace-fold-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 12px;
}

.trace-fold-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}

.trace-fold-title {
  display: flex;
  align-items: center;
  gap: 6px;
}

.trace-steps-body {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #e2e8f0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.trace-step-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
}

.step-num {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #e2e8f0;
  color: #475569;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  flex-shrink: 0;
}

.step-type-badge {
  font-size: 10px;
  background: #e0e7ff;
  color: #4338ca;
  padding: 1px 4px;
  border-radius: 3px;
  display: inline-block;
  margin-right: 4px;
}

.step-content {
  color: #334155;
  line-height: 1.4;
}

/* Markdown 正文 */
.markdown-body {
  font-size: 14px;
  line-height: 1.7;
  color: #1e293b;
  word-break: break-word;
}

:deep(.evidence-fold-item) {
  margin: 10px 0;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  overflow: hidden;
  transition: all 0.2s ease;
}

:deep(.evidence-fold-item[open]) {
  background: #ffffff;
  border-color: #cbd5e1;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

:deep(.evidence-fold-summary) {
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  font-size: 13px;
  color: #334155;
  outline: none;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

:deep(.evidence-fold-summary:hover) {
  background: #f1f5f9;
}

:deep(.evidence-tag) {
  display: inline-block;
  padding: 1px 6px;
  font-size: 11px;
  font-weight: 600;
  color: #2563eb;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 4px;
}

:deep(.evidence-preview-text) {
  color: #64748b;
  font-size: 12px;
  font-style: italic;
  max-width: 420px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.evidence-fold-item blockquote) {
  margin: 8px 12px;
  padding: 8px 12px;
  border-left: 3px solid #3b82f6;
  background: #f8fafc;
  border-radius: 0 4px 4px 0;
  color: #334155;
  font-size: 13px;
  line-height: 1.6;
}

:deep(.evidence-fold-actions) {
  padding: 0 12px 10px 12px;
}

:deep(.evidence-jump-btn) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  color: #1d4ed8;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

:deep(.evidence-jump-btn:hover) {
  background: #dbeafe;
  border-color: #93c5fd;
  transform: translateY(-1px);
}

.metric-ribbon {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.metric-badge {
  font-size: 11px;
  background: #f1f5f9;
  color: #475569;
  padding: 2px 8px;
  border-radius: 4px;
}

/* 证据卡片栏 */
.evidence-pack-section {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #f1f5f9;
}

.evidence-section-title {
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  margin-bottom: 8px;
}

.evidence-cards-scroll {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
}

.evidence-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.evidence-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.evidence-book-title {
  font-size: 12px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 170px;
}

.evidence-page-tag {
  font-size: 11px;
  font-weight: 700;
  color: #2563eb;
  background: #eff6ff;
  padding: 1px 5px;
  border-radius: 4px;
}

.evidence-card-body {
  font-size: 12px;
  line-height: 1.5;
  color: #475569;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-style: italic;
}

.evidence-card-footer {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}

/* 追问气泡 */
.follow-up-bar {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.follow-title {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}

.follow-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* 思考中 */
.thinking-content {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #64748b;
}

/* 底部输入框 */
.chat-input-bar {
  padding: 12px 24px 16px;
  background: #ffffff;
  border-top: 1px solid #e2e8f0;
  flex-shrink: 0;
}

.input-container {
  max-width: 860px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.message-textarea {
  border-radius: 10px;
}

.input-actions-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.input-scope-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #64748b;
}

.indicator-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
}

.send-btn {
  font-weight: 600;
  padding: 0 20px;
}

/* 右侧思维链轨迹面板 */
.trace-side-panel {
  width: 320px;
  background: #ffffff;
  border-left: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  height: 100%;
}

.trace-panel-header {
  height: 48px;
  padding: 0 16px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.panel-title {
  font-size: 13px;
  font-weight: 700;
  color: #1e293b;
  display: flex;
  align-items: center;
  gap: 6px;
}

.trace-panel-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.empty-trace {
  font-size: 12px;
  color: #94a3b8;
  text-align: center;
  margin-top: 40px;
}

.trace-timeline {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.timeline-step {
  display: flex;
  gap: 10px;
}

.timeline-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #3b82f6;
  margin-top: 5px;
  flex-shrink: 0;
}

.timeline-card {
  flex: 1;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 12px;
}

.timeline-title-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
}

.step-type {
  font-weight: 700;
  color: #1d4ed8;
}

.step-time {
  color: #94a3b8;
  font-size: 11px;
}

.timeline-desc {
  color: #334155;
  line-height: 1.4;
}

.timeline-obs {
  margin-top: 6px;
  padding-top: 4px;
  border-top: 1px dashed #e2e8f0;
  font-size: 11px;
  color: #059669;
}

.obs-tag {
  font-weight: 600;
  margin-right: 4px;
}
</style>
