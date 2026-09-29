<template>
  <el-container class="layout">
    <el-header class="header">
      <div class="brand">fitMirror</div>
      <el-menu mode="horizontal" :router="true" :default-active="$route.path">
        <el-menu-item index="/chat">AI 客服</el-menu-item>
        <el-menu-item index="/ops">运营工作台</el-menu-item>
        <el-menu-item index="/ops/knowledge">知识库</el-menu-item>
      </el-menu>
    </el-header>
    <el-main class="main-no-pad">
      <router-view />
    </el-main>
  </el-container>
</template>

<style scoped>
.layout { min-height: 100vh; }
.header { display: flex; align-items: center; background: #fff; border-bottom: 1px solid #eee; }
.brand { font-weight: 700; font-size: 20px; margin-right: 24px; color: #4a86ff; }
.main-no-pad { padding: 16px; }
</style>
