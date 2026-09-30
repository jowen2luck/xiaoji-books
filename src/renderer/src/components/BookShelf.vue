<template>
  <div class="shelf-page">
    <!-- 顶部欢迎横幅 -->
    <div class="shelf-masthead">
      <div class="masthead-left">
        <div class="masthead-mark">
          <span class="masthead-num">{{ books.length || '—' }}</span>
          <span class="masthead-label">部馆藏</span>
        </div>
        <div class="masthead-content">
          <h1 class="masthead-title">馆藏书库</h1>
          <p class="masthead-desc">涵盖政治经济、历史传记、哲学方法论、文化社会研究等领域的经典文献馆藏。</p>
        </div>
        <div class="masthead-actions">
          <n-button type="primary" size="small" class="btn-new-session" @click="showSessionModal = true">
            <template #icon><n-icon size="13"><AddOutline /></n-icon></template>
            新建会话
          </n-button>
        </div>
      </div>
      <div class="masthead-decoration">
        <span class="deco-line"></span>
        <span class="deco-mark">§</span>
        <span class="deco-line"></span>
      </div>
    </div>

    <!-- 筛选工具栏 -->
    <div class="shelf-toolbar">
      <div class="toolbar-search">
        <n-input
          v-model:value="searchQuery"
          placeholder="搜索书名、作者或关键词..."
          clearable
          class="search-input"
        >
          <template #prefix>
            <n-icon size="14"><SearchOutline /></n-icon>
          </template>
        </n-input>
      </div>
      <div class="toolbar-filters">
        <n-select
          v-model:value="activeCategory"
          :options="categoryOptions"
          placeholder="全部主题"
          size="small"
          class="category-select"
          clearable
        />
        <n-select
          v-model:value="sortBy"
          :options="sortOptions"
          size="small"
          class="sort-select"
        />
      </div>
    </div>

    <!-- 列表 -->
    <div class="shelf-content">
      <!-- 加载 -->
      <div v-if="loading" class="shelf-loading">
        <div class="loading-books">
          <div class="loading-book" v-for="i in 6" :key="i">
            <div class="book-spine"></div>
          </div>
        </div>
        <span class="loading-text">正在整理馆藏...</span>
      </div>

      <!-- 空 -->
      <div v-else-if="filteredBooks.length === 0" class="shelf-empty">
        <div class="empty-mark">⊞</div>
        <div class="empty-title">暂无匹配书籍</div>
        <div class="empty-hint">尝试调整筛选条件或搜索关键词</div>
      </div>

      <!-- 书籍网格 -->
      <div v-else class="books-grid">
        <div
          v-for="book in filteredBooks"
          :key="book.id"
          class="book-card"
          @click="handleOpenBook(book)"
        >
          <!-- 书籍封面模拟 -->
          <div class="book-cover">
            <div class="cover-spine"></div>
            <div class="cover-body">
              <span class="cover-category">{{ book.primaryCategory?.slice(0, 4) || '文献' }}</span>
              <span class="cover-title">{{ book.title?.slice(0, 6) || '未命名' }}</span>
              <span class="cover-author">{{ (book.authors && book.authors[0] ? book.authors[0] : book.author || '佚名').slice(0, 8) }}</span>
            </div>
          </div>

          <!-- 信息 -->
          <div class="book-info">
            <h3 class="book-name" :title="book.title">《{{ book.title }}》</h3>
            <p class="book-author">{{ (book.authors && book.authors[0]) || book.author || '佚名' }}</p>
            <div class="book-meta-row">
              <span class="meta-category">{{ book.primaryCategory || '文献' }}</span>
              <span class="meta-pages">{{ book.pageCount || book.totalPages || '?' }}页</span>
              <n-tooltip v-if="segLabel(book)" trigger="hover" placement="top">
                <template #trigger>
                  <span class="meta-seg" :class="'seg-' + (book.segmentationQuality || 'coarse')">
                    {{ segLabel(book) }}
                  </span>
                </template>
                段落切分质量：平均 {{ book.avgParasPerPage }} 段/页，
                {{ Math.round((book.singlePageRatio || 0) * 100) }}% 的页面未做段落切分（整页作为一条记录）。
                成因是 OCR 阶段未保留段落版面信息，属抽取质量问题而非阅读故障。
                本工具当前只做「页级对应」，无法在原版影印上高亮定位到具体段落。
              </n-tooltip>
            </div>
            <div class="book-tags" v-if="book.tags && book.tags.length > 0">
              <span v-for="tag in book.tags.slice(0, 3)" :key="tag" class="book-tag">{{ tag }}</span>
              <span v-if="book.tags.length > 3" class="book-tag more">+{{ book.tags.length - 3 }}</span>
            </div>
          </div>

          <!-- 悬浮按钮 -->
          <div class="book-action" @click.stop="handleOpenBook(book)">
            <span class="action-text">打开阅读</span>
            <span class="action-arrow">→</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建会话 Modal -->
    <n-modal
      v-model:show="showSessionModal"
      preset="dialog"
      title="新建研读会话"
      positive-text="创建会话"
      negative-text="取消"
      :loading="sessionCreating"
      @positive-click="handleCreateSession"
      @negative-click="showSessionModal = false"
    >
      <div style="padding: 8px 4px 4px;">
        <!-- 伴读模式三选一 -->
        <n-radio-group v-model:value="sessionMode" size="small" style="width: 100%;">
          <n-radio-button value="book">选定一本书</n-radio-button>
          <n-radio-button value="category">选定一类主题</n-radio-button>
          <n-radio-button value="multi">选定多本书</n-radio-button>
        </n-radio-group>

        <!-- 模式提示 -->
        <div class="session-mode-hint">
          <span v-if="sessionMode === 'book'">在馆藏中点选一本精读书籍</span>
          <span v-else-if="sessionMode === 'category'">围绕一个主题分类进行综合研读</span>
          <span v-else>勾选多本相关书籍进行对照研读</span>
        </div>

        <!-- 分类模式: 下拉选分类 -->
        <div v-if="sessionMode === 'category'" class="session-field">
          <label class="session-field-label">选择主题分类</label>
          <n-select
            v-model:value="sessionCategory"
            :options="categoryOptions.filter(c => c.value)"
            placeholder="请选择"
          />
        </div>

        <!-- 多书 / 单书模式: 可选书籍列表 -->
        <div v-if="sessionMode !== 'category'" class="session-field">
          <label class="session-field-label">
            <template v-if="sessionMode === 'multi'">
              已选 {{ selectedBookIds.length }} 本（点击勾选）
            </template>
            <template v-else>
              点击选择一本书
            </template>
          </label>
          <div class="session-book-list">
            <div
              v-for="book in filteredBooks.slice(0, 80)"
              :key="book.id"
              class="session-book-item"
              :class="{
                selected: sessionMode === 'book'
                  ? selectedBookIds[0] === book.id
                  : selectedBookIds.includes(book.id)
              }"
              @click="toggleBookSelection(book.id)"
            >
              <span class="sb-check" v-if="sessionMode === 'multi'">{{
                selectedBookIds.includes(book.id) ? '☑' : '☐'
              }}</span>
              <span class="sb-check" v-else>{{
                selectedBookIds[0] === book.id ? '◉' : '○'
              }}</span>
              <span class="sb-name">《{{ book.title }}》</span>
              <span class="sb-cat">{{ book.primaryCategory || '文献' }}</span>
            </div>
            <div v-if="filteredBooks.length === 0" class="session-no-books">暂无可选用书籍</div>
            <div v-if="filteredBooks.length > 80" class="session-more-hint">仅展示前 80 本，可用顶部搜索框缩小范围</div>
          </div>
        </div>
      </div>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { SearchOutline, AddOutline } from '@vicons/ionicons5'
import { useMessage } from 'naive-ui'

const emit = defineEmits(['open-reader', 'open-chat'])
const message = useMessage()

// 状态
const loading = ref(false)
const books = ref([])
const searchQuery = ref('')
const activeCategory = ref(null)
const sortBy = ref('default')

// 新建会话 Modal
const showSessionModal = ref(false)
const sessionCreating = ref(false)
const sessionMode = ref('book')   // 'book' | 'category' | 'multi'
const sessionCategory = ref(null)
const selectedBookIds = ref([])

// 段落切分质量标签：让退化数据在列表层就可见，而不是等用户翻到阅读器才发现
function segLabel (book) {
  if (!book || !book.avgParasPerPage) return ''
  const n = book.avgParasPerPage
  if (n >= 3) return `切分 ${n} 段/页`
  if (n >= 1.2) return `切分偏粗 ${n} 段/页`
  return '整页未切分'
}

function toggleBookSelection (bookId) {
  if (sessionMode.value === 'multi') {
    const idx = selectedBookIds.value.indexOf(bookId)
    if (idx >= 0) selectedBookIds.value.splice(idx, 1)
    else selectedBookIds.value.push(bookId)
  } else {
    selectedBookIds.value = [bookId]
  }
}

async function handleCreateSession () {
  sessionCreating.value = true
  try {
    let scope = { type: 'global' }
    if (sessionMode.value === 'book') {
      if (!selectedBookIds.value[0]) {
        message.warning('请先选择一本书')
        return false   // 返回 false 让 naive-ui 保持弹窗打开
      }
      scope = { type: 'single_book', bookIds: [selectedBookIds.value[0]] }
    } else if (sessionMode.value === 'category') {
      if (!sessionCategory.value) {
        message.warning('请先选择一本主题分类')
        return false
      }
      scope = { type: 'category', categories: [sessionCategory.value] }
    } else if (sessionMode.value === 'multi') {
      if (selectedBookIds.value.length < 2) {
        message.warning('请至少勾选两本书')
        return false
      }
      scope = { type: 'multi_book', bookIds: [...selectedBookIds.value] }
    }
    const qMap = {
      book: `精读研读：《${(books.value.find(b => b.id === selectedBookIds.value[0]) || {}).title || '已选文献'}》`,
      category: `专题研读：${sessionCategory.value || '未选分类'}`,
      multi: `对照研读：共 ${selectedBookIds.value.length} 本馆藏`
    }
    const res = await window.api.createSession({ question: qMap[sessionMode.value], scope })
    if (res.success && res.data) {
      showSessionModal.value = false
      selectedBookIds.value = []
      sessionCategory.value = null
      message.success('已创建研读会话')
      emit('open-chat', { sessionId: res.data.id })
    } else {
      message.error('创建失败：' + (res.error || '未知'))
      return false
    }
  } catch (e) {
    message.error('创建失败：' + (e.message || '未知'))
    return false
  } finally {
    sessionCreating.value = false
  }
}

const categoryOptions = [
  { label: '全部主题', value: null },
  { label: '政治经济与社会主义', value: '政治经济与社会主义' },
  { label: '历史与人物传记', value: '历史与人物传记' },
  { label: '哲学与方法论', value: '哲学与方法论' },
  { label: '文化与社会研究', value: '文化与社会研究' }
]

const sortOptions = [
  { label: '默认排序', value: 'default' },
  { label: '书名 A-Z', value: 'title_asc' },
  { label: '添加时间', value: 'recent' }
]

const filteredBooks = computed(() => {
  let list = books.value

  // 分类筛选
  if (activeCategory.value) {
    list = list.filter(b => b.primaryCategory === activeCategory.value)
  }

  // 搜索
  if (searchQuery.value?.trim()) {
    const q = searchQuery.value.trim().toLowerCase()
    list = list.filter(b =>
      b.title?.toLowerCase().includes(q) ||
      b.author?.toLowerCase().includes(q) ||
      b.tags?.some(t => t.toLowerCase().includes(q))
    )
  }

  // 排序
  if (sortBy.value === 'title_asc') {
    list = [...list].sort((a, b) => (a.title || '').localeCompare(b.title || ''))
  }

  return list
})

onMounted(async () => {
  await loadBooks()
  // 侧栏「新建会话」按钮回调
  window.addEventListener('book-shelf:open-new-session', () => {
    showSessionModal.value = true
  })
})

async function loadBooks() {
  loading.value = true
  if (window.api?.listBooks) {
    try {
      const res = await window.api.listBooks()
      if (res.success && Array.isArray(res.data)) {
        books.value = res.data
      }
    } catch (e) {
      console.warn('Failed to load books:', e)
    }
  }
  loading.value = false
}

function handleOpenBook(book) {
  emit('open-reader', { bookId: book.id, page: 1 })
}
</script>

<style scoped>
.shelf-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  background: var(--color-bg);
  overflow: hidden;
}

/* ==================== 顶部欢迎横幅 ==================== */
.shelf-masthead {
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  padding: 20px 32px;
  flex-shrink: 0;
}

.masthead-left {
  display: flex;
  align-items: center;
  gap: 18px;
}

.masthead-mark {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, #fef3c7, #fde68a);
  border: 1.5px solid #f59e0b;
}

.masthead-num {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 900;
  color: #92400e;
  line-height: 1;
}

.masthead-label {
  font-size: 12px;
  font-weight: 600;
  color: #b45309;
  letter-spacing: 0.5px;
}

.masthead-content {
  flex: 1;
}

.masthead-title {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--color-ink);
  margin: 0;
  letter-spacing: 1px;
  line-height: 1.3;
}

.masthead-desc {
  font-size: 12px;
  color: var(--color-ink-muted);
  margin: 4px 0 0;
  line-height: 1.5;
}

.masthead-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
}

.btn-new-session {
  font-weight: 500;
  border-radius: var(--radius-md) !important;
}

.masthead-decoration {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-top: 14px;
}

.deco-line {
  flex: 1;
  height: 1px;
  background: var(--color-border);
  max-width: 120px;
}

.deco-mark {
  font-size: 16px;
  color: var(--color-accent);
  font-family: var(--font-display);
  font-weight: 600;
}

/* ==================== 筛选工具栏 ==================== */
.shelf-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 32px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}

.toolbar-search {
  flex: 1;
  max-width: 400px;
}

.search-input {
  border-radius: var(--radius-lg) !important;
}

.toolbar-filters {
  display: flex;
  gap: 8px;
  margin-left: auto;
}

.category-select {
  width: 160px;
}

.sort-select {
  width: 110px;
}

/* ==================== 内容区 ==================== */
.shelf-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px 32px 32px;
}

/* 加载 */
.shelf-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 20px;
}

.loading-books {
  display: flex;
  gap: 12px;
}

.loading-book {
  width: 28px;
  height: 120px;
  border-radius: 2px 4px 4px 2px;
  overflow: hidden;
}

.book-spine {
  width: 100%;
  height: 100%;
  background: linear-gradient(135deg, #d6d0c5, #e7e2da);
  animation: book-shimmer 1.5s ease-in-out infinite;
}

.loading-book:nth-child(2) .book-spine { animation-delay: 0.1s; background: linear-gradient(135deg, #fde68a, #fef3c7); }
.loading-book:nth-child(3) .book-spine { animation-delay: 0.2s; background: linear-gradient(135deg, #a5f3fc, #cffafe); }
.loading-book:nth-child(4) .book-spine { animation-delay: 0.3s; background: linear-gradient(135deg, #d6d0c5, #e7e2da); }
.loading-book:nth-child(5) .book-spine { animation-delay: 0.4s; background: linear-gradient(135deg, #fde68a, #fef3c7); }
.loading-book:nth-child(6) .book-spine { animation-delay: 0.5s; }

@keyframes book-shimmer {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}

.loading-text {
  font-size: 12px;
  color: var(--color-ink-faint);
}

/* 空状态 */
.shelf-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 8px;
}

.empty-mark {
  font-size: 32px;
  opacity: 0.3;
}

.empty-title {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 600;
  color: var(--color-ink-muted);
}

.empty-hint {
  font-size: 12px;
  color: var(--color-ink-faint);
}

/* ==================== 书籍网格 ==================== */
.books-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 16px;
}

.book-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
  display: flex;
  flex-direction: column;
}

.book-card:hover {
  border-color: var(--color-accent);
  box-shadow: 0 8px 24px rgba(28, 25, 23, 0.08);
  transform: translateY(-3px);
}

.book-card:hover .book-action {
  opacity: 1;
  transform: translateY(0);
}

/* 书皮封面 */
.book-cover {
  height: 100px;
  display: flex;
  overflow: hidden;
  background: var(--color-bg-deep);
}

.cover-spine {
  width: 18px;
  flex-shrink: 0;
  background: linear-gradient(90deg, rgba(0, 0, 0, 0.06), transparent);
}

.cover-body {
  flex: 1;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  position: relative;
  background: linear-gradient(135deg, var(--color-bg-warm), var(--color-bg-deep));
}

.cover-category {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-accent);
}

.cover-title {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  color: var(--color-ink);
  line-height: 1.3;
}

.cover-author {
  font-size: 10px;
  color: var(--color-ink-muted);
  margin-top: auto;
}

/* 书籍信息 */
.book-info {
  padding: 12px 14px 10px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex: 1;
}

.book-name {
  font-family: var(--font-display);
  font-size: 13.5px;
  font-weight: 600;
  color: var(--color-ink);
  margin: 0;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.book-author {
  font-size: 11px;
  color: var(--color-ink-muted);
  margin: 0;
}

.book-meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}

.meta-category {
  font-size: 10px;
  font-weight: 500;
  color: var(--color-info);
  background: var(--color-info-soft);
  padding: 1px 6px;
  border-radius: 3px;
}

.meta-pages {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--color-ink-faint);
}

/* 段落切分质量标识 */
.meta-seg {
  font-size: 11px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 3px;
  cursor: help;
  border: 1px solid transparent;
}

.meta-seg.seg-ok {
  color: var(--color-success);
  background: var(--color-success-soft);
}

.meta-seg.seg-warn {
  color: var(--color-accent);
  background: var(--color-accent-soft);
  border-color: #fde68a;
}

.meta-seg.seg-coarse {
  color: var(--color-ink-muted);
  background: var(--color-bg-deep);
  border-color: var(--color-border-deep);
}

.book-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}

.book-tag {
  font-size: 10px;
  color: var(--color-ink-muted);
  background: var(--color-bg-warm);
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid var(--color-border);
}

.book-tag.more {
  background: transparent;
  border: none;
  color: var(--color-ink-faint);
}

.book-action {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  border-top: 1px solid var(--color-border);
  background: var(--color-bg);
  transition: all 0.2s ease;
}

.action-text {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-ink-muted);
}

.action-arrow {
  font-size: 12px;
  color: var(--color-ink-faint);
  transition: transform 0.15s;
}

.book-card:hover .action-text {
  color: var(--color-accent);
}

.book-card:hover .action-arrow {
  color: var(--color-accent);
  transform: translateX(3px);
}

/* ==================== 新建会话 Modal ==================== */
.session-mode-hint {
  font-size: 12px;
  color: var(--color-ink-muted);
  margin: 10px 0 14px;
  padding: 6px 10px;
  background: var(--color-bg-warm);
  border-radius: var(--radius-sm);
  line-height: 1.4;
}

.session-field {
  margin-top: 4px;
}

.session-field-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-ink-muted);
  margin-bottom: 8px;
}

.session-book-list {
  max-height: 280px;
  overflow-y: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session-book-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background 0.15s;
  font-size: 12px;
}

.session-book-item:hover {
  background: var(--color-bg-warm);
}

.session-book-item.selected {
  background: var(--color-info-soft);
  font-weight: 500;
}

.sb-check {
  font-size: 12px;
  width: 16px;
  text-align: center;
  flex-shrink: 0;
  color: var(--color-ink-muted);
}

.session-book-item.selected .sb-check {
  color: var(--color-accent);
}

.sb-name {
  flex: 1;
  color: var(--color-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sb-cat {
  font-size: 10px;
  color: var(--color-ink-faint);
  flex-shrink: 0;
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-no-books {
  padding: 20px;
  text-align: center;
  color: var(--color-ink-faint);
  font-size: 12px;
}

.session-more-hint {
  padding: 6px 10px;
  font-size: 11px;
  color: var(--color-ink-muted);
  text-align: center;
}
</style>
