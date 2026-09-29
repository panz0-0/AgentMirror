<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../../api'

// 领域枚举（独立，不复用）
const BADCASE_STATUS = {
  open: { label: '待处理', type: 'danger' },
  resolved: { label: '已解决', type: 'success' },
  ignored: { label: '已忽略', type: 'info' },
}
const CASE_TYPE = {
  intent: { label: '意图错误', type: 'warning' },
  quality: { label: '回复质量', type: 'danger' },
}
const SOURCE_LABEL = {
  online: { label: '线上', type: 'danger' },
  offline: { label: '离线', type: 'info' },
}

const loading = ref(false)
const running = ref(false)
const activeTab = ref('overview')
const summary = ref({})
const intentCases = ref([])
const qualityCases = ref([])
const badcases = ref([])
const badcaseFilter = ref('all')
const badcaseSource = ref('all')

// 分页状态（每页 10 条）
const PAGE_SIZE = 10
const intentPage = ref(1)
const qualityPage = ref(1)
const badcasePage = ref(1)

// 反馈弹窗
const feedbackVisible = ref(false)
const feedbackTarget = ref(null)
const feedbackForm = ref({ status: 'open', feedback_note: '', reclassified_intent: '', expected_reply: '' })

const intentOptions = [
  'product_tryon', 'product_catalog', 'product_intro',
  'policy_faq', 'general_chat', 'similar_product', 'product_advice',
]

const filteredBadcases = computed(() => {
  let list = badcases.value
  if (badcaseFilter.value !== 'all') list = list.filter((b) => b.status === badcaseFilter.value)
  if (badcaseSource.value !== 'all') list = list.filter((b) => b.source === badcaseSource.value)
  return list
})

// 分页数据
const pagedIntent = computed(() => {
  const start = (intentPage.value - 1) * PAGE_SIZE
  return intentCases.value.slice(start, start + PAGE_SIZE)
})
const pagedQuality = computed(() => {
  const start = (qualityPage.value - 1) * PAGE_SIZE
  return qualityCases.value.slice(start, start + PAGE_SIZE)
})
const pagedBadcases = computed(() => {
  const start = (badcasePage.value - 1) * PAGE_SIZE
  return filteredBadcases.value.slice(start, start + PAGE_SIZE)
})

// 筛选变化时回到第 1 页
watch([badcaseFilter, badcaseSource], () => { badcasePage.value = 1 })

async function loadAll() {
  loading.value = true
  try {
    const [s, ic, qc, bc] = await Promise.all([
      api.evalSummary(),
      api.evalIntentCases(),
      api.evalQualityCases(),
      api.evalBadcases(),
    ])
    summary.value = s
    intentCases.value = ic || []
    qualityCases.value = qc || []
    badcases.value = bc || []
  } catch (e) {
    ElMessage.error(e.message || '加载评测数据失败')
  } finally {
    loading.value = false
  }
}

async function runEvaluation() {
  running.value = true
  try {
    await api.evalRun()
    ElMessage.success('评测完成，已刷新数据')
    await loadAll()
  } catch (e) {
    ElMessage.error(e.message || '评测执行失败')
  } finally {
    running.value = false
  }
}

function openFeedback(row) {
  feedbackTarget.value = row
  feedbackForm.value = {
    status: row.status || 'open',
    feedback_note: row.feedback_note || '',
    reclassified_intent: row.reclassified_intent || '',
    expected_reply: row.expected_reply || '',
  }
  feedbackVisible.value = true
}

async function submitFeedback() {
  if (!feedbackTarget.value) return
  try {
    await api.evalSubmitFeedback(feedbackTarget.value.id, feedbackForm.value)
    ElMessage.success('反馈已提交')
    feedbackVisible.value = false
    await loadAll()
  } catch (e) {
    ElMessage.error(e.message || '提交失败')
  }
}

async function applyReflux(row) {
  if (row.case_type === 'quality' && !row.expected_reply) {
    ElMessage.warning('请先在「反馈」中填写期望回复，再执行自动回流')
    return
  }
  try {
    const res = await api.evalApplyBadcase(row.id)
    if (res.applied) {
      const paths = Object.entries(res.paths || {})
        .filter(([, v]) => v.applied)
        .map(([k]) => k)
      ElMessage.success(`自动回流成功：${paths.join('、')}`)
    } else {
      const reasons = Object.entries(res.paths || {})
        .filter(([, v]) => !v.applied)
        .map(([k, v]) => `${k}: ${v.reason}`)
      ElMessage.warning(`回流未应用：${reasons.join('；')}`)
    }
    await loadAll()
  } catch (e) {
    ElMessage.error(e.message || '回流失败')
  }
}

function scoreColor(score) {
  if (score >= 4.5) return '#10b981'
  if (score >= 3.5) return '#f59e0b'
  return '#ef4444'
}

function pct(v) {
  if (v == null) return '-'
  return (v * 100).toFixed(1) + '%'
}

onMounted(loadAll)
</script>

<template>
  <div class="eval-page fm-page" v-loading="loading">
    <header class="fm-page-header">
      <div>
        <h1 class="fm-page-title">评测与 Badcase 回流闭环</h1>
        <p class="fm-page-desc">量化意图分类与回复质量，Badcase 反馈驱动迭代</p>
      </div>
      <el-button type="primary" :loading="running" @click="runEvaluation">
        {{ running ? '评测中...' : '执行全量评测' }}
      </el-button>
    </header>

    <el-tabs v-model="activeTab" class="eval-tabs">
      <!-- 总览 -->
      <el-tab-pane label="总览指标" name="overview">
        <el-row :gutter="16">
          <el-col :span="6">
            <el-card class="metric-card" shadow="hover">
              <div class="metric-label">意图准确率</div>
              <div class="metric-value" :style="{ color: '#10b981' }">
                {{ pct(summary.intent?.accuracy) }}
              </div>
              <div class="metric-sub">
                {{ summary.intent?.correct }} / {{ summary.intent?.total }} 正确
              </div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card class="metric-card" shadow="hover">
              <div class="metric-label">Macro F1</div>
              <div class="metric-value" :style="{ color: '#3b82f6' }">
                {{ pct(summary.intent?.macro_f1) }}
              </div>
              <div class="metric-sub">多类别均衡指标</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card class="metric-card" shadow="hover">
              <div class="metric-label">回复质量均分</div>
              <div class="metric-value" :style="{ color: '#8b5cf6' }">
                {{ summary.quality?.correctness_avg?.toFixed(1) || '-' }}
              </div>
              <div class="metric-sub">
                相关性 {{ summary.quality?.relevance_avg?.toFixed(1) }} ·
                完整性 {{ summary.quality?.completeness_avg?.toFixed(1) }}
              </div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card class="metric-card" shadow="hover">
              <div class="metric-label">Badcase 解决率</div>
              <div class="metric-value" :style="{ color: '#f59e0b' }">
                {{ pct(summary.badcase?.resolve_rate) }}
              </div>
              <div class="metric-sub">
                待处理 {{ summary.badcase?.open }} ·
                已解决 {{ summary.badcase?.resolved }} ·
                线上 {{ summary.badcase?.online_count || 0 }} ·
                离线 {{ summary.badcase?.offline_count || 0 }}
              </div>
            </el-card>
          </el-col>
        </el-row>

        <el-card class="fm-card" style="margin-top:16px">
          <template #header><span class="card-title">质量维度雷达</span></template>
          <div class="radar-bars">
            <div v-for="dim in ['relevance_avg','correctness_avg','completeness_avg','usefulness_avg']" :key="dim" class="bar-row">
              <span class="bar-label">{{ {relevance_avg:'相关性',correctness_avg:'正确性',completeness_avg:'完整性',usefulness_avg:'有用性'}[dim] }}</span>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: (summary.quality?.[dim] || 0) * 20 + '%', background: scoreColor(summary.quality?.[dim] || 0) }"></div>
              </div>
              <span class="bar-value">{{ summary.quality?.[dim]?.toFixed(1) || '-' }}</span>
            </div>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- 意图样本 -->
      <el-tab-pane label="意图样本" name="intent">
        <el-card class="fm-card">
          <template #header>
            <span class="card-title">意图分类明细（{{ intentCases.length }} 条）</span>
          </template>
          <el-table :data="pagedIntent" size="small" max-height="520">
            <el-table-column label="样本" min-width="200">
              <template #default="{ row }">{{ row.text || '(空文本/图片)' }}</template>
            </el-table-column>
            <el-table-column label="期望意图" width="140">
              <template #default="{ row }"><el-tag size="small" type="info">{{ row.expected_intent }}</el-tag></template>
            </el-table-column>
            <el-table-column label="预测意图" width="140">
              <template #default="{ row }">
                <el-tag size="small" :type="row.correct ? 'success' : 'danger'">{{ row.predicted_intent }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="路由匹配" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.route_match != null" size="small" :type="row.route_match ? 'success' : 'danger'">
                  {{ row.route_match ? '是' : '否' }}
                </el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="置信度" width="90">
              <template #default="{ row }">{{ (row.confidence * 100).toFixed(0) }}%</template>
            </el-table-column>
            <el-table-column label="结果" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="row.correct ? 'success' : 'danger'">{{ row.correct ? '通过' : '失败' }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
          <div class="pagination-wrap">
            <el-pagination
              v-model:current-page="intentPage"
              :page-size="PAGE_SIZE"
              :total="intentCases.length"
              layout="prev, pager, next, jumper"
              background
              small
            />
          </div>
        </el-card>
      </el-tab-pane>

      <!-- 质量样本 -->
      <el-tab-pane label="质量样本" name="quality">
        <el-card class="fm-card">
          <template #header>
            <span class="card-title">回复质量明细（{{ qualityCases.length }} 条）</span>
          </template>
          <el-table :data="pagedQuality" size="small" max-height="520">
            <el-table-column label="问题" min-width="160">
              <template #default="{ row }">{{ row.query }}</template>
            </el-table-column>
            <el-table-column label="路由" width="150">
              <template #default="{ row }">
                <el-tag size="small" :type="row.agentflow ? 'success' : 'info'">{{ row.route }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="相关性" width="80" align="center">
              <template #default="{ row }"><b :style="{color:scoreColor(row.relevance)}">{{ row.relevance }}</b></template>
            </el-table-column>
            <el-table-column label="正确性" width="80" align="center">
              <template #default="{ row }"><b :style="{color:scoreColor(row.correctness)}">{{ row.correctness }}</b></template>
            </el-table-column>
            <el-table-column label="完整性" width="80" align="center">
              <template #default="{ row }"><b :style="{color:scoreColor(row.completeness)}">{{ row.completeness }}</b></template>
            </el-table-column>
            <el-table-column label="有用性" width="80" align="center">
              <template #default="{ row }"><b :style="{color:scoreColor(row.usefulness)}">{{ row.usefulness }}</b></template>
            </el-table-column>
            <el-table-column label="评审" width="70" align="center">
              <template #default="{ row }">{{ row.judge_source }}</template>
            </el-table-column>
            <el-table-column label="延迟" width="90" align="right">
              <template #default="{ row }">{{ row.latency_ms }}ms</template>
            </el-table-column>
          </el-table>
          <div class="pagination-wrap">
            <el-pagination
              v-model:current-page="qualityPage"
              :page-size="PAGE_SIZE"
              :total="qualityCases.length"
              layout="prev, pager, next, jumper"
              background
              small
            />
          </div>
        </el-card>
      </el-tab-pane>

      <!-- Badcase 回流 -->
      <el-tab-pane label="Badcase 回流" name="badcase">
        <el-card class="fm-card">
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span class="card-title">Badcase 列表（{{ badcases.length }} 条）</span>
              <div style="display:flex;gap:8px;align-items:center">
                <el-radio-group v-model="badcaseSource" size="small">
                  <el-radio-button value="all">全部来源</el-radio-button>
                  <el-radio-button value="online">线上</el-radio-button>
                  <el-radio-button value="offline">离线</el-radio-button>
                </el-radio-group>
                <el-radio-group v-model="badcaseFilter" size="small">
                  <el-radio-button value="all">全部</el-radio-button>
                  <el-radio-button value="open">待处理</el-radio-button>
                  <el-radio-button value="resolved">已解决</el-radio-button>
                  <el-radio-button value="ignored">已忽略</el-radio-button>
                </el-radio-group>
              </div>
            </div>
          </template>

          <el-empty v-if="filteredBadcases.length === 0" description="暂无 Badcase，所有样本通过评测" />

          <el-table v-else :data="pagedBadcases" size="small" max-height="520">
            <el-table-column label="类型" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="CASE_TYPE[row.case_type].type">{{ CASE_TYPE[row.case_type].label }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="来源" width="70">
              <template #default="{ row }">
                <el-tag v-if="SOURCE_LABEL[row.source]" size="small" :type="SOURCE_LABEL[row.source].type">{{ SOURCE_LABEL[row.source].label }}</el-tag>
                <span v-else style="color:#9ca3af;font-size:12px">-</span>
              </template>
            </el-table-column>
            <el-table-column label="问题" min-width="180">
              <template #default="{ row }">{{ row.query }}</template>
            </el-table-column>
            <el-table-column label="期望" width="130">
              <template #default="{ row }"><el-tag size="small" type="info">{{ row.expected }}</el-tag></template>
            </el-table-column>
            <el-table-column label="实际" width="130">
              <template #default="{ row }"><el-tag size="small" type="danger">{{ row.actual }}</el-tag></template>
            </el-table-column>
            <el-table-column label="失败原因" min-width="160">
              <template #default="{ row }">
                <span v-if="row.failure_reason" style="color:#ef4444;font-size:12px">{{ row.failure_reason }}</span>
                <span v-else style="color:#9ca3af;font-size:12px">-</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="BADCASE_STATUS[row.status].type">{{ BADCASE_STATUS[row.status].label }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="180" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openFeedback(row)">反馈</el-button>
                <el-button link type="success" @click="applyReflux(row)">自动回流</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="filteredBadcases.length > 0" class="pagination-wrap">
            <el-pagination
              v-model:current-page="badcasePage"
              :page-size="PAGE_SIZE"
              :total="filteredBadcases.length"
              layout="prev, pager, next, jumper"
              background
              small
            />
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- 反馈弹窗 -->
    <el-dialog v-model="feedbackVisible" title="Badcase 反馈" width="560px" destroy-on-close>
      <div v-if="feedbackTarget" class="feedback-context">
        <div class="ctx-row"><span class="ctx-label">问题：</span>{{ feedbackTarget.query }}</div>
        <div class="ctx-row">
          <span class="ctx-label">类型：</span>
          <el-tag size="small" :type="CASE_TYPE[feedbackTarget.case_type].type">{{ CASE_TYPE[feedbackTarget.case_type].label }}</el-tag>
        </div>
        <div class="ctx-row"><span class="ctx-label">期望：</span>{{ feedbackTarget.expected }}</div>
        <div class="ctx-row"><span class="ctx-label">实际：</span>{{ feedbackTarget.actual }}</div>
      </div>

      <el-form label-width="100px" style="margin-top:16px">
        <el-form-item label="处理状态">
          <el-radio-group v-model="feedbackForm.status">
            <el-radio value="open">待处理</el-radio>
            <el-radio value="resolved">已解决</el-radio>
            <el-radio value="ignored">已忽略</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="feedbackTarget?.case_type === 'intent'" label="重分类意图">
          <el-select v-model="feedbackForm.reclassified_intent" placeholder="选择正确意图" clearable style="width:100%">
            <el-option v-for="i in intentOptions" :key="i" :label="i" :value="i" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="feedbackTarget?.case_type === 'quality'" label="期望回复">
          <el-input v-model="feedbackForm.expected_reply" type="textarea" :rows="3" placeholder="描述期望的回复内容" />
        </el-form-item>
        <el-form-item label="反馈备注">
          <el-input v-model="feedbackForm.feedback_note" type="textarea" :rows="2" placeholder="记录问题原因或修复方案" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="feedbackVisible = false">取消</el-button>
        <el-button type="primary" @click="submitFeedback">提交反馈</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.eval-page {
  height: 100vh;
  overflow-y: auto;
  box-sizing: border-box;
}
.eval-tabs { margin-top: 8px; }
.metric-card { text-align: center; }
.metric-label { font-size: 13px; color: var(--fm-text-muted); font-weight: 500; }
.metric-value { font-size: 32px; font-weight: 700; margin: 6px 0; }
.metric-sub { font-size: 12px; color: var(--fm-text-muted); }
.card-title { font-weight: 600; }
.radar-bars { display: flex; flex-direction: column; gap: 12px; padding: 8px 0; }
.bar-row { display: flex; align-items: center; gap: 12px; }
.bar-label { width: 60px; font-size: 13px; color: var(--fm-text-secondary); }
.bar-track { flex: 1; height: 16px; background: var(--fm-surface-muted); border-radius: 8px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 8px; transition: width 0.4s ease; }
.bar-value { width: 40px; text-align: right; font-size: 13px; font-weight: 600; }
.feedback-context { background: var(--fm-surface-muted); border-radius: 8px; padding: 12px; font-size: 13px; }
.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 12px; }
.ctx-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.ctx-label { color: var(--fm-text-muted); flex-shrink: 0; }
</style>
