<template>
  <n-drawer v-model:show="showDrawer" :width="760" placement="right">
    <n-drawer-content title="📚 馆藏图书与多维分类中心" closable>
      <div class="shelf-drawer-body">
        <!-- 统计与操作 -->
        <div class="shelf-stats-bar">
          <div class="stats-group">
            <span class="stat-badge">馆藏文献: <strong>{{ books.length }}</strong> 本</span>
            <span class="stat-badge">累计总页数: <strong>{{ totalPages }}</strong> 页</span>
            <span class="stat-badge">分类领域: <strong>{{ categoryList.length }}</strong> 类</span>
          </div>

          <div class="search-box">
            <n-input
              v-model:value="searchKeyword"
              placeholder="搜索书名、作者或标签..."
              clearable
              size="small"
              style="width: 240px;"
              @update:value="filterBooks"
            />
          </div>
        </div>

        <!-- 分类选择 -->
        <div class="category-pills">
          <n-tag
            :checked="selectedCategory === 'all'"
            checkable
            size="small"
            @click="selectCategory('all')"
          >
            全部 ({{ books.length }})
          </n-tag>
          <n-tag
            v-for="cat in categoryList"
            :key="cat"
            :checked="selectedCategory === cat"
            checkable
            size="small"
            @click="selectCategory(cat)"
          >
            {{ cat }} ({{ getBookCountByCategory(cat) }})
          </n-tag>
        </div>

        <!-- 书籍卡片列表 -->
        <n-spin :show="loading">
          <div class="books-scroll-list">
            <div v-if="filteredBooks.length === 0" class="empty-hint">
              未找到符合条件的书籍
            </div>

            <div
              v-for="b in filteredBooks"
              :key="b.id"
              class="drawer-book-card"
            >
              <div class="card-top-row">
                <div class="book-main-title">
                  <span class="book-icon">📖</span>
                  <span class="title-bold" :title="b.title">《{{ b.title }}》</span>
                </div>
                <div class="book-tags-row">
                  <n-tag size="tiny" type="info" round>{{ b.primaryCategory }}</n-tag>
                  <n-tag size="tiny" type="default" round>{{ b.pageCount }} 页</n-tag>
                </div>
              </div>

              <div class="card-author-row">
                <span>作者/出处：{{ b.authors?.join('、') || '马克思主义文献库' }}</span>
              </div>

              <!-- 动态标签展示 -->
              <div class="tags-cluster">
                <n-tag
                  v-for="t in b.tags"
                  :key="t"
                  size="tiny"
                  round
                  :bordered="false"
                  class="custom-tag"
                >
                  #{{ t }}
                </n-tag>
                <n-button size="tiny" quaternary circle @click="openAddTagModal(b)">
                  +
                </n-button>
              </div>

              <div class="card-footer-actions">
                <n-button
                  size="tiny"
                  type="primary"
                  secondary
                  @click="handleSelectForParallelRead(b)"
                >
                  📖 原文并行预览
                </n-button>
                <n-button
                  size="tiny"
                  quaternary
                  @click="handleSelectForChat(b)"
                >
                  💬 开启单书研读
                </n-button>
              </div>
            </div>
          </div>
        </n-spin>
      </div>
    </n-drawer-content>

    <!-- 打标 Modal -->
    <n-modal v-model:show="showTagModal" preset="dialog" title="为书籍添加主题标签">
      <div style="padding: 12px 0;">
        <p style="margin-bottom: 8px; font-size: 13px;">正在为《{{ currentEditingBook?.title }}》添加标签：</p>
        <n-input v-model:value="newTagInput" placeholder="输入新标签名，例如：唯物主义、经济学" />
      </div>
      <template #action>
        <n-button size="small" @click="showTagModal = false">取消</n-button>
        <n-button size="small" type="primary" :disabled="!newTagInput.trim()" @click="confirmAddTag">
          保存标签
        </n-button>
      </template>
    </n-modal>
  </n-drawer>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useMessage } from 'naive-ui'

const props = defineProps({
  show: { type: Boolean, default: false }
})

const emit = defineEmits(['update:show', 'select-book-for-qa', 'select-book-for-read'])

const message = useMessage()

const showDrawer = computed({
  get: () => props.show,
  set: (val) => emit('update:show', val)
})

const books = ref([])
const filteredBooks = ref([])
const loading = ref(false)
const searchKeyword = ref('')
const selectedCategory = ref('all')

const showTagModal = ref(false)
const currentEditingBook = ref(null)
const newTagInput = ref('')

const categoryList = [
  '政治经济与社会主义',
  '历史与人物传记',
  '哲学与方法论',
  '文化与社会研究'
]

const totalPages = computed(() => books.value.reduce((acc, b) => acc + (b.pageCount || 0), 0))

onMounted(() => {
  loadBooks()
})

watch(() => props.show, (val) => {
  if (val && books.value.length === 0) {
    loadBooks()
  }
})

async function loadBooks() {
  loading.value = true
  try {
    if (window.api?.listBooks) {
      const res = await window.api.listBooks()
      if (res.success && Array.isArray(res.data)) {
        books.value = res.data
        filterBooks()
      }
    }
  } catch (err) {
    console.error('加载图书失败:', err)
  } finally {
    loading.value = false
  }
}

function filterBooks() {
  let list = books.value

  if (selectedCategory.value !== 'all') {
    list = list.filter(b => b.primaryCategory === selectedCategory.value)
  }

  if (searchKeyword.value.trim()) {
    const kw = searchKeyword.value.trim().toLowerCase()
    list = list.filter(b => {
      const titleMatch = b.title?.toLowerCase().includes(kw)
      const catMatch = b.primaryCategory?.toLowerCase().includes(kw)
      const tagMatch = b.tags?.some(t => t.toLowerCase().includes(kw))
      return titleMatch || catMatch || tagMatch
    })
  }

  filteredBooks.value = list
}

function selectCategory(cat) {
  selectedCategory.value = cat
  filterBooks()
}

function getBookCountByCategory(cat) {
  return books.value.filter(b => b.primaryCategory === cat).length
}

function handleSelectForParallelRead(book) {
  showDrawer.value = false
  emit('select-book-for-read', book)
}

function handleSelectForChat(book) {
  showDrawer.value = false
  emit('select-book-for-qa', book)
}

function openAddTagModal(book) {
  currentEditingBook.value = book
  newTagInput.value = ''
  showTagModal.value = true
}

async function confirmAddTag() {
  if (!currentEditingBook.value || !newTagInput.value.trim()) return
  const tag = newTagInput.value.trim().replace(/^#/, '')
  const currentTags = Array.isArray(currentEditingBook.value.tags) ? [...currentEditingBook.value.tags] : []
  if (!currentTags.includes(tag)) {
    currentTags.push(tag)
    try {
      if (window.api?.updateBookClassification) {
        await window.api.updateBookClassification({
          bookId: currentEditingBook.value.id,
          category: currentEditingBook.value.primaryCategory,
          tags: currentTags
        })
        currentEditingBook.value.tags = currentTags
        message.success(`已为《${currentEditingBook.value.title}》添加标签 #${tag}`)
      }
    } catch (e) {
      message.error('保存标签失败: ' + e.message)
    }
  }
  showTagModal.value = false
}
</script>

<style scoped>
.shelf-drawer-body {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 16px;
}

.shelf-stats-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 12px;
  border-bottom: 1px solid #f1f5f9;
}

.stats-group {
  display: flex;
  gap: 12px;
}

.stat-badge {
  font-size: 12px;
  color: #64748b;
  background: #f8fafc;
  padding: 4px 8px;
  border-radius: 6px;
}

.category-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.books-scroll-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
  max-height: calc(100vh - 200px);
  padding-right: 4px;
}

.empty-hint {
  text-align: center;
  color: #94a3b8;
  font-size: 13px;
  margin-top: 40px;
}

.drawer-book-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px 14px;
  transition: all 0.2s ease;
}

.drawer-book-card:hover {
  border-color: #cbd5e1;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.card-top-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.book-main-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 700;
  color: #1e293b;
  max-width: 440px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.book-tags-row {
  display: flex;
  gap: 6px;
}

.card-author-row {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 8px;
}

.tags-cluster {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}

.custom-tag {
  background: #f1f5f9;
  color: #475569;
}

.card-footer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px dashed #f1f5f9;
}
</style>
