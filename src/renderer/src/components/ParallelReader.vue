<template>
  <div class="parallel-reader">
    <!-- 极简顶栏 -->
    <header class="reader-top-bar">
      <div class="top-left">
        <div class="back-btn" @click="$emit('back')">
          <span class="back-arrow">‹</span>
          <span class="back-label">书库</span>
        </div>
        <div class="book-breadcrumb">
          <span class="crumb-book">{{ currentBook?.title || '加载中...' }}</span>
          <span class="crumb-sep">/</span>
          <span class="crumb-page">第 {{ currentPage }} 页</span>
        </div>
      </div>

      <div class="top-right">
        <!-- 页码快速跳转 -->
        <div class="page-jump">
          <span class="page-jump-label">跳转</span>
          <n-input-number
            v-model:value="jumpPage"
            :min="1"
            :max="currentBook?.totalPages || currentBook?.pageCount || 999"
            size="tiny"
            style="width: 70px"
            @update:value="handleJumpPage"
            :show-button="false"
          />
          <span class="page-total">/ {{ currentBook?.totalPages || currentBook?.pageCount || '—' }}</span>
        </div>

        <!-- 分割比例 — 点击循环切换 -->
        <div class="split-toggle" @click="cycleSplitRatio" :title="`当前: ${splitRatioLabel}`">
          <span class="split-icon">{{ splitRatioIcon }}</span>
        </div>

        <!-- 伴读提问 -->
        <div class="ask-btn" @click="chatPanelOpen = true" :class="{ active: chatPanelOpen }">
          <span class="ask-icon">!</span>
          <span class="ask-label">伴读</span>
        </div>
      </div>
    </header>

    <!-- 主体对照区 -->
    <div class="reader-body" :class="`split-${splitRatio}`">
      <!-- PDF 原版影印 -->
      <section class="pane-pane original-pane">
        <div class="pane-label">
          <span class="label-dot pdf-dot"></span>
          <span class="label-text">原版影印 · 第 {{ currentPage }} 页</span>
          <div class="pane-control-page">
            <span class="page-arrow" :class="{ disabled: currentPage <= 1 }" @click="goPrevPage()">‹</span>
            <span class="page-arrow" :class="{ disabled: currentPage >= (currentBook?.totalPages || currentBook?.pageCount || 999) }" @click="goNextPage()">›</span>
          </div>
        </div>
        <div class="pane-canvas">
          <div v-if="!pdfUrl" class="empty-pane">
            <div class="empty-mark">⊟</div>
            <div class="empty-text">请在左侧馆藏书库选择一本书</div>
          </div>
          <iframe
            v-else
            :src="pdfPageUrl"
            class="pdf-frame"
            frameborder="0"
          ></iframe>
        </div>
      </section>

      <!-- 中央分割线 -->
      <div class="split-divider">
        <div class="divider-grip"></div>
      </div>

      <!-- OCR 提取文字 -->
      <section class="pane-pane text-pane">
        <div class="pane-label">
          <span class="label-dot text-dot"></span>
          <span class="label-text">提取文字 · 本页 {{ totalParagraphs }} 段</span>
          <n-tooltip trigger="hover" placement="bottom">
            <template #trigger>
              <span class="label-hint" title="为什么不能在左侧影印上高亮？">?</span>
            </template>
            本工具目前只做「页级对应」：左栏影印与右栏文字按同一页码并排展示。
            抽取阶段未保留段落在页面上的坐标，因此无法在原版影印上高亮定位到具体段落。
          </n-tooltip>
        </div>
        <div class="pane-canvas">
          <div class="text-scroll" ref="textScrollRef">
            <div v-if="paragraphs.length === 0" class="empty-pane">
              <div class="empty-mark">⟫</div>
              <div class="empty-text">本页暂无提取文字</div>
              <div class="empty-sub">可能是空白页，或该页 OCR 失败</div>
            </div>

            <!-- 段落切分质量提示：抽取阶段未保留版面信息时如实告知 -->
            <div v-else-if="paragraphs.length === 1" class="seg-notice">
              <span class="seg-notice-icon">⚠</span>
              <div class="seg-notice-body">
                <div class="seg-notice-title">本页未做段落切分</div>
                <div class="seg-notice-text">
                  该书在 OCR 阶段未保留段落版面信息，整页文字作为单条记录入库，
                  因此这里看到的是一整段而非若干自然段。这不是阅读故障，而是抽取质量问题。
                </div>
              </div>
            </div>

            <div v-else class="paragraphs-flow">
              <div
                v-for="para in paragraphs"
                :key="para.id"
                class="para-card"
                :data-para-id="para.id"
                :class="{ highlighted: para.id === highlightedParagraphId }"
              >
                <div class="para-meta">
                  <span class="para-num">{{ para.paraIndex ?? ((para.pageIndex ?? 0) + 1) + '.' + (paragraphs.indexOf(para) + 1) }}</span>
                  <span class="para-page">{{ para.printedPage || `P.${(para.pageIndex ?? 0) + 1}` }}</span>
                  <span class="para-len">{{ para.text?.length || 0 }}字</span>
                </div>
                <div class="para-text">{{ para.text }}</div>
                <div class="para-actions">
                  <n-button size="tiny" secondary @click="askAboutPara(para)">
                    提问此段
                  </n-button>
                </div>
              </div>
            </div>

            <div class="load-more">
              <n-button v-if="hasMore" size="small" quaternary @click="loadMoreParagraphs">
                下一页（第 {{ currentPage + 1 }} 页）
              </n-button>
              <div v-else class="load-more-end">已是本页最后一段 · 本工具按页对应，不提供跨页检索</div>
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- 右侧伴读提问面板 — 抽屉 -->
    <transition name="slide-panel">
      <aside v-if="chatPanelOpen" class="chat-slide-panel">
        <div class="chat-panel-header">
          <div class="chat-panel-title">
            <span class="title-icon">!</span>
            <span>伴读提问</span>
          </div>
          <div class="header-controls">
            <n-tooltip trigger="hover">
              <template #trigger>
                <n-button quaternary circle size="tiny" @click="toggleTrace">
                  <template #icon>
                    <n-icon size="14"><SparklesOutline /></n-icon>
                  </template>
                </n-button>
              </template>
              {{ showTrace ? '收起思维链' : '展开思维链' }}
            </n-tooltip>
            <n-button quaternary circle size="tiny" @click="chatPanelOpen = false">
              <template #icon>
                <n-icon size="14"><CloseOutline /></n-icon>
              </template>
            </n-button>
          </div>
        </div>

        <!-- Scope indicator -->
        <div class="chat-scope-bar">
          <span class="scope-indicator"></span>
          <span class="scope-text">仅基于《{{ currentBook?.title }}》第 {{ currentPage }} 页内容回答</span>
        </div>

        <!-- 消息流 -->
        <div class="chat-messages" ref="chatMsgRef">
          <div v-if="chatMessages.length === 0" class="chat-empty">
            <div class="chat-empty-mark">!</div>
            <div class="chat-empty-title">针对当前页的内容提问</div>
            <div class="chat-empty-hint">例如：解释第3段的核心论点、分析作者在此处的修辞手法...</div>
            <div class="chat-quick-prompts">
              <n-tag
                v-for="p in quickPrompts"
                :key="p"
                size="small"
                round
                clickable
                class="quick-tag"
                @click="sendChatMessage(p)"
              >
                {{ p }}
              </n-tag>
            </div>
          </div>

          <div v-for="(msg, idx) in chatMessages" :key="idx" class="chat-msg" :class="msg.role">
            <div v-if="msg.role === 'user'" class="msg-bubble user-bubble">
              {{ msg.content }}
            </div>
            <div v-else class="msg-bubble assistant-bubble">
              <div class="msg-header">
                <span class="msg-avatar">!</span>
                <span class="msg-name">书友</span>
              </div>
              <div class="msg-text" v-html="renderMarkdown(msg.content)"></div>
              <!-- 思维链折叠 -->
              <div v-if="msg.trace && msg.trace.length > 0" class="msg-trace">
                <div class="trace-toggle" @click="msg._showTrace = !msg._showTrace">
                  推理 {{ msg.trace.length }} 步
                </div>
                <div v-if="msg._showTrace" class="trace-body">
                  <div v-for="(s, si) in msg.trace" :key="si" class="trace-row">
                    <span class="trace-num">{{ si + 1 }}</span>
                    <span class="trace-text">{{ s.thought || s.action || s.content }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 思考中 -->
          <div v-if="chatLoading" class="chat-msg assistant">
            <div class="msg-bubble assistant-bubble thinking">
              <div class="thinking-dots"><span></span><span></span><span></span></div>
              <span class="thinking-span">书友正在阅读当前页...</span>
            </div>
          </div>
        </div>

        <!-- 输入区 -->
        <div class="chat-input-zone">
          <n-input
            v-model:value="chatInput"
            type="textarea"
            placeholder="就本页内容提问... (Enter 发送)"
            :autosize="{ minRows: 1, maxRows: 4 }"
            @keydown.enter.exact.prevent="sendChatMessage()"
            :disabled="chatLoading"
          />
          <div class="input-controls">
            <span class="input-keyhint">Shift+Enter 换行</span>
            <n-button type="primary" size="small" :loading="chatLoading" :disabled="!chatInput.trim()" @click="sendChatMessage()">
              发送
            </n-button>
          </div>
        </div>
      </aside>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useMessage } from 'naive-ui'
import { marked } from 'marked'
import {
  SparklesOutline,
  CloseOutline
} from '@vicons/ionicons5'

const props = defineProps({
  initialBookId: { type: Number, default: null },
  initialPage: { type: Number, default: 1 },
  initialParagraphId: { type: String, default: null },
  initialSessionId: { type: String, default: '' }
})

const emit = defineEmits(['back', 'jump-shelf'])

const message = useMessage()

// 书本 & 页码
const currentBook = ref(null)
const currentPage = ref(props.initialPage || 1)
const currentParagraphId = ref(props.initialParagraphId)
const jumpPage = ref(currentPage.value)
const pdfUrl = ref('')

// PDF页面URL — 附带 #page= 锚点，翻页时iframe自动跳转
const pdfPageUrl = computed(() => {
  if (!pdfUrl.value) return ''
  // 移除已有锚点，添加新锚点
  const base = pdfUrl.value.split('#')[0]
  return `${base}#page=${currentPage.value}&view=FitH`
})

// 分割比例
const splitRatio = ref('equal') // equal | pdf | text
const splitRatioLabel = computed(() => ({
  equal: '1 : 1',
  pdf: '偏重影印',
  text: '偏重文本'
}[splitRatio.value]))
const splitRatioIcon = computed(() => ({
  equal: '⇆',
  pdf: '⟨⟩⟩',
  text: '⟨⟩⟨'
}[splitRatio.value]))

// 段落数据
const paragraphs = ref([])
const totalParagraphs = ref(0)
const hasMore = ref(false)
const textScrollRef = ref(null)
const highlightedParagraphId = ref(props.initialParagraphId)

// 聊天
const chatPanelOpen = ref(false)
const chatMessages = ref([])
const chatInput = ref('')
const chatLoading = ref(false)
const showTrace = ref(false)
const chatMsgRef = ref(null)

const quickPrompts = [
  '解释本页的核心论点',
  '梳理本页的逻辑结构',
  '本页有哪些关键概念',
  '分析作者在此处的修辞手法'
]

onMounted(async () => {
  if (props.initialBookId) {
    await loadBook(props.initialBookId)
  }
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
})

function handleKeydown(e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
  if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
    e.preventDefault()
    goPrevPage()
  } else if (e.key === 'ArrowRight' || e.key === 'PageDown') {
    e.preventDefault()
    goNextPage()
  } else if (e.key === 'Home') {
    e.preventDefault()
    currentPage.value = 1
  } else if (e.key === 'End') {
    e.preventDefault()
    currentPage.value = currentBook.value?.totalPages || currentBook.value?.pageCount || 999
  }
}

watch(() => props.initialBookId, async (id) => {
  if (id) await loadBook(id)
})

watch(currentPage, (p) => {
  jumpPage.value = p
  // 翻页时右侧文字区回到顶部
  if (textScrollRef.value) textScrollRef.value.scrollTop = 0
  loadPageParagraphs()
})

async function loadBook(bookId) {
  if (window.api?.getBook) {
    const res = await window.api.getBook(bookId)
    if (res.success && res.data) {
      currentBook.value = res.data
      // 兼容性：优先 pdfUrl/filePath，回退到 sourcePath
      const srcLike = res.data.pdfUrl || res.data.filePath || res.data.sourcePath || ''
      if (srcLike.startsWith('book-pdf://')) {
        pdfUrl.value = srcLike
      } else if (srcLike) {
        pdfUrl.value = window.api.getPdfUrl ? window.api.getPdfUrl(srcLike) : srcLike
      } else {
        pdfUrl.value = ''
      }
      await loadPageParagraphs()
    }
  }
}

async function loadPageParagraphs() {
  if (!currentBook.value) return
  const api = window.api || {}
  const fetchParas = api.getParagraphs || api.getBookParagraphs
  if (fetchParas) {
    const res = await fetchParas({
      bookId: currentBook.value.id,
      pageIndex: currentPage.value - 1,  // DB page_index 是 0-based
      limit: 200
    })
    if (res.success && res.data) {
      paragraphs.value = res.data.paragraphs || res.data.list || []
      totalParagraphs.value = res.data.total || 0
      hasMore.value = res.data.hasMore || false

      // 跳转高亮
      if (highlightedParagraphId.value) {
        await nextTick()
        scrollToPara(highlightedParagraphId.value)
      }
    }
  }
}

async function loadMoreParagraphs() {
  // load next page's paragraphs
  currentPage.value += 1
}

function handleJumpPage(page) {
  if (page && page >= 1) {
    currentPage.value = page
  }
}

function goPrevPage() {
  if (currentPage.value > 1) currentPage.value--
}

function goNextPage() {
  if (currentPage.value < (currentBook.value?.totalPages || 999)) currentPage.value++
}

function cycleSplitRatio() {
  const order = ['equal', 'pdf', 'text']
  const idx = order.indexOf(splitRatio.value)
  splitRatio.value = order[(idx + 1) % 3]
}

function scrollToPara(paraId) {
  if (!paraId || !textScrollRef.value) return
  nextTick(() => {
    const root = textScrollRef.value
    // id 可能含 ':' 等特殊字符，逐个比对比 CSS 选择器更稳
    const cards = Array.from(root.querySelectorAll('[data-para-id]'))
    let el = cards.find(c => c.dataset.paraId === paraId)
    if (!el) {
      // 兜底：证据 id 与段落 id 形态不同时（如 ev_ 前缀），退化为首个段落
      const norm = String(paraId).replace(/^ev_/, '').replace(/_\d+$/, '')
      el = cards.find(c => c.dataset.paraId === norm || c.dataset.paraId.includes(norm))
    }
    if (!el) el = cards[0]
    if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  })
}

function askAboutPara(para) {
  chatPanelOpen.value = true
  chatInput.value = `关于这一段："${para.text?.slice(0, 40)}..."，请解释其含义`
}

// Chat
async function sendChatMessage(forcedInput) {
  const text = forcedInput || chatInput.value.trim()
  if (!text || chatLoading.value) return

  chatMessages.value.push({ role: 'user', content: text })
  chatInput.value = ''
  chatLoading.value = true

  try {
    const res = await window.api.askInquiry({
      question: text,
      scope: { type: 'single_book', bookId: props.initialBookId, page: currentPage.value },
      sessionId: props.initialSessionId,
      history: chatMessages.value.slice(-6).map(m => ({ role: m.role, content: m.content }))
    })

    if (res.success && res.data) {
      chatMessages.value.push({
        role: 'assistant',
        content: res.data.markdownAnswer,
        trace: res.data.executionTrace || [],
        _showTrace: false
      })
    } else {
      chatMessages.value.push({
        role: 'assistant',
        content: '抱歉，回答出现异常: ' + (res.error || '未知错误')
      })
    }
  } catch (e) {
    chatMessages.value.push({
      role: 'assistant',
      content: '网络异常: ' + e.message
    })
  } finally {
    chatLoading.value = false
    nextTick(() => {
      if (chatMsgRef.value) chatMsgRef.value.scrollTop = chatMsgRef.value.scrollHeight
    })
  }
}

function toggleTrace() {
  showTrace.value = !showTrace.value
  chatMessages.value.forEach(m => { m._showTrace = showTrace.value })
}

function renderMarkdown(text) {
  if (!text) return ''
  try { return marked.parse(text) } catch { return text }
}

// Expose methods for parent
defineExpose({
  jumpToPage(page) { currentPage.value = page },
  selectBook(bookId) { loadBook(bookId) }
})
</script>

<style scoped>
.parallel-reader {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  background: var(--color-bg);
  overflow: hidden;
  position: relative;
}

/* ==================== 极简顶栏 ==================== */
.reader-top-bar {
  height: var(--h-topbar);
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  flex-shrink: 0;
  z-index: 10;
}

.top-left {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
  flex: 1;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 2px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: var(--radius-md);
  color: var(--color-ink-muted);
  transition: all 0.15s;
}

.back-btn:hover {
  background: var(--color-bg);
  color: var(--color-accent);
}

.back-arrow {
  font-size: 20px;
  line-height: 1;
  font-weight: 600;
}

.back-label {
  font-size: 12px;
  font-weight: 500;
}

.book-breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--color-ink-muted);
}

.crumb-book {
  font-family: var(--font-display);
  font-weight: 600;
  color: var(--color-ink);
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
}

.crumb-sep {
  color: var(--color-ink-faint);
}

.crumb-page {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-info);
}

.top-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

/* 跳页器 */
.page-jump {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--color-ink-muted);
}

.page-jump-label {
  font-size: 12px;
  color: var(--color-ink-faint);
  margin-right: 2px;
}

.page-total {
  font-family: var(--font-mono);
  color: var(--color-ink-faint);
}

/* 分割比例切换 */
.split-toggle {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--color-ink-muted);
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  transition: all 0.15s;
}

.split-toggle:hover {
  color: var(--color-accent);
  border-color: var(--color-accent);
}

.split-icon {
  font-size: 14px;
  font-weight: 600;
}

/* 伴读按钮 */
.ask-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, #fef3c7, #fde68a);
  border: 1px solid #f59e0b;
  color: #92400e;
  cursor: pointer;
  transition: all 0.15s;
  font-size: 12px;
  font-weight: 600;
}

.ask-btn:hover {
  box-shadow: 0 2px 8px rgba(245, 158, 11, 0.2);
  transform: translateY(-1px);
}

.ask-btn.active {
  background: linear-gradient(135deg, #b45309, #d97706);
  border-color: #b45309;
  color: #ffffff;
}

.ask-icon {
  font-size: 14px;
  font-weight: 700;
  line-height: 1;
}

/* ==================== 主体对照区 ==================== */
.reader-body {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  position: relative;
}

.split-equal .original-pane { flex: 1; }
.split-equal .text-pane { flex: 1; }
.split-pdf .original-pane { flex: 1.5; }
.split-pdf .text-pane { flex: 1; }
.split-text .original-pane { flex: 1; }
.split-text .text-pane { flex: 1.5; }

.pane-pane {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: var(--color-surface);
  min-width: 320px;
}

.pane-label {
  height: 30px;
  padding: 0 14px;
  background: var(--color-bg-warm);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  color: var(--color-ink-muted);
  font-weight: 500;
  flex-shrink: 0;
  gap: 8px;
}

.label-text {
  flex: 1;
}

.label-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 6px;
  display: inline-block;
  flex-shrink: 0;
}

.pdf-dot { background: var(--color-info); }
.text-dot { background: var(--color-accent); }

/* 面板标签上的说明入口 */
.label-hint {
  width: 15px;
  height: 15px;
  border-radius: 50%;
  border: 1px solid var(--color-border-deep);
  color: var(--color-ink-faint);
  font-size: 10px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: help;
  flex-shrink: 0;
}

.label-hint:hover {
  border-color: var(--color-accent);
  color: var(--color-accent);
}

/* 段落切分质量提示 */
.seg-notice {
  display: flex;
  gap: 10px;
  max-width: 760px;
  margin: 0 auto;
  padding: 12px 14px;
  background: var(--color-accent-soft);
  border: 1px solid #fde68a;
  border-left: 3px solid var(--color-accent);
  border-radius: var(--radius-md);
}

.seg-notice-icon {
  font-size: 14px;
  color: var(--color-accent);
  flex-shrink: 0;
  line-height: 1.5;
}

.seg-notice-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-ink);
  margin-bottom: 3px;
}

.seg-notice-text {
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-ink-muted);
}

.empty-sub {
  font-size: 11px;
  color: var(--color-ink-faint);
  opacity: 0.8;
}

.load-more-end {
  font-size: 11px;
  color: var(--color-ink-faint);
  text-align: center;
  padding: 10px 0 4px;
}

.pane-control-page {
  display: flex;
  gap: 4px;
}

.page-arrow {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 16px;
  color: var(--color-ink-muted);
  transition: all 0.1s;
}

.page-arrow:hover:not(.disabled) {
  background: var(--color-surface);
  color: var(--color-accent);
}

.page-arrow.disabled {
  opacity: 0.3;
  cursor: default;
}

.pane-canvas {
  flex: 1;
  height: calc(100% - 30px);
  overflow: hidden;
  position: relative;
}

.empty-pane {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 10px;
  color: var(--color-ink-faint);
}

.empty-mark {
  font-size: 28px;
  opacity: 0.4;
}

.empty-text {
  font-size: 12px;
  color: var(--color-ink-faint);
}

.pdf-frame {
  width: 100%;
  height: 100%;
  border: none;
  background: #525659;
}

/* 中间分割线 */
.split-divider {
  width: 6px;
  background: var(--color-bg-warm);
  border-left: 1px solid var(--color-border);
  border-right: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.divider-grip {
  width: 2px;
  height: 24px;
  border-radius: 1px;
  background: var(--color-border-deep);
}

/* 文字滚动区 */
.text-scroll {
  overflow-y: auto;
  height: 100%;
  padding: 16px 20px;
  background: var(--color-bg);
}

.paragraphs-flow {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: 760px;
  margin: 0 auto;
}

.para-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 12px 16px;
  transition: all 0.15s;
}

.para-card:hover {
  border-color: var(--color-border-deep);
  box-shadow: var(--shadow-sm);
}

.para-card.highlighted {
  border-color: var(--color-accent);
  background: var(--color-accent-soft);
  box-shadow: 0 0 0 2px rgba(180, 83, 9, 0.1);
}

.para-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.para-num {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-accent);
  font-weight: 600;
}

.para-page {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-info);
  background: var(--color-info-soft);
  padding: 0 5px;
  border-radius: 3px;
  font-weight: 500;
}

.para-len {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--color-ink-faint);
}

.para-text {
  font-family: var(--font-display);
  font-size: 14px;
  line-height: 1.85;
  color: var(--color-ink);
  letter-spacing: 0.2px;
  white-space: pre-wrap;
  word-break: break-word;
}

.para-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 6px;
}

.load-more {
  text-align: center;
  padding: 10px 0;
}

/* ==================== 右侧伴读面板 ==================== */
.chat-slide-panel {
  width: var(--w-chat-panel);
  min-width: 320px;
  max-width: 560px;
  background: var(--color-surface);
  border-left: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  box-shadow: -4px 0 16px rgba(28, 25, 23, 0.06);
}

.chat-panel-header {
  height: 40px;
  padding: 0 14px;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.chat-panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 600;
  color: var(--color-ink);
}

.title-icon {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: linear-gradient(135deg, #fef3c7, #fde68a);
  border: 1.5px solid #f59e0b;
  color: #92400e;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
}

.header-controls {
  display: flex;
  gap: 4px;
}

.chat-scope-bar {
  padding: 6px 14px;
  background: var(--color-accent-soft);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--color-accent);
}

.scope-indicator {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-accent);
  flex-shrink: 0;
}

.scope-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 聊天消息流 */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.chat-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding-top: 32px;
  gap: 8px;
}

.chat-empty-mark {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--color-accent-soft);
  border: 2px solid #f59e0b;
  color: #92400e;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 700;
}

.chat-empty-title {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 600;
  color: var(--color-ink);
}

.chat-empty-hint {
  font-size: 11px;
  color: var(--color-ink-faint);
  line-height: 1.5;
  max-width: 240px;
}

.chat-quick-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: center;
  margin-top: 8px;
}

.quick-tag {
  cursor: pointer !important;
}

.quick-tag:hover {
  border-color: #f59e0b !important;
  background: #fffbeb !important;
}

/* 消息气泡 */
.chat-msg {
  display: flex;
}

.chat-msg.user {
  justify-content: flex-end;
}

.msg-bubble {
  max-width: 90%;
  font-size: 13px;
  line-height: 1.65;
}

.user-bubble {
  background: linear-gradient(135deg, #92400e, #b45309);
  color: #ffffff;
  padding: 9px 14px;
  border-radius: 14px 14px 3px 14px;
}

.assistant-bubble {
  background: var(--color-bg-warm);
  border: 1px solid var(--color-border);
  padding: 10px 14px;
  border-radius: 14px 14px 14px 3px;
}

.msg-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.msg-avatar {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: linear-gradient(135deg, #fef3c7, #fde68a);
  border: 1.5px solid #f59e0b;
  color: #92400e;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}

.msg-name {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-ink);
}

.msg-text {
  color: var(--color-ink-soft);
}

/* 思维链 */
.msg-trace {
  margin-top: 8px;
  border-top: 1px dashed var(--color-border);
  padding-top: 6px;
}

.trace-toggle {
  font-size: 12px;
  color: var(--color-accent);
  font-weight: 600;
  cursor: pointer;
}

.trace-body {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.trace-row {
  display: flex;
  gap: 6px;
  font-size: 11px;
  color: var(--color-ink-muted);
  line-height: 1.4;
}

.trace-num {
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

/* 思考中 */
.thinking {
  display: flex;
  align-items: center;
  gap: 10px;
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

.thinking-span {
  font-size: 12px;
  color: var(--color-ink-muted);
  font-style: italic;
}

/* 输入区 */
.chat-input-zone {
  padding: 10px 12px;
  border-top: 1px solid var(--color-border);
  background: var(--color-bg);
  flex-shrink: 0;
}

.input-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
}

.input-keyhint {
  font-size: 10px;
  color: var(--color-ink-faint);
}

/* 面板滑入动画 */
.slide-panel-enter-active,
.slide-panel-leave-active {
  transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s ease;
}

.slide-panel-enter-from,
.slide-panel-leave-to {
  transform: translateX(100%);
  opacity: 0;
}

.slide-panel-enter-to,
.slide-panel-leave-from {
  transform: translateX(0);
  opacity: 1;
}
</style>
