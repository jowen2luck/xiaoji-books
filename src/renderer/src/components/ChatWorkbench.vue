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
            <template #icon><n-icon size="12"><CreateOutline /></n-icon></template>
          </n-button>
        </div>

        <div class="header-divider"></div>

        <!-- 伴读 Scope 范围切换器 -->
        <div class="scope-compact-selector">
          <span class="scope-prefix-label">范围</span>
          <n-radio-group v-model:value="scopeType" size="tiny" @update:value="onScopeChange">
            <n-radio-button value="global">全库</n-radio-button>
            <n-radio-button value="category">分类</n-radio-button>
            <n-radio-button value="single_book">单书</n-radio-button>
            <n-radio-button value="multi_book">多书</n-radio-button>
          </n-radio-group>

          <n-select
            v-if="scopeType === 'category'"
            v-model:value="selectedCategory"
            :options="categoryOptions"
            placeholder="选择主题学科"
            size="tiny"
            style="width: 150px; margin-left: 6px;"
          />

          <n-select
            v-if="scopeType === 'single_book'"
            v-model:value="selectedBookId"
            :options="bookOptions"
            filterable
            placeholder="选择精读书籍"
            size="tiny"
            style="width: 200px; margin-left: 6px;"
          />

          <n-select
            v-if="scopeType === 'multi_book'"
            v-model:value="selectedBookIds"
            :options="bookOptions"
            filterable
            multiple
            placeholder="勾选多本书籍"
            size="tiny"
            style="width: 240px; margin-left: 6px;"
            :max-tag-count="2"
          />
        </div>
      </div>

      <div class="header-right">
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
              原文对照
            </n-button>
          </template>
          按页并排查看原书影印与提取文字（本工具为页级对应，不支持段落高亮定位）
        </n-tooltip>

        <div class="header-actions">
          <n-tooltip trigger="hover">
            <template #trigger>
              <n-button
                quaternary
                circle
                size="small"
                :type="showTracePanel ? 'primary' : 'default'"
                @click="showTracePanel = !showTracePanel"
              >
                <template #icon><n-icon size="15"><SparklesOutline /></n-icon></template>
              </n-button>
            </template>
            {{ showTracePanel ? '收起思维链' : '展开思维链' }}
          </n-tooltip>

          <n-tooltip trigger="hover">
            <template #trigger>
              <n-button quaternary circle size="small" @click="confirmClearHistory">
                <template #icon><n-icon size="15"><RefreshOutline /></n-icon></template>
              </n-button>
            </template>
            清空当前会话
          </n-tooltip>
        </div>
      </div>
    </div>

    <!-- 主对话体与右侧思维链分栏 -->
    <div class="workbench-main-body">
      <!-- 聊天对话主视窗 -->
      <div class="chat-viewport">
        <div class="messages-container" ref="chatScrollRef">
          <!-- 学术编辑风格欢迎 Hero -->
          <div v-if="messages.length === 0" class="hero-editorial">
            <div class="hero-masthead">
              <div class="hero-mark">
                <span class="hero-mark-char">𓆣</span>
              </div>
              <div class="hero-meta">
                <span class="hero-meta-volume">VOL. 01</span>
                <span class="hero-meta-divider">·</span>
                <span class="hero-meta-date">{{ todayDate }}</span>
              </div>
            </div>
            <h1 class="hero-headline">文献考据与学术研读</h1>
            <p class="hero-standfirst">
              基于不可变原著存证与认知分层模型，为你的学术探索抽丝剥茧、溯源求证。
            </p>

            <div class="hero-divider">
              <span class="divider-ornament">§</span>
            </div>

            <div class="editorial-prompt-grid">
              <div
                v-for="(chip, idx) in promptChips"
                :key="idx"
                class="editorial-prompt-card"
                @click="applyPromptChip(chip.query)"
                :style="{ '--card-delay': idx * 50 + 'ms' }"
              >
                <div class="prompt-card-icon">{{ chip.icon }}</div>
                <div class="prompt-card-body">
                  <span class="prompt-card-label">{{ chip.label }}</span>
                  <span class="prompt-card-desc">{{ chip.query }}</span>
                </div>
                <div class="prompt-card-arrow">→</div>
              </div>
            </div>
          </div>

          <!-- 消息气泡流 -->
          <div v-for="(msg, idx) in messages" :key="idx" class="message-row" :class="msg.role">
            <!-- 用户气泡 -->
            <div v-if="msg.role === 'user'" class="user-bubble">
              <div class="bubble-content user-content">
                {{ msg.content }}
              </div>
            </div>

            <!-- 助手气泡 -->
            <div v-else class="assistant-bubble">
              <div class="bubble-header assistant-header">
                <span class="assistant-avatar">
                  <span class="avatar-char">𓆣</span>
                </span>
                <span class="assistant-name">小鸡书友</span>
                <span class="assistant-verified">不可变溯源</span>
              </div>

              <div class="bubble-content assistant-content">
                <!-- 实时/历史思维链折叠 -->
                <div v-if="msg.executionTrace && msg.executionTrace.length > 0" class="trace-fold-card">
                  <div class="trace-fold-header" @click="msg._showTrace = !msg._showTrace">
                    <span class="trace-fold-title">
                      <n-icon size="13"><SparklesOutline /></n-icon>
                      推理轨迹 · {{ msg.executionTrace.length }} 步
                    </span>
                    <span class="trace-fold-toggle">{{ msg._showTrace ? '收起' : '展开' }}</span>
                  </div>
                  <div v-if="msg._showTrace" class="trace-steps-body">
                    <div v-for="(step, sIdx) in msg.executionTrace" :key="sIdx" class="trace-step-item">
                      <div class="step-marker">{{ sIdx + 1 }}</div>
                      <div class="step-info">
                        <span class="step-type-badge">{{ step.type || '推理' }}</span>
                        <span class="step-content">{{ step.thought || step.message || step.content || step.action }}</span>
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

                <!-- 量化指标 ribbon -->
                <div v-if="msg.computations && msg.computations.length > 0" class="metric-ribbon">
                  <div v-for="c in msg.computations" :key="c.text" class="metric-badge">
                    {{ c.text }}
                  </div>
                </div>

                <!-- 核心事实证据卡片 -->
                <div v-if="msg.evidencePack && ((msg.evidencePack.references && msg.evidencePack.references.length > 0) || (msg.evidencePack.evidence && msg.evidencePack.evidence.length > 0))" class="evidence-pack-section">
                  <div class="evidence-section-header">
                    <span class="evidence-dot"></span>
                    <span>本轮原典依据 · {{ (msg.evidencePack.references || msg.evidencePack.evidence).length }} 处</span>
                  </div>
                  <div class="evidence-card-grid">
                    <div
                      v-for="(refItem, rIdx) in (msg.evidencePack.references || msg.evidencePack.evidence || []).slice(0, 4)"
                      :key="rIdx"
                      class="evidence-card"
                    >
                      <div class="evidence-card-top">
                        <span class="evidence-book-name">《{{ refItem.bookTitle || '文献' }}》</span>
                        <span class="evidence-page-num">{{ refItem.printedPage || `P.${(refItem.pageIndex || 0) + 1}` }}</span>
                      </div>
                      <div class="evidence-card-quote">
                        {{ refItem.snippet || refItem.excerpt || refItem.text || '引文摘录...' }}
                      </div>
                      <div class="evidence-card-actions">
                        <n-button size="tiny" type="primary" secondary @click="openParallelForEvidence(refItem)">
                          原文对照
                        </n-button>
                        <n-button size="tiny" quaternary @click="openSourceDrawer(refItem)">
                          查阅上下文
                        </n-button>
                      </div>
                    </div>
                  </div>
                  <div v-if="(msg.evidencePack.references || msg.evidencePack.evidence || []).length > 4" class="evidence-more">
                    <n-button size="tiny" quaternary @click="showAllEvidence(msg)">
                      还有 {{ (msg.evidencePack.references || msg.evidencePack.evidence).length - 4 }} 处原典依据 ›
                    </n-button>
                  </div>
                </div>

                <!-- 深入研讨追问建议 -->
                <div v-if="msg.followUps && msg.followUps.length > 0" class="follow-up-bar">
                  <span class="follow-title">深入研讨追问</span>
                  <div class="follow-chips">
                    <n-tag
                      v-for="fu in msg.followUps"
                      :key="fu"
                      size="small"
                      round
                      type="warning"
                      clickable
                      class="follow-chip"
                      @click="sendQuickQuestion(fu)"
                    >
                      {{ fu }}
                    </n-tag>
                  </div>
                </div>

                <!-- 消息操作条 -->
                <div class="msg-actions">
                  <n-tooltip trigger="hover">
                    <template #trigger>
                      <n-button quaternary circle size="tiny" @click="copyMessage(msg)">
                        <template #icon><n-icon size="12"><CopyOutline /></n-icon></template>
                      </n-button>
                    </template>
                    复制回答
                  </n-tooltip>
                  <n-tooltip trigger="hover">
                    <template #trigger>
                      <n-button quaternary circle size="tiny" @click="copyCitation(msg)">
                        <template #icon><n-icon size="12"><BookmarkOutline /></n-icon></template>
                      </n-button>
                    </template>
                    复制含引用
                  </n-tooltip>
                  <n-tooltip trigger="hover">
                    <template #trigger>
                      <n-button quaternary circle size="tiny" @click="regenerateLast">
                        <template #icon><n-icon size="12"><RefreshOutline /></n-icon></template>
                      </n-button>
                    </template>
                    重新生成
                  </n-tooltip>
                </div>
              </div>
            </div>
          </div>

          <!-- 助手实时思考状态 -->
          <div v-if="loading" class="assistant-bubble thinking-bubble">
            <div class="bubble-header assistant-header">
              <span class="assistant-avatar thinking">
                <span class="avatar-char pulse">𓆣</span>
              </span>
              <span class="assistant-name">小鸡书友</span>
              <span class="assistant-status">正在考据推理中…</span>
            </div>
            <div class="thinking-content">
              <div class="thinking-dots">
                <span></span><span></span><span></span>
              </div>
              <span class="thinking-text">{{ currentThoughtText || '正在编排学术逻辑与原典锚点...' }}</span>
            </div>
          </div>
        </div>

        <!-- 底部输入操作栏 -->
        <div class="chat-input-bar">
          <div class="input-container">
            <div class="input-scope-hint">
              <span class="scope-dot"></span>
              <span class="scope-label">{{ currentScopeDisplay }}</span>
            </div>
            <div class="input-textarea-wrap">
              <n-input
                v-model:value="inputText"
                type="textarea"
                placeholder="提出关于文献、作者观点或不同流派论述的疑问... (Enter 发送)"
                :autosize="{ minRows: 2, maxRows: 6 }"
                :disabled="loading"
                @keydown="handleKeyDown"
                class="message-textarea"
                textarea-class="custom-textarea"
              />
              <div class="input-bottom-row">
                <span class="input-hint">Shift+Enter 换行</span>
                <n-button
                  type="primary"
                  size="small"
                  :loading="loading"
                  :disabled="!inputText.trim()"
                  @click="handleSubmit"
                  class="send-btn"
                >
                  <template #icon><n-icon><SendOutline /></n-icon></template>
                  发送
                </n-button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧思维链轨迹面板 -->
      <div v-if="showTracePanel" class="trace-side-panel">
        <div class="trace-panel-header">
          <div class="panel-title">
            <n-icon size="15"><SparklesOutline /></n-icon>
            <span>思维链推理全景</span>
          </div>
          <n-button quaternary circle size="tiny" @click="showTracePanel = false">
            <template #icon><n-icon size="12"><CloseOutline /></n-icon></template>
          </n-button>
        </div>
        <div class="trace-panel-content">
          <div v-if="activeExecutionTrace.length === 0" class="empty-trace">
            <div class="empty-icon">◇</div>
            <div class="empty-label">暂无推理轨迹</div>
            <div class="empty-desc">发起提问后，推理步骤将实时呈现于此</div>
          </div>
          <div v-else class="trace-timeline">
            <div v-for="(step, idx) in activeExecutionTrace" :key="idx" class="timeline-step">
              <div class="timeline-connector">
                <div class="timeline-dot">{{ idx + 1 }}</div>
                <div v-if="idx < activeExecutionTrace.length - 1" class="timeline-line"></div>
              </div>
              <div class="timeline-card">
                <div class="timeline-card-header">
                  <span class="step-type-pill">{{ step.type || '推导' }}</span>
                  <span class="step-idx">步骤 {{ idx + 1 }}</span>
                </div>
                <div class="timeline-desc">{{ step.thought || step.message || step.content || step.action }}</div>
                <div v-if="step.observation" class="timeline-obs">
                  <span class="obs-label">观察：</span>{{ step.observation }}
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
import { useMessage, useDialog } from 'naive-ui'
import { marked } from 'marked'
import {
  CreateOutline,
  BookOutline,
  SparklesOutline,
  RefreshOutline,
  SendOutline,
  CloseOutline,
  CopyOutline,
  BookmarkOutline
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
const dialog = useDialog()

// 状态
const messages = ref([])
const inputText = ref('')
const loading = ref(false)
const currentThoughtText = ref('')
const chatScrollRef = ref(null)

const scopeType = ref('global')
const selectedCategory = ref(null)
const selectedBookId = ref(null)
const selectedBookIds = ref([])

const books = ref([])
const showTracePanel = ref(false)
const activeExecutionTrace = ref([])

// 抽屉
const showDrawer = ref(false)
const activeDrawerEvidence = ref(null)

// 欢迎卡片推荐提示词
const promptChips = ref([
  {
    icon: '⚐',
    label: '国际歌与巴黎公社',
    query: '请结合馆藏史料，分析《国际歌》创作的历史背景以及巴黎公社在文献中的核心论述。'
  },
  {
    icon: '⛰',
    label: '《国家与革命》论析',
    query: '《国家与革命》的核心要义是什么？列宁是如何论述国家消亡与无产阶级专政的？'
  },
  {
    icon: '⚖',
    label: '学术流派观点对比',
    query: '对比布哈林与普列汉诺夫在唯物史观与经济政策上的学术分歧与代表性引文。'
  },
  {
    icon: '◈',
    label: '无产阶级专政考据',
    query: '跨文献检索马克思、恩格斯、列宁对"无产阶级专政"概念的定义与原文论据。'
  }
])

// 格式化日期
const todayDate = computed(() => {
  const d = new Date()
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')}`
})

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
  if (scopeType.value === 'global') return `全库 ${books.value.length} 本馆藏 · 宏观探索`
  if (scopeType.value === 'category') return `分类：${selectedCategory.value || '未选择'}`
  if (scopeType.value === 'multi_book') return `多书：已选 ${selectedBookIds.value.length} 本`
  const b = books.value.find(item => item.id === selectedBookId.value)
  return `单书：${b ? `《${b.title}》` : '未选择'}`
})

// 监听会话切换
watch(() => props.currentSessionId, async (newId) => {
  if (newId) {
    await loadSessionData(newId)
  }
}, { immediate: true })

onMounted(async () => {
  await loadBooks()

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
        selectedCategory.value = sess.scope.categories?.[0] || sess.scope.category || null
        selectedBookId.value = sess.scope.bookIds?.[0] || sess.scope.bookId || null
        selectedBookIds.value = sess.scope.bookIds || (sess.scope.bookId ? [sess.scope.bookId] : [])
      }
      scrollToBottom()
    }
  } catch (err) {
    console.warn('Failed to load session:', err)
  }
}

function scrollToBottom(force = false) {
  nextTick(() => {
    if (chatScrollRef.value) {
      const el = chatScrollRef.value
      const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
      if (force || distFromBottom < 80) {
        el.scrollTop = el.scrollHeight
      }
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

  const currentScope = (() => {
    const t = scopeType.value
    if (t === 'multi_book') {
      return { type: 'multi_book', bookIds: [...selectedBookIds.value] }
    }
    return {
      type: t,
      category: t === 'category' ? selectedCategory.value : undefined,
      bookId: t === 'single_book' ? selectedBookId.value : undefined
    }
  })()

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
    list.push({ text: `命中核心证据 ${comp.relevantParagraphs} 处` })
  }
  if (comp.distinctBooks) {
    list.push({ text: `跨越典籍 ${comp.distinctBooks} 部` })
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

function showAllEvidence(msg) {
  const allRefs = msg.evidencePack?.references || msg.evidencePack?.evidence || []
  activeDrawerEvidence.value = allRefs[0] || null
  showDrawer.value = true
  // TODO: 未来可在 SourceDrawer 中展示全部证据列表
}

function copyMessage(msg) {
  navigator.clipboard.writeText(msg.content)
  message.success('已复制回答')
}

function copyCitation(msg) {
  const refs = msg.evidencePack?.references || msg.evidencePack?.evidence || []
  const citations = refs.map(r => `《${r.bookTitle || '文献'}》${r.printedPage || 'p.' + ((r.pageIndex || 0) + 1)}`).join('; ')
  const text = citations ? `${msg.content}\n\n引用：${citations}` : msg.content
  navigator.clipboard.writeText(text)
  message.success('已复制回答含引用')
}

function regenerateLast() {
  const lastUserMsg = [...messages.value].reverse().find(m => m.role === 'user')
  if (lastUserMsg) {
    inputText.value = lastUserMsg.content
    handleSubmit()
  }
}

function openParallelForEvidence(refItem) {
  emit('open-parallel-reader', {
    bookId: refItem.bookId,
    page: (refItem.pageIndex !== undefined ? refItem.pageIndex + 1 : 1),
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
  dialog.warning({
    title: '清空会话',
    content: `确定清空当前视图的 ${messages.value.length} 条消息吗？此操作不可恢复。`,
    positiveText: '清空',
    negativeText: '取消',
    onPositiveClick: () => {
      messages.value = []
      message.info('当前视图历史已清空')
    }
  })
}

function onScopeChange(type) {
  if (type === 'category' && !selectedCategory.value) {
    selectedCategory.value = categoryOptions[0].value
  }
  if (type === 'single_book' && !selectedBookId.value && books.value.length > 0) {
    selectedBookId.value = books.value[0].id
  }
  if (type === 'multi_book' && selectedBookIds.value.length === 0 && books.value.length > 0) {
    selectedBookIds.value = books.value.slice(0, 3).map(b => b.id)
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
  background: var(--color-bg);
  overflow: hidden;
}

/* ==================== 顶部状态栏 ==================== */
.workbench-header {
  height: var(--h-topbar);
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
  flex-shrink: 0;
  z-index: 5;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
}

.session-title-box {
  display: flex;
  align-items: center;
  gap: 6px;
}

.title-text {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 600;
  color: var(--color-ink);
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-divider {
  width: 1px;
  height: 20px;
  background: var(--color-border);
}

.scope-compact-selector {
  display: flex;
  align-items: center;
}

.scope-prefix-label {
  font-size: 11px;
  color: var(--color-ink-muted);
  font-weight: 500;
  margin-right: 4px;
  letter-spacing: 0.5px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.reader-shortcut-btn {
  font-weight: 500;
  border-radius: var(--radius-md) !important;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* ==================== 主视窗分栏 ==================== */
.workbench-main-body {
  display: flex;
  flex: 1;
  min-height: 0;
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
  padding: 0 0 20px;
  display: flex;
  flex-direction: column;
  gap: 0;
}

/* ==================== 编辑式欢迎 Hero ==================== */
.hero-editorial {
  max-width: var(--w-content-max);
  margin: 32px auto 20px;
  padding: 40px 44px 36px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  position: relative;
  overflow: hidden;
}

.hero-editorial::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, #b45309, #d97706, #f59e0b);
}

.hero-masthead {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 28px;
}

.hero-mark {
  width: 44px;
  height: 44px;
  border: 1.5px solid var(--color-accent);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.hero-mark-char {
  font-size: 22px;
  color: var(--color-accent);
}

.hero-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-ink-faint);
  font-family: var(--font-mono);
}

.hero-meta-divider {
  color: var(--color-border-deep);
}

.hero-headline {
  font-family: var(--font-display);
  font-size: 26px;
  font-weight: 700;
  color: var(--color-ink);
  margin: 0 0 10px 0;
  line-height: 1.3;
}

.hero-standfirst {
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-ink-muted);
  margin: 0;
  max-width: 480px;
}

.hero-divider {
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 28px 0 24px;
  position: relative;
}

.hero-divider::before,
.hero-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--color-border);
}

.divider-ornament {
  padding: 0 14px;
  font-size: 16px;
  color: var(--color-accent);
  font-family: var(--font-display);
  font-weight: 600;
}

.editorial-prompt-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.editorial-prompt-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all 0.2s ease;
  animation: card-appear 0.5s ease backwards;
  animation-delay: var(--card-delay);
}

@keyframes card-appear {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.editorial-prompt-card:hover {
  background: var(--color-surface-raised);
  border-color: var(--color-accent);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.prompt-card-icon {
  font-size: 18px;
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--color-accent-soft);
  display: flex;
  align-items: center;
  justify-content: center;
}

.prompt-card-body {
  flex: 1;
  min-width: 0;
}

.prompt-card-label {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--color-ink);
  display: block;
  line-height: 1.3;
}

.prompt-card-desc {
  font-size: 11px;
  color: var(--color-ink-muted);
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-top: 2px;
  line-height: 1.4;
}

.prompt-card-arrow {
  font-size: 14px;
  color: var(--color-ink-faint);
  transition: color 0.15s, transform 0.15s;
}

.editorial-prompt-card:hover .prompt-card-arrow {
  color: var(--color-accent);
  transform: translateX(2px);
}

/* ==================== 消息气泡 ==================== */
.message-row {
  display: flex;
  flex-direction: column;
  padding: 0 24px;
  margin-top: 18px;
  max-width: var(--w-content-max);
  margin-left: auto;
  margin-right: auto;
  width: 100%;
}

.message-row.user {
  align-items: flex-end;
}

/* 用户气泡 */
.user-bubble {
  background: linear-gradient(135deg, #92400e, #b45309);
  color: #ffffff;
  border-radius: 18px 18px 4px 18px;
  padding: 12px 18px;
  max-width: 75%;
  box-shadow: 0 2px 8px rgba(146, 64, 14, 0.15);
  position: relative;
}

.user-content {
  font-size: 14px;
  line-height: 1.65;
  letter-spacing: 0.2px;
}

/* 助手气泡 */
.assistant-bubble {
  background: transparent;
  border: none;
  padding: 0;
  max-width: 90%;
  border-radius: 0;
  box-shadow: none;
}

.assistant-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.assistant-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, #fef3c7, #fde68a);
  border: 1.5px solid #f59e0b;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.avatar-char {
  font-size: 13px;
  color: #92400e;
}

.avatar-char.pulse {
  animation: gentle-pulse 1.5s ease-in-out infinite;
}

@keyframes gentle-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

.assistant-name {
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 600;
  color: var(--color-ink);
}

.assistant-verified {
  font-size: 10px;
  color: var(--color-success);
  background: var(--color-success-soft);
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
  letter-spacing: 0.3px;
}

.assistant-status {
  font-size: 11px;
  color: var(--color-accent);
  font-weight: 400;
}

/* 助手正文内容 */
.assistant-content {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  border-top-left-radius: 4px;
  box-shadow: var(--shadow-sm);
}

/* 思维链折叠 */
.trace-fold-card {
  background: var(--color-bg-warm);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 8px 12px;
  margin-bottom: 14px;
}

.trace-fold-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;
}

.trace-fold-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-ink-muted);
  display: flex;
  align-items: center;
  gap: 6px;
}

.trace-fold-toggle {
  font-size: 11px;
  color: var(--color-accent);
  font-weight: 500;
}

.trace-steps-body {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--color-border-deep);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.trace-step-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.step-marker {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--color-surface);
  border: 1px solid var(--color-border-deep);
  color: var(--color-ink-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 600;
  flex-shrink: 0;
  margin-top: 1px;
}

.step-info {
  flex: 1;
  font-size: 12px;
  line-height: 1.5;
  color: var(--color-ink-soft);
}

.step-type-badge {
  font-size: 12px;
  color: var(--color-info);
  background: var(--color-info-soft);
  padding: 0 4px;
  border-radius: 3px;
  font-weight: 600;
  margin-right: 4px;
}

/* Markdown 正文 */
.markdown-body {
  font-size: 14px;
  line-height: 1.8;
  color: var(--color-ink);
  word-break: break-word;
}

/* 量化指标 */
.metric-ribbon {
  display: flex;
  gap: 8px;
  margin-top: 14px;
}

.metric-badge {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-ink-muted);
  background: var(--color-bg-warm);
  padding: 3px 10px;
  border-radius: var(--radius-sm);
  letter-spacing: 0.3px;
}

/* 证据卡片区 */
.evidence-pack-section {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--color-border);
}

.evidence-section-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 600;
  color: var(--color-ink-muted);
  margin-bottom: 10px;
}

.evidence-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-accent);
  flex-shrink: 0;
}

.evidence-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 8px;
}

.evidence-more {
  margin-top: 8px;
  text-align: center;
}

.msg-actions {
  display: flex;
  gap: 4px;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--color-border);
  opacity: 0;
  transition: opacity 0.15s;
}

.assistant-bubble:hover .msg-actions,
.msg-actions:focus-within {
  opacity: 1;
}

.evidence-card {
  background: var(--color-accent-soft);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: border-color 0.15s;
}

.evidence-card:hover {
  border-color: var(--color-accent-light);
}

.evidence-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.evidence-book-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 150px;
}

.evidence-page-num {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 500;
  color: var(--color-info);
  background: var(--color-info-soft);
  padding: 1px 6px;
  border-radius: 3px;
}

.evidence-card-quote {
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-ink-muted);
  font-style: italic;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.evidence-card-actions {
  display: flex;
  gap: 6px;
  margin-top: 2px;
}

/* 追问引导 */
.follow-up-bar {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.follow-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-ink-muted);
}

.follow-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.follow-chip {
  cursor: pointer !important;
  border: 1px solid var(--color-border) !important;
  transition: all 0.15s !important;
}

.follow-chip:hover {
  border-color: #f59e0b !important;
  background: #fffbeb !important;
}

/* 思考中 */
.thinking-bubble .assistant-content {
  display: flex;
  align-items: center;
  background: var(--color-accent-soft);
  border-color: #fde68a;
}

.thinking-content {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  color: var(--color-ink-muted);
}

.thinking-dots {
  display: flex;
  gap: 3px;
}

.thinking-dots span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-accent);
  animation: dot-bounce 1.4s ease-in-out infinite;
}

.thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
.thinking-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes dot-bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

.thinking-text {
  font-style: italic;
}

/* ==================== 底部输入栏 ==================== */
.chat-input-bar {
  padding: 12px 24px 16px;
  background: var(--color-surface);
  border-top: 1px solid var(--color-border);
  flex-shrink: 0;
}

.input-container {
  max-width: 860px;
  margin: 0 auto;
}

.input-scope-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.scope-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-success);
}

.scope-label {
  font-size: 11px;
  color: var(--color-ink-muted);
  font-weight: 400;
}

.input-textarea-wrap {
  background: var(--color-bg);
  border: 1.5px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: border-color 0.2s;
}

.input-textarea-wrap:focus-within {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px rgba(180, 83, 9, 0.08);
}

.input-bottom-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  border-top: 1px solid var(--color-border);
  background: var(--color-surface);
}

.input-hint {
  font-size: 10px;
  color: var(--color-ink-faint);
}

.send-btn {
  font-weight: 500 !important;
  border-radius: var(--radius-md) !important;
  letter-spacing: 0.3px;
}

/* ==================== 右侧思维链面板 ==================== */
.trace-side-panel {
  width: 300px;
  background: var(--color-surface);
  border-left: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  height: 100%;
}

.trace-panel-header {
  height: 44px;
  padding: 0 14px;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.panel-title {
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 600;
  color: var(--color-ink);
  display: flex;
  align-items: center;
  gap: 6px;
}

.trace-panel-content {
  flex: 1;
  overflow-y: auto;
  padding: 14px;
}

.empty-trace {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding-top: 60px;
  gap: 10px;
}

.empty-icon {
  font-size: 24px;
  color: var(--color-border-deep);
}

.empty-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-ink-muted);
}

.empty-desc {
  font-size: 11px;
  color: var(--color-ink-faint);
  line-height: 1.5;
}

.trace-timeline {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.timeline-step {
  display: flex;
  gap: 10px;
}

.timeline-connector {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 20px;
  flex-shrink: 0;
}

.timeline-dot {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--color-surface);
  border: 1.5px solid var(--color-accent);
  color: var(--color-accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 600;
  z-index: 1;
}

.timeline-line {
  width: 1px;
  flex: 1;
  background: var(--color-border);
  margin: 2px 0;
}

.timeline-card {
  flex: 1;
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  margin-bottom: 10px;
  font-size: 12px;
}

.timeline-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.step-type-pill {
  font-size: 10px;
  font-weight: 600;
  color: var(--color-accent);
  background: var(--color-accent-warm);
  padding: 1px 6px;
  border-radius: 3px;
}

.step-idx {
  font-size: 10px;
  color: var(--color-ink-faint);
}

.timeline-desc {
  color: var(--color-ink-soft);
  line-height: 1.55;
}

.timeline-obs {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--color-border);
  font-size: 11px;
  color: var(--color-success);
}

.obs-label {
  font-weight: 600;
}
</style>
