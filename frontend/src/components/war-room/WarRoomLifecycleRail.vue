<template>
  <section class="war-room-lifecycle-rail" data-testid="war-room-lifecycle-rail">
    <article v-for="stage in stages" :key="stage.key" :class="['lifecycle-stage', stage.status]">
      <span class="stage-index">{{ stage.index }}</span>
      <div>
        <strong>{{ stage.title }}</strong>
        <small>{{ stage.desc }}</small>
      </div>
      <i aria-hidden="true">{{ stage.status === 'done' ? '✓' : stage.status === 'current' ? '•' : '' }}</i>
    </article>
  </section>
</template>

<script setup>
defineProps({
  stages: { type: Array, required: true }
})
</script>
