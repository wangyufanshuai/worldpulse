<template>
  <header class="war-room-topbar">
    <div class="war-room-brand">
      <span class="brand-orbit"><Globe2 :size="25" /></span>
      <span>
        <strong>WorldPulse AI</strong>
        <small>地缘政治推演沙盘 · {{ WORLDPULSE_VERSION }}</small>
      </span>
    </div>
    <nav class="war-room-tabs" aria-label="War Room 模块">
      <RouterLink v-for="tab in topSections" :key="tab.key" :to="sectionPath(tab.key)" :class="{ active: activeSection === tab.key }">
        <component :is="tab.icon" :size="15" /> {{ tab.label }}
      </RouterLink>
    </nav>
    <div class="war-room-status">
      <span class="not-prediction"><AlertTriangle :size="17" /> 不是预测</span>
      <button type="button" class="top-icon-action" data-testid="war-room-command-search-trigger" @click="$emit('open-command-search')"><Search :size="17" /></button>
      <button type="button" class="top-icon-action" @click="$emit('show-upcoming', '说明中心', '这里将汇总模型边界、数据来源和操作说明。')"><Info :size="17" /></button>
      <RouterLink class="top-icon-action" :to="sectionPath('graph')" aria-label="知识图谱"><BookOpen :size="17" /></RouterLink>
      <RouterLink class="top-icon-action" :to="sectionPath('trust')" aria-label="可信度中心" data-testid="war-room-trust-link"><ShieldCheck :size="17" /></RouterLink>
      <RouterLink class="top-icon-action" :to="sectionPath('settings')" aria-label="设置"><Settings :size="17" /></RouterLink>
      <button type="button" class="top-icon-action" @click="$emit('show-upcoming', '通知中心', '告警订阅和运行完成提醒将在后续版本接入。')"><Bell :size="17" /></button>
      <span class="commander-avatar">指挥官</span>
      <ChevronDown :size="15" />
    </div>
  </header>
</template>

<script setup>
import { AlertTriangle, Bell, BookOpen, ChevronDown, Globe2, Info, Search, Settings, ShieldCheck } from 'lucide-vue-next'
import { WORLDPULSE_VERSION } from '../../version'

defineProps({
  activeSection: { type: String, required: true },
  sectionPath: { type: Function, required: true },
  topSections: { type: Array, required: true }
})

defineEmits(['open-command-search', 'show-upcoming'])
</script>
