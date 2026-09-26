<template>
  <n-config-provider :theme-overrides="themeOverrides">
    <n-message-provider>
      <n-dialog-provider>
        <div class="app-shell">
          <!-- 左侧仿小鸡助手现代侧边栏 (以会话管理为主要界面) -->
          <aside class="app-sidebar" :class="{ 'is-collapsed': isSidebarCollapsed }">
            <!-- 品牌与折叠开关 -->
            <div class="sidebar-header">
              <div class="brand-row" v-if="!isSidebarCollapsed">
                <div class="brand-info" @click="activeView = 'chat'">
                  <div class="brand-avatar">🐥</div>
                  <div class="brand-text-group">
                    <span class="brand-title">小鸡书友</span>
                    <span class="brand-subtitle">图书伴读与考据 ✨</span>
                  </div>
                </div>
                <n-tooltip trigger="hover" placement="right">
                  <template #trigger>
                    <n-button quaternary circle size="small" class="collapse-btn" @click="toggleSidebar">
                      <template #icon><n-icon><ChevronBackOutline /></n-icon></template>
                    </n-button>
                  </template>
                  折叠侧边栏
                </n-tooltip>
              </div>

              <!-- 折叠状态下的品牌触发器 -->
              <div class="collapsed-brand-row" v-else>
                <n-tooltip trigger="hover" placement="right">
                  <template #trigger>
                    <div class="collapsed-avatar" @click="toggleSidebar">
                      🐥
                    </div>
                  </template>
                  展开侧边栏
                </n-tooltip>
              </div>

              <!-- 新建研读对话按钮 -->
              <div class="new-chat-box">
                <n-button
                  v-if="!isSidebarCollapsed"
                  type="primary"
                  secondary
                  block
                  class="new-chat-btn"
                  @click="handleCreateNewSession"
                >
                  <template #icon><n-icon><AddOutline /></n-icon></template>
                  新建研读对话
                </n-button>

                <n-tooltip v-else trigger="hover" placement="right">
                  <template #trigger>
                    <n-button
                      type="primary"
                      secondary
                      circle
                      size="small"
                      class="new-chat-circle-btn"
                      @click="handleCreateNewSession"
                    >
                      <template #icon><n-icon><AddOutline /></n-icon></template>
                    </n-button>
                  </template>
                  新建研读对话
                </n-tooltip>
              </div>
            </div>

            <!-- 会话管理列表 (主要界面) -->
            <div class="sidebar-session-section" v-if="!isSidebarCollapsed">
              <div class="session-section-header">
                <span class="section-title">研读会话</span>
                <span class="session-badge" v-if="sessionsList.length > 0">{{ sessionsList.length }}</span>
              </div>

              <div class="session-list-scroll">
                <div
                  v-for="s in sessionsList"
                  :key="s.id"
                  :class="['session-item-card', { active: s.id === currentSessionId && activeView === 'chat' }]"
                  @click="handleSelectSession(s.id)"
                >
                  <div class="session-item-content">
                    <span class="session-item-title" :title="s.title">{{ s.title || '研读对话' }}</span>
                    <span class="session-item-time">{{ formatTime(s.updatedAt) }}</span>
                  </div>

                  <!-- 悬浮操作图标 -->
                  <div class="session-item-actions" @click.stop>
                    <n-tooltip trigger="hover">
                      <template #trigger>
                        <n-button quaternary circle size="tiny" @click="openRenameModal(s.id, s.title)">
                          <template #icon><n-icon size="13"><CreateOutline /></n-icon></template>
                        </n-button>
                      </template>
                      重命名
                    </n-tooltip>

                    <n-popconfirm @positive-click="handleDeleteSession(s.id)" positive-text="删除" negative-text="取消">
                      <template #trigger>
                        <n-button quaternary circle size="tiny" class="delete-btn">
                          <template #icon><n-icon size="13"><TrashOutline /></n-icon></template>
                        </n-button>
                      </template>
                      确定移除该研读会话记录吗？
                    </n-popconfirm>
                  </div>
                </div>
              </div>
            </div>

            <!-- 折叠状态下的快捷图标会话入口 -->
            <div class="collapsed-session-icons" v-else>
              <n-tooltip v-for="s in sessionsList.slice(0, 6)" :key="s.id" trigger="hover" placement="right">
                <template #trigger>
                  <div
                    class="collapsed-sess-dot"
                    :class="{ active: s.id === currentSessionId && activeView === 'chat' }"
                    @click="handleSelectSession(s.id)"
                  >
                    💬
                  </div>
                </template>
                {{ s.title }}
              </n-tooltip>
            </div>

            <!-- 侧边栏底部快捷功能导航 -->
            <div class="sidebar-footer-nav">
              <div
                class="footer-nav-item"
                :class="{ active: activeView === 'chat' }"
                @click="activeView = 'chat'"
                title="伴读对话主窗口"
              >
                <n-icon size="18"><ChatbubbleEllipsesOutline /></n-icon>
                <span class="footer-nav-label" v-if="!isSidebarCollapsed">伴读对话</span>
              </div>

              <div
                class="footer-nav-item"
                :class="{ active: activeView === 'reader' }"
                @click="openParallelReaderDirect"
                title="原文并行阅读器 (原件影印与提取文字左右对照)"
              >
                <n-icon size="18"><BookOutline /></n-icon>
                <span class="footer-nav-label" v-if="!isSidebarCollapsed">原文并行预览</span>
              </div>

              <div
                class="footer-nav-item"
                @click="showShelfDrawer = true"
                title="馆藏 67 本图书与分类标签检索"
              >
                <n-icon size="18"><LibraryOutline /></n-icon>
                <span class="footer-nav-label" v-if="!isSidebarCollapsed">馆藏书库</span>
              </div>
            </div>
          </aside>

          <!-- 右侧主要工作区 -->
          <main class="app-main-content">
            <!-- 核心主题：聊天会话工作台 -->
            <ChatWorkbench
              ref="chatWorkbenchRef"
              v-show="activeView === 'chat'"
              :current-session-id="currentSessionId"
              :current-session-title="currentSessionTitle"
              @start-rename-session="openRenameModal(currentSessionId, currentSessionTitle)"
              @session-updated="handleSessionUpdated"
              @open-parallel-reader="handleJumpToParallelReader"
            />

            <!-- 新增核心：原文阅读 (提取的文字和原书原件并行预览) -->
            <ParallelReader
              ref="parallelReaderRef"
              v-show="activeView === 'reader'"
              :initial-book-id="readerTargetBookId"
              :initial-page="readerTargetPage"
              :initial-paragraph-id="readerTargetParagraphId"
              @back-to-chat="activeView = 'chat'"
              @ask-question="handleAskFromReader"
            />
          </main>

          <!-- 馆藏书库抽屉 (按需打开，不喧宾夺主) -->
          <BookShelfDrawer
            v-model:show="showShelfDrawer"
            @select-book-for-qa="handleSelectBookForQA"
            @select-book-for-read="handleSelectBookForRead"
          />

          <!-- 会话重命名 Modal -->
          <n-modal v-model:show="showRenameModal" preset="dialog" title="重命名研读会话">
            <div style="padding: 12px 0;">
              <n-input
                v-model:value="renameInputTitle"
                placeholder="请输入会话新标题"
                @keydown.enter="confirmRenameSession"
                autofocus
              />
            </div>
            <template #action>
              <n-button size="small" @click="showRenameModal = false">取消</n-button>
              <n-button size="small" type="primary" :disabled="!renameInputTitle.trim()" @click="confirmRenameSession">
                保存
              </n-button>
            </template>
          </n-modal>
        </div>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import {
  ChatbubbleEllipsesOutline,
  BookOutline,
  LibraryOutline,
  AddOutline,
  CreateOutline,
  TrashOutline,
  ChevronBackOutline,
  ChevronForwardOutline
} from '@vicons/ionicons5'

import ChatWorkbench from './components/ChatWorkbench.vue'
import ParallelReader from './components/ParallelReader.vue'
import BookShelfDrawer from './components/BookShelfDrawer.vue'

// 主题样式定制 (小鸡书友暖色与科技青蓝)
const themeOverrides = {
  common: {
    primaryColor: '#f59e0b',
    primaryColorHover: '#d97706',
    primaryColorPressed: '#b45309',
    primaryColorSuppl: '#fef3c7',
    infoColor: '#2563eb'
  }
}

// 视图切换状态 ('chat', 'reader')
const activeView = ref('chat')
const isSidebarCollapsed = ref(false)

// 会话管理状态
const sessionsList = ref([])
const currentSessionId = ref('')
const showRenameModal = ref(false)
const renameSessionId = ref('')
const renameInputTitle = ref('')

// 原文阅读器联动状态
const readerTargetBookId = ref(null)
const readerTargetPage = ref(1)
const readerTargetParagraphId = ref(null)

// 书架辅助抽屉
const showShelfDrawer = ref(false)

// 组件引用
const chatWorkbenchRef = ref(null)
const parallelReaderRef = ref(null)

const currentSessionTitle = computed(() => {
  const s = sessionsList.value.find(item => item.id === currentSessionId.value)
  return s?.title || '研读对话'
})

onMounted(async () => {
  await loadSessions()
})

function toggleSidebar() {
  isSidebarCollapsed.value = !isSidebarCollapsed.value
}

async function loadSessions() {
  if (window.api?.listSessions) {
    try {
      const res = await window.api.listSessions()
      if (res.success && Array.isArray(res.data)) {
        sessionsList.value = res.data
        if (sessionsList.value.length > 0 && !currentSessionId.value) {
          currentSessionId.value = sessionsList.value[0].id
        }
      }
    } catch (e) {
      console.warn('Failed to load sessions:', e)
    }
  }
}

async function handleSessionUpdated(newSessionId) {
  await loadSessions()
  if (newSessionId) {
    currentSessionId.value = newSessionId
  }
}

async function handleCreateNewSession() {
  if (window.api?.createSession) {
    try {
      const res = await window.api.createSession({ title: '研读新对话' })
      if (res.success && res.data) {
        await loadSessions()
        currentSessionId.value = res.data.id
        activeView.value = 'chat'
      }
    } catch (e) {
      console.error('Create session error:', e)
    }
  }
}

function handleSelectSession(id) {
  currentSessionId.value = id
  activeView.value = 'chat'
}

function openRenameModal(id, currentTitle) {
  renameSessionId.value = id
  renameInputTitle.value = currentTitle || ''
  showRenameModal.value = true
}

async function confirmRenameSession() {
  const title = renameInputTitle.value.trim()
  if (!title || !renameSessionId.value) return
  if (window.api?.renameSession) {
    await window.api.renameSession({ id: renameSessionId.value, title })
    await loadSessions()
  }
  showRenameModal.value = false
}

async function handleDeleteSession(id) {
  if (window.api?.deleteSession) {
    await window.api.deleteSession(id)
    await loadSessions()
    if (currentSessionId.value === id) {
      currentSessionId.value = sessionsList.value[0]?.id || ''
    }
  }
}

function handleJumpToParallelReader({ bookId, page, paragraphId }) {
  readerTargetBookId.value = bookId
  readerTargetPage.value = page || 1
  readerTargetParagraphId.value = paragraphId || null
  activeView.value = 'reader'

  if (parallelReaderRef.value?.selectBook) {
    parallelReaderRef.value.jumpToPage(page || 1)
  }
}

function openParallelReaderDirect() {
  activeView.value = 'reader'
}

function handleAskFromReader({ question, scope }) {
  activeView.value = 'chat'
  chatWorkbenchRef.value?.askDirectQuestion({ question, scope })
}

function handleSelectBookForQA(book) {
  activeView.value = 'chat'
  chatWorkbenchRef.value?.setTargetBook(book)
}

function handleSelectBookForRead(book) {
  handleJumpToParallelReader({ bookId: book.id, page: 1 })
}

function formatTime(isoStr) {
  if (!isoStr) return ''
  try {
    const d = new Date(isoStr)
    const now = new Date()
    const diffMin = Math.floor((now - d) / (1000 * 60))
    if (diffMin < 2) return '刚刚'
    if (diffMin < 60) return `${diffMin}分钟前`
    const diffHours = Math.floor(diffMin / 60)
    if (diffHours < 24) return `${diffHours}小时前`
    return `${d.getMonth() + 1}/${d.getDate()}`
  } catch {
    return ''
  }
}
</script>

<style scoped>
.app-shell {
  display: flex;
  height: 100vh;
  width: 100vw;
  background-color: #f8fafc;
  overflow: hidden;
}

/* 左侧侧边栏 */
.app-sidebar {
  width: 260px;
  background: #ffffff;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  user-select: none;
  transition: width 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  flex-shrink: 0;
  z-index: 20;
}

.app-sidebar.is-collapsed {
  width: 68px;
}

.sidebar-header {
  padding: 16px 14px 12px;
  border-bottom: 1px solid #f1f5f9;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.brand-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.brand-info {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}

.brand-avatar {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: #fffbeb;
  border: 1px solid #fef3c7;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  box-shadow: 0 2px 4px rgba(245, 158, 11, 0.1);
}

.brand-text-group {
  display: flex;
  flex-direction: column;
}

.brand-title {
  font-weight: 800;
  font-size: 15px;
  color: #0f172a;
  letter-spacing: 0.5px;
}

.brand-subtitle {
  font-size: 11px;
  color: #94a3b8;
}

.collapsed-brand-row {
  display: flex;
  justify-content: center;
}

.collapsed-avatar {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: #fffbeb;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  cursor: pointer;
}

.new-chat-box {
  width: 100%;
}

.new-chat-btn {
  font-weight: 700;
  background: #fffbeb;
  border-color: #fde68a;
  color: #b45309;
  border-radius: 8px;
}

.new-chat-circle-btn {
  background: #fffbeb;
  color: #b45309;
  margin: 0 auto;
  display: flex;
}

/* 会话管理列表 */
.sidebar-session-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 10px 10px 0;
}

.session-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 6px 8px;
}

.section-title {
  font-size: 11px;
  font-weight: 700;
  color: #94a3b8;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

.session-badge {
  font-size: 10px;
  background: #f1f5f9;
  color: #64748b;
  padding: 1px 6px;
  border-radius: 10px;
  font-weight: 600;
}

.session-list-scroll {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-right: 2px;
}

.session-item-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s ease;
  position: relative;
}

.session-item-card:hover {
  background: #f8fafc;
}

.session-item-card.active {
  background: #fffbeb;
  box-shadow: 0 1px 3px rgba(245, 158, 11, 0.08);
}

.session-item-card.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 3px;
  background: #f59e0b;
  border-radius: 2px;
}

.session-item-content {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.session-item-title {
  font-size: 13px;
  color: #334155;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-item-card.active .session-item-title {
  color: #92400e;
  font-weight: 700;
}

.session-item-time {
  font-size: 10px;
  color: #94a3b8;
  margin-top: 2px;
}

.session-item-actions {
  display: none;
  align-items: center;
  gap: 2px;
  margin-left: 6px;
}

.session-item-card:hover .session-item-actions {
  display: flex;
}

/* 折叠图标模式 */
.collapsed-session-icons {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding-top: 12px;
}

.collapsed-sess-dot {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.collapsed-sess-dot:hover {
  background: #f1f5f9;
}

.collapsed-sess-dot.active {
  background: #fef3c7;
}

/* 侧边栏底部导航 */
.sidebar-footer-nav {
  padding: 10px;
  border-top: 1px solid #f1f5f9;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.footer-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s ease;
}

.footer-nav-item:hover {
  background: #f8fafc;
  color: #0f172a;
}

.footer-nav-item.active {
  background: #eff6ff;
  color: #1d4ed8;
  font-weight: 600;
}

.footer-nav-label {
  font-size: 13px;
  white-space: nowrap;
}

/* 右侧主工作区 */
.app-main-content {
  flex: 1;
  height: 100%;
  overflow: hidden;
  position: relative;
}
</style>
