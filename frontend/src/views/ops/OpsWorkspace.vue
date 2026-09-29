<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Picture, Search } from '@element-plus/icons-vue'
import { api } from '../../api'

const skus = ref([])
const skuTotal = ref(0)
const skuFilter = ref({ keyword: '', status: '', category: '' })
const metadata = ref({ dropdowns: {}, platforms: {}, languages: {} })
const editingSkuId = ref('')
const currentImageUrl = ref('')
const form = ref({
  sku_code: '',
  name: '',
  category: '女装/连衣裙',
  style: '简约 modern minimal',
  platform: '淘宝',
  language: '中文',
  model_attrs: '',
  model_scene: '居家 Home',
  shooting_style: '棚拍 Studio',
  face_visible: 'show',
  additional_requirements: '',
})
const imageFile = ref(null)
const uploadRef = ref(null)
const job = ref(null)
const workspace = ref(null)
const stepStatusMsg = ref('')
const imageStatusMsg = ref('')
const imageProgress = ref({ done: 0, total: 0, percent: 0 })
const activeStep = ref(0)
const stepLoading = ref({ analyze: false, prompts: false, images: false })
const saveLoading = ref(false)
const openCampaign = ref([])
const openPrompts = ref([])

const isEditing = computed(() => !!editingSkuId.value)
const categories = computed(() => (metadata.value.dropdowns?.categories || []).filter(([, v]) => v && !v.startsWith('——')))
const styles = computed(() => (metadata.value.dropdowns?.styles || []).filter(([, v]) => v && !v.startsWith('——')))
const platforms = computed(() => (metadata.value.platforms?.options || []).filter(([, v]) => v && !v.startsWith('——')))
const languages = computed(() => (metadata.value.languages?.options || []).filter(([, v]) => v && !v.startsWith('——')))
const modelScenes = computed(() => (metadata.value.dropdowns?.model_scenes || []).filter(([, v]) => v && !v.startsWith('——')))
const shootingStyles = computed(() => (metadata.value.dropdowns?.shooting_styles || []).filter(([, v]) => v && !v.startsWith('——')))
const faceOptions = computed(() => metadata.value.dropdowns?.face_options || [['show', '露脸'], ['hide', '不露脸']])

const skuStatusOptions = computed(() => {
  const set = new Set(skus.value.map((s) => s.status).filter(Boolean))
  return [...set].sort()
})

const skuCategoryOptions = computed(() => {
  const set = new Set(skus.value.map((s) => s.category).filter(Boolean))
  return [...set].sort()
})

const filteredSkus = computed(() => {
  const kw = skuFilter.value.keyword.trim().toLowerCase()
  const { status, category } = skuFilter.value
  return skus.value.filter((s) => {
    if (status && s.status !== status) return false
    if (category && s.category !== category) return false
    if (!kw) return true
    const hay = `${s.sku_code || ''} ${s.name || ''} ${s.category || ''}`.toLowerCase()
    return hay.includes(kw)
  })
})

const hasActiveSkuFilters = computed(() =>
  Boolean(skuFilter.value.keyword.trim() || skuFilter.value.status || skuFilter.value.category)
)

const SKU_STATUS_META = {
  draft: { label: '草稿', class: 'sku-st-draft' },
  analyzed: { label: '已分析', class: 'sku-st-analyzed' },
  ready: { label: '就绪', class: 'sku-st-ready' },
  generating: { label: '生成中', class: 'sku-st-generating' },
  generated: { label: '已完成', class: 'sku-st-done' },
  done: { label: '已完成', class: 'sku-st-done' },
}

function skuStatusLabel(status) {
  return SKU_STATUS_META[status]?.label || status
}

function skuStatusClass(status) {
  return SKU_STATUS_META[status]?.class || 'sku-st-default'
}

function clearSkuFilters() {
  skuFilter.value = { keyword: '', status: '', category: '' }
}

const canGenPrompts = computed(() => workspace.value?.has_campaign && !stepLoading.value.analyze)
const canGenImages = computed(() => {
  if (!workspace.value?.has_prompts || stepLoading.value.prompts) return false
  const ip = workspace.value?.image_progress
  if (ip?.complete) return false
  return true
})

const IMAGE_ORDER = ['H1', 'H2', 'H3', 'H4', 'H5', 'product_ref', 'D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7', 'D8', 'D9']
const sortedImages = computed(() => {
  const imgs = workspace.value?.images || []
  return [...imgs].sort((a, b) => {
    const ia = IMAGE_ORDER.indexOf(a.code)
    const ib = IMAGE_ORDER.indexOf(b.code)
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
  })
})
const imagePreviewList = computed(() => sortedImages.value.map((i) => i.url))
const showImageProgress = computed(() =>
  stepLoading.value.images ||
  (imageProgress.value.total > 0 && imageProgress.value.done < imageProgress.value.total)
)

const STAGE_MSG = {
  start: '准备分析...',
  stage1: '视觉分析中...',
  stage2: '营销策略生成中...',
  stage3: '提示词生成中...',
  campaign: '等待确认营销策略',
  prompts: '等待确认提示词',
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

function syncImageProgress(ws) {
  const p = ws?.image_progress || {}
  const done = p.done ?? 0
  const total = p.total ?? 0
  imageProgress.value = {
    done,
    total,
    percent: total ? Math.round((done / total) * 100) : 0,
  }
  if (total && done >= total) {
    imageStatusMsg.value = '图片已生成完成'
  } else if (total) {
    imageStatusMsg.value = `已完成 ${done}/${total} 张`
  } else {
    imageStatusMsg.value = ''
  }
}

function updateImageProgressFromJob(data) {
  const p = data.progress || data.image_progress || {}
  const total = p.total || imageProgress.value.total || 0
  const done = p.done ?? imageProgress.value.done ?? 0
  if (!total) return
  imageProgress.value = {
    done,
    total,
    percent: Math.round((done / total) * 100),
  }
  const code = p.code ? ` · ${p.code}` : ''
  imageStatusMsg.value = `图片生成中 ${done}/${total}${code}`
}

function updateStepStatusFromJob(data) {
  const p = data.progress || {}
  const stage = p.stage || data.current_node || ''
  stepStatusMsg.value = STAGE_MSG[stage] || (data.status === 'running' ? '处理中...' : '')
  if (data.status === 'failed') {
    stepStatusMsg.value = `失败: ${data.error_msg || p.error || '未知错误'}`
  }
}

function isImageJob(data) {
  if (!data) return false
  const stage = data.progress?.stage || data.progress_json?.stage
  return data.current_node === 'images' || ['images', 'image_done', 'images_partial'].includes(stage)
}

function syncActiveStep(ws) {
  if (!ws) { activeStep.value = 0; return }
  if (ws.image_progress?.complete) {
    activeStep.value = 4
  } else if (ws.has_images) {
    activeStep.value = 3
  } else if (ws.has_prompts) {
    activeStep.value = 2
  } else if (ws.has_campaign) {
    activeStep.value = 1
  } else {
    activeStep.value = 0
  }
}

async function loadWorkspace(skuId) {
  if (!skuId) {
    workspace.value = null
    imageProgress.value = { done: 0, total: 0, percent: 0 }
    imageStatusMsg.value = ''
    return
  }
  workspace.value = await api.getSkuWorkspace(skuId)
  syncActiveStep(workspace.value)
  syncImageProgress(workspace.value)
  if (workspace.value?.campaign_sections?.length) {
    openCampaign.value = [workspace.value.campaign_sections[0].key]
  }
  if (workspace.value?.prompt_list?.length) {
    openPrompts.value = [workspace.value.prompt_list[0].code]
  }
}

async function loadJobState(skuId) {
  const latest = await api.getLatestJob(skuId)
  if (latest) {
    job.value = latest
    if (isImageJob(latest) && latest.status === 'running') {
      updateImageProgressFromJob(latest)
      stepLoading.value.images = true
      resumePolling(latest.job_id || latest.id, latest)
    } else {
      updateStepStatusFromJob(latest)
      if (latest.image_progress) syncImageProgress({ image_progress: latest.image_progress })
    }
  } else {
    job.value = null
    stepStatusMsg.value = ''
  }
}

let pollToken = 0
async function pollJob(jobId, until, { maxIter = 120, onTick } = {}) {
  const token = ++pollToken
  for (let i = 0; i < maxIter; i++) {
    if (token !== pollToken) return null
    const data = await api.getJob(jobId)
    job.value = data
    if (onTick) onTick(data)
    else updateStepStatusFromJob(data)
    if (data.status === 'failed') {
      throw new Error(data.error_msg || data.progress?.error || '任务失败')
    }
    if (until(data)) {
      await loadWorkspace(editingSkuId.value)
      await loadSkus()
      return data
    }
    if (i % 3 === 0) await loadWorkspace(editingSkuId.value)
    await sleep(2000)
  }
  throw new Error('任务超时，请稍后刷新查看')
}

async function pollImageJob(jobId, until) {
  const token = ++pollToken
  for (let i = 0; i < 600; i++) {
    if (token !== pollToken) return null
    const data = await api.getJob(jobId)
    job.value = data
    updateImageProgressFromJob(data)
    if (data.status === 'failed') {
      throw new Error(data.error_msg || data.progress?.error || '图片生成失败')
    }
    if (i % 1 === 0 || data.progress?.stage === 'image_done') {
      await loadWorkspace(editingSkuId.value)
    }
    if (until(data)) {
      await loadWorkspace(editingSkuId.value)
      await loadSkus()
      syncImageProgress(workspace.value)
      return data
    }
    await sleep(1000)
  }
  throw new Error('图片生成超时，已生成的图片会保留，可再次点击继续')
}

function resumePolling(jobId, latest) {
  if (isImageJob(latest)) {
    pollImageJob(jobId, (d) =>
      d.status === 'done' ||
      (d.status === 'paused' && d.progress?.stage === 'images_partial') ||
      d.status === 'failed'
    )
      .then((d) => {
        if (d?.status === 'done') ElMessage.success('图片生成完成！')
        else if (d?.progress?.stage === 'images_partial') {
          ElMessage.warning('部分图片未完成，可再次点击「生成图片」继续')
        }
      })
      .catch((e) => ElMessage.error(e.message))
      .finally(() => { stepLoading.value.images = false })
    return
  }
  pollJob(jobId, (d) => d.status === 'paused' || d.status === 'done' || d.status === 'failed')
    .then((d) => {
      if (d?.status === 'paused') ElMessage.success('任务已完成，请查看下方内容')
    })
    .catch((e) => ElMessage.error(e.message))
    .finally(() => {
      stepLoading.value.analyze = false
      stepLoading.value.prompts = false
    })
}

function resetForm() {
  editingSkuId.value = ''
  currentImageUrl.value = ''
  imageFile.value = null
  uploadRef.value?.clearFiles()
  job.value = null
  workspace.value = null
  stepStatusMsg.value = ''
  imageStatusMsg.value = ''
  imageProgress.value = { done: 0, total: 0, percent: 0 }
  activeStep.value = 0
  pollToken++
  form.value = {
    sku_code: '', name: '', category: '女装/连衣裙', style: '简约 modern minimal',
    platform: '淘宝', language: '中文', model_attrs: '',
    model_scene: '居家 Home', shooting_style: '棚拍 Studio', face_visible: 'show',
    additional_requirements: '',
  }
}

async function loadMeta() {
  metadata.value = await api.getMetadata()
}

async function loadSkus() {
  const data = await api.listSkus({ page: 1, size: 500 })
  skus.value = data.items || []
  skuTotal.value = data.total ?? skus.value.length
}

async function selectSku(row) {
  if (!row?.id) return
  editingSkuId.value = row.id
  pollToken++
  stepLoading.value = { analyze: false, prompts: false, images: false }
  try {
    const detail = await api.getSku(row.id)
    form.value = {
      sku_code: detail.sku_code || '',
      name: detail.name || '',
      category: detail.category || '女装/连衣裙',
      style: detail.style || '',
      platform: detail.platform || '淘宝',
      language: detail.language || '中文',
      model_attrs: detail.model_attrs || '',
      model_scene: detail.model_scene || '居家 Home',
      shooting_style: detail.shooting_style || '棚拍 Studio',
      face_visible: detail.face_visible || 'show',
      additional_requirements: detail.additional_requirements || '',
    }
    currentImageUrl.value = detail.source_image_path ? `/api/sku/${row.id}/image?t=${Date.now()}` : ''
    imageFile.value = null
    await loadWorkspace(row.id)
    await loadJobState(row.id)
    ElMessage.success(`已加载 ${detail.sku_code}`)
  } catch (e) {
    ElMessage.error(e.message || '加载失败')
  }
}

function buildFormData() {
  const fd = new FormData()
  Object.entries(form.value).forEach(([k, v]) => fd.append(k, v ?? ''))
  if (imageFile.value) fd.append('image', imageFile.value)
  return fd
}

async function saveSku() {
  if (!form.value.sku_code) return ElMessage.warning('请填写 SKU')
  saveLoading.value = true
  try {
    const fd = buildFormData()
    if (isEditing.value) {
      await api.updateSku(editingSkuId.value, fd)
      ElMessage.success('SKU 已保存')
    } else {
      const data = await api.createSku(fd)
      editingSkuId.value = data.id
      ElMessage.success('SKU 已创建')
    }
    await loadSkus()
    if (editingSkuId.value) {
      currentImageUrl.value = `/api/sku/${editingSkuId.value}/image?t=${Date.now()}`
    }
  } finally {
    saveLoading.value = false
  }
}

function onFileChange(file) {
  // 清除 upload 内部文件列表，避免 limit 阻止下次更换
  uploadRef.value?.clearFiles()
  imageFile.value = file.raw
  currentImageUrl.value = URL.createObjectURL(file.raw)
}

function onFileExceed(files) {
  // 已选过图片时再点"更换"会触发 exceed，手动替换
  uploadRef.value?.clearFiles()
  if (files?.[0]) {
    imageFile.value = files[0]
    currentImageUrl.value = URL.createObjectURL(files[0])
  }
}

async function analyzeCurrent() {
  const skuId = editingSkuId.value
  if (!skuId) return ElMessage.warning('请先选择或创建 SKU')
  stepLoading.value.analyze = true
  stepStatusMsg.value = '正在提交分析任务...'
  job.value = null
  try {
    const data = await api.startGeneration({ sku_id: skuId, mode: 'hero', stop_at: 'campaign' })
    job.value = data
    const result = await pollJob(data.job_id, (d) => d.status === 'paused' || d.status === 'failed')
    if (result?.status === 'paused') {
      ElMessage.success('分析完成！请查看营销策略，确认后生成提示词')
    }
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    stepLoading.value.analyze = false
  }
}

async function ensureJob(node) {
  if (job.value?.job_id && job.value.status === 'paused' && job.value.current_node === node) {
    return job.value.job_id || job.value.id
  }
  const ensured = await api.ensureGenerationJob({ sku_id: editingSkuId.value, node, mode: 'hero' })
  job.value = { ...job.value, ...ensured, id: ensured.job_id }
  return ensured.job_id
}

async function confirmPrompts() {
  if (!workspace.value?.has_campaign) return ElMessage.warning('请先完成产品分析')
  stepLoading.value.prompts = true
  try {
    const jobId = await ensureJob('campaign')
    stepStatusMsg.value = '正在生成提示词...'
    await api.resumeGeneration({ job_id: jobId, action: 'confirm' })
    const result = await pollJob(jobId, (d) =>
      (d.status === 'paused' && d.current_node === 'prompts') || d.status === 'failed'
    )
    if (result?.current_node === 'prompts') {
      ElMessage.success(`提示词已生成（${workspace.value?.prompt_list?.length || 0} 条），可开始出图`)
    }
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    stepLoading.value.prompts = false
  }
}

async function generateImages() {
  if (!workspace.value?.has_prompts) return ElMessage.warning('请先生成提示词')
  const ip = workspace.value?.image_progress
  if (ip?.complete) return ElMessage.info('图片已全部生成')
  stepLoading.value.images = true
  try {
    const jobId = await ensureJob('prompts')
    imageStatusMsg.value = '正在生成图片，请耐心等待...'
    await api.resumeGeneration({ job_id: jobId, action: 'confirm' })
    const result = await pollImageJob(jobId, (d) =>
      d.status === 'done' ||
      (d.status === 'paused' && d.progress?.stage === 'images_partial') ||
      d.status === 'failed'
    )
    if (result?.status === 'done') {
      ElMessage.success('图片生成完成！')
    } else if (result?.progress?.stage === 'images_partial') {
      ElMessage.warning('部分图片未完成，可再次点击继续生成')
    }
  } catch (e) {
    ElMessage.error(e.message)
    await loadWorkspace(editingSkuId.value)
  } finally {
    stepLoading.value.images = false
  }
}

function formatSectionValue(val) {
  if (Array.isArray(val)) return val
  return [String(val)]
}

onMounted(async () => {
  await loadMeta()
  await loadSkus()
})
</script>

<template>
  <div class="ops-page fm-page">
    <header class="fm-page-header">
      <h1 class="fm-page-title">运营工作台</h1>
      <p class="fm-page-desc">管理 SKU、生成营销策略与商品视觉素材</p>
    </header>

    <el-steps :active="activeStep" finish-status="success" align-center class="steps-bar fm-card">
      <el-step title="产品分析" description="Stage1+2" />
      <el-step title="营销策略" description="确认 campaign" />
      <el-step title="提示词" description="Stage3 prompts" />
      <el-step title="生成图片" description="H/D/M 主图" />
    </el-steps>

    <el-row :gutter="16" class="ops-row">
      <!-- 左：产品信息 -->
      <el-col :span="7">
        <el-card class="fm-card">
          <template #header>
            <div class="card-header">
              <span>① 产品信息</span>
              <el-tag v-if="isEditing" type="success" size="small">编辑中</el-tag>
              <el-tag v-else type="info" size="small">新建</el-tag>
            </div>
          </template>
          <el-form label-width="72px" size="small">
            <el-form-item label="SKU"><el-input v-model="form.sku_code" :disabled="isEditing" /></el-form-item>
            <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
            <el-form-item label="类目">
              <el-select v-model="form.category" filterable style="width:100%">
                <el-option v-for="[val, label] in categories" :key="val" :label="label" :value="val" />
              </el-select>
            </el-form-item>
            <el-form-item label="风格">
              <el-select v-model="form.style" filterable style="width:100%">
                <el-option v-for="[val, label] in styles" :key="val" :label="label" :value="val" />
              </el-select>
            </el-form-item>
            <el-form-item label="模特"><el-input v-model="form.model_attrs" placeholder="亚洲女性, 身高165cm, 体重55kg" /></el-form-item>
            <el-form-item label="图片">
              <div class="img-row">
                <el-image v-if="currentImageUrl" :src="currentImageUrl" class="preview-img" fit="cover" :preview-src-list="[currentImageUrl]" />
                <el-upload
                  ref="uploadRef"
                  :auto-upload="false"
                  :show-file-list="false"
                  :on-change="onFileChange"
                  :on-exceed="onFileExceed"
                >
                  <el-button size="small">{{ currentImageUrl ? '更换' : '选择图片' }}</el-button>
                </el-upload>
              </div>
            </el-form-item>
            <div class="form-actions">
              <el-button type="primary" :loading="saveLoading" @click="saveSku">{{ isEditing ? '保存' : '创建' }}</el-button>
              <el-button type="warning" :loading="stepLoading.analyze" :disabled="!isEditing" @click="analyzeCurrent">
                <el-icon class="btn-icon-gap"><Search /></el-icon>
                分析产品
              </el-button>
              <el-button @click="resetForm">新建</el-button>
            </div>
          </el-form>
        </el-card>
        <el-card class="fm-card sku-list-card">
          <template #header>
            <div class="sku-list-header">
              <span>SKU 列表 <span class="sku-count">{{ filteredSkus.length }}/{{ skuTotal }}</span></span>
            </div>
          </template>
          <div class="sku-filter-bar">
            <el-input
              v-model="skuFilter.keyword"
              size="small"
              clearable
              placeholder="搜索 SKU / 名称"
              class="sku-filter-search"
            >
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <el-select
              v-model="skuFilter.status"
              size="small"
              clearable
              placeholder="状态"
              class="sku-filter-select"
            >
              <el-option
                v-for="st in skuStatusOptions"
                :key="st"
                :label="skuStatusLabel(st)"
                :value="st"
              />
            </el-select>
            <el-select
              v-model="skuFilter.category"
              size="small"
              clearable
              placeholder="类目"
              class="sku-filter-select sku-filter-category"
            >
              <el-option v-for="cat in skuCategoryOptions" :key="cat" :label="cat" :value="cat" />
            </el-select>
            <el-button
              v-if="hasActiveSkuFilters"
              size="small"
              text
              type="primary"
              class="sku-filter-clear"
              @click="clearSkuFilters"
            >
              清除
            </el-button>
          </div>
          <el-table
            :data="filteredSkus"
            size="small"
            height="380"
            highlight-current-row
            :row-class-name="({ row }) => (row.id === editingSkuId ? 'row-active' : '')"
            @row-click="selectSku"
          >
            <el-table-column label="图" width="48">
              <template #default="{ row }">
                <img v-if="row.source_image_path" :src="`/api/sku/${row.id}/image`" class="sku-thumb" />
              </template>
            </el-table-column>
            <el-table-column prop="sku_code" label="SKU" width="96" show-overflow-tooltip />
            <el-table-column prop="name" label="名称" min-width="100" show-overflow-tooltip />
            <el-table-column prop="category" label="类目" width="88" show-overflow-tooltip />
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag size="small" :class="['sku-status-tag', skuStatusClass(row.status)]">
                  {{ skuStatusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="!filteredSkus.length" class="sku-list-empty">无匹配 SKU</div>
        </el-card>
      </el-col>

      <!-- 中：策略 + 提示词 -->
      <el-col :span="10">
        <el-card class="panel-card fm-card">
          <template #header><span>② 营销策略 & 提示词</span></template>

          <div v-if="stepStatusMsg && (stepLoading.analyze || stepLoading.prompts)" class="status-box light">
            <p class="status-text">{{ stepStatusMsg }}</p>
          </div>

          <div v-if="workspace?.product_name" class="product-name">{{ workspace.product_name }}</div>

          <div v-if="workspace?.has_campaign" class="section-block">
            <h4>营销策略 (campaign.json)</h4>
            <el-collapse v-model="openCampaign">
              <el-collapse-item v-for="sec in workspace.campaign_sections" :key="sec.key" :title="sec.label" :name="sec.key">
                <ul v-if="Array.isArray(sec.value)" class="value-list">
                  <li v-for="(item, i) in sec.value" :key="i">{{ item }}</li>
                </ul>
                <p v-else>{{ sec.value }}</p>
              </el-collapse-item>
            </el-collapse>
            <el-button type="success" class="action-btn" :loading="stepLoading.prompts" :disabled="!canGenPrompts" @click="confirmPrompts">
              <el-icon class="btn-icon-gap"><Check /></el-icon>
              确认并生成提示词
            </el-button>
          </div>
          <el-empty v-else description="点击「分析产品」后在此显示营销策略" :image-size="60" />

          <div v-if="workspace?.has_prompts" class="section-block prompts-block">
            <h4>提示词 (prompts.json) · 共 {{ workspace.prompt_list.length }} 条</h4>
            <el-collapse v-model="openPrompts">
              <el-collapse-item v-for="p in workspace.prompt_list" :key="p.code" :name="p.code">
                <template #title>
                  <span class="prompt-code">{{ p.code }}</span>
                  <span class="prompt-meta">{{ p.size }} · {{ (p.objective || '').slice(0, 30) }}</span>
                </template>
                <pre class="prompt-text">{{ p.prompt }}</pre>
              </el-collapse-item>
            </el-collapse>
          </div>
        </el-card>
      </el-col>

      <!-- 右：出图 -->
      <el-col :span="7">
        <el-card class="panel-card fm-card">
          <template #header><span>③ 生成图片</span></template>
          <el-button type="warning" class="action-btn full" :loading="stepLoading.images" :disabled="!canGenImages" @click="generateImages">
            <el-icon class="btn-icon-gap"><Picture /></el-icon>
            {{ workspace?.image_progress?.complete ? '图片已生成' : (workspace?.image_progress?.done ? '继续生成图片' : '生成图片') }}
          </el-button>
          <p v-if="!workspace?.has_prompts" class="hint">请先在中间栏确认并生成提示词</p>

          <div v-if="showImageProgress" class="status-box image-progress">
            <p class="status-text">{{ imageStatusMsg || '图片生成中...' }}</p>
            <el-progress :percentage="imageProgress.percent" :stroke-width="10" />
          </div>

          <div v-if="sortedImages.length" class="img-grid">
            <div v-for="(img, idx) in sortedImages" :key="img.id" class="img-item" :class="{ 'is-ref': img.code === 'product_ref' }">
              <div class="img-thumb-wrap">
                <el-image
                  :src="img.url"
                  :preview-src-list="imagePreviewList"
                  :initial-index="idx"
                  fit="cover"
                  class="gen-img"
                  preview-teleported
                  lazy
                />
                <div class="img-overlay">
                  <span class="overlay-text">预览</span>
                </div>
              </div>
              <span class="img-code">{{ img.code }}</span>
            </div>
          </div>
          <el-empty v-else-if="workspace?.has_prompts" description="点击「生成图片」后在此展示" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.ops-page {
  height: 100vh;
  overflow-y: auto;
  box-sizing: border-box;
}

.steps-bar {
  margin-bottom: 16px;
  background: var(--fm-surface);
  padding: 18px 16px;
  border-radius: var(--fm-radius-lg);
  border: 1px solid var(--fm-border);
  box-shadow: var(--fm-shadow-sm);
}

.ops-row { min-height: calc(100vh - 200px); }
.sku-list-card { margin-top: 12px; flex: 1; display: flex; flex-direction: column; min-height: 0; }

.sku-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sku-count {
  font-size: 11px;
  color: var(--fm-text-muted);
  font-weight: 500;
  margin-left: 4px;
}

.sku-filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  margin-bottom: 10px;
  background: linear-gradient(180deg, var(--fm-surface) 0%, var(--fm-surface-muted) 100%);
  border: 1px solid var(--fm-border);
  border-radius: var(--fm-radius-md);
  box-shadow: var(--fm-shadow-sm);
}

.sku-filter-search {
  flex: 1;
  min-width: 0;
}

.sku-filter-select {
  width: 88px;
  flex-shrink: 0;
}

.sku-filter-category {
  width: 108px;
}

.sku-filter-clear {
  flex-shrink: 0;
  padding: 0 4px;
}

.sku-filter-bar :deep(.el-input__wrapper),
.sku-filter-bar :deep(.el-select__wrapper) {
  box-shadow: none;
  background: var(--fm-surface);
  border: 1px solid var(--fm-border);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.sku-filter-bar :deep(.el-input__wrapper:hover),
.sku-filter-bar :deep(.el-select__wrapper:hover) {
  border-color: var(--fm-border-strong);
}

.sku-filter-bar :deep(.el-input__wrapper.is-focus),
.sku-filter-bar :deep(.el-select__wrapper.is-focused) {
  border-color: var(--fm-primary);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.12);
}

.sku-status-tag {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  border: none;
  font-weight: 600;
  font-size: 11px;
  padding: 0 8px;
  height: 22px;
  line-height: 22px;
}

/* 草稿 */
.sku-st-draft {
  background: #f1f5f9;
  color: #64748b;
}

/* 已分析 — 蓝，表示分析阶段完成 */
.sku-st-analyzed {
  background: #eff6ff;
  color: #2563eb;
}

/* 就绪 — 青绿，表示可继续生成 */
.sku-st-ready {
  background: #ecfdf5;
  color: #059669;
}

/* 生成中 */
.sku-st-generating {
  background: #fff7ed;
  color: #ea580c;
}

/* 已完成 */
.sku-st-done {
  background: #d1fae5;
  color: #047857;
}

.sku-st-default {
  background: #f8fafc;
  color: #475569;
}

.sku-list-empty {
  padding: 16px;
  text-align: center;
  font-size: 12px;
  color: var(--fm-text-muted);
}
.card-header { display: flex; align-items: center; gap: 8px; }
.btn-icon-gap { margin-right: 4px; }

.sku-thumb {
  width: 36px;
  height: 36px;
  object-fit: cover;
  border-radius: var(--fm-radius-sm);
  border: 1px solid var(--fm-border);
}

.preview-img {
  width: 64px;
  height: 64px;
  border-radius: var(--fm-radius-sm);
  border: 1px solid var(--fm-border);
}

.img-row { display: flex; align-items: center; gap: 8px; }
.form-actions { display: flex; gap: 6px; flex-wrap: wrap; }
:deep(.row-active) { background: var(--fm-primary-soft) !important; }
.panel-card { min-height: 480px; }

.status-box {
  background: var(--fm-primary-soft);
  border: 1px solid rgba(59, 130, 246, 0.2);
  border-radius: var(--fm-radius-md);
  padding: 10px 12px;
  margin-bottom: 12px;
}

.status-box.light {
  background: var(--fm-surface-muted);
  border-color: var(--fm-border);
}

.status-box.image-progress { margin-top: 12px; }
.status-text { font-size: 13px; color: var(--fm-primary-hover); margin: 0 0 8px; }

.product-name {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 12px;
  color: var(--fm-text);
  letter-spacing: -0.02em;
}

.section-block { margin-bottom: 16px; }
.section-block h4 { font-size: 13px; color: var(--fm-text-secondary); margin: 0 0 8px; font-weight: 600; }
.prompts-block { border-top: 1px solid var(--fm-border); padding-top: 12px; }
.prompt-code { font-weight: 700; color: var(--fm-primary); margin-right: 8px; }
.prompt-meta { font-size: 11px; color: var(--fm-text-muted); }

.prompt-text {
  white-space: pre-wrap;
  font-size: 12px;
  line-height: 1.55;
  background: var(--fm-surface-muted);
  padding: 10px;
  border-radius: var(--fm-radius-sm);
  border: 1px solid var(--fm-border);
  max-height: 200px;
  overflow-y: auto;
}

.value-list { margin: 0; padding-left: 18px; font-size: 13px; color: var(--fm-text-secondary); }
.action-btn { margin-top: 12px; }
.action-btn.full { width: 100%; }
.hint { font-size: 12px; color: var(--fm-text-muted); margin-top: 8px; }

.img-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-top: 12px; }
.img-item { text-align: center; }
.img-item.is-ref { grid-column: 1 / -1; }

.img-thumb-wrap {
  position: relative;
  width: 100%;
  aspect-ratio: 3 / 4;
  border-radius: var(--fm-radius-md);
  overflow: hidden;
  border: 1px solid var(--fm-border);
  background: var(--fm-surface-muted);
  cursor: zoom-in;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}

.img-item.is-ref .img-thumb-wrap { aspect-ratio: 16 / 9; max-height: 140px; }

.img-thumb-wrap:hover {
  transform: translateY(-2px);
  box-shadow: var(--fm-shadow-md);
  border-color: var(--fm-accent-muted);
}

.gen-img { width: 100%; height: 100%; display: block; }
:deep(.gen-img .el-image__inner) { width: 100%; height: 100%; object-fit: cover; transition: transform 0.3s ease; }
.img-thumb-wrap:hover :deep(.gen-img .el-image__inner) { transform: scale(1.04); }

.img-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(15, 23, 42, 0);
  transition: background 0.2s ease;
  pointer-events: none;
}

.img-thumb-wrap:hover .img-overlay { background: rgba(15, 23, 42, 0.22); }

.overlay-text {
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  opacity: 0;
  transform: translateY(4px);
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.img-thumb-wrap:hover .overlay-text { opacity: 1; transform: translateY(0); }
.img-code { display: block; font-size: 11px; color: var(--fm-text-secondary); margin-top: 6px; font-weight: 600; }
</style>
