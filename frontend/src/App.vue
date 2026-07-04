<template>
  <div class="app-shell">
    <header class="studio-header">
      <RouterLink to="/" class="brand" aria-label="返回 WorldPulse Studio 首页">
        <span class="brand-mark"><Globe2 :size="18" /></span>
        <span>
          <strong>WorldPulse Studio</strong>
          <small>项目制全球局势研判系统</small>
        </span>
      </RouterLink>
      <nav class="top-nav">
        <RouterLink to="/"><LayoutDashboard :size="16" /> 控制台</RouterLink>
        <a href="/api/health" target="_blank" rel="noreferrer"><Activity :size="16" /> API</a>
        <a href="https://github.com/wangyufanshuai/worldpulse" target="_blank" rel="noreferrer"><Github :size="16" /> GitHub</a>
      </nav>
    </header>
    <RouterView />
  </div>
</template>

<script setup>
import { Activity, Github, Globe2, LayoutDashboard } from 'lucide-vue-next'
</script>
