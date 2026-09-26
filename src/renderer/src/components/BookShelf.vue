<template>
  <div class="bookshelf-container">
    <!-- 顶部操作栏与统计 -->
    <div class="header-bar">
      <div class="stats-overview">
        <n-statistic label="馆藏文献总数" :value="books.length">
          <template #suffix>本</template>
        </n-statistic>
        <n-statistic label="累计总页数" :value="totalPages" style="margin-left: 24px;">
          <template #suffix>页</template>
        </n-statistic>
        <n-statistic label="分类体系数" :value="categoryList.length" style="margin-left: 24px;">
          <template #suffix>类</template>
        </n-statistic>
      </div>

      <div class="filter-controls">
        <n-input
          v-model:value="searchKeyword"
          placeholder="快速搜索书名..."
          clearable
          style="width: 220px;"
          @update:value="filterBooks"
        />
        <n-button type="warning" secondary :loading="syncing" @click="handleSyncProcessed">
          📥 扫描并入库已处理书籍
        </n-button>
        <n-button type="primary" @click="loadBooks">
          🔄 刷新书库
        </n-button>
      </div>
    </div>

    <!-- 分类与标签快捷筛选栏 -->
    <div class="category-tabs">
      <n-radio-group v-model:value="selectedCategory" size="small" @update:value="filterBooks">
        <n-radio-button value="all">全部书目 ({{ books.length }})</n-radio-button>
        <n-radio-button v-for="cat in categoryList" :key="cat" :value="cat">
          {{ cat }} ({{ getBookCountByCategory(cat) }})
        </n-radio-button>
      </n-radio-group>
    </div>

    <!-- 书籍网格卡片 -->
    <n-spin :show="loading">
      <div v-if="filteredBooks.length === 0" class="empty-state">
        <n-empty description="未找到符合条件的书籍" />
      </div>

      <div v-else class="book-grid">
        <n-card
          v-for="b in filteredBooks"
          :key="b.id"
          hoverable
          class="book-card"
          size="small"
        >
          <div class="card-header">
            <span class="category-tag">{{ b.primaryCategory }}</span>
            <span class="page-tag">{{ b.pageCount }} 页</span>
          </div>

          <h3 class="book-title" :title="b.title">{{ b.title }}</h3>
          <p class="book-author">编审/作者：{{ b.authors.join(', ') }}</p>

          <!-- 标签展示 -->
          <div class="tags-container">
            <n-tag
              v-for="tag in b.tags"
              :key="tag"
              size="tiny"
              type="info"
              round
            >
              # {{ tag }}
            </n-tag>
          </div>

          <!-- 底部操作按钮 -->
          <template #action>
            <div class="card-actions">
              <n-button size="tiny" quaternary type="primary" @click="openOutline(b)">
                📑 大纲
              </n-button>
              <n-button size="tiny" quaternary type="warning" @click="openTagModal(b)">
                🏷️ 打标
              </n-button>
              <n-button size="tiny" quaternary type="info" @click="$emit('select-book-for-read', b)">
                📖 通读
              </n-button>
              <n-button size="tiny" type="primary" secondary @click="$emit('select-book-for-qa', b)">
                💬 研读
              </n-button>
            </div>
          </template>
        </n-card>
      </div>
    </n-spin>

    <!-- 目录大纲模态框 -->
    <n-modal v-model:show="showOutlineModal" preset="card" title="📚 目录大纲架构" style="width: 600px;">
      <div v-if="outlineLoading" style="text-align:center; padding: 20px;">
        <n-spin />
      </div>
      <div v-else class="outline-content">
        <h3>《{{ currentBook?.title }}》</h3>
        <p style="color: #666; font-size: 13px;">所属分类：{{ currentBook?.primaryCategory }} | 总页数：{{ currentBook?.pageCount }} 页</p>
        <n-divider style="margin: 12px 0;" />
        <div v-if="!currentBook?.toc?.length" style="color: #999;">
          该文献原始扫描件未嵌入标准书签，已在后台自动进行页面与段落切片。
        </div>
        <div v-else class="toc-list">
          <div v-for="t in currentBook.toc" :key="t.id" class="toc-item">
            <span class="toc-title">{{ t.title }}</span>
            <span class="toc-page">第 {{ t.pageIndex + 1 }} 页</span>
          </div>
        </div>
      </div>
    </n-modal>

    <!-- 分类打标模态框 -->
    <n-modal v-model:show="showTagModal" preset="dialog" title="🏷️ 调整书籍分类与标签" positive-text="保存" negative-text="取消" @positive-click="saveTags">
      <div v-if="tagEditingBook" style="display: flex; flex-direction: column; gap: 14px; margin-top: 10px;">
        <div><strong>书名：</strong>《{{ tagEditingBook.title }}》</div>
        <div>
          <label style="display:block; margin-bottom: 6px; font-weight: 500;">主学科/领域分类：</label>
          <n-select v-model:value="editCategory" :options="categorySelectOptions" />
        </div>
        <div>
          <label style="display:block; margin-bottom: 6px; font-weight: 500;">主题标签（支持自定义输入并按回车）：</label>
          <n-dynamic-tags v-model:value="editTags" />
        </div>
      </div>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { DEFAULT_CATEGORIES } from '../../../main/domain/TagTaxonomy.js'

defineEmits(['select-book-for-qa', 'select-book-for-read'])

const message = useMessage()

const books = ref([])
const loading = ref(false)
const syncing = ref(false)
const searchKeyword = ref('')
const selectedCategory = ref('all')

async function handleSyncProcessed() {
  if (!window.api?.syncProcessedBooks) {
    message.error('未检测到 Electron 通信桥接 (window.api)，请稍候或重启应用')
    return
  }
  syncing.value = true
  message.info('正在扫描已提取典籍切片并构建全文索引，请稍候...')
  try {
    const res = await window.api.syncProcessedBooks()
    if (res.success && res.data) {
      message.success(`扫描完成！发现 ${res.data.discoveredBooks} 本，新增入库 ${res.data.newlyIngested} 本（索引 ${res.data.totalParagraphsIndexed} 段落）`)
      await loadBooks()
    } else {
      message.warning('扫描未发现新处理书籍: ' + (res.error || '无变更'))
    }
  } catch (err) {
    message.error('扫描切片入库异常: ' + err.message)
  } finally {
    syncing.value = false
  }
}

const showOutlineModal = ref(false)
const outlineLoading = ref(false)
const currentBook = ref(null)

const showTagModal = ref(false)
const tagEditingBook = ref(null)
const editCategory = ref('')
const editTags = ref([])

const categorySelectOptions = DEFAULT_CATEGORIES.map(c => ({ label: c.name, value: c.name }))

const totalPages = computed(() => books.value.reduce((acc, b) => acc + (b.pageCount || 0), 0))

const categoryList = computed(() => {
  const set = new Set()
  books.value.forEach(b => {
    if (b.primaryCategory) set.add(b.primaryCategory)
  })
  return Array.from(set)
})

const filteredBooks = computed(() => {
  return books.value.filter(b => {
    if (selectedCategory.value !== 'all' && b.primaryCategory !== selectedCategory.value) {
      return false
    }
    if (searchKeyword.value) {
      const q = searchKeyword.value.toLowerCase()
      const titleMatch = b.title.toLowerCase().includes(q)
      const tagMatch = b.tags?.some(t => t.toLowerCase().includes(q))
      return titleMatch || tagMatch
    }
    return true
  })
})

function getBookCountByCategory(cat) {
  return books.value.filter(b => b.primaryCategory === cat).length
}

async function loadBooks() {
  loading.value = true
  try {
    if (window.api?.listBooks) {
      const res = await window.api.listBooks()
      if (res.success) {
        books.value = res.data
      }
    }
  } catch (err) {
    message.error('加载书库失败: ' + err.message)
  } finally {
    loading.value = false
  }
}

async function openOutline(book) {
  currentBook.value = book
  showOutlineModal.value = true
  outlineLoading.value = true
  try {
    if (window.api?.getBook) {
      const res = await window.api.getBook(book.id)
      if (res.success && res.data) {
        currentBook.value = res.data
      }
    }
  } catch (err) {
    message.error('获取大纲失败')
  } finally {
    outlineLoading.value = false
  }
}

function openTagModal(book) {
  tagEditingBook.value = book
  editCategory.value = book.primaryCategory || '未分类'
  editTags.value = [...(book.tags || [])]
  showTagModal.value = true
}

async function saveTags() {
  if (!tagEditingBook.value) return
  try {
    if (window.api?.updateBookClassification) {
      await window.api.updateBookClassification({
        bookId: tagEditingBook.value.id,
        category: editCategory.value,
        tags: editTags.value
      })
      tagEditingBook.value.primaryCategory = editCategory.value
      tagEditingBook.value.tags = editTags.value
      message.success('分类与标签已成功保存')
      loadBooks()
    }
  } catch (err) {
    message.error('保存失败: ' + err.message)
  }
}

function filterBooks() {}

onMounted(() => {
  loadBooks()
})
</script>

<style scoped>
.bookshelf-container {
  height: 100%;
  overflow-y: auto;
  padding: 24px;
}
.header-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #ffffff;
  padding: 16px 20px;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  margin-bottom: 16px;
}
.stats-overview {
  display: flex;
}
.filter-controls {
  display: flex;
  gap: 12px;
}
.category-tabs {
  margin-bottom: 20px;
}
.book-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
  gap: 16px;
}
.book-card {
  border-radius: 10px;
  transition: transform 0.2s, box-shadow 0.2s;
}
.book-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(0,0,0,0.06);
}
.card-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}
.category-tag {
  font-size: 12px;
  color: #2b6cb0;
  background: #ebf8ff;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 500;
}
.page-tag {
  font-size: 12px;
  color: #a0aec0;
}
.book-title {
  margin: 0 0 6px 0;
  font-size: 15px;
  color: #1a202c;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.book-author {
  margin: 0 0 10px 0;
  font-size: 12px;
  color: #718096;
}
.tags-container {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 24px;
}
.card-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.toc-list {
  max-height: 380px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.toc-item {
  display: flex;
  justify-content: space-between;
  padding: 6px 10px;
  background: #f7fafc;
  border-radius: 6px;
  font-size: 13px;
}
.toc-title {
  color: #2d3748;
}
.toc-page {
  color: #a0aec0;
}
.empty-state {
  padding: 60px;
  text-align: center;
}
</style>
