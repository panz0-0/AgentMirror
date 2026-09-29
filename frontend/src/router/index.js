import { createRouter, createWebHistory } from 'vue-router'
import AppShell from '../layouts/AppShell.vue'
import OpsWorkspace from '../views/ops/OpsWorkspace.vue'
import KnowledgeManage from '../views/ops/KnowledgeManage.vue'
import EvaluationDashboard from '../views/ops/EvaluationDashboard.vue'
import CallLogView from '../views/ops/CallLogView.vue'
import CustomerChat from '../views/customer/CustomerChat.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: AppShell,
      redirect: '/chat',
      children: [
        { path: 'chat', component: CustomerChat },
        { path: 'ops', component: OpsWorkspace },
        { path: 'ops/knowledge', component: KnowledgeManage },
        { path: 'ops/evaluation', component: EvaluationDashboard },
        { path: 'ops/logs', component: CallLogView },
      ],
    },
  ],
})
