<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../../api'

const docs = ref([])
const total = ref(0)
const vectorCount = ref(0)
const file = ref(null)
const docType = ref('faq')
const filterType = ref('all')
const previewVisible = ref(false)
const previewData = ref(null)
const previewLoading = ref(false)

const typeOptions = [
  { value: 'all', label: '全部' },
  { value: 'faq', label: 'FAQ' },
  { value: 'script', label: '话术' },
  { value: 'policy', label: '政策' },
  { value: 'product', label: '商品说明' },
]

const typeLabel = (t) => typeOptions.find((o) => o.value === t)?.label || t

const filteredDocs = computed(() => {
  if (filterType.value === 'all') return docs.value
  return docs.value.filter((d) => d.doc_type === filterType.value)
})

async function load() {
  const data = await api.listKnowledge(filterType.value)
  docs.value = data.items || []
  total.value = data.total || 0
  vectorCount.value = data.vector_count || 0
}

function onFilterChange() {
  load()
}

function onChange(f) {
  file.value = f.raw
}

async function upload() {
  if (!file.value) return ElMessage.warning('请选择文件')
  const fd = new FormData()
  fd.append('file', file.value)
  fd.append('doc_type', docType.value)
  try {
    await api.uploadKnowledge(fd)
    ElMessage.success('上传成功，已向量化入库')
    file.value = null
    await load()
  } catch (e) {
    ElMessage.error(e.message || '上传失败')
  }
}

async function showPreview(row) {
  previewLoading.value = true
  previewVisible.value = true
  previewData.value = null
  try {
    previewData.value = await api.previewKnowledge(row.id)
  } catch (e) {
    ElMessage.error(e.message || '预览失败')
    previewVisible.value = false
  } finally {
    previewLoading.value = false
  }
}

function downloadFile(row) {
  window.open(`/api/knowledge/${row.id}/download`, '_blank')
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确定删除「${row.title}」？向量将同步删除。`, '删除确认', { type: 'warning' })
    const res = await api.deleteKnowledge(row.id)
    ElMessage.success(`已删除，当前向量数: ${res?.vector_count ?? '-'}`)
    await load()
  } catch { /* cancelled */ }
}

function formatSize(bytes) {
  if (!bytes) return '-'
  if (bytes < 1024) return bytes + ' B'
  return (bytes / 1024).toFixed(1) + ' KB'
}

function formatTime(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

onMounted(load)
</script>

<template>
  <div class="knowledge-page fm-page">
    <header class="fm-page-header">
      <h1 class="fm-page-title">知识库管理</h1>
      <p class="fm-page-desc">上传 FAQ、话术与政策文档，自动向量化供 AI 客服检索</p>
    </header>

    <el-card class="fm-card">
      <template #header>
        <div class="card-header">
          <span class="stats">文档 {{ total }} 篇 · 向量 {{ vectorCount }} 条</span>
        </div>
      </template>

      <el-form inline class="upload-form">
        <el-form-item label="上传类型">
          <el-select v-model="docType" style="width:120px">
            <el-option v-for="o in typeOptions.filter(x => x.value !== 'all')" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-upload :auto-upload="false" :limit="1" accept=".txt,.md,.pdf,.docx,.doc" :on-change="onChange">
            <el-button>选择文件 (txt/md/pdf/docx)</el-button>
          </el-upload>
        </el-form-item>
        <el-button type="primary" @click="upload">上传入库</el-button>
      </el-form>

      <div class="filter-bar">
        <span class="filter-label">筛选：</span>
        <el-radio-group v-model="filterType" @change="onFilterChange">
          <el-radio-button v-for="o in typeOptions" :key="o.value" :value="o.value">{{ o.label }}</el-radio-button>
        </el-radio-group>
        <span class="filter-count">显示 {{ filteredDocs.length }} 条</span>
      </div>

      <el-table :data="filteredDocs" style="margin-top:12px" empty-text="暂无文档，请上传或运行 seed_demo_data.py">
        <el-table-column prop="title" label="文件名" min-width="180" />
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.doc_type === 'faq' ? '' : row.doc_type === 'script' ? 'success' : row.doc_type === 'policy' ? 'warning' : 'info'">
              {{ typeLabel(row.doc_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="向量块" width="80" />
        <el-table-column label="大小" width="90">
          <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="上传时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="80" />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="showPreview(row)">预览</el-button>
            <el-button link @click="downloadFile(row)">下载</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="previewVisible" :title="previewData?.title || '文档预览'" width="720px" destroy-on-close>
      <div v-loading="previewLoading">
        <div v-if="previewData" class="preview-meta">
          <el-tag size="small">{{ typeLabel(previewData.doc_type) }}</el-tag>
          <span>{{ previewData.extension }} · {{ formatSize(previewData.file_size) }} · {{ previewData.chunk_count }} 向量块</span>
        </div>
        <pre v-if="previewData" class="preview-body">{{ previewData.preview_text }}</pre>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.knowledge-page {
  height: 100vh;
  overflow-y: auto;
  box-sizing: border-box;
}

.card-header { display: flex; justify-content: flex-end; align-items: center; }
.stats { font-size: 13px; color: var(--fm-text-muted); font-weight: 500; }
.upload-form { margin-bottom: 8px; }
.filter-bar { display: flex; align-items: center; gap: 12px; margin-top: 8px; flex-wrap: wrap; }
.filter-label { font-size: 13px; color: var(--fm-text-secondary); font-weight: 500; }
.filter-count { font-size: 12px; color: var(--fm-text-muted); margin-left: auto; }
.preview-meta { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; font-size: 13px; color: var(--fm-text-secondary); }

.preview-body {
  background: var(--fm-surface-muted);
  border: 1px solid var(--fm-border);
  border-radius: var(--fm-radius-md);
  padding: 16px;
  max-height: 480px;
  overflow: auto;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--fm-text);
}
</style>
