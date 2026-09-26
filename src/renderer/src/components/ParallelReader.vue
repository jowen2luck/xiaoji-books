<template>
  <div class="parallel-reader-container">
    <!-- 顶部控制与工具栏 -->
    <div class="reader-toolbar">
      <div class="toolbar-left">
        <n-button quaternary circle size="small" class="back-btn" @click="$emit('back-to-chat')" title="返回伴读对话">
          <template #icon><n-icon :size="18"><ArrowBackOutline /></n-icon></template>
        </n-button>

        <div class="book-selector-wrap">
          <n-select
            v-model:value="selectedBookId"
            :options="bookOptions"
            filterable
            placeholder="选择或搜索要对照阅读的书籍..."
            size="small"
            style="width: 320px;"
            @update:value="onBookChange"
          />
        </div>

        <div v-if="currentBook" class="book-meta-chips">
          <n-tag size="small" type="info" round>{{ currentBook.primaryCategory || '学术文献' }}</n-tag>
          <span class="meta-item">共 {{ currentBook.pageCount || totalPages }} 页</span>
          <span class="meta-item">已录入 {{ totalParagraphs }} 段文字</span>
        </div>
      </div>

      <!-- 中间：翻页控制与页码联动 -->
      <div class="toolbar-center">
        <div class="page-navigator">
          <n-button
            size="tiny"
            quaternary
            :disabled="currentPage <= 1"
            @click="jumpToPage(currentPage - 1)"
            title="上一页"
          >
            <template #icon><n-icon><ChevronBackOutline /></n-icon></template>
          </n-button>

          <span class="page-label">第</span>
          <n-input-number
            v-model:value="inputPageNumber"
            size="tiny"
            :min="1"
            :max="maxPage"
            style="width: 70px;"
            :show-button="false"
            @keydown.enter="jumpToPage(inputPageNumber)"
            @blur="jumpToPage(inputPageNumber)"
          />
          <span class="page-label">/ {{ maxPage }} 页</span>

          <n-button
            size="tiny"
            quaternary
            :disabled="currentPage >= maxPage"
            @click="jumpToPage(currentPage + 1)"
            title="下一页"
          >
            <template #icon><n-icon><ChevronForwardOutline /></n-icon></template>
          </n-button>
        </div>

        <n-divider vertical style="margin: 0 12px;" />

        <n-radio-group v-model:value="textDisplayMode" size="tiny">
          <n-radio-button value="currentPage">当前页文字</n-radio-button>
          <n-radio-button value="allContinuous">整书连续通读</n-radio-button>
        </n-radio-group>
      </div>

      <!-- 右侧：布局与外部操作 -->
      <div class="toolbar-right">
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button-group size="tiny">
              <n-button :type="splitRatio === 'equal' ? 'primary' : 'default'" @click="splitRatio = 'equal'">1:1 对等</n-button>
              <n-button :type="splitRatio === 'pdf' ? 'primary' : 'default'" @click="splitRatio = 'pdf'">原件优先</n-button>
              <n-button :type="splitRatio === 'text' ? 'primary' : 'default'" @click="splitRatio = 'text'">文字优先</n-button>
            </n-button-group>
          </template>
          切换左右分栏视图比例
        </n-tooltip>

        <n-tooltip trigger="hover" v-if="currentBook?.sourcePath">
          <template #trigger>
            <n-button size="tiny" secondary type="info" @click="openExternalPdf">
              <template #icon><n-icon><OpenOutline /></n-icon></template>
              本地打开原件
            </n-button>
          </template>
          在系统默认 PDF 软件中打开此文献原件
        </n-tooltip>
      </div>
    </div>

    <!-- 主对照预览分栏区域 -->
    <div class="parallel-split-layout" :class="`split-${splitRatio}`">
      <!-- 左侧：原书原件 (PDF 原本) -->
      <div class="pane original-pane">
        <div class="pane-header">
          <div class="pane-title">
            <span class="pane-badge pdf-badge">📖 原书原件影印</span>
            <span class="pane-subtitle" v-if="currentBook">
              《{{ currentBook.title }}》· 第 {{ currentPage }} 页
            </span>
          </div>
          <div class="pane-actions">
            <n-tag size="tiny" type="default" round>Chromium 内置引擎</n-tag>
          </div>
        </div>

        <div class="pane-content pdf-container">
          <div v-if="!currentBook" class="pane-placeholder">
            <n-empty description="请选择要阅读的书籍" />
          </div>

          <div v-else-if="!currentBook.sourcePath" class="pane-placeholder">
            <n-empty description="该书籍无对应本地 PDF 原件路径" />
          </div>

          <iframe
            v-else
            :key="pdfIframeKey"
            :src="pdfUrlWithPage"
            class="pdf-iframe"
            title="原书原件预览"
          ></iframe>
        </div>
      </div>

      <!-- 中间分界线指示条 -->
      <div class="split-divider">
        <div class="divider-line"></div>
        <div class="divider-badge">对照</div>
      </div>

      <!-- 右侧：数字化提取文字 -->
      <div class="pane extracted-pane">
        <div class="pane-header">
          <div class="pane-title">
            <span class="pane-badge text-badge">📝 数字化提取文字</span>
            <span class="pane-subtitle">
              {{ textDisplayMode === 'currentPage' ? `第 ${currentPage} 页 (共 ${paragraphs.length} 段)` : `全书连续流 (已载入 ${paragraphs.length} 段)` }}
            </span>
          </div>
          <div class="pane-actions">
            <n-button size="tiny" quaternary :loading="loading" @click="loadParagraphs(true)">
              🔄 刷新文字
            </n-button>
          </div>
        </div>

        <div class="pane-content text-scroll-container" ref="textScrollRef" @mouseup="onTextSelect">
          <div v-if="loading && paragraphs.length === 0" class="pane-loading">
            <n-spin size="medium" />
            <p>正在调取数字化原文字据...</p>
          </div>

          <div v-else-if="paragraphs.length === 0" class="pane-placeholder">
            <n-empty :description="textDisplayMode === 'currentPage' ? `第 ${currentPage} 页未录入提取文字或纯空白页` : '暂无提取文字'" />
          </div>

          <div v-else class="paragraphs-list">
            <div
              v-for="p in paragraphs"
              :key="p.id"
              class="para-card"
              :class="{ 'highlighted': targetParagraphId === p.id }"
            >
              <div class="para-meta-row">
                <span
                  class="para-page-badge"
                  @click="jumpToPage(p.pageIndex + 1)"
                  :title="`点击使左侧原件跳转到第 ${p.pageIndex + 1} 页`"
                >
                  📍 {{ p.printedPage || `第 ${p.pageIndex + 1} 页` }}
                </span>
                <span class="para-index-tag">段落 #{{ p.paraIndex + 1 }}</span>
                <span class="para-length-tag">{{ p.text.length }} 字</span>

                <div class="para-actions">
                  <n-button
                    size="tiny"
                    quaternary
                    type="primary"
                    @click="askWithParagraph(p)"
                    title="带着本段文字返回伴读对话，由小鸡助手深入解析"
                  >
                    💡 研读此段
                  </n-button>
                  <n-button
                    size="tiny"
                    quaternary
                    @click="copyParagraph(p.text)"
                    title="复制文字"
                  >
                    📋
                  </n-button>
                </div>
              </div>

              <div class="para-text-content">
                {{ p.text }}
              </div>
            </div>

            <!-- 连续通读更多加载 -->
            <div
              v-if="textDisplayMode === 'allContinuous' && paragraphs.length < totalParagraphs"
              class="load-more-bar"
            >
              <n-button size="small" secondary :loading="loading" @click="loadMoreParagraphs">
                加载后续章节段落...
              </n-button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { useMessage } from 'naive-ui'
import {
  ArrowBackOutline,
  ChevronBackOutline,
  ChevronForwardOutline,
  OpenOutline
} from '@vicons/ionicons5'

const props = defineProps({
  initialBookId: { type: String, default: null },
  initialPage: { type: Number, default: 1 },
  initialParagraphId: { type: String, default: null }
})

const emit = defineEmits(['back-to-chat', 'ask-question'])
const message = useMessage()

// 状态
const books = ref([])
const selectedBookId = ref(null)
const currentBook = ref(null)
const currentPage = ref(1)
const inputPageNumber = ref(1)
const targetParagraphId = ref(null)

const paragraphs = ref([])
const totalParagraphs = ref(0)
const loading = ref(false)
const offset = ref(0)
const pageSize = 40

// 视图控制
const splitRatio = ref('equal') // 'equal', 'pdf', 'text'
const textDisplayMode = ref('currentPage') // 'currentPage', 'allContinuous'
const selectedSelectionText = ref('')

// 计算最大页码
const maxPage = computed(() => currentBook.value?.pageCount || 100)
const totalPages = computed(() => currentBook.value?.pageCount || 1)

// 书籍下拉选项
const bookOptions = computed(() => {
  return books.value.map(b => ({
    label: `《${b.title}》 (${b.primaryCategory || '文献'} · ${b.pageCount || 0}页)`,
    value: b.id
  }))
})

// 原书 PDF 地址（携带 #page=X 实现原生跳页）
const pdfUrlWithPage = computed(() => {
  if (!currentBook.value?.sourcePath) return ''
  const baseUrl = window.api?.getPdfUrl
    ? window.api.getPdfUrl(currentBook.value.sourcePath)
    : `book-pdf:///${currentBook.value.sourcePath.replace(/\\/g, '/').replace(/^\/+/, '')}`
  return `${baseUrl}#page=${currentPage.value}&view=FitH`
})

// iframe 缓存刷新 key
const pdfIframeKey = computed(() => {
  return `${selectedBookId.value}_p${currentPage.value}`
})

// 初始化与监听
onMounted(async () => {
  await loadBooks()
  if (props.initialBookId) {
    const target = books.value.find(b => b.id === props.initialBookId)
    if (target) {
      selectBook(target, props.initialPage || 1, props.initialParagraphId)
      return
    }
  }
  if (books.value.length > 0 && !selectedBookId.value) {
    selectBook(books.value[0], 1)
  }
})

watch(() => props.initialBookId, (newId) => {
  if (newId) {
    const b = books.value.find(item => item.id === newId)
    if (b) selectBook(b, props.initialPage || 1, props.initialParagraphId)
  }
})

watch(textDisplayMode, () => {
  loadParagraphs(true)
})

async function loadBooks() {
  if (window.api?.listBooks) {
    const res = await window.api.listBooks()
    if (res.success && Array.isArray(res.data)) {
      books.value = res.data
    }
  }
}

function selectBook(book, page = 1, paraId = null) {
  selectedBookId.value = book.id
  currentBook.value = book
  currentPage.value = Math.max(1, Math.min(page, book.pageCount || 999))
  inputPageNumber.value = currentPage.value
  targetParagraphId.value = paraId
  loadParagraphs(true)
}

function onBookChange(bookId) {
  const b = books.value.find(item => item.id === bookId)
  if (b) {
    selectBook(b, 1)
  }
}

function jumpToPage(page) {
  const target = Math.max(1, Math.min(page, maxPage.value))
  currentPage.value = target
  inputPageNumber.value = target
  if (textDisplayMode.value === 'currentPage') {
    loadParagraphs(true)
  }
}

async function loadParagraphs(reset = false) {
  if (!selectedBookId.value) return
  if (reset) {
    offset.value = 0
    paragraphs.value = []
  }
  loading.value = true
  try {
    if (window.api?.getBookParagraphs) {
      const payload = {
        bookId: selectedBookId.value,
        offset: offset.value,
        limit: pageSize
      }
      if (textDisplayMode.value === 'currentPage') {
        payload.pageIndex = currentPage.value - 1
      }
      const res = await window.api.getBookParagraphs(payload)
      if (res.success && res.data) {
        totalParagraphs.value = res.data.total
        if (reset) {
          paragraphs.value = res.data.paragraphs
        } else {
          paragraphs.value.push(...res.data.paragraphs)
        }
        offset.value += res.data.paragraphs.length

        // 如果有指定目标段落，滚动到该段落
        if (targetParagraphId.value) {
          nextTick(() => {
            const el = document.querySelector('.para-card.highlighted')
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
          })
        }
      }
    }
  } catch (err) {
    message.error('加载提取文字失败: ' + err.message)
  } finally {
    loading.value = false
  }
}

async function loadMoreParagraphs() {
  if (loading.value || paragraphs.value.length >= totalParagraphs.value) return
  await loadParagraphs(false)
}

function onTextSelect() {
  const sel = window.getSelection()?.toString().trim()
  if (sel && sel.length > 4) {
    selectedSelectionText.value = sel
  }
}

function copyParagraph(text) {
  navigator.clipboard.writeText(text)
  message.success('段落文字已复制到剪贴板')
}

function askWithParagraph(p) {
  const query = `请针对《${currentBook.value?.title}》第 ${p.pageIndex + 1} 页的以下原文论述进行学术研读与要点解读：\n\n> "${p.text}"`
  emit('ask-question', {
    question: query,
    scope: { type: 'single_book', bookId: currentBook.value?.id, bookTitle: currentBook.value?.title }
  })
}

async function openExternalPdf() {
  if (!currentBook.value?.sourcePath) return
  if (window.api?.openPath) {
    const res = await window.api.openPath(currentBook.value.sourcePath)
    if (!res.success) {
      message.warning('打开原件失败: ' + (res.error || '未知错误'))
    } else {
      message.info('已在系统默认阅读器中打开原件')
    }
  }
}

// 暴露外部联动 API
defineExpose({
  selectBook,
  jumpToPage
})
</script>

<style scoped>
.parallel-reader-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  background: #f8fafc;
  overflow: hidden;
}

/* 顶部工具栏 */
.reader-toolbar {
  height: 52px;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  gap: 16px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
  z-index: 10;
  flex-shrink: 0;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.book-meta-chips {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #64748b;
  white-space: nowrap;
}

.toolbar-center {
  display: flex;
  align-items: center;
  justify-content: center;
}

.page-navigator {
  display: flex;
  align-items: center;
  gap: 6px;
}

.page-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* 对照分栏布局 */
.parallel-split-layout {
  display: flex;
  flex: 1;
  height: calc(100% - 52px);
  overflow: hidden;
  position: relative;
}

/* 比例控制 */
.parallel-split-layout.split-equal .original-pane {
  flex: 1;
}
.parallel-split-layout.split-equal .extracted-pane {
  flex: 1;
}

.parallel-split-layout.split-pdf .original-pane {
  flex: 1.4;
}
.parallel-split-layout.split-pdf .extracted-pane {
  flex: 0.8;
}

.parallel-split-layout.split-text .original-pane {
  flex: 0.8;
}
.parallel-split-layout.split-text .extracted-pane {
  flex: 1.4;
}

.split-divider {
  width: 14px;
  background: #f1f5f9;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border-left: 1px solid #e2e8f0;
  border-right: 1px solid #e2e8f0;
  position: relative;
  user-select: none;
}

.divider-line {
  width: 1px;
  height: 100%;
  background: #cbd5e1;
}

.divider-badge {
  position: absolute;
  background: #e2e8f0;
  color: #475569;
  font-size: 10px;
  font-weight: 600;
  padding: 4px 2px;
  border-radius: 4px;
  writing-mode: vertical-rl;
  letter-spacing: 2px;
}

/* 分栏通用 */
.pane {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: #ffffff;
}

.pane-header {
  height: 40px;
  padding: 0 16px;
  background: #fafaf9;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.pane-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pane-badge {
  font-size: 12px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 6px;
}

.pdf-badge {
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
}

.text-badge {
  background: #fefce8;
  color: #b45309;
  border: 1px solid #fef08a;
}

.pane-subtitle {
  font-size: 12px;
  color: #64748b;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pane-content {
  flex: 1;
  height: calc(100% - 40px);
  overflow: hidden;
  position: relative;
}

.pane-placeholder, .pane-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #94a3b8;
  font-size: 13px;
  gap: 12px;
}

/* PDF iframe */
.pdf-iframe {
  width: 100%;
  height: 100%;
  border: none;
  background: #525659;
}

/* 文字滚动列表 */
.text-scroll-container {
  overflow-y: auto;
  padding: 16px 20px;
  background: #f8fafc;
}

.paragraphs-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 800px;
  margin: 0 auto;
}

.para-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
  transition: all 0.2s ease;
}

.para-card:hover {
  border-color: #cbd5e1;
  box-shadow: 0 3px 8px rgba(0, 0, 0, 0.05);
}

.para-card.highlighted {
  border-color: #f59e0b;
  background: #fffdfa;
  box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.2);
}

.para-meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.para-page-badge {
  font-size: 11px;
  font-weight: 600;
  color: #2563eb;
  background: #eff6ff;
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.para-page-badge:hover {
  background: #dbeafe;
  text-decoration: underline;
}

.para-index-tag, .para-length-tag {
  font-size: 11px;
  color: #94a3b8;
}

.para-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
}

.para-text-content {
  font-size: 14px;
  line-height: 1.75;
  color: #1e293b;
  text-align: justify;
  letter-spacing: 0.2px;
  word-break: break-word;
  white-space: pre-wrap;
}

.load-more-bar {
  text-align: center;
  padding: 16px 0;
}
</style>
