<template>
  <div class="war-room-lifecycle-console">
    <WarRoomLifecycleControl
      :control="control"
      :show-delta-overlay="showDeltaOverlay"
      @cancel="$emit('cancel')"
      @clone="$emit('clone')"
      @compare="$emit('compare')"
      @pause="$emit('pause')"
      @replay="$emit('replay')"
      @resume="$emit('resume')"
      @retry="$emit('retry')"
      @run="$emit('run')"
      @show-upcoming="$emit('show-upcoming', $event)"
      @toggle-delta="$emit('toggle-delta')"
    />

    <WarRoomLifecycleMap
      :active-agents="activeAgents"
      :active-replay-day="activeReplayDay"
      :causal-edges="causalEdges"
      :countries="countries"
      :current-replay-time="currentReplayTime"
      :events="events"
      :image-src="imageSrc"
      :processed-events="processedEvents"
      :replay-speed="replaySpeed"
      :routes="routes"
      @open-country-analysis="$emit('open-country-analysis', $event)"
      @select-causal-edge="(edge, id) => $emit('select-causal-edge', edge, id)"
      @select-country="$emit('select-country', $event)"
      @select-day="$emit('select-day', $event)"
      @select-event="$emit('select-event', $event)"
      @select-supply-chain="$emit('select-supply-chain', $event)"
      @show-causal="$emit('show-causal')"
    />

    <WarRoomEventStream :events="lifecycleEvents" :mode="lifecycleEventMode" />

    <WarRoomConsistencyAudit :report="consistencyAudit" />

    <WarRoomLifecycleKpis :kpis="kpis" />
  </div>
</template>

<script setup>
import WarRoomEventStream from './WarRoomEventStream.vue'
import WarRoomConsistencyAudit from './WarRoomConsistencyAudit.vue'
import WarRoomLifecycleControl from './WarRoomLifecycleControl.vue'
import WarRoomLifecycleKpis from './WarRoomLifecycleKpis.vue'
import WarRoomLifecycleMap from './WarRoomLifecycleMap.vue'

defineProps({
  control: { type: Object, default: () => ({}) },
  showDeltaOverlay: { type: Boolean, default: false },
  activeAgents: { type: String, default: '0/20' },
  activeReplayDay: { type: [String, Number], default: 0 },
  causalEdges: { type: Array, default: () => [] },
  countries: { type: Array, default: () => [] },
  currentReplayTime: { type: String, default: '' },
  events: { type: Array, default: () => [] },
  imageSrc: { type: String, default: '' },
  processedEvents: { type: Number, default: 0 },
  replaySpeed: { type: [String, Number], default: 1 },
  routes: { type: Array, default: () => [] },
  lifecycleEvents: { type: Array, default: () => [] },
  lifecycleEventMode: { type: String, default: 'projection' },
  consistencyAudit: { type: Object, default: null },
  kpis: { type: Array, default: () => [] }
})

defineEmits([
  'cancel',
  'clone',
  'compare',
  'open-country-analysis',
  'pause',
  'replay',
  'resume',
  'retry',
  'run',
  'select-causal-edge',
  'select-country',
  'select-day',
  'select-event',
  'select-supply-chain',
  'show-causal',
  'show-upcoming',
  'toggle-delta'
])
</script>
