<template>
  <aside class="war-room-event-stream" data-testid="war-room-event-stream">
    <header>
      <div>
        <span class="section-kicker">实时事件流</span>
        <h2>{{ sourceLabel }}</h2>
      </div>
      <select disabled data-testid="war-room-event-filter">
        <option>全部事件</option>
      </select>
    </header>
    <div class="event-stream-list">
      <article v-for="event in normalizedEvents" :key="event.id" :class="event.tone">
        <time>{{ event.time }}</time>
        <div>
          <span>{{ event.type }}</span>
          <strong>{{ event.title }}</strong>
          <p>{{ event.detail }}</p>
          <small v-if="event.marker" data-testid="lifecycle-event-marker">{{ event.marker }}</small>
        </div>
      </article>
    </div>
    <footer>{{ footerLabel }}</footer>
  </aside>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  events: { type: Array, required: true },
  mode: { type: String, default: 'projection' }
})

const sourceLabel = computed(() => props.mode === 'live' ? '真实生命周期事件' : '历史本地确定性投影')
const footerLabel = computed(() => props.mode === 'live' ? '来自 run_events，可审计、可断点续传' : '当前为历史投影，不代表后台 worker 日志')

const normalizedEvents = computed(() => {
  return (props.events || []).map((event, index) => ({
    id: event.id || `${event.run_id || 'event'}-${event.seq || index}`,
    time: event.time || formatTime(event.created_at),
    type: event.type || event.event_type || 'ENGINE',
    title: event.title || '--',
    detail: event.detail || '',
    tone: event.tone || toneFor(event.event_type || event.type)
    ,marker: markerFor(event)
  }))
})

function formatTime(value) {
  if (!value) return '--:--:--'
  return String(value).replace('T', ' ').slice(11, 19)
}

function toneFor(type) {
  return {
    WORKER: 'blue',
    ENGINE: 'green',
    AGENT: 'cyan',
    CONSISTENCY: 'orange',
    SNAPSHOT: 'blue',
  }[String(type || '').toUpperCase()] || 'blue'
}

function markerFor(event) {
  const payload = event.payload || {}
  const title = String(event.title || '').toLowerCase()
  if (payload.recovered_by || title.includes('checkpoint')) return '检查点恢复'
  if (payload.idempotent) return '幂等命中'
  if (payload.attempt_number > 1 || title.includes('retry')) return '重试'
  if (title.includes('failed') || title.includes('failure')) return '失败'
  if (payload.attempt_number === 1 || title.includes('queued')) return '首次执行'
  return ''
}
</script>
