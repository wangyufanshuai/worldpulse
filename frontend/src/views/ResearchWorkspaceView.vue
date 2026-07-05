<template>
  <ResearchWorkspacePage :project-id="projectId" :section="section" />
</template>

<script setup>
import ResearchWorkspacePage from './research-workspace/ResearchWorkspacePage.vue'

defineProps({ projectId: String, section: String })
</script>
