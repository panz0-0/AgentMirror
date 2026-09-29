<template>
  <div class="app-shell">
    <aside class="nav-rail">
      <div class="brand-block" title="fitMirror">
        <div class="brand-mark">
          <el-icon :size="22"><Monitor /></el-icon>
        </div>
        <span class="brand-name">fitMirror</span>
      </div>
      <nav class="nav-items">
        <router-link to="/chat" class="nav-item" :class="{ active: isChat }">
          <el-icon class="nav-icon" :size="20"><ChatDotRound /></el-icon>
          <span class="nav-label">AI客服</span>
        </router-link>
        <router-link to="/ops" class="nav-item" :class="{ active: isOps }">
          <el-icon class="nav-icon" :size="20"><SetUp /></el-icon>
          <span class="nav-label">运营台</span>
        </router-link>
        <router-link to="/ops/knowledge" class="nav-item" :class="{ active: isKnowledge }">
          <el-icon class="nav-icon" :size="20"><Collection /></el-icon>
          <span class="nav-label">知识库</span>
        </router-link>
        <router-link to="/ops/evaluation" class="nav-item" :class="{ active: isEvaluation }">
          <el-icon class="nav-icon" :size="20"><DataAnalysis /></el-icon>
          <span class="nav-label">评测</span>
        </router-link>
        <router-link to="/ops/logs" class="nav-item" :class="{ active: isLogs }">
          <el-icon class="nav-icon" :size="20"><Document /></el-icon>
          <span class="nav-label">调用日志</span>
        </router-link>
      </nav>
    </aside>

    <main class="shell-main">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { ChatDotRound, Collection, DataAnalysis, Document, Monitor, SetUp } from '@element-plus/icons-vue'

const route = useRoute()
const isChat = computed(() => route.path === '/chat' || route.path === '/')
const isOps = computed(() => route.path === '/ops')
const isKnowledge = computed(() => route.path.startsWith('/ops/knowledge'))
const isEvaluation = computed(() => route.path.startsWith('/ops/evaluation'))
const isLogs = computed(() => route.path.startsWith('/ops/logs'))
</script>

<style scoped>
.app-shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.nav-rail {
  width: 76px;
  background: var(--fm-nav-bg);
  border-right: 1px solid var(--fm-nav-border);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 18px 0 16px;
  flex-shrink: 0;
  z-index: 100;
}

.brand-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 28px;
  cursor: default;
}

.brand-mark {
  width: 44px;
  height: 44px;
  border-radius: var(--fm-radius-md);
  background: linear-gradient(145deg, rgba(16, 185, 129, 0.25), rgba(59, 130, 246, 0.2));
  border: 1px solid rgba(255, 255, 255, 0.12);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6ee7b7;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

.brand-name {
  color: rgba(255, 255, 255, 0.55);
  font-size: 9px;
  margin-top: 6px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.nav-items {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
  padding: 0 10px;
}

.nav-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 10px 4px;
  border-radius: var(--fm-radius-md);
  color: var(--fm-nav-text);
  text-decoration: none;
  font-size: 11px;
  font-weight: 500;
  transition: background 0.18s ease, color 0.18s ease, transform 0.18s ease;
}

.nav-item:hover {
  background: var(--fm-nav-bg-hover);
  color: #fff;
}

.nav-item.active {
  background: var(--fm-nav-active-bg);
  color: var(--fm-nav-active-text);
}

.nav-item:active {
  transform: scale(0.97);
}

.nav-icon {
  opacity: 0.9;
}

.shell-main {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  background: var(--fm-surface-muted);
}
</style>
