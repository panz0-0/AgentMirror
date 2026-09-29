<template>
  <div class="call-log-view">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>API 调用日志</span>
          <div class="filters">
            <el-select v-model="statusFilter" placeholder="状态码" size="small" style="width: 100px" @change="onFilterChange">
              <el-option label="全部" value="all" />
              <el-option label="2xx 成功" value="2xx" />
              <el-option label="4xx 客户端错误" value="4xx" />
              <el-option label="5xx 服务端错误" value="5xx" />
            </el-select>
            <el-input v-model="pathFilter" placeholder="路径关键词" size="small" style="width: 180px" clearable @change="onFilterChange" />
            <el-button type="primary" size="small" @click="loadLogs">刷新</el-button>
          </div>
        </div>
      </template>

      <el-table :data="pagedLogs" size="small" max-height="600" empty-text="暂无日志">
        <el-table-column label="时间" width="180">
          <template #default="{ row }"><span class="ts">{{ row.ts }}</span></template>
        </el-table-column>
        <el-table-column label="方法" width="60">
          <template #default="{ row }">
            <el-tag :type="methodTagType(row.method)" size="small" effect="plain">{{ row.method }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="路径" min-width="200" show-overflow-tooltip>
          <template #default="{ row }"><span class="path">{{ row.path }}</span></template>
        </el-table-column>
        <el-table-column label="状态" width="70" align="center">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="延迟" width="80" align="right">
          <template #default="{ row }">
            <span :class="row.latency_ms > 1000 ? 'latency-slow' : ''">{{ row.latency_ms }}ms</span>
          </template>
        </el-table-column>
        <el-table-column label="参数" width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.params ? JSON.stringify(row.params) : '-' }}</template>
        </el-table-column>
        <el-table-column label="错误" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.error" class="error-text">{{ row.error }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="logs.length"
          layout="total, prev, pager, next, jumper"
          small
          background
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../../api'

const PAGE_SIZE = 20

const logs = ref([])
const statusFilter = ref('all')
const pathFilter = ref('')
const currentPage = ref(1)
const pageSize = PAGE_SIZE

const pagedLogs = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return logs.value.slice(start, start + pageSize)
})

const methodTagType = (m) => ({ GET: 'info', POST: 'success', PUT: 'warning', DELETE: 'danger' }[m] || '')
const statusTagType = (s) => s < 300 ? 'success' : s < 400 ? 'info' : s < 500 ? 'warning' : 'danger'

function onFilterChange() {
  currentPage.value = 1
  loadLogs()
}

async function loadLogs() {
  try {
    const params = { limit: 200 }
    if (statusFilter.value !== 'all') params.status_filter = statusFilter.value
    if (pathFilter.value) params.path_filter = pathFilter.value
    const res = await api.getCallLogs(params)
    logs.value = res?.items || []
  } catch (e) {
    logs.value = []
  }
}

onMounted(loadLogs)
</script>

<style scoped>
.call-log-view { padding: 16px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.filters { display: flex; gap: 8px; align-items: center; }
.ts { font-family: monospace; font-size: 12px; color: var(--fm-text-secondary, #888); }
.path { font-family: monospace; font-size: 12px; }
.latency-slow { color: #f56c6c; font-weight: bold; }
.error-text { color: #f56c6c; font-size: 12px; font-family: monospace; }
.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 12px; }
</style>
