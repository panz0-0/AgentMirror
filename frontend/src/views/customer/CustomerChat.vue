<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ChatDotRound,
  ChatLineRound,
  Delete,
  DArrowLeft,
  DArrowRight,
  Menu,
  Picture,
  Plus,
  Scissor,
  Service,
  ShoppingBag,
  User,
} from '@element-plus/icons-vue'
import { api } from '../../api'

const USER_ID_KEY = 'fitmirror_user_id'
function getOrCreateUserId() {
  let id = localStorage.getItem(USER_ID_KEY)
  if (!id) {
    id = `u_${crypto.randomUUID().replace(/-/g, '').slice(0, 12)}`
    localStorage.setItem(USER_ID_KEY, id)
  }
  return id
}
const userId = getOrCreateUserId()

function showError(err, fallback = '操作失败，请稍后重试') {
  ElMessage.error(err?.message || fallback)
}

function messageKey(m, index) {
  return m.id ?? `${m.created_at || 't'}-${index}`
}

const sessionId = ref('')
const sessions = ref([])
const messages = ref([])
const input = ref('')
const loading = ref(false)
const typing = ref(false)
/** @type {import('vue').Ref<'tryon'|'product'|'chat'|'compose'|'search'|null>} */
const loadingPhase = ref(null)
const pendingProductName = ref('')
const freshMessageKeys = ref(new Set())

const MIN_LOADING_MS = {
  tryon: 900,
  product: 750,
  chat: 650,
  compose: 850,
  search: 750,
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const chatBox = ref(null)
const catalog = ref({ categories: [], items: [], total: 0 })
const selectedCategory = ref('')
const contextMenu = ref({ show: false, x: 0, y: 0, session: null })
const pendingImage = ref(null) // { file, preview, name }
const fileInputRef = ref(null)

const LAYOUT_KEY = 'fitmirror_cs_layout'
function loadLayout() {
  try {
    return JSON.parse(localStorage.getItem(LAYOUT_KEY) || '{}')
  } catch {
    return {}
  }
}
const saved = loadLayout()
const sessionWidth = ref(saved.sessionWidth ?? 200)
const catalogWidth = ref(saved.catalogWidth ?? 240)
const sessionVisible = ref(saved.sessionVisible ?? true)
const catalogVisible = ref(saved.catalogVisible ?? true)

let resizeState = null

function saveLayout() {
  localStorage.setItem(LAYOUT_KEY, JSON.stringify({
    sessionWidth: sessionWidth.value,
    catalogWidth: catalogWidth.value,
    sessionVisible: sessionVisible.value,
    catalogVisible: catalogVisible.value,
  }))
}

function startResize(side, e) {
  e.preventDefault()
  resizeState = {
    side,
    startX: e.clientX,
    startW: side === 'session' ? sessionWidth.value : catalogWidth.value,
  }
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  document.addEventListener('mousemove', onResizeMove)
  document.addEventListener('mouseup', stopResize)
}

function onResizeMove(e) {
  if (!resizeState) return
  const dx = e.clientX - resizeState.startX
  if (resizeState.side === 'session') {
    sessionWidth.value = Math.min(360, Math.max(140, resizeState.startW + dx))
  } else {
    catalogWidth.value = Math.min(420, Math.max(160, resizeState.startW - dx))
  }
}

function stopResize() {
  resizeState = null
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  document.removeEventListener('mousemove', onResizeMove)
  document.removeEventListener('mouseup', stopResize)
  saveLayout()
}

function toggleSessionPanel() {
  sessionVisible.value = !sessionVisible.value
  saveLayout()
}

function toggleCatalogPanel() {
  catalogVisible.value = !catalogVisible.value
  saveLayout()
}

const quickTips = [
  { label: '发货/退换货查询', text: '发货和退换货政策是什么？' },
  { label: '虚拟试穿效果图', text: '我想试穿这件衣服' },
  { label: '查看店铺商品', text: '店里现在有哪些商品？' },
  { label: '女装有哪些', text: '女装有哪些款式？' },
  { label: '裤子推荐', text: '有什么裤子推荐？' },
  { label: '身高176适合什么码', text: '身高176 适合什么尺码' },
]

const filteredProducts = ref([])

const previewImageList = computed(() => {
  const urls = []
  for (const m of messages.value) {
    if (m.metadata?.image_url) urls.push(resolveImageUrl(m.metadata.image_url))
  }
  if (pendingImage.value?.preview) urls.push(pendingImage.value.preview)
  return [...new Set(urls.filter(Boolean))]
})

function resolveImageUrl(url) {
  if (!url) return ''
  if (url.startsWith('blob:') || url.startsWith('http')) return url
  return url
}

function isLocalPreviewUrl(url) {
  return !!url && url.startsWith('blob:')
}

function isPendingUserImage(m) {
  return m?.role === 'user' && (m.metadata?.pending || isLocalPreviewUrl(m.metadata?.image_url))
}

function previewIndex(url) {
  const list = previewImageList.value
  const u = resolveImageUrl(url)
  const idx = list.indexOf(u)
  return idx >= 0 ? idx : 0
}

function tryonGalleryUrls(m) {
  if (m?.metadata?.type !== 'tryon_result') return []
  const gallery = m.metadata?.gallery_urls
  if (Array.isArray(gallery) && gallery.length) {
    return [...new Set(gallery.map(resolveImageUrl).filter(Boolean))]
  }
  const single = messageImageUrl(m)
  return single ? [single] : []
}

function messagePreviewList(m) {
  if (m?.metadata?.type === 'tryon_result') {
    return tryonGalleryUrls(m)
  }
  const url = messageImageUrl(m)
  return url ? [url] : []
}

function previewIndexInList(url, list) {
  const u = resolveImageUrl(url)
  const idx = list.indexOf(u)
  return idx >= 0 ? idx : 0
}

function hasImageMeta(m) {
  if (m?.metadata?.type === 'tryon_result') {
    return tryonGalleryUrls(m).length > 0
  }
  return m?.metadata?.image_url && ['image', 'product_match', 'product_intro', 'similar_product'].includes(m.metadata?.type)
}

function messageImageUrl(m) {
  return resolveImageUrl(m.metadata?.image_url)
}

function isFreshMessage(m, index) {
  return m?.role === 'assistant' && freshMessageKeys.value.has(messageKey(m, index))
}

function markLatestAssistantFresh() {
  const lastAssistant = [...messages.value].reverse().find((m) => m.role === 'assistant')
  if (!lastAssistant) return
  const idx = messages.value.indexOf(lastAssistant)
  freshMessageKeys.value = new Set([...freshMessageKeys.value, messageKey(lastAssistant, idx)])
}

function clearFreshMessageKey(m, index) {
  const key = messageKey(m, index)
  if (!freshMessageKeys.value.has(key)) return
  setTimeout(() => {
    const next = new Set(freshMessageKeys.value)
    next.delete(key)
    freshMessageKeys.value = next
  }, 520)
}

function inferChatPhase(text) {
  const t = text || ''
  if (/试穿|上身效果|效果图/.test(t)) return 'tryon'
  if (/发货|物流|退换|退货|换货|售后|保修|政策|几天|多久/.test(t)) return 'search'
  return 'chat'
}

const loadingHint = computed(() => {
  const hints = {
    tryon: '正在合成上身效果图…',
    product: '正在为您介绍商品…',
    compose: '正在识别图片并匹配商品…',
    chat: '正在思考回复…',
    search: '正在检索知识库…',
  }
  if (loadingPhase.value) return hints[loadingPhase.value]
  if (typing.value) return '正在输入中...'
  return 'AI 智能助手接待中 · 人工客服不在线'
})

async function runWithMinLoading(phase, task) {
  const minMs = MIN_LOADING_MS[phase] ?? 650
  loading.value = true
  typing.value = true
  loadingPhase.value = phase
  try {
    await Promise.all([task(), sleep(minMs)])
    await loadHistory()
    await loadSessions()
    markLatestAssistantFresh()
    await scrollBottom()
  } catch (err) {
    throw err
  } finally {
    loading.value = false
    typing.value = false
    loadingPhase.value = null
    pendingProductName.value = ''
  }
}

async function loadCatalog() {
  try {
    catalog.value = await api.getCatalog()
    filterCategory(selectedCategory.value)
  } catch (err) {
    showError(err, '加载商品目录失败')
  }
}

function filterCategory(cat) {
  selectedCategory.value = cat
  if (!cat) {
    filteredProducts.value = catalog.value.items || []
  } else {
    const group = catalog.value.categories?.find((c) => c.name === cat)
    filteredProducts.value = group?.items || []
  }
}

async function loadSessions() {
  try {
    sessions.value = await api.listSessions(userId)
  } catch (err) {
    showError(err, '加载会话列表失败')
  }
}

async function newSession() {
  try {
    const s = await api.createSession({ user_id: userId, title: '新的对话' })
    sessionId.value = s.session_id
    await loadSessions()
    await loadHistory()
  } catch (err) {
    showError(err, '创建会话失败')
  }
}

async function selectSession(id) {
  sessionId.value = id
  await loadHistory()
}

async function deleteSession(id) {
  try {
    await api.deleteSession(id, userId)
    await loadSessions()
    if (sessionId.value === id) {
      if (sessions.value.length) {
        sessionId.value = sessions.value[0].id
        await loadHistory()
      } else {
        await newSession()
      }
    }
    ElMessage.success('会话已删除')
  } catch (err) {
    showError(err, '删除会话失败')
  }
}

function onSessionContextMenu(e, s) {
  e.preventDefault()
  contextMenu.value = { show: true, x: e.clientX, y: e.clientY, session: s }
}

function closeContextMenu() {
  contextMenu.value.show = false
}

async function confirmDeleteSession() {
  const s = contextMenu.value.session
  closeContextMenu()
  if (!s) return
  try {
    await ElMessageBox.confirm(`确定删除「${s.title}」？`, '删除会话', { type: 'warning' })
    await deleteSession(s.id)
  } catch { /* cancelled */ }
}

async function ensureSession() {
  await loadSessions()
  if (sessions.value.length) {
    sessionId.value = sessions.value[0].id
    await loadHistory()
  } else {
    await newSession()
  }
}

async function loadHistory() {
  if (!sessionId.value) return
  try {
    messages.value = await api.getHistory(sessionId.value)
    await scrollBottom()
  } catch (err) {
    showError(err, '加载聊天记录失败')
  }
}

async function scrollBottom() {
  await nextTick()
  if (chatBox.value) chatBox.value.scrollTop = chatBox.value.scrollHeight
}

function useTip(text) {
  input.value = text
  send()
}

async function askAboutProduct(item) {
  if (!item?.id || loading.value) return
  pendingProductName.value = item.name || '商品'
  try {
    await runWithMinLoading('product', async () => {
      const fd = new FormData()
      fd.append('session_id', sessionId.value)
      fd.append('user_id', userId)
      await api.introduceProduct(item.id, fd)
    })
  } catch (err) {
    showError(err, '获取商品介绍失败')
  }
}

async function handleAction(action) {
  if (!action) return
  if (action.type === 'message' && action.text) {
    input.value = action.text
    await send()
  } else if (action.type === 'tryon' && action.sku_id) {
    try {
      await runWithMinLoading('tryon', async () => {
        const fd = new FormData()
        fd.append('session_id', sessionId.value)
        fd.append('user_id', userId)
        fd.append('sku_id', action.sku_id)
        await api.startTryon(fd)
      })
    } catch (err) {
      showError(err, '获取试穿效果图失败')
    }
  }
}

function clearPendingImage(revokePreview = true) {
  if (revokePreview && pendingImage.value?.preview) URL.revokeObjectURL(pendingImage.value.preview)
  pendingImage.value = null
}

function setPendingImage(file) {
  clearPendingImage()
  pendingImage.value = {
    file,
    preview: URL.createObjectURL(file),
    name: file.name || '图片',
  }
}

async function send() {
  const text = input.value.trim()
  const hasImage = !!pendingImage.value?.file
  if ((!text && !hasImage) || loading.value) return

  const savedText = text
  const savedImage = pendingImage.value
  let previewToRevoke = savedImage?.preview ?? null
  const optimisticMeta = savedImage
    ? { type: 'image', image_url: savedImage.preview, pending: true }
    : null

  const phase = savedImage ? 'compose' : inferChatPhase(savedText)

  loading.value = true
  typing.value = true
  loadingPhase.value = phase
  input.value = ''
  // 保留 blob 预览供乐观消息展示，请求结束后再释放
  pendingImage.value = null

  messages.value.push({
    id: `tmp-${Date.now()}`,
    role: 'user',
    content: savedText || '[图片]',
    metadata: optimisticMeta,
    created_at: new Date().toISOString(),
  })
  await scrollBottom()

  try {
    const fd = new FormData()
    fd.append('session_id', sessionId.value)
    fd.append('user_id', userId)
    if (savedText) fd.append('content', savedText)
    if (savedImage?.file) fd.append('image', savedImage.file)

    const minMs = MIN_LOADING_MS[phase]
    const apiCall = savedImage?.file
      ? () => api.sendComposeMessage(fd)
      : () => api.sendMessage({ session_id: sessionId.value, user_id: userId, content: savedText })

    await Promise.all([apiCall(), sleep(minMs)])
    await loadHistory()
    await loadSessions()
    markLatestAssistantFresh()
    const lastUser = messages.value.filter((m) => m.role === 'user').pop()
    if (lastUser?.content?.includes('有哪些商品') || lastUser?.content?.includes('有什么商品')) {
      await loadCatalog()
    }
  } catch (err) {
    if (previewToRevoke) {
      URL.revokeObjectURL(previewToRevoke)
      previewToRevoke = null
    }
    messages.value = messages.value.filter((m) => !String(m.id).startsWith('tmp-'))
    input.value = savedText
    if (savedImage) setPendingImage(savedImage.file)
    showError(err, '发送失败，请重试')
  } finally {
    if (previewToRevoke) URL.revokeObjectURL(previewToRevoke)
    loading.value = false
    typing.value = false
    loadingPhase.value = null
    await scrollBottom()
  }
}

function focusPasteHint() {
  ElMessage.info('请使用 Ctrl+V 粘贴截图，或点击「图片」选择文件')
}

function onPaste(e) {
  const items = e.clipboardData?.items
  if (!items) return
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      e.preventDefault()
      const file = item.getAsFile()
      if (file) setPendingImage(file)
      return
    }
  }
}

function onFileSelect(e) {
  const file = e.target.files?.[0]
  if (file) setPendingImage(file)
  e.target.value = ''
}

function roleLabel(role) {
  return role === 'user' ? '我' : 'AI客服'
}

function renderContent(text) {
  if (!text || text === '[图片]') return ''
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
  return escaped
}

onMounted(async () => {
  await ensureSession()
  await loadCatalog()
  document.addEventListener('click', closeContextMenu)
})

onUnmounted(() => {
  document.removeEventListener('click', closeContextMenu)
  stopResize()
  clearPendingImage()
})
</script>

<template>
  <div class="cs-layout">
    <button
      v-if="!sessionVisible"
      type="button"
      class="edge-toggle left"
      title="显示会话记录"
      @click="toggleSessionPanel"
    >
      <el-icon :size="14"><DArrowRight /></el-icon>
    </button>

    <aside
      v-show="sessionVisible"
      class="session-panel"
      :style="{ width: sessionWidth + 'px' }"
    >
      <div class="session-header">
        <span class="panel-title">会话记录</span>
        <div class="panel-actions">
          <button type="button" class="btn-new" @click="newSession">
            <el-icon :size="12"><Plus /></el-icon>
            新对话
          </button>
          <button type="button" class="btn-icon" title="隐藏会话栏" @click="toggleSessionPanel">
            <el-icon :size="12"><DArrowLeft /></el-icon>
          </button>
        </div>
      </div>
      <div class="session-list">
        <div
          v-for="s in sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: s.id === sessionId }"
          @click="selectSession(s.id)"
          @contextmenu="onSessionContextMenu($event, s)"
        >
          <div class="session-title">{{ s.title }}</div>
          <div class="session-time">{{ s.updated_at?.slice(0, 16)?.replace('T', ' ') || '' }}</div>
        </div>
        <div v-if="!sessions.length" class="session-empty">暂无会话</div>
      </div>
      <div class="resize-handle" @mousedown="startResize('session', $event)" />
    </aside>

    <main class="chat-main">
      <header class="chat-header">
        <div class="header-left">
          <button
            v-if="!sessionVisible"
            type="button"
            class="header-toggle"
            title="显示会话记录"
            @click="toggleSessionPanel"
          >
            <el-icon :size="16"><Menu /></el-icon>
          </button>
          <div class="avatar-ai">
            <el-icon :size="20"><Service /></el-icon>
          </div>
          <div>
            <div class="header-title">在线客服</div>
            <div class="header-sub">{{ loadingHint }}</div>
          </div>
        </div>
        <div class="header-status">
          <button
            v-if="!catalogVisible"
            type="button"
            class="header-toggle"
            title="显示店铺商品"
            @click="toggleCatalogPanel"
          >
            <el-icon :size="16"><ShoppingBag /></el-icon>
          </button>
          <span class="dot-online" />
          <span class="status-text">在线</span>
        </div>
      </header>

      <div ref="chatBox" class="chat-body">
        <div
          v-for="(m, i) in messages"
          :key="messageKey(m, i)"
          class="msg-row"
          :class="[m.role, { 'msg-row--fresh': isFreshMessage(m, i), 'msg-row--user-tmp': String(m.id).startsWith('tmp-') }]"
        >
          <div class="msg-label">{{ roleLabel(m.role) }}</div>
          <div class="msg-wrap">
            <div class="avatar" :class="m.role">
              <el-icon :size="18">
                <User v-if="m.role === 'user'" />
                <Service v-else />
              </el-icon>
            </div>
            <div class="bubble" :class="[m.role, { 'bubble--fresh': isFreshMessage(m, i) }]">
              <div
                v-if="renderContent(m.content)"
                class="msg-text"
                :class="{ 'msg-text--fresh': isFreshMessage(m, i) }"
                v-html="renderContent(m.content)"
              />
              <div
                v-if="isPendingUserImage(m)"
                class="msg-image-wrap msg-image-wrap--pending"
              >
                <img :src="m.metadata.image_url" alt="发送中的图片" class="msg-image" />
                <span class="msg-image-badge">发送中</span>
              </div>
              <el-image
                v-else-if="m.role === 'user' && m.metadata?.image_url"
                :src="messageImageUrl(m)"
                :preview-src-list="messagePreviewList(m)"
                :initial-index="0"
                fit="cover"
                class="msg-image"
                preview-teleported
              />
              <div
                v-if="m.role === 'assistant' && m.metadata?.type === 'tryon_result' && tryonGalleryUrls(m).length"
                class="tryon-gallery"
                :class="{ 'tryon-gallery--reveal': isFreshMessage(m, i) }"
              >
                <div
                  v-for="(url, gi) in tryonGalleryUrls(m)"
                  :key="`${messageKey(m, i)}-${gi}`"
                  class="tryon-shot-wrap"
                  :style="{ animationDelay: isFreshMessage(m, i) ? `${gi * 120}ms` : '0ms' }"
                >
                  <el-image
                    :src="url"
                    :preview-src-list="tryonGalleryUrls(m)"
                    :initial-index="gi"
                    fit="cover"
                    class="msg-product-img tryon-shot"
                    preview-teleported
                    @load="clearFreshMessageKey(m, i)"
                  />
                </div>
              </div>
              <el-image
                v-else-if="m.role === 'assistant' && hasImageMeta(m)"
                :src="messageImageUrl(m)"
                :preview-src-list="messagePreviewList(m)"
                :initial-index="0"
                fit="cover"
                class="msg-product-img"
                :class="{ 'msg-product-img--fresh': isFreshMessage(m, i) }"
                preview-teleported
                @load="clearFreshMessageKey(m, i)"
              />
              <div v-if="m.metadata?.actions?.length" class="action-btns" :class="{ 'action-btns--fresh': isFreshMessage(m, i) }">
                <button
                  v-for="(act, j) in m.metadata.actions"
                  :key="j"
                  class="action-btn"
                  :class="[m.role, { 'action-btn--loading': loading && act.type === 'tryon' && loadingPhase === 'tryon' }]"
                  :disabled="loading"
                  @click="handleAction(act)"
                >{{ act.label }}</button>
              </div>
            </div>
          </div>
        </div>
        <div v-if="loading" class="msg-row assistant msg-row--loading">
          <div class="msg-label">AI客服</div>
          <div class="msg-wrap">
            <div class="avatar assistant">
              <el-icon :size="18"><Service /></el-icon>
            </div>
            <!-- 试穿加载 -->
            <div v-if="loadingPhase === 'tryon'" class="bubble assistant tryon-loading-bubble">
              <div class="loading-head">
                <span class="loading-dot" />
                <span>正在合成上身效果图</span>
              </div>
              <div class="tryon-skeleton">
                <div class="skeleton-shimmer" />
                <div class="skeleton-icon">
                  <el-icon :size="22"><Picture /></el-icon>
                </div>
              </div>
              <div class="loading-hint">根据您的身材参考，智能匹配模特展示中…</div>
            </div>
            <!-- 商品介绍加载 -->
            <div v-else-if="loadingPhase === 'product'" class="bubble assistant product-loading-bubble">
              <div class="loading-head">
                <span class="loading-dot loading-dot--accent" />
                <span>正在介绍商品</span>
              </div>
              <div class="product-skeleton">
                <div class="product-skeleton-img">
                  <div class="skeleton-shimmer" />
                  <el-icon :size="18"><ShoppingBag /></el-icon>
                </div>
                <div class="product-skeleton-lines">
                  <div class="sk-line sk-line--title" />
                  <div class="sk-line" />
                  <div class="sk-line sk-line--short" />
                </div>
              </div>
              <div class="loading-hint">{{ pendingProductName ? `正在整理「${pendingProductName}」详情…` : '正在整理商品详情…' }}</div>
            </div>
            <!-- 图文识别加载 -->
            <div v-else-if="loadingPhase === 'compose'" class="bubble assistant compose-loading-bubble">
              <div class="loading-head">
                <span class="loading-dot loading-dot--accent" />
                <span>正在识别图片</span>
              </div>
              <div class="compose-skeleton">
                <div class="compose-skeleton-img">
                  <div class="skeleton-shimmer" />
                  <el-icon :size="20"><Picture /></el-icon>
                </div>
                <div class="compose-skeleton-lines">
                  <div class="sk-line" />
                  <div class="sk-line sk-line--short" />
                </div>
              </div>
              <div class="loading-hint">AI 正在分析图片并匹配店铺商品…</div>
            </div>
            <!-- 知识库检索加载 -->
            <div v-else-if="loadingPhase === 'search'" class="bubble assistant search-loading-bubble">
              <div class="loading-head">
                <span class="loading-dot loading-dot--search" />
                <span>正在检索知识库</span>
              </div>
              <div class="search-skeleton">
                <div v-for="n in 3" :key="n" class="search-skeleton-row">
                  <div class="sk-line" :style="{ width: `${72 + n * 8}%` }" />
                </div>
              </div>
              <div class="loading-hint">为您查找相关政策与常见问题…</div>
            </div>
            <!-- 普通对话思考 -->
            <div v-else class="bubble assistant chat-loading-bubble">
              <div class="loading-head">
                <span class="loading-dot" />
                <span>正在思考</span>
              </div>
              <div class="chat-skeleton">
                <div class="sk-line" />
                <div class="sk-line sk-line--short" />
              </div>
              <div class="typing-bubble typing-bubble--inline"><span /><span /><span /></div>
            </div>
          </div>
        </div>
      </div>

      <div class="quick-tips">
        <span class="tips-label">快捷咨询：</span>
        <button
          v-for="tip in quickTips"
          :key="tip.label"
          class="tip-chip"
          :disabled="loading"
          @click="useTip(tip.text)"
        >{{ tip.label }}</button>
      </div>

      <!-- 微信式输入区 -->
      <div class="wechat-compose" @paste="onPaste">
        <div class="compose-toolbar">
          <button type="button" class="tool-btn" title="表情（开发中）" disabled>
            <el-icon :size="18"><ChatDotRound /></el-icon>
          </button>
          <label class="tool-btn" title="发送图片">
            <el-icon :size="18"><Picture /></el-icon>
            <input ref="fileInputRef" type="file" accept="image/*" hidden @change="onFileSelect" />
          </label>
          <button type="button" class="tool-btn" title="截图粘贴：Ctrl+V" @click="focusPasteHint">
            <el-icon :size="18"><Scissor /></el-icon>
          </button>
          <button type="button" class="tool-btn" title="快捷话术" @click="useTip('店里现在有哪些商品？')">
            <el-icon :size="18"><ChatLineRound /></el-icon>
          </button>
        </div>
        <div class="compose-box">
          <textarea
            v-model="input"
            class="compose-text"
            rows="3"
            placeholder="聊天框可以输入文字、粘贴图片，确认后再发送..."
            @keydown.enter.exact.prevent="send"
          />
          <div v-if="pendingImage" class="attach-card">
            <el-image
              :src="pendingImage.preview"
              :preview-src-list="[pendingImage.preview]"
              fit="cover"
              class="attach-thumb"
              preview-teleported
            />
            <div class="attach-info">
              <div class="attach-name">{{ pendingImage.name }}</div>
              <div class="attach-hint">点击缩略图可预览 · 发送前可继续输入文字</div>
            </div>
            <button type="button" class="attach-remove" @click="clearPendingImage">×</button>
          </div>
        </div>
        <div class="compose-footer">
          <span class="compose-tip">Enter 发送 · 图片粘贴后不会立即发出</span>
          <button type="button" class="btn-send-text" :disabled="loading" @click="send">发送(S)</button>
        </div>
      </div>
    </main>

    <aside
      v-show="catalogVisible"
      class="catalog-panel"
      :style="{ width: catalogWidth + 'px' }"
    >
      <div class="resize-handle left" @mousedown="startResize('catalog', $event)" />
      <div class="catalog-header">
        <span>店铺商品 <span class="badge">{{ catalog.total }}</span></span>
        <button type="button" class="btn-icon light" title="隐藏商品栏" @click="toggleCatalogPanel">
          <el-icon :size="12"><DArrowRight /></el-icon>
        </button>
      </div>
      <div class="category-chips">
        <button class="cat-chip" :class="{ active: !selectedCategory }" @click="filterCategory('')">全部</button>
        <button
          v-for="c in catalog.categories"
          :key="c.name"
          class="cat-chip"
          :class="{ active: selectedCategory === c.name }"
          @click="filterCategory(c.name)"
        >{{ c.name }} ({{ c.count }})</button>
      </div>
      <div class="product-grid">
        <div
          v-for="p in filteredProducts"
          :key="p.id"
          class="product-card"
          :class="{ 'product-card--loading': loading && loadingPhase === 'product' && pendingProductName === p.name }"
          @click="askAboutProduct(p)"
        >
          <div class="product-img-wrap">
            <img v-if="p.image_url" :src="p.image_url" :alt="p.name" />
            <div v-else class="no-img">无图</div>
          </div>
          <div class="product-info">
            <div class="product-name">{{ p.name }}</div>
            <div class="product-code">{{ p.sku_code }}</div>
            <div class="product-cat">{{ p.category }}</div>
          </div>
        </div>
        <div v-if="!filteredProducts.length" class="catalog-empty">暂无商品，请先在运营台上传</div>
      </div>
    </aside>

    <button
      v-if="!catalogVisible"
      type="button"
      class="edge-toggle right"
      title="显示店铺商品"
      @click="toggleCatalogPanel"
    >
      <el-icon :size="14"><DArrowLeft /></el-icon>
    </button>

    <div
      v-if="contextMenu.show"
      class="ctx-menu"
      :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }"
      @click.stop
    >
      <button type="button" class="ctx-delete" @click="confirmDeleteSession">
        <el-icon :size="14"><Delete /></el-icon>
        删除会话
      </button>
    </div>
  </div>
</template>

<style scoped>
.cs-layout {
  display: flex;
  height: 100vh;
  background: var(--fm-surface-chat);
  position: relative;
}

.session-panel,
.catalog-panel {
  position: relative;
  background: var(--fm-surface);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  box-shadow: var(--fm-shadow-sm);
}

.session-panel {
  border-right: 1px solid var(--fm-border);
  min-width: 140px;
  max-width: 360px;
}

.catalog-panel {
  border-left: 1px solid var(--fm-border);
  min-width: 160px;
  max-width: 420px;
}

.resize-handle {
  position: absolute;
  top: 0;
  right: -3px;
  width: 6px;
  height: 100%;
  cursor: col-resize;
  z-index: 5;
}

.resize-handle.left { right: auto; left: -3px; }
.resize-handle:hover { background: rgba(16, 185, 129, 0.2); }

.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--fm-text);
  letter-spacing: -0.01em;
}

.panel-actions { display: flex; align-items: center; gap: 6px; }

.btn-icon {
  border: 1px solid var(--fm-border);
  background: var(--fm-surface-muted);
  color: var(--fm-text-secondary);
  border-radius: var(--fm-radius-sm);
  width: 26px;
  height: 26px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.btn-icon.light { background: var(--fm-surface); }
.btn-icon:hover {
  background: var(--fm-accent-soft);
  border-color: var(--fm-accent);
  color: var(--fm-accent-hover);
}

.header-toggle {
  border: none;
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
  border-radius: var(--fm-radius-sm);
  width: 30px;
  height: 30px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-right: 4px;
  transition: background 0.15s ease;
}

.header-toggle:hover { background: rgba(255, 255, 255, 0.18); }

.edge-toggle {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  z-index: 20;
  width: 24px;
  height: 52px;
  border: 1px solid var(--fm-border);
  background: var(--fm-surface);
  color: var(--fm-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  box-shadow: var(--fm-shadow-md);
  transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}

.edge-toggle.left { left: 0; border-radius: 0 var(--fm-radius-md) var(--fm-radius-md) 0; }
.edge-toggle.right { right: 0; border-radius: var(--fm-radius-md) 0 0 var(--fm-radius-md); }
.edge-toggle:hover {
  background: var(--fm-accent-soft);
  color: var(--fm-accent-hover);
  border-color: var(--fm-accent-muted);
}

.session-header {
  padding: 14px 12px;
  border-bottom: 1px solid var(--fm-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.btn-new {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--fm-accent);
  color: #fff;
  border: none;
  border-radius: var(--fm-radius-sm);
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease, transform 0.15s ease;
}

.btn-new:hover { background: var(--fm-accent-hover); }
.btn-new:active { transform: scale(0.98); }

.session-list { flex: 1; overflow-y: auto; }

.session-item {
  position: relative;
  padding: 11px 12px 11px 14px;
  cursor: pointer;
  border-bottom: 1px solid var(--fm-border);
  transition: background 0.15s ease;
}

.session-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 0 2px 2px 0;
  background: transparent;
  transition: background 0.15s ease;
}

.session-item:hover { background: var(--fm-surface-subtle); }
.session-item.active { background: var(--fm-accent-soft); }
.session-item.active::before { background: var(--fm-accent); }

.session-title {
  font-size: 12px;
  color: var(--fm-text);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-time { font-size: 10px; color: var(--fm-text-muted); margin-top: 3px; }
.session-empty { padding: 24px 16px; color: var(--fm-text-muted); font-size: 12px; text-align: center; }

.chat-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }

.chat-header {
  background: var(--fm-chat-header);
  color: #fff;
  padding: 14px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: var(--fm-shadow-sm);
}

.header-left { display: flex; align-items: center; gap: 12px; }

.avatar-ai {
  width: 40px;
  height: 40px;
  border-radius: var(--fm-radius-md);
  background: rgba(16, 185, 129, 0.2);
  border: 1px solid rgba(110, 231, 183, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6ee7b7;
}

.header-title { font-size: 15px; font-weight: 700; letter-spacing: -0.02em; }
.header-sub { font-size: 11px; opacity: 0.82; margin-top: 2px; color: #cbd5e1; }
.header-status { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.status-text { color: #e2e8f0; }

.dot-online {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--fm-accent);
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.25);
  display: inline-block;
}

.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 18px 20px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.35) 0%, transparent 120px),
    var(--fm-surface-chat);
}

.msg-row { margin-bottom: 18px; display: flex; flex-direction: column; }
.msg-row.user { align-items: flex-end; }
.msg-row.assistant { align-items: flex-start; }
.msg-label { font-size: 10px; color: var(--fm-text-muted); margin-bottom: 5px; font-weight: 500; }
.msg-wrap { display: flex; align-items: flex-end; gap: 10px; max-width: 78%; }
.msg-row.user .msg-wrap { flex-direction: row-reverse; }
.msg-row.assistant .msg-wrap { flex-direction: row; }

.avatar {
  width: 36px;
  height: 36px;
  border-radius: var(--fm-radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: #fff;
}

.avatar.user { background: var(--fm-accent); }
.avatar.assistant { background: var(--fm-primary); }

.bubble {
  padding: 11px 14px;
  border-radius: var(--fm-radius-md);
  font-size: 13px;
  line-height: 1.65;
  word-break: break-word;
  box-shadow: var(--fm-shadow-sm);
}

.bubble.user {
  background: var(--fm-chat-user-bubble);
  color: #14281a;
  border-top-right-radius: 3px;
}

.bubble.assistant {
  background: var(--fm-chat-assistant-bubble);
  color: var(--fm-text);
  border: 1px solid var(--fm-border);
  border-top-left-radius: 3px;
}

.msg-text { margin-bottom: 6px; }
.msg-text :deep(strong) { font-weight: 700; color: var(--fm-text); }

.msg-image,
.msg-product-img {
  max-width: 220px;
  max-height: 220px;
  border-radius: var(--fm-radius-sm);
  display: block;
  cursor: zoom-in;
}

.msg-image-wrap {
  position: relative;
  display: inline-block;
  max-width: 220px;
}

.msg-image-wrap--pending .msg-image {
  opacity: 0.92;
  cursor: default;
}

.msg-image-badge {
  position: absolute;
  right: 8px;
  bottom: 8px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(20, 40, 26, 0.72);
  color: #fff;
  font-size: 11px;
  line-height: 1.5;
  backdrop-filter: blur(4px);
}

.msg-row--fresh {
  animation: msgRowIn 0.42s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.msg-row--user-tmp {
  animation: userMsgIn 0.28s ease both;
}

.msg-row--loading {
  animation: msgRowIn 0.3s ease both;
}

.msg-text--fresh {
  animation: textFadeIn 0.45s ease 0.08s both;
}

.msg-product-img--fresh {
  animation: mediaFadeIn 0.5s cubic-bezier(0.22, 1, 0.36, 1) 0.12s both;
}

.action-btns--fresh {
  animation: textFadeIn 0.4s ease 0.2s both;
}

.tryon-gallery {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
}

.tryon-shot-wrap {
  border-radius: var(--fm-radius-sm);
  overflow: hidden;
  background: var(--fm-surface-muted);
}

.tryon-gallery:not(.tryon-gallery--reveal) .tryon-shot-wrap {
  opacity: 1;
}

.tryon-gallery--reveal .tryon-shot-wrap {
  animation: tryonShotIn 0.55s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.tryon-shot {
  width: 148px;
  height: 198px;
  max-width: 148px;
  max-height: 198px;
  display: block;
}

/* ── 统一加载态 ── */
.tryon-loading-bubble,
.product-loading-bubble,
.compose-loading-bubble,
.search-loading-bubble,
.chat-loading-bubble {
  min-width: 168px;
  padding: 12px 14px 14px;
}

.loading-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--fm-text);
  margin-bottom: 10px;
}

.loading-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--fm-primary);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
  animation: loadingPulse 1.2s ease-in-out infinite;
  flex-shrink: 0;
}

.loading-dot--accent {
  background: var(--fm-accent);
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2);
}

.loading-dot--search {
  background: #8b5cf6;
  box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.2);
}

.loading-hint {
  margin-top: 8px;
  font-size: 10px;
  color: var(--fm-text-muted);
  line-height: 1.4;
}

.skeleton-shimmer {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    105deg,
    transparent 35%,
    rgba(255, 255, 255, 0.65) 50%,
    transparent 65%
  );
  animation: skeletonShimmer 1.4s ease-in-out infinite;
}

.skeleton-icon {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--fm-text-muted);
  opacity: 0.55;
}

.sk-line {
  height: 8px;
  border-radius: 4px;
  background: linear-gradient(90deg, #e8edf3, #f1f4f8, #e8edf3);
  margin-bottom: 7px;
  position: relative;
  overflow: hidden;
}

.sk-line::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(105deg, transparent 35%, rgba(255, 255, 255, 0.7) 50%, transparent 65%);
  animation: skeletonShimmer 1.4s ease-in-out infinite;
}

.sk-line--title { width: 68%; height: 10px; }
.sk-line--short { width: 48%; margin-bottom: 0; }

.tryon-skeleton {
  position: relative;
  width: 148px;
  height: 198px;
  border-radius: var(--fm-radius-sm);
  background: linear-gradient(135deg, #e8edf3 0%, #f4f6f9 50%, #e8edf3 100%);
  overflow: hidden;
  border: 1px solid var(--fm-border);
}

.product-skeleton {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.product-skeleton-img {
  position: relative;
  width: 72px;
  height: 72px;
  border-radius: var(--fm-radius-sm);
  background: linear-gradient(135deg, #e8edf3, #f4f6f9);
  overflow: hidden;
  border: 1px solid var(--fm-border);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--fm-text-muted);
  opacity: 0.55;
}

.product-skeleton-lines { flex: 1; padding-top: 4px; }

.compose-skeleton {
  display: flex;
  gap: 10px;
  align-items: center;
}

.compose-skeleton-img {
  position: relative;
  width: 64px;
  height: 64px;
  border-radius: var(--fm-radius-sm);
  background: linear-gradient(135deg, #e8edf3, #f4f6f9);
  overflow: hidden;
  border: 1px solid var(--fm-border);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--fm-text-muted);
  opacity: 0.55;
}

.compose-skeleton-lines { flex: 1; }

.search-skeleton { padding: 2px 0; }

.search-skeleton-row { margin-bottom: 8px; }
.search-skeleton-row:last-child { margin-bottom: 0; }

.chat-skeleton { margin-bottom: 8px; }

.typing-bubble--inline {
  display: inline-flex;
  gap: 5px;
  align-items: center;
  padding: 0;
}

.typing-bubble--inline span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--fm-text-muted);
  animation: blink 1.2s infinite;
}

.typing-bubble--inline span:nth-child(2) { animation-delay: 0.2s; }
.typing-bubble--inline span:nth-child(3) { animation-delay: 0.4s; }

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

.action-btn--loading {
  opacity: 0.72;
}

@keyframes tryonShotIn {
  from {
    opacity: 0;
    transform: translateY(12px) scale(0.96);
    filter: blur(2px);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
    filter: blur(0);
  }
}

@keyframes msgRowIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes userMsgIn {
  from { opacity: 0; transform: translateX(8px); }
  to { opacity: 1; transform: translateX(0); }
}

@keyframes textFadeIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes mediaFadeIn {
  from {
    opacity: 0;
    transform: scale(0.96);
    filter: blur(1px);
  }
  to {
    opacity: 1;
    transform: scale(1);
    filter: blur(0);
  }
}

@keyframes skeletonShimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

@keyframes loadingPulse {
  0%, 100% { opacity: 0.5; transform: scale(0.92); }
  50% { opacity: 1; transform: scale(1); }
}

:deep(.msg-image .el-image__inner),
:deep(.msg-product-img .el-image__inner) { border-radius: var(--fm-radius-sm); }

.action-btns { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }

.action-btn {
  border-radius: var(--fm-radius-pill);
  padding: 5px 13px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease, transform 0.15s ease;
}

.action-btn:active { transform: scale(0.98); }
.action-btn.assistant {
  background: var(--fm-primary-soft);
  border: 1px solid rgba(59, 130, 246, 0.35);
  color: var(--fm-primary-hover);
}

.action-btn.assistant:hover {
  background: var(--fm-primary);
  color: #fff;
}

.action-btn.user {
  background: rgba(0, 0, 0, 0.06);
  border: 1px solid rgba(0, 0, 0, 0.1);
  color: var(--fm-text);
}

.typing-bubble { display: flex; gap: 5px; align-items: center; padding: 12px 16px; }
.typing-bubble span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--fm-text-muted);
  animation: blink 1.2s infinite;
}

.typing-bubble span:nth-child(2) { animation-delay: 0.2s; }
.typing-bubble span:nth-child(3) { animation-delay: 0.4s; }

@keyframes blink { 0%, 80%, 100% { opacity: 0.3; } 40% { opacity: 1; } }

.quick-tips {
  padding: 8px 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  background: var(--fm-surface);
  border-top: 1px solid var(--fm-border);
}

.tips-label { font-size: 11px; color: var(--fm-text-muted); font-weight: 500; }

.tip-chip {
  background: var(--fm-surface);
  border: 1px solid var(--fm-border);
  color: var(--fm-primary-hover);
  border-radius: var(--fm-radius-pill);
  padding: 5px 12px;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
}

.tip-chip:hover:not(:disabled) {
  background: var(--fm-primary-soft);
  border-color: rgba(59, 130, 246, 0.35);
}

.tip-chip:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  transform: none;
}

.tip-chip:active:not(:disabled) { transform: scale(0.98); }

.wechat-compose {
  background: var(--fm-surface-subtle);
  border-top: 1px solid var(--fm-border);
}

.compose-toolbar {
  display: flex;
  gap: 4px;
  padding: 8px 14px 0;
}

.tool-btn {
  border: none;
  background: none;
  color: var(--fm-text-secondary);
  cursor: pointer;
  padding: 6px;
  border-radius: var(--fm-radius-sm);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s ease, color 0.15s ease;
}

.tool-btn:hover:not(:disabled) {
  background: var(--fm-surface);
  color: var(--fm-accent-hover);
}

.tool-btn:disabled { opacity: 0.35; cursor: not-allowed; }

.compose-box {
  margin: 8px 14px;
  background: var(--fm-surface);
  border: 1px solid var(--fm-border);
  border-radius: var(--fm-radius-md);
  padding: 10px;
  min-height: 92px;
  box-shadow: var(--fm-shadow-sm);
}

.compose-text {
  width: 100%;
  border: none;
  outline: none;
  resize: none;
  font-size: 14px;
  line-height: 1.55;
  background: transparent;
  font-family: inherit;
  color: var(--fm-text);
}

.compose-text::placeholder { color: var(--fm-text-muted); }

.attach-card {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
  padding: 8px;
  background: var(--fm-surface-muted);
  border: 1px solid var(--fm-border);
  border-radius: var(--fm-radius-sm);
  max-width: 320px;
}

.attach-thumb { width: 56px; height: 56px; border-radius: var(--fm-radius-sm); flex-shrink: 0; cursor: zoom-in; }
.attach-info { flex: 1; min-width: 0; }
.attach-name { font-size: 12px; color: var(--fm-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.attach-hint { font-size: 10px; color: var(--fm-text-muted); margin-top: 2px; }

.attach-remove {
  border: none;
  background: #ef4444;
  color: #fff;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  cursor: pointer;
  flex-shrink: 0;
  font-size: 16px;
  line-height: 1;
  transition: transform 0.15s ease;
}

.attach-remove:active { transform: scale(0.95); }

.compose-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 14px 12px;
}

.compose-tip { font-size: 11px; color: var(--fm-text-muted); }

.btn-send-text {
  background: var(--fm-surface);
  border: 1px solid var(--fm-border-strong);
  border-radius: var(--fm-radius-sm);
  padding: 6px 18px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  color: var(--fm-text-secondary);
  transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
}

.btn-send-text:hover:not(:disabled) {
  background: var(--fm-accent);
  color: #fff;
  border-color: var(--fm-accent);
}

.btn-send-text:active:not(:disabled) { transform: scale(0.98); }
.btn-send-text:disabled { opacity: 0.55; cursor: not-allowed; }

.catalog-header {
  padding: 14px 12px;
  font-weight: 600;
  font-size: 13px;
  border-bottom: 1px solid var(--fm-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  color: var(--fm-text);
}

.badge {
  background: var(--fm-accent);
  color: #fff;
  border-radius: var(--fm-radius-pill);
  padding: 1px 8px;
  font-size: 10px;
  font-weight: 700;
}

.category-chips {
  padding: 10px 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  border-bottom: 1px solid var(--fm-border);
  max-height: 88px;
  overflow-y: auto;
}

.cat-chip {
  background: var(--fm-surface-muted);
  border: 1px solid var(--fm-border);
  border-radius: var(--fm-radius-pill);
  padding: 3px 9px;
  font-size: 10px;
  cursor: pointer;
  color: var(--fm-text-secondary);
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.cat-chip.active,
.cat-chip:hover {
  background: var(--fm-accent-soft);
  border-color: var(--fm-accent-muted);
  color: var(--fm-accent-hover);
}

.product-grid { flex: 1; overflow-y: auto; padding: 10px 8px; }

.product-card {
  display: flex;
  gap: 10px;
  padding: 9px;
  border-radius: var(--fm-radius-md);
  cursor: pointer;
  margin-bottom: 6px;
  border: 1px solid var(--fm-border);
  background: var(--fm-surface);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

.product-card:hover:not(.product-card--loading) {
  background: var(--fm-accent-soft);
  border-color: var(--fm-accent-muted);
  transform: translateX(-2px);
  box-shadow: var(--fm-shadow-md);
}

.product-card--loading {
  opacity: 0.65;
  pointer-events: none;
  border-color: var(--fm-accent-muted);
  background: var(--fm-accent-soft);
}

.product-img-wrap {
  width: 54px;
  height: 54px;
  border-radius: var(--fm-radius-sm);
  overflow: hidden;
  background: var(--fm-surface-subtle);
  flex-shrink: 0;
  transition: transform 0.2s ease;
}

.product-card:hover .product-img-wrap { transform: scale(1.04); }
.product-img-wrap img { width: 100%; height: 100%; object-fit: cover; }

.no-img {
  font-size: 10px;
  color: var(--fm-text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.product-info { min-width: 0; flex: 1; }
.product-name { font-size: 11px; color: var(--fm-text); font-weight: 600; }
.product-code { font-size: 10px; color: var(--fm-accent-hover); margin-top: 2px; font-weight: 500; }
.product-cat { font-size: 10px; color: var(--fm-text-muted); margin-top: 1px; }
.catalog-empty { padding: 24px 16px; text-align: center; color: var(--fm-text-muted); font-size: 12px; }

.ctx-menu {
  position: fixed;
  background: var(--fm-surface);
  border: 1px solid var(--fm-border);
  border-radius: var(--fm-radius-md);
  box-shadow: var(--fm-shadow-lg);
  z-index: 9999;
  overflow: hidden;
  min-width: 140px;
}

.ctx-delete {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 10px 16px;
  border: none;
  background: none;
  text-align: left;
  font-size: 13px;
  cursor: pointer;
  color: var(--fm-text-secondary);
  transition: background 0.15s ease, color 0.15s ease;
}

.ctx-delete:hover { background: #fef2f2; color: #dc2626; }
</style>
