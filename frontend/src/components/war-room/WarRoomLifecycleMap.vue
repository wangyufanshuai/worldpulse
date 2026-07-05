<template>
  <section class="war-room-lifecycle-map" data-testid="war-room-lifecycle-map">
    <header>
      <div>
        <span class="section-kicker">全球态势演化与因果链</span>
        <h2>确定性地图 + 阶段 Tick</h2>
      </div>
      <div class="map-tools">
        <span>D+{{ activeReplayDay }}</span>
        <button type="button" data-testid="war-room-causal-toggle" @click="$emit('show-causal')">显示因果链</button>
      </div>
    </header>

    <div class="lifecycle-map-stage">
      <div class="lifecycle-tickbar" data-testid="war-room-lifecycle-ticks">
        <article
          v-for="tick in ticks"
          :key="tick.day"
          :data-testid="`war-room-map-tick-${tick.day}`"
          :class="{ active: tick.day === nearestTick }"
          @click="$emit('select-day', tick.day)"
        >
          <strong>D+{{ tick.day }}</strong>
          <span>{{ tick.label }}</span>
        </article>
      </div>

      <div class="lifecycle-map-canvas">
        <img :src="imageSrc" alt="WorldPulse 全球态势地图" />
        <svg viewBox="0 0 1000 560" preserveAspectRatio="none">
          <defs>
            <marker id="lifecycleArrow" markerWidth="8" markerHeight="8" refX="7" refY="3.5" orient="auto">
              <path d="M0,0 L8,3.5 L0,7 Z" fill="#36a7ff" />
            </marker>
            <marker id="lifecycleHotArrow" markerWidth="8" markerHeight="8" refX="7" refY="3.5" orient="auto">
              <path d="M0,0 L8,3.5 L0,7 Z" fill="#ff8a3d" />
            </marker>
          </defs>
          <g class="lifecycle-routes">
            <g
              v-for="route in routes.slice(0, 5)"
              :key="route.key"
              data-testid="war-room-map-route"
              @click="$emit('select-supply-chain', route.chain || route)"
            >
              <path class="route-hitbox" :d="route.path" />
              <path :d="route.path" marker-end="url(#lifecycleArrow)" />
              <circle
                v-if="route.mid"
                class="route-hotspot"
                :cx="route.mid.x"
                :cy="route.mid.y"
                r="7"
              />
            </g>
            <g
              v-for="edge in causalEdges.slice(0, 8)"
              :key="edge.id"
              class="hot"
              data-testid="war-room-map-causal-edge"
              @click="$emit('select-causal-edge', edge.edge || edge, edge.id)"
            >
              <path class="route-hitbox" :d="edge.path" />
              <path :d="edge.path" marker-end="url(#lifecycleHotArrow)" />
            </g>
          </g>
          <g class="lifecycle-countries">
            <g
              v-for="country in countries.slice(0, 10)"
              :key="country.code"
              :transform="`translate(${country.x}, ${country.y})`"
              :class="{ hot: Number(country.risk || 0) >= 70 }"
              data-testid="war-room-map-country"
              @click="$emit('select-country', country)"
              @dblclick="$emit('open-country-analysis', country.code)"
            >
              <circle class="aura" :r="country.radius + 12" />
              <circle class="core" :r="country.radius" />
              <text y="-18">{{ country.code }}</text>
              <text y="30">{{ Math.round(country.risk || 0) }}</text>
            </g>
          </g>
          <g class="lifecycle-events">
            <g
              v-for="event in events.slice(0, 5)"
              :key="event.key"
              :transform="`translate(${event.x}, ${event.y})`"
              data-testid="war-room-map-event"
              @click="$emit('select-event', event)"
            >
              <circle r="14" />
              <path d="M0 -7 L7 6 H-7 Z" />
              <text y="30">{{ event.label }}</text>
            </g>
          </g>
        </svg>
      </div>

      <footer class="lifecycle-map-footer">
        <span>模拟时间：{{ currentReplayTime }}</span>
        <span>已处理事件：{{ processedEvents }}</span>
        <span>活跃 Agent：{{ activeAgents }}</span>
        <span>推演速率：{{ replaySpeed }}.0x</span>
      </footer>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  activeAgents: { type: String, default: '18/20' },
  activeReplayDay: { type: Number, default: 0 },
  causalEdges: { type: Array, default: () => [] },
  countries: { type: Array, default: () => [] },
  currentReplayTime: { type: String, default: 'D+0' },
  events: { type: Array, default: () => [] },
  imageSrc: { type: String, required: true },
  processedEvents: { type: Number, default: 0 },
  replaySpeed: { type: Number, default: 1 },
  routes: { type: Array, default: () => [] }
})

defineEmits(['open-country-analysis', 'select-causal-edge', 'select-country', 'select-day', 'select-event', 'select-supply-chain', 'show-causal'])

const ticks = [
  { day: 0, label: '初始态势' },
  { day: 3, label: '局势升温' },
  { day: 7, label: '冲突扩散' },
  { day: 14, label: '多域对抗' },
  { day: 30, label: '长期影响' },
]

const nearestTick = computed(() => {
  return ticks.reduce((best, tick) => Math.abs(tick.day - props.activeReplayDay) < Math.abs(best.day - props.activeReplayDay) ? tick : best, ticks[0]).day
})
</script>
