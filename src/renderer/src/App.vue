<template>
  <n-config-provider :theme-overrides="themeOverrides">
    <n-message-provider>
      <n-dialog-provider>
        <div class="app-shell">
          <!-- 左侧极简导航栏 -->
          <aside class="app-sidebar" :class="{ collapsed: sidebarCollapsed }">
            <!-- 品牌标识 -->
            <div class="sidebar-brand">
              <div class="brand-mark-wrap" @click="goHome">
                <span class="mark-symbol">🐔</span>
                <span class="mark-circle"></span>
              </div>
              <transition name="fade-slide">
                <span class="brand-name" v-show="!sidebarCollapsed">小鸡书友</span>
              </transition>
            </div>

            <!-- 主导航 -->
            <nav class="sidebar-nav">
              <template v-for="item in navItems" :key="item.key">
                <n-tooltip v-if="sidebarCollapsed" trigger="hover" placement="right">
                  <template #trigger>
                    <div
                      class="nav-item"
                      :class="{ active: activeView === item.key, disabled: item.disabled }"
                      @click="item.action"
                    >
                      <span class="nav-icon">{{ item.icon }}</span>
                    </div>
                  </template>
                  {{ item.label }}
                </n-tooltip>
                <div
                  v-else
                  class="nav-item"
                  :class="{ active: activeView === item.key, disabled: item.disabled }"
                  @click="item.action"
                >
                  <span class="nav-icon">{{ item.icon }}</span>
                  <span class="nav-text">{{ item.label }}</span>
                </div>
              </template>
            </nav>

            <!-- 新建会话入口 -->
            <n-tooltip v-if="sidebarCollapsed" trigger="hover" placement="right">
              <template #trigger>
                <div class="sidebar-new-session collapsed" @click="openNewSessionFromSidebar">
                  <span class="new-session-icon">＋</span>
                </div>
              </template>
              新建会话
            </n-tooltip>
            <div class="sidebar-new-session" v-else @click="openNewSessionFromSidebar">
              <span class="new-session-icon">＋</span>
              <span class="new-session-label">新建会话</span>
            </div>

            <!-- 研读历史折叠区 -->
            <div class="sidebar-sessions" v-show="!sidebarCollapsed">
              <div class="sessions-collapse-header" @click="sessionsExpanded = !sessionsExpanded">
                <span class="collapse-label">研读历史 ({{ sessionsList.length }})</span>
                <span class="collapse-chevron" :class="{ rotated: sessionsExpanded }">›</span>
              </div>
              <transition name="expand">
                <div class="sessions-mini-list" v-show="sessionsExpanded">
                  <div class="sessions-search" v-if="sessionsList.length > 0">
                    <n-input v-model:value="sessionSearch" size="tiny" placeholder="搜索会话..." clearable />
                  </div>
                  <div
                    v-for="s in filteredSessions"
                    :key="s.id"
                    class="session-mini-item"
                    :class="{ active: s.id === currentSessionId }"
                    @click="openSessionInReader(s.id)"
                  >
                    <span class="mini-title">{{ s.title || '研读对话' }}</span>
                    <span class="mini-time">{{ formatTime(s.updatedAt) }}</span>
                    <span class="mini-delete" title="删除会话" @click.stop="confirmDeleteSession(s)">✕</span>
                  </div>
                  <div v-if="filteredSessions.length === 0" class="sessions-empty">
                    {{ sessionsList.length === 0 ? '暂无研读会话' : '无匹配会话' }}
                  </div>
                </div>
              </transition>
            </div>

            <!-- 折叠态：研读历史飞出面板 -->
            <n-tooltip v-if="sidebarCollapsed" trigger="hover" placement="right">
              <template #trigger>
                <div class="sidebar-sessions-collapsed" @click="sessionsFlyoutOpen = !sessionsFlyoutOpen">
                  <span class="sessions-icon">☰</span>
                  <span v-if="sessionsList.length" class="sessions-badge">{{ sessionsList.length }}</span>
                </div>
              </template>
              研读历史
            </n-tooltip>
            <transition name="flyout">
              <div v-if="sidebarCollapsed && sessionsFlyoutOpen" class="sessions-flyout" @click.stop>
                <div class="flyout-header">
                  <span class="flyout-title">研读历史 ({{ sessionsList.length }})</span>
                  <n-input v-model:value="sessionSearch" size="tiny" placeholder="搜索会话..." clearable />
                </div>
                <div class="flyout-list">
                  <div
                    v-for="s in filteredSessions"
                    :key="s.id"
                    class="flyout-item"
                    :class="{ active: s.id === currentSessionId }"
                    @click="openSessionInReader(s.id); sessionsFlyoutOpen = false"
                  >
                    <span class="mini-title">{{ s.title || '研读对话' }}</span>
                    <span class="mini-time">{{ formatTime(s.updatedAt) }}</span>
                    <span class="mini-delete" title="删除会话" @click.stop="confirmDeleteSession(s)">✕</span>
                  </div>
                  <div v-if="filteredSessions.length === 0" class="sessions-empty">
                    {{ sessionsList.length === 0 ? '暂无研读会话' : '无匹配会话' }}
                  </div>
                </div>
              </div>
            </transition>

            <!-- 底部折叠按钮 -->
            <div class="sidebar-bottom">
              <div class="collapse-toggle" @click="sidebarCollapsed = !sidebarCollapsed">
                <span class="toggle-icon">{{ sidebarCollapsed ? '›' : '‹' }}</span>
              </div>
            </div>
          </aside>

          <!-- 右侧主内容区 -->
          <main class="app-main">
            <!-- 馆藏书库 — 一级页面 -->
            <BookShelf
              v-show="activeView === 'shelf'"
              @open-reader="handleOpenReaderFromShelf"
              @open-chat="handleOpenChat"
            />

            <!-- 原文并行预览 — 二级页面 -->
            <ParallelReader
              v-if="activeView === 'reader'"
              :initial-book-id="readerTargetBookId"
              :initial-page="readerTargetPage"
              :initial-paragraph-id="readerTargetParagraphId"
              :initial-session-id="currentSessionId"
              @back="activeView = 'shelf'"
              @jump-shelf="activeView = 'shelf'"
            />

            <!-- 伴读研读工作台 — 新建会话 / 历史会话点入 -->
            <ChatWorkbench
              v-if="activeView === 'workbench'"
              :current-session-id="currentSessionId"
              :current-session-title="currentSessionTitle"
              @session-updated="loadSessions"
              @open-parallel-reader="handleOpenReaderFromShelf"
              @start-rename-session="startRenameSession"
            />
          </main>

          <!-- 重命名 Modal -->
          <n-modal v-model:show="showRenameModal" preset="dialog" title="重命名会话">
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

          <!-- 删除会话确认 Modal -->
          <n-modal v-model:show="showDeleteModal" preset="dialog" title="删除会话">
            <div style="padding: 12px 0;">
              <p style="margin: 0; font-size: 13px; color: var(--color-ink-soft); line-height: 1.6;">
                确定删除「{{ pendingDeleteTitle }}」吗？此操作不可恢复。
              </p>
            </div>
            <template #action>
              <n-button size="small" @click="cancelDeleteSession">取消</n-button>
              <n-button size="small" type="error" @click="performDeleteSession">删除</n-button>
            </template>
          </n-modal>
        </div>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import BookShelf from './components/BookShelf.vue'
import ParallelReader from './components/ParallelReader.vue'
import ChatWorkbench from './components/ChatWorkbench.vue'

// 主题色板覆盖
const themeOverrides = {
  common: {
    primaryColor: '#b45309',
    primaryColorHover: '#92400e',
    primaryColorPressed: '#78350f',
    primaryColorSuppl: '#fef3c7',
    infoColor: '#0e7490',
    infoColorHover: '#0369a1',
    infoColorPressed: '#155e75',
    infoColorSuppl: '#cffafe',
    successColor: '#047857',
    textColorBase: '#1c1917',
    textColor1: '#1c1917',
    textColor2: '#44403c',
    textColor3: '#78716c',
    bodyColor: '#faf8f5',
    cardColor: '#ffffff',
    modalColor: '#ffffff',
    dividerColor: '#e7e2da',
    borderColor: '#e7e2da',
    hoverColor: '#f5f0e8',
    placeholderColor: '#a8a29e'
  }
}

// 视图状态 — 默认馆藏书库
const activeView = ref('shelf')
const sidebarCollapsed = ref(false)
const sessionsExpanded = ref(true)
const sessionSearch = ref('')
const sessionsFlyoutOpen = ref(false)

// 导航项
const navItems = computed(() => [
  { key: 'shelf', icon: '⊞', label: '馆藏书库', disabled: false, action: () => { activeView.value = 'shelf' } },
  { key: 'workbench', icon: '⚙', label: '伴读工作台', disabled: false, action: () => { if (currentSessionId.value) activeView.value = 'workbench' } },
  { key: 'reader', icon: '⊟', label: '原文对照', disabled: !readerTargetBookId.value, action: () => { if (readerTargetBookId.value) activeView.value = 'reader' } }
])

// 历史会话
const sessionsList = ref([])
const currentSessionId = ref('')
const currentSessionTitle = ref('研读对话')
const showRenameModal = ref(false)
const renameSessionId = ref('')
const renameInputTitle = ref('')

// 会话过滤
const filteredSessions = computed(() => {
  const q = sessionSearch.value.trim().toLowerCase()
  if (!q) return sessionsList.value
  return sessionsList.value.filter(s => (s.title || '研读对话').toLowerCase().includes(q))
})

// 删除会话
const showDeleteModal = ref(false)
const pendingDeleteId = ref('')
const pendingDeleteTitle = ref('')

function confirmDeleteSession(s) {
  pendingDeleteId.value = s.id
  pendingDeleteTitle.value = s.title || '研读对话'
  showDeleteModal.value = true
}

function cancelDeleteSession() {
  showDeleteModal.value = false
  pendingDeleteId.value = ''
  pendingDeleteTitle.value = ''
}

async function performDeleteSession() {
  const id = pendingDeleteId.value
  try {
    if (window.api?.deleteSession) {
      await window.api.deleteSession(id)
      sessionsList.value = sessionsList.value.filter(x => x.id !== id)
      if (currentSessionId.value === id) currentSessionId.value = ''
    }
  } catch (e) {
    console.warn('Failed to delete session:', e)
  } finally {
    cancelDeleteSession()
  }
}

// 阅读器跳转参数
const readerTargetBookId = ref(null)
const readerTargetPage = ref(1)
const readerTargetParagraphId = ref(null)

onMounted(async () => {
  await loadSessions()
})

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

function handleOpenReaderFromShelf({ bookId, page, paragraphId }) {
  readerTargetBookId.value = bookId
  readerTargetPage.value = page || 1
  readerTargetParagraphId.value = paragraphId || null
  activeView.value = 'reader'
}

async function openNewSessionFromSidebar() {
  // 直接在侧栏触发 BookShelf 的新建会话弹窗
  activeView.value = 'shelf'
  // 通过事件总线通知 BookShelf 打开 Modal
  setTimeout(() => {
    window.dispatchEvent(new CustomEvent('book-shelf:open-new-session'))
  }, 100)
}

async function handleOpenChat({ sessionId }) {
  if (!sessionId) return
  // 加载会话以取得标题
  currentSessionId.value = sessionId
  try {
    const res = await window.api.getSession(sessionId)
    if (res.success && res.data) {
      currentSessionTitle.value = res.data.title || res.data.scope?.categories?.[0] || '研读对话'
    }
  } catch { /* ignore */ }
  activeView.value = 'workbench'
}

function openSessionInReader(sessionId) {
  currentSessionId.value = sessionId
  activeView.value = 'workbench'
}

function goHome() {
  activeView.value = 'shelf'
}

function startRenameSession() {
  renameSessionId.value = currentSessionId.value
  renameInputTitle.value = currentSessionTitle.value || ''
  showRenameModal.value = true
}

async function confirmRenameSession() {
  if (renameSessionId.value && renameInputTitle.value.trim()) {
    try {
      await window.api.renameSession({ id: renameSessionId.value, title: renameInputTitle.value.trim() })
      currentSessionTitle.value = renameInputTitle.value.trim()
    } catch { /* ignore */ }
  }
  showRenameModal.value = false
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
  background-color: var(--color-bg);
  overflow: hidden;
}

/* ==================== 左侧导航栏 ==================== */
.app-sidebar {
  width: var(--w-sidebar);
  background: linear-gradient(180deg, #1c1917 0%, #292524 100%);
  display: flex;
  flex-direction: column;
  user-select: none;
  flex-shrink: 0;
  position: relative;
  transition: width 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.app-sidebar.collapsed {
  width: var(--w-sidebar-collapsed);
}

.app-sidebar.collapsed .sidebar-brand {
  padding: 0;
  justify-content: center;
}

.app-sidebar.collapsed .sidebar-nav {
  padding: 12px 0;
  align-items: center;
}

.app-sidebar.collapsed .nav-item {
  padding: 9px 0;
  justify-content: center;
}

.app-sidebar::after {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 1px;
  background: rgba(255, 255, 255, 0.06);
}

/* 品牌标识 */
.sidebar-brand {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
  cursor: pointer;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.brand-mark-wrap {
  position: relative;
  width: 30px;
  height: 30px;
  flex-shrink: 0;
}

.mark-symbol {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 17px;
  color: #fbbf24;
  z-index: 2;
}

.mark-circle {
  position: absolute;
  inset: 0;
  border: 1.5px solid rgba(251, 191, 36, 0.25);
  border-radius: 50%;
  animation: ring-breath 4s ease-in-out infinite;
}

@keyframes ring-breath {
  0%, 100% { opacity: 0.4; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.08); }
}

.brand-name {
  font-family: var(--font-body);
  font-size: 14px;
  font-weight: 700;
  color: #fef3c7;
  white-space: nowrap;
}

/* 主导航 */
.sidebar-nav {
  padding: 12px 10px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: var(--radius-md);
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  transition: all 0.15s ease;
  font-size: 13px;
  font-weight: 400;
}

.nav-item:hover:not(.disabled) {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.85);
}

.nav-item.active {
  background: rgba(251, 191, 36, 0.1);
  color: #fbbf24;
  font-weight: 500;
}

.nav-item.disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.nav-icon {
  font-size: 16px;
  width: 22px;
  text-align: center;
  flex-shrink: 0;
}

.nav-text {
  white-space: nowrap;
}

/* 新建会话入口 */
.sidebar-new-session {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  margin: 6px 10px 4px;
  border-radius: var(--radius-md);
  background: rgba(180, 83, 9, 0.12);
  border: 1.5px dashed rgba(180, 83, 9, 0.3);
  cursor: pointer;
  transition: all 0.15s;
}

.sidebar-new-session:hover {
  background: rgba(180, 83, 9, 0.2);
  border-style: solid;
}

.sidebar-new-session.collapsed {
  justify-content: center;
  padding: 8px 0;
  margin: 6px 8px 4px;
}

.new-session-icon {
  font-size: 16px;
  font-weight: 700;
  color: #b45309;
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: rgba(180, 83, 9, 0.15);
}

.new-session-label {
  font-size: 13px;
  font-weight: 500;
  color: #b45309;
}

/* 研读历史折叠 */
.sidebar-sessions {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0 10px;
}

.sessions-collapse-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  margin-top: 4px;
  border-radius: var(--radius-md);
  cursor: pointer;
  color: rgba(255, 255, 255, 0.4);
  font-size: 12px;
  transition: all 0.15s;
}

.sessions-collapse-header:hover {
  background: rgba(255, 255, 255, 0.04);
  color: rgba(255, 255, 255, 0.7);
}

.collapse-chevron {
  font-size: 16px;
  transition: transform 0.2s;
  display: inline-block;
}

.collapse-chevron.rotated {
  transform: rotate(90deg);
}

.sessions-mini-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-bottom: 6px;
}

.sessions-search {
  padding: 4px 2px 6px;
}

.mini-delete {
  margin-left: auto;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.25);
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 3px;
  opacity: 0;
  transition: all 0.12s;
  flex-shrink: 0;
}

.session-mini-item:hover .mini-delete,
.flyout-item:hover .mini-delete {
  opacity: 1;
}

.mini-delete:hover {
  color: #f87171;
  background: rgba(248, 113, 113, 0.1);
}

/* 折叠态研读历史 */
.sidebar-sessions-collapsed {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  margin: 4px 12px;
  border-radius: var(--radius-md);
  cursor: pointer;
  color: rgba(255, 255, 255, 0.5);
  transition: all 0.15s;
}

.sidebar-sessions-collapsed:hover {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.85);
}

.sessions-icon {
  font-size: 15px;
}

.sessions-badge {
  position: absolute;
  top: -2px;
  right: -2px;
  min-width: 14px;
  height: 14px;
  padding: 0 3px;
  border-radius: 7px;
  background: var(--color-accent);
  color: #fff;
  font-size: 9px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.sessions-flyout {
  position: absolute;
  top: 0;
  left: calc(var(--w-sidebar-collapsed) + 8px);
  width: 260px;
  max-height: 70vh;
  background: #292524;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  z-index: 100;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.flyout-header {
  padding: 10px 12px 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.flyout-title {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.6);
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.flyout-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
}

.flyout-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background 0.12s;
}

.flyout-item:hover {
  background: rgba(255, 255, 255, 0.06);
}

.flyout-item.active {
  background: rgba(251, 191, 36, 0.08);
}

.flyout-item .mini-title {
  font-size: 12px;
}

.flyout-item .mini-time {
  font-size: 11px;
}

.session-mini-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.12s;
}

.session-mini-item:hover {
  background: rgba(255, 255, 255, 0.06);
}

.session-mini-item.active {
  background: rgba(251, 191, 36, 0.08);
}

.mini-title {
  font-size: 11.5px;
  color: rgba(255, 255, 255, 0.6);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.session-mini-item.active .mini-title {
  color: #fef3c7;
}

.mini-time {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.3);
  margin-left: 6px;
  flex-shrink: 0;
}

.sessions-empty {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.3);
  padding: 8px 10px;
  text-align: center;
}

/* 底部折叠按钮 */
.sidebar-bottom {
  padding: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.collapse-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  padding: 6px 0;
  border-radius: var(--radius-md);
  cursor: pointer;
  color: rgba(255, 255, 255, 0.35);
  transition: all 0.15s;
  font-size: 18px;
  font-weight: 700;
}

.collapse-toggle:hover {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.7);
}

/* 过渡动画 */
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.2s ease;
}
.fade-slide-enter-from,
.fade-slide-leave-to {
  opacity: 0;
  transform: translateX(-8px);
}

.expand-enter-active,
.expand-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

.flyout-enter-active,
.flyout-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.flyout-enter-from,
.flyout-leave-to {
  opacity: 0;
  transform: translateX(-6px);
}

/* 右侧主内容 */
.app-main {
  flex: 1;
  height: 100%;
  overflow: hidden;
  position: relative;
}
</style>
