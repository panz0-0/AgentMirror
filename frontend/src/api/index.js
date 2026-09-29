import axios from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 180000 })

http.interceptors.response.use(
  (res) => {
    const body = res.data
    if (body && body.code === 200) return body.data
    return Promise.reject(new Error(body?.message || '请求失败'))
  },
  (error) => {
    const status = error?.response?.status
    const detail = error?.response?.data?.detail
    const message = status === 500
      ? '服务器开小差了，请稍后重试'
      : (detail || error?.message || '请求失败')
    return Promise.reject(new Error(message))
  },
)

export const api = {
  health: () => http.get('/health'),
  listSkus: (params) => http.get('/sku', { params }),
  getSku: (id) => http.get(`/sku/${id}`),
  getSkuWorkspace: (id) => http.get(`/sku/${id}/workspace`),
  createSku: (formData) => http.post('/sku', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  updateSku: (id, formData) => http.put(`/sku/${id}`, formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  startGeneration: (payload) => http.post('/generation/start', payload),
  resumeGeneration: (payload) => http.post('/generation/resume', payload),
  ensureGenerationJob: (payload) => http.post('/generation/ensure', payload),
  getLatestJob: (skuId) => http.get(`/generation/sku/${skuId}/latest`),
  getJob: (id) => http.get(`/generation/${id}`),
  createSession: (payload) => http.post('/chat/session', payload),
  listSessions: (userId) => http.get('/chat/sessions', { params: { user_id: userId } }),
  deleteSession: (sessionId, userId = 'guest') => http.delete(`/chat/session/${sessionId}`, { params: { user_id: userId } }),
  getHistory: (sessionId) => http.get(`/chat/session/${sessionId}/history`),
  sendMessage: (payload) => http.post('/chat/message', payload),
  sendComposeMessage: (formData) => http.post('/chat/message/compose', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  introduceProduct: (skuId, formData) => http.post(`/chat/product/${skuId}`, formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  startTryon: (formData) => http.post('/chat/tryon', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  getCatalog: () => http.get('/chat/catalog'),
  listKnowledge: (docType = 'all') => http.get('/knowledge/list', { params: { doc_type: docType } }),
  previewKnowledge: (id) => http.get(`/knowledge/${id}/preview`),
  uploadKnowledge: (formData) => http.post('/knowledge/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  deleteKnowledge: (id) => http.delete(`/knowledge/${id}`),
  getMetadata: () => http.get('/metadata'),
  // 评测与 Badcase 闭环
  evalSummary: () => http.get('/evaluation/summary'),
  evalIntentCases: () => http.get('/evaluation/intent-cases'),
  evalQualityCases: () => http.get('/evaluation/quality-cases'),
  evalBadcases: (status) => http.get('/evaluation/badcases', { params: status ? { status } : {} }),
  evalSubmitFeedback: (id, payload) => http.post(`/evaluation/badcases/${id}/feedback`, payload),
  evalRun: () => http.post('/evaluation/run'),
  evalApplyBadcase: (id) => http.post(`/evaluation/badcases/${id}/apply`),
  evalDynamicRules: () => http.get('/evaluation/dynamic-rules'),
  evalRemoveRule: (ruleId) => http.delete(`/evaluation/dynamic-rules/${ruleId}`),

  // 调用日志
  getCallLogs: (params = {}) => http.get('/logs/calls', { params }),
}

export default http
