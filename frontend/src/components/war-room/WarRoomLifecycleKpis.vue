<template>
  <section class="war-room-lifecycle-kpis" data-testid="war-room-lifecycle-kpis">
    <article v-for="kpi in kpis" :key="kpi.key" :class="kpi.tone">
      <span>{{ kpi.label }}</span>
      <strong>{{ kpi.value }}<small>{{ kpi.unit }}</small></strong>
      <p>{{ kpi.detail }}</p>
      <em v-if="kpi.delta !== undefined && kpi.delta !== null" :class="deltaClass(kpi.delta)">{{ signed(kpi.delta) }}</em>
      <i></i>
    </article>
  </section>
</template>

<script setup>
defineProps({
  kpis: { type: Array, required: true }
})

function signed(value) {
  const number = Number(value || 0)
  if (!Number.isFinite(number) || number === 0) return '0'
  return `${number > 0 ? '+' : ''}${number.toFixed(Math.abs(number) >= 10 ? 0 : 1)}`
}

function deltaClass(value) {
  const number = Number(value || 0)
  if (number > 0) return 'up'
  if (number < 0) return 'down'
  return 'flat'
}
</script>
