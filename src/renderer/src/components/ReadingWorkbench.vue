<template>
  <div class="workbench-layout">
    <!-- 顶部 Scope 范围设定卡片 -->
    <div class="scope-header">
      <div class="scope-mode-selector">
        <span class="scope-label">🎯 伴读作用域 (Scope)：</span>
        <n-radio-group v-model:value="scopeType" size="small" @update:value="onScopeTypeChange">
          <n-radio-button value="global">全库宏观探索</n-radio-button>
          <n-radio-button value="category">按分类主题</n-radio-button>
          <n-radio-button value="single_book">指定单书精读</n-radio-button>
        </n-radio-group>
      </div>

      <div class="scope-target-picker">
        <n-select
          v-if="scopeType === 'category'"
          v-model:value="selectedCategory"
          :options="categoryOptions"
          placeholder="选择关注的主题领域"
          size="small"
          style="width: 220px;"
        />
        <n-select
          v-if="scopeType === 'single_book'"
          v-model:value="selectedBookId"
          :options="bookOptions"
          filterable
          placeholder="选择精读的具体书目"
          size="small"
          style="width: 280px;"
        />
      </div>
    </div>

    <!-- 主体区域：左侧问答主区 + 右侧可收放思维链面板 -->
    <div class="workbench-body">
      <!-- 左侧对话与输入主区 -->
      <div class="chat-section">
        <div class="chat-container" ref="chatScrollRef">
          <!-- 欢迎卡片 -->
          <div v-if="messages.length === 0" class="welcome-card">
            <h2>📚 欢迎使用图书伴读助手</h2>
            <p>基于不可变原著存证与认识论四层分层模型，支持单书精读、分类对比、证据溯源与学术批判解读。</p>
            
            <div class="quick-prompts">
              <span style="font-weight: 500; font-size: 13px; color: #4a5568;">💡 点击快捷开启伴读研讨：</span>
              <div class="prompt-chips">
                <n-tag
                  v-for="p in quickPrompts"
                  :key="p"
                  clickable
                  type="info"
                  @click="askQuick(p)"
                >
                  {{ p }}
                </n-tag>
              </div>
            </div>
          </div>

          <!-- 消息气泡流 -->
          <div v-for="(msg, idx) in messages" :key="idx" class="message-wrapper">
            <!-- 用户气泡 -->
            <div v-if="msg.role === 'user'" class="user-bubble">
              <div class="bubble-content">{{ msg.content }}</div>
            </div>

            <!-- 助手气泡 -->
            <div v-else class="assistant-bubble">
              <!-- 正文回答 -->
              <div class="markdown-body" v-html="renderMarkdown(msg.content)" @click="handleMarkdownClick($event, msg.evidencePack)"></div>

              <!-- 认识论定量计算指标卡片 -->
              <div v-if="msg.computations && msg.computations.length > 0" class="metric-ribbon">
                <div v-for="c in msg.computations" :key="c.text" class="metric-badge">
                  📊 {{ c.text }}
                </div>
              </div>

              <!-- 追问引导气泡 -->
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
                    @click="askQuick(fu)"
                  >
                    {{ fu }}
                  </n-tag>
                </div>
              </div>

              <!-- 查看思维链按钮 -->
              <div v-if="msg.executionTrace && msg.executionTrace.length > 0" class="msg-trace-footer">
                <n-button text size="tiny" type="primary" @click="viewMessageTrace(msg)">
                  🧠 查看本轮思维链轨迹 (共 {{ msg.executionTrace.length }} 步)
                </n-button>
              </div>
            </div>
          </div>

          <!-- 加载思考中 -->
          <div v-if="loading" class="assistant-bubble thinking-bubble">
            <n-spin size="small" />
            <span style="margin-left: 10px; color: #4a5568;">
              正在跨章节检索原著物理证据并执行认识论合成...
            </span>
          </div>
        </div>

        <!-- 底部输入栏 -->
        <div class="input-bar">
          <n-input
            v-model:value="inputText"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 4 }"
            placeholder="提出关于指定书目或主题的问题（支持回车发送，Shift+Enter换行）..."
            @keydown.enter.prevent="handleEnter"
          />
          <n-button type="primary" :loading="loading" :disabled="!inputText.trim()" @click="submitQuestion">
            🚀 发送
          </n-button>
        </div>
      </div>

      <!-- 右侧可收放思维链侧边栏 (Chain of Thought Sidebar) -->
      <div class="thought-sidebar" :class="{ 'is-collapsed': isThoughtCollapsed }">
        <!-- 折叠状态下的垂直快捷条 -->
        <div
          v-if="isThoughtCollapsed"
          class="collapsed-bar"
          @click="isThoughtCollapsed = false"
          title="点击展开思维链面板"
        >
          <div class="expand-btn">◀</div>
          <div class="collapsed-title">
            <span>🧠</span>
            <span>思</span>
            <span>维</span>
            <span>链</span>
          </div>
          <div v-if="thoughtSteps.length > 0" class="collapsed-count" :title="`当前追踪到 ${thoughtSteps.length} 个步骤`">
            {{ thoughtSteps.length }}
          </div>
        </div>

        <!-- 展开状态下的完整思维链追踪面板 -->
        <div v-else class="expanded-panel">
          <!-- 头部标题与控制按钮 -->
          <div class="thought-header">
            <div class="thought-header-left">
              <span class="thought-icon">🧠</span>
              <span class="thought-title">智能体思维链</span>
              <span v-if="loading" class="thought-status-badge running">推理中</span>
              <span v-else-if="thoughtSteps.length > 0" class="thought-status-badge ready">已就绪</span>
            </div>
            <div class="thought-header-right">
              <n-button quaternary circle size="tiny" title="清空当前轨迹" @click="clearTrace" :disabled="loading">
                <template #icon>🧹</template>
              </n-button>
              <n-button quaternary circle size="tiny" title="收起面板" @click="isThoughtCollapsed = true">
                <template #icon>▶</template>
              </n-button>
            </div>
          </div>

          <!-- 当前追踪的提问摘要 -->
          <div v-if="activeQuerySnippet" class="thought-query-snippet">
            <span class="snippet-label">追踪命题：</span>
            <span class="snippet-text">{{ activeQuerySnippet }}</span>
          </div>

          <!-- 步骤时间线容器 -->
          <div class="thought-timeline" ref="thoughtScrollRef">
            <div v-if="thoughtSteps.length === 0" class="empty-trace">
              <div class="empty-icon">💡</div>
              <div class="empty-text">暂无思维链轨迹</div>
              <div class="empty-hint">
                发起提问后，智能体的意图分诊、工具调度（FTS检索/大纲/书评）与认识论推理将实时呈现在此。
              </div>
            </div>

            <div v-else class="steps-list">
              <div
                v-for="(step, sIdx) in thoughtSteps"
                :key="sIdx"
                class="step-item"
                :class="step.type"
              >
                <!-- 节点标记与连接线 -->
                <div class="step-connector">
                  <div class="step-dot" :class="step.type">
                    <span v-if="step.type === 'thought'">💭</span>
                    <span v-else-if="step.type === 'action'">🛠️</span>
                    <span v-else-if="step.type === 'observation'">👁️</span>
                    <span v-else-if="step.type === 'synthesize'">💡</span>
                    <span v-else>📍</span>
                  </div>
                  <div v-if="sIdx < thoughtSteps.length - 1" class="step-line"></div>
                </div>

                <!-- 步骤详细内容卡片 -->
                <div class="step-card">
                  <div class="step-meta">
                    <span class="step-type-name" :class="step.type">{{ getStepTypeName(step.type) }}</span>
                    <span class="step-time">{{ step.time }}</span>
                  </div>
                  <div v-if="step.tool" class="step-tool-badge">
                    <code>{{ step.tool }}</code>
                  </div>
                  <div class="step-message">{{ step.message }}</div>
                </div>
              </div>

              <!-- 正在运行脉冲提示 -->
              <div v-if="loading" class="step-item running-pulse">
                <div class="step-connector">
                  <div class="step-dot pulse-dot">⏳</div>
                </div>
                <div class="step-card running-card">
                  <span class="pulse-text">智能体正在探索原著证据并编排决策...</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 侧边原文证据与伴读抽屉 -->
    <SourceDrawer ref="sourceDrawerRef" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useMessage } from 'naive-ui'
import { marked } from 'marked'
import SourceDrawer from './SourceDrawer.vue'
import { DEFAULT_CATEGORIES } from '../../../main/domain/TagTaxonomy.js'

const props = defineProps({
  initialBook: { type: Object, default: null }
})

const message = useMessage()
const sourceDrawerRef = ref(null)
const chatScrollRef = ref(null)
const thoughtScrollRef = ref(null)

const scopeType = ref('global')
const selectedCategory = ref(null)
const selectedBookId = ref(null)
const books = ref([])
const loading = ref(false)
const inputText = ref('')
const messages = ref([])

// 思维链状态追踪
const isThoughtCollapsed = ref(false)
const thoughtSteps = ref([])
const activeQuerySnippet = ref('')
let unsubscribeThought = null

const categoryOptions = DEFAULT_CATEGORIES.map(c => ({ label: c.name, value: c.name }))
const bookOptions = computed(() => books.value.map(b => ({ label: `《${b.title}》`, value: b.id })))

const quickPrompts = [
  '结合《国际歌与巴黎公社》，公社采取了哪些具有里程碑意义的制度？',
  '鲍狄埃的诗歌创作在国际工人运动中起到了怎样的思想动员作用？',
  '布哈林在经济过渡时期提出了哪些关键理论假设？',
  '对比巴黎公社文献与十月革命史料，在国家政权建设上的异同？'
]

function getStepTypeName(type) {
  switch (type) {
    case 'thought': return '意图与推理'
    case 'action': return '工具调用'
    case 'observation': return '事实观察'
    case 'synthesize': return '认识论合成'
    default: return '智能体步骤'
  }
}

async function loadBooks() {
  if (window.api?.listBooks) {
    const res = await window.api.listBooks()
    if (res.success) {
      books.value = res.data
    }
  }
}

function onScopeTypeChange() {
  if (scopeType.value === 'category' && !selectedCategory.value) {
    selectedCategory.value = categoryOptions[0]?.value
  }
  if (scopeType.value === 'single_book' && !selectedBookId.value) {
    selectedBookId.value = books.value[0]?.id
  }
}

function askQuick(promptText) {
  inputText.value = promptText
  submitQuestion()
}

function handleEnter(e) {
  if (!e.shiftKey) {
    submitQuestion()
  }
}

function clearTrace() {
  thoughtSteps.value = []
  activeQuerySnippet.value = ''
}

function viewMessageTrace(msg) {
  if (msg.executionTrace && msg.executionTrace.length > 0) {
    thoughtSteps.value = [...msg.executionTrace]
    activeQuerySnippet.value = msg.query || '历史问答'
    isThoughtCollapsed.value = false
    scrollThoughtToBottom()
  }
}

async function submitQuestion() {
  const q = inputText.value.trim()
  if (!q || loading.value) return

  // 组装 Scope
  const currentScope = { type: scopeType.value }
  if (scopeType.value === 'single_book' && selectedBookId.value) {
    currentScope.bookIds = [selectedBookId.value]
  } else if (scopeType.value === 'category' && selectedCategory.value) {
    currentScope.categories = [selectedCategory.value]
  }

  messages.value.push({ role: 'user', content: q })
  inputText.value = ''
  loading.value = true

  // 重置并激活本轮思维链
  thoughtSteps.value = []
  activeQuerySnippet.value = q
  scrollToBottom()
  scrollThoughtToBottom()

  try {
    if (window.api?.askInquiry) {
      const historyPayload = messages.value.slice(0, -1).map(m => ({ role: m.role, content: m.content }))
      const res = await window.api.askInquiry({ question: q, scope: currentScope, history: historyPayload })
      if (res.success && res.data) {
        const trace = (res.data.executionTrace && res.data.executionTrace.length > 0)
          ? res.data.executionTrace
          : [...thoughtSteps.value]

        messages.value.push({
          role: 'assistant',
          query: q,
          content: res.data.markdownAnswer,
          computations: res.data.computations,
          followUps: res.data.followUps,
          evidencePack: res.data.evidencePack,
          executionTrace: trace
        })

        thoughtSteps.value = trace
      } else {
        message.error('提问失败: ' + (res.error || '未知错误'))
      }
    }
  } catch (err) {
    message.error('请求异常: ' + err.message)
  } finally {
    loading.value = false
    scrollToBottom()
    scrollThoughtToBottom()
  }
}

function renderMarkdown(md) {
  if (!md) return ''
  return marked.parse(md)
}

function handleMarkdownClick(event, evidencePack) {
  if (!evidencePack || !evidencePack.evidence) return
  const targetText = event.target.innerText || ''
  if (targetText.includes('原文抽屉') || targetText.includes('证据 [') || targetText.includes('🔖')) {
    sourceDrawerRef.value?.open(evidencePack.evidence[0])
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (chatScrollRef.value) {
      chatScrollRef.value.scrollTop = chatScrollRef.value.scrollHeight
    }
  })
}

function scrollThoughtToBottom() {
  nextTick(() => {
    if (thoughtScrollRef.value) {
      thoughtScrollRef.value.scrollTop = thoughtScrollRef.value.scrollHeight
    }
  })
}

function setTargetBook(book) {
  scopeType.value = 'single_book'
  selectedBookId.value = book.id
  inputText.value = `解读《${book.title}》的核心思想与章节结构`
}

defineExpose({ setTargetBook })

onMounted(() => {
  loadBooks()
  if (props.initialBook) {
    setTargetBook(props.initialBook)
  }

  // 监听后端推流的实时思维链步骤
  if (window.api?.onThoughtStep) {
    unsubscribeThought = window.api.onThoughtStep((step) => {
      thoughtSteps.value.push(step)
      scrollThoughtToBottom()
    })
  }
})

onUnmounted(() => {
  if (unsubscribeThought) {
    unsubscribeThought()
  }
})
</script>

<style scoped>
.workbench-layout {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #f7f9fa;
  overflow: hidden;
}

.scope-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}

.scope-mode-selector {
  display: flex;
  align-items: center;
  gap: 8px;
}

.scope-label {
  font-size: 13px;
  font-weight: 500;
  color: #4a5568;
}

.workbench-body {
  display: flex;
  flex: 1;
  overflow: hidden;
  position: relative;
}

.chat-section {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  height: 100%;
}

.chat-container {
  flex: 1;
  overflow-y: auto;
  padding: 24px 32px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.welcome-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 10px;
}

.welcome-card h2 {
  margin: 0 0 8px 0;
  font-size: 18px;
  color: #1a202c;
}

.welcome-card p {
  margin: 0 0 16px 0;
  font-size: 14px;
  color: #718096;
}

.prompt-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.message-wrapper {
  display: flex;
  flex-direction: column;
}

.user-bubble {
  align-self: flex-end;
  background: #3182ce;
  color: #ffffff;
  padding: 10px 16px;
  border-radius: 12px 12px 2px 12px;
  max-width: 75%;
  font-size: 14px;
  line-height: 1.5;
}

.assistant-bubble {
  align-self: flex-start;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px 12px 12px 2px;
  padding: 20px;
  max-width: 85%;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.03);
}

.thinking-bubble {
  display: flex;
  align-items: center;
}

.markdown-body {
  font-size: 14px;
  line-height: 1.7;
  color: #2d3748;
}

.metric-ribbon {
  display: flex;
  gap: 8px;
  margin-top: 14px;
  flex-wrap: wrap;
}

.metric-badge {
  background: #edf2f7;
  color: #4a5568;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 6px;
}

.follow-up-bar {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px dashed #e2e8f0;
}

.follow-title {
  font-size: 12px;
  color: #718096;
  font-weight: 500;
}

.follow-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.msg-trace-footer {
  margin-top: 12px;
  padding-top: 8px;
  border-top: 1px dashed #edf2f7;
  display: flex;
  justify-content: flex-end;
}

.input-bar {
  display: flex;
  gap: 12px;
  padding: 16px 24px;
  background: #ffffff;
  border-top: 1px solid #e2e8f0;
  flex-shrink: 0;
}

/* ========================================= */
/* 右侧可折叠思维链侧边栏 (Thought Sidebar) */
/* ========================================= */
.thought-sidebar {
  width: 320px;
  background: #ffffff;
  border-left: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  transition: width 0.22s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  height: 100%;
  flex-shrink: 0;
}

.thought-sidebar.is-collapsed {
  width: 38px;
  cursor: pointer;
  background: #f8fafc;
}

.thought-sidebar.is-collapsed:hover {
  background: #edf2f7;
}

/* 折叠状态栏 */
.collapsed-bar {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 14px;
  gap: 14px;
  height: 100%;
  user-select: none;
}

.expand-btn {
  font-size: 12px;
  color: #718096;
}

.collapsed-title {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  color: #4a5568;
  writing-mode: vertical-rl;
  letter-spacing: 2px;
}

.collapsed-count {
  background: #3182ce;
  color: #ffffff;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 8px;
}

/* 展开状态面板 */
.expanded-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 320px;
}

.thought-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 14px;
  border-bottom: 1px solid #edf2f7;
  background: #ffffff;
  flex-shrink: 0;
}

.thought-header-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.thought-icon {
  font-size: 15px;
}

.thought-title {
  font-size: 13px;
  font-weight: 600;
  color: #2d3748;
}

.thought-status-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 8px;
  font-weight: 600;
}

.thought-status-badge.running {
  background: #feebc8;
  color: #c05621;
  animation: pulse-glow 1.5s infinite;
}

.thought-status-badge.ready {
  background: #c6f6d5;
  color: #22543d;
}

@keyframes pulse-glow {
  0% { opacity: 1; }
  50% { opacity: 0.5; }
  100% { opacity: 1; }
}

.thought-query-snippet {
  padding: 7px 12px;
  background: #f7fafc;
  border-bottom: 1px dashed #e2e8f0;
  font-size: 11px;
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.snippet-label {
  color: #a0aec0;
  flex-shrink: 0;
}

.snippet-text {
  color: #4a5568;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.thought-timeline {
  flex: 1;
  overflow-y: auto;
  padding: 14px 12px;
}

.empty-trace {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 240px;
  text-align: center;
  padding: 0 14px;
}

.empty-icon {
  font-size: 28px;
  margin-bottom: 8px;
  opacity: 0.6;
}

.empty-text {
  font-size: 13px;
  font-weight: 600;
  color: #718096;
  margin-bottom: 6px;
}

.empty-hint {
  font-size: 11px;
  color: #a0aec0;
  line-height: 1.5;
}

.steps-list {
  display: flex;
  flex-direction: column;
}

.step-item {
  display: flex;
  gap: 10px;
  position: relative;
  padding-bottom: 14px;
}

.step-connector {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 22px;
  flex-shrink: 0;
}

.step-dot {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  z-index: 2;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.step-dot.thought { background: #edf2f7; }
.step-dot.action { background: #ebf8ff; }
.step-dot.observation { background: #f0fff4; }
.step-dot.synthesize { background: #faf5ff; }

.pulse-dot {
  background: #fffaf0;
  animation: spin-pulse 2s linear infinite;
}

@keyframes spin-pulse {
  100% { transform: rotate(360deg); }
}

.step-line {
  flex: 1;
  width: 2px;
  background: #edf2f7;
  margin-top: 4px;
  margin-bottom: -4px;
}

.step-card {
  flex: 1;
  background: #f8fafc;
  border: 1px solid #edf2f7;
  border-radius: 8px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.step-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.step-type-name {
  font-size: 11px;
  font-weight: 700;
  border-radius: 4px;
  padding: 1px 5px;
}

.step-type-name.thought { color: #4a5568; background: #e2e8f0; }
.step-type-name.action { color: #2b6cb0; background: #bee3f8; }
.step-type-name.observation { color: #22543d; background: #c6f6d5; }
.step-type-name.synthesize { color: #553c9a; background: #e9d8fd; }

.step-time {
  font-size: 10px;
  color: #a0aec0;
}

.step-tool-badge {
  font-size: 11px;
}

.step-tool-badge code {
  background: #e2e8f0;
  color: #2b6cb0;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 10px;
}

.step-message {
  font-size: 12px;
  line-height: 1.5;
  color: #2d3748;
  word-break: break-word;
  white-space: pre-wrap;
}

.running-card {
  border-style: dashed;
  background: #fffaf0;
  border-color: #feebc8;
}

.pulse-text {
  font-size: 11px;
  color: #dd6b20;
  font-style: italic;
}
</style>
