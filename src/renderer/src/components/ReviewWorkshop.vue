<template>
  <div class="review-workshop-container">
    <div class="workshop-header">
      <h2>📝 深度书评与学术研读工坊</h2>
      <p>超越简单的问答检索，基于原著逻辑体系生成深度书评导读、知识框架脑图及跨书观点对比矩阵。</p>
    </div>

    <n-tabs type="line" animated>
      <!-- Tab 1: 单书深度导读与学术书评 -->
      <n-tab-pane name="single_review" tab="📖 单书精读导读">
        <div class="pane-content">
          <div class="selection-row">
            <span style="font-weight: 500;">选择精读书目：</span>
            <n-select
              v-model:value="selectedBookId"
              :options="bookOptions"
              filterable
              placeholder="选择文献..."
              style="width: 320px;"
            />
            <n-button type="primary" :loading="loadingReview" :disabled="!selectedBookId" @click="generateReview">
              ✨ 生成深度书评
            </n-button>
          </div>

          <div v-if="reviewReport" class="report-container">
            <n-card class="report-card">
              <div class="report-badge">📘 深度学术书评报告</div>
              <h1 class="report-title">《{{ reviewReport.bookTitle }}》体系性解读</h1>
              <div class="report-tags">
                <n-tag size="small" type="info">{{ reviewReport.category }}</n-tag>
                <n-tag v-for="t in reviewReport.tags" :key="t" size="small"># {{ t }}</n-tag>
                <span class="report-page-count">共 {{ reviewReport.pageCount }} 页</span>
              </div>

              <n-divider />

              <div class="report-section">
                <h3>一、核心论旨与时代命题 (Core Thesis)</h3>
                <p class="thesis-box">{{ reviewReport.coreThesis }}</p>
              </div>

              <div class="report-section">
                <h3>二、全书架构与导读指引 (Architecture)</h3>
                <div class="markdown-preview" v-html="renderMarkdown(reviewReport.structureSummary)"></div>
              </div>

              <div class="report-section">
                <h3>三、批判性反思与现代价值 (Critique & Reflections)</h3>
                <div class="markdown-preview" v-html="renderMarkdown(reviewReport.critique)"></div>
              </div>

              <div class="report-section">
                <h3>四、原典核心锚点证据 (Evidence Anchors)</h3>
                <div class="anchor-list">
                  <div
                    v-for="(anc, idx) in reviewReport.anchors"
                    :key="idx"
                    class="anchor-item"
                    @click="openSourceDrawer(anc)"
                  >
                    <div class="anchor-page">{{ anc.page || '出处' }}</div>
                    <div class="anchor-excerpt">“{{ anc.excerpt }}”</div>
                    <div class="anchor-hint">点击查看原文抽屉 ➔</div>
                  </div>
                </div>
              </div>
            </n-card>
          </div>
        </div>
      </n-tab-pane>

      <!-- Tab 2: 跨书多方观点对比 -->
      <n-tab-pane name="compare_review" tab="⚖️ 跨书观点碰撞">
        <div class="pane-content">
          <div class="compare-controls">
            <n-input
              v-model:value="compareTopic"
              placeholder="输入对比的核心议题（例如：巴黎公社与无产阶级国家学说、工人诗歌动员方式...）"
              style="max-width: 480px;"
            />
            <n-button type="primary" :loading="loadingCompare" :disabled="!compareTopic.trim()" @click="runComparison">
              ⚔️ 观点碰撞对比
            </n-button>
          </div>

          <div v-if="comparisonData" class="comparison-results">
            <h3>议题对比矩阵：{{ comparisonData.topic }}</h3>
            <div class="matrix-grid">
              <n-card
                v-for="(item, idx) in comparisonData.comparisonMatrix"
                :key="idx"
                class="matrix-card"
                size="small"
              >
                <div class="matrix-book-header">
                  <strong>《{{ item.bookTitle }}》</strong>
                  <n-tag size="tiny" type="info">{{ item.page }}</n-tag>
                </div>
                <blockquote class="matrix-quote">
                  “{{ item.representativeExcerpt }}”
                </blockquote>
                <div class="matrix-footer">
                  <span style="font-size: 11px; color: #a0aec0;">匹配关联证据 {{ item.evidenceCount }} 处</span>
                  <n-button size="tiny" quaternary type="primary" @click="openSourceDrawer(item)">
                    📖 查看上下文
                  </n-button>
                </div>
              </n-card>
            </div>
          </div>
        </div>
      </n-tab-pane>
    </n-tabs>

    <!-- 侧边原文抽屉 -->
    <SourceDrawer ref="sourceDrawerRef" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { marked } from 'marked'
import SourceDrawer from './SourceDrawer.vue'

const message = useMessage()
const sourceDrawerRef = ref(null)

const books = ref([])
const selectedBookId = ref(null)
const loadingReview = ref(false)
const reviewReport = ref(null)

const compareTopic = ref('巴黎公社的历史经验与工人运动')
const loadingCompare = ref(false)
const comparisonData = ref(null)

const bookOptions = computed(() => books.value.map(b => ({ label: `《${b.title}》`, value: b.id })))

async function loadBooks() {
  if (window.api?.listBooks) {
    const res = await window.api.listBooks()
    if (res.success) {
      books.value = res.data
      if (books.value.length > 0) {
        selectedBookId.value = books.value[0].id
      }
    }
  }
}

async function generateReview() {
  if (!selectedBookId.value) return
  loadingReview.value = true
  try {
    if (window.api?.generateReview) {
      const res = await window.api.generateReview(selectedBookId.value)
      if (res.success) {
        reviewReport.value = res.data
      } else {
        message.error('生成书评失败: ' + res.error)
      }
    }
  } catch (err) {
    message.error('生成书评异常')
  } finally {
    loadingReview.value = false
  }
}

async function runComparison() {
  if (!compareTopic.value.trim()) return
  loadingCompare.value = true
  try {
    if (window.api?.compareBooks) {
      const res = await window.api.compareBooks({ topic: compareTopic.value, bookIds: [] })
      if (res.success) {
        comparisonData.value = res.data
      }
    }
  } catch (err) {
    message.error('对比分析异常')
  } finally {
    loadingCompare.value = false
  }
}

function openSourceDrawer(anc) {
  sourceDrawerRef.value?.open({
    id: anc.evidenceId || `ev_${Date.now()}`,
    bookTitle: reviewReport.value?.bookTitle || anc.bookTitle || '原著',
    printedPage: anc.page,
    pageIndex: 0,
    excerpt: anc.excerpt || anc.representativeExcerpt
  })
}

function renderMarkdown(md) {
  return marked.parse(md || '')
}

onMounted(() => {
  loadBooks()
})
</script>

<style scoped>
.review-workshop-container {
  height: 100%;
  overflow-y: auto;
  padding: 24px 32px;
}
.workshop-header {
  margin-bottom: 20px;
}
.workshop-header h2 {
  margin: 0 0 6px 0;
  font-size: 20px;
  color: #1a202c;
}
.workshop-header p {
  margin: 0;
  font-size: 13px;
  color: #718096;
}
.pane-content {
  padding-top: 16px;
}
.selection-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
}
.report-card {
  border-radius: 12px;
  padding: 16px 20px;
}
.report-badge {
  font-size: 12px;
  font-weight: 600;
  color: #3182ce;
  margin-bottom: 6px;
}
.report-title {
  margin: 0 0 10px 0;
  font-size: 22px;
  color: #1a202c;
}
.report-tags {
  display: flex;
  align-items: center;
  gap: 8px;
}
.report-page-count {
  font-size: 12px;
  color: #a0aec0;
  margin-left: 12px;
}
.report-section {
  margin-top: 24px;
}
.report-section h3 {
  margin: 0 0 10px 0;
  font-size: 16px;
  color: #2d3748;
}
.thesis-box {
  background: #f7fafc;
  border-left: 4px solid #3182ce;
  padding: 12px 16px;
  font-size: 14px;
  line-height: 1.6;
  color: #2b6cb0;
  border-radius: 0 6px 6px 0;
}
.anchor-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.anchor-item {
  background: #fffdf5;
  border: 1px solid #f6e05e;
  border-radius: 6px;
  padding: 10px 14px;
  cursor: pointer;
  transition: background 0.2s;
}
.anchor-item:hover {
  background: #fefcbf;
}
.anchor-page {
  font-size: 12px;
  font-weight: 600;
  color: #b7791f;
  margin-bottom: 4px;
}
.anchor-excerpt {
  font-size: 13px;
  color: #2d3748;
  line-height: 1.5;
}
.anchor-hint {
  font-size: 11px;
  color: #3182ce;
  text-align: right;
  margin-top: 4px;
}
.compare-controls {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
}
.matrix-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
  margin-top: 14px;
}
.matrix-card {
  border-radius: 8px;
}
.matrix-book-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.matrix-quote {
  margin: 0;
  font-size: 13px;
  color: #4a5568;
  line-height: 1.6;
  background: #f7fafc;
  padding: 8px 10px;
  border-radius: 4px;
}
.matrix-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 10px;
}
</style>
