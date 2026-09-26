<template>
  <div class="reader-container">
    <!-- 顶部书目信息与控制栏 -->
    <div class="reader-top-bar">
      <div class="reader-book-info">
        <n-select
          v-model:value="selectedBookId"
          :options="bookOptions"
          filterable
          placeholder="切换通读书目..."
          style="width: 280px;"
          @update:value="onBookChange"
        />
        <div v-if="currentBook" class="meta-inline">
          <span class="meta-label">已加载：{{ paragraphs.length }} / {{ totalCount }} 段</span>
          <span class="meta-label">总页数：{{ currentBook.pageCount }} 页</span>
          <n-tag size="small" type="info">{{ currentBook.primaryCategory }}</n-tag>
        </div>
      </div>

      <div class="reader-actions">
        <n-button size="small" type="primary" secondary :disabled="!selectedText" @click="interpretSelected">
          🔍 解读划选词句 ({{ selectedText ? selectedText.length : 0 }}字)
        </n-button>
        <n-button size="small" :loading="loading" @click="loadParagraphs(true)">
          🔄 重新通读
        </n-button>
      </div>
    </div>

    <!-- 主通读区域与右侧解读面板 -->
    <div class="reader-main-area">
      <!-- 左侧连续段落滚动流 -->
      <div class="paragraphs-scroll" ref="scrollContainer" @scroll="onScroll" @mouseup="onTextSelect">
        <div v-if="paragraphs.length === 0 && !loading" class="empty-reader">
          请选择需要通读的书籍。
        </div>

        <div
          v-for="(p, idx) in paragraphs"
          :key="p.id"
          class="paragraph-block"
        >
          <div class="para-header">
            <span class="para-anchor">{{ p.printedPage }} · 段落 #{{ p.paraIndex + 1 }}</span>
            <n-button size="tiny" quaternary @click="interpretParagraph(p)">
              💡 单段解析
            </n-button>
          </div>
          <div class="para-body">{{ p.text }}</div>
        </div>

        <div v-if="loading" class="loading-more">
          <n-spin size="small" />
          <span style="margin-left: 8px;">正在从不可变数据库流式调取后续章节...</span>
        </div>

        <div v-else-if="paragraphs.length >= totalCount && totalCount > 0" class="end-of-book">
          —— 已通读至全书末尾 ——
        </div>
      </div>

      <!-- 右侧划词即时伴读抽屉/面板 -->
      <div v-if="activeInterpretation || interpLoading" class="interpretation-side">
        <div class="interp-header">
          <span style="font-weight: 600;">🧠 智能伴读即时解析</span>
          <n-button size="tiny" quaternary @click="activeInterpretation = null">✕</n-button>
        </div>

        <div v-if="interpLoading" style="padding: 24px; text-align: center;">
          <n-spin size="medium" />
          <p style="color: #718096; font-size: 13px; margin-top: 8px;">通义千问正在深研所选文句的思想内核...</p>
        </div>

        <div v-else-if="activeInterpretation" class="interp-content">
          <div class="target-quote">
            <div style="font-size: 11px; color: #a0aec0; margin-bottom: 4px;">所选文句：</div>
            “{{ activeInterpretation.target }}”
          </div>
          <n-divider style="margin: 12px 0;" />
          <div class="interp-markdown" v-html="renderMarkdown(activeInterpretation.result)"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { marked } from 'marked'

const props = defineProps({
  initialBook: { type: Object, default: null }
})

const message = useMessage()

const books = ref([])
const selectedBookId = ref(null)
const currentBook = ref(null)
const paragraphs = ref([])
const totalCount = ref(0)
const offset = ref(0)
const pageSize = 40
const loading = ref(false)

const scrollContainer = ref(null)
const selectedText = ref('')
const interpLoading = ref(false)
const activeInterpretation = ref(null)

const bookOptions = computed(() => books.value.map(b => ({ label: `《${b.title}》`, value: b.id })))

async function loadBooks() {
  if (window.api?.listBooks) {
    const res = await window.api.listBooks()
    if (res.success) {
      books.value = res.data
      if (!selectedBookId.value && books.value.length > 0) {
        setTargetBook(books.value[0])
      }
    }
  }
}

function setTargetBook(book) {
  selectedBookId.value = book.id
  currentBook.value = book
  loadParagraphs(true)
}

defineExpose({ setTargetBook })

async function onBookChange(bookId) {
  const b = books.value.find(item => item.id === bookId)
  if (b) {
    currentBook.value = b
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
      const res = await window.api.getBookParagraphs({
        bookId: selectedBookId.value,
        offset: offset.value,
        limit: pageSize
      })
      if (res.success && res.data) {
        totalCount.value = res.data.total
        paragraphs.value = paragraphs.value.concat(res.data.paragraphs)
        offset.value += res.data.paragraphs.length
      }
    }
  } catch (err) {
    message.error('加载段落流失败')
  } finally {
    loading.value = false
  }
}

function onScroll(e) {
  const el = e.target
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 80) {
    if (!loading.value && paragraphs.value.length < totalCount.value) {
      loadParagraphs(false)
    }
  }
}

function onTextSelect() {
  const sel = window.getSelection()
  const t = sel ? sel.toString().trim() : ''
  if (t && t.length >= 2) {
    selectedText.value = t
  }
}

async function interpretSelected() {
  if (!selectedText.value) return
  await runInterpret(selectedText.value)
}

async function interpretParagraph(p) {
  await runInterpret(p.text)
}

async function runInterpret(text) {
  interpLoading.value = true
  activeInterpretation.value = { target: text, result: '' }
  try {
    if (window.api?.askInquiry) {
      const prompt = `请结合文献学与当时的历史背景，深度解读以下文段的核心论点与理论内涵：\n\n“${text}”`
      const res = await window.api.askInquiry({
        question: prompt,
        scope: { type: 'single_book', bookIds: [selectedBookId.value] }
      })
      if (res.success && res.data) {
        activeInterpretation.value.result = res.data.markdownAnswer
      }
    }
  } catch (err) {
    message.error('解读失败')
  } finally {
    interpLoading.value = false
  }
}

function renderMarkdown(md) {
  return marked.parse(md || '')
}

onMounted(() => {
  loadBooks()
  if (props.initialBook) {
    setTargetBook(props.initialBook)
  }
})
</script>

<style scoped>
.reader-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fdfbf7; /* 温润护眼底色 */
}
.reader-top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 24px;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
}
.reader-book-info {
  display: flex;
  align-items: center;
  gap: 16px;
}
.meta-inline {
  display: flex;
  align-items: center;
  gap: 10px;
}
.meta-label {
  font-size: 12px;
  color: #718096;
}
.reader-actions {
  display: flex;
  gap: 10px;
}
.reader-main-area {
  display: flex;
  flex: 1;
  overflow: hidden;
}
.paragraphs-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 32px 64px;
  max-width: 860px;
  margin: 0 auto;
  user-select: text;
}
.paragraph-block {
  margin-bottom: 24px;
  padding: 12px 16px;
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #edf2f7;
  transition: box-shadow 0.2s;
}
.paragraph-block:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.03);
}
.para-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.para-anchor {
  font-size: 11px;
  color: #a0aec0;
  font-family: monospace;
}
.para-body {
  font-size: 16px;
  line-height: 1.8;
  color: #2d3748;
  text-align: justify;
}
.loading-more, .end-of-book, .empty-reader {
  text-align: center;
  padding: 24px;
  color: #a0aec0;
  font-size: 13px;
}
.interpretation-side {
  width: 440px;
  background: #ffffff;
  border-left: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}
.interp-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  border-bottom: 1px solid #edf2f7;
}
.interp-content {
  padding: 16px;
}
.target-quote {
  background: #f7fafc;
  border-left: 3px solid #3182ce;
  padding: 10px 12px;
  font-size: 13px;
  color: #4a5568;
  line-height: 1.5;
  border-radius: 0 4px 4px 0;
}
.interp-markdown {
  font-size: 13px;
  line-height: 1.7;
  color: #2d3748;
}
</style>
