<template>
  <div v-if="toastMessage" class="war-room-toast">{{ toastMessage }}</div>
  <aside v-if="commandSearchOpen" class="feature-drawer command-search-drawer" data-testid="war-room-command-search">
    <button class="drawer-close" type="button" @click="$emit('close-command')"><X :size="16" /> 关闭</button>
    <div class="section-kicker"><Search :size="16" /> 指挥搜索</div><h2>定位国家、链路、事件和运行</h2>
    <label class="command-search-box">搜索实体<input :value="commandQuery" type="search" placeholder="输入：中国 / chips / D+14 / run id" data-testid="war-room-command-search-input" @input="$emit('update-query', $event.target.value)" /></label>
    <div class="command-result-list">
      <button v-for="item in commandSearchResults" :key="item.id" type="button" :data-entity-id="item.id" @click="$emit('activate-command', item)"><span>{{ entityTypeLabel(item.type) }}</span><strong>{{ item.title_zh }}</strong><small>{{ item.subtitle_zh }}</small></button>
    </div>
    <p v-if="!commandSearchResults.length" class="sandbox-note">没有匹配结果。可以搜索国家代码、供应链、D+天数或 Agent 决策。</p>
  </aside>
  <aside v-if="entityDetail" class="feature-drawer entity-detail-drawer" data-testid="war-room-entity-detail-drawer" :data-entity-id="entityDetail.id">
    <button class="drawer-close" type="button" @click="$emit('close-entity')"><X :size="16" /> 关闭</button>
    <div class="section-kicker"><FileSearch :size="16" /> 实体详情</div><h2>{{ entityDetail.title_zh || entityDetail.title }}</h2><p>{{ entityDetail.summary_zh || entityDetail.summary }}</p>
    <dl><div v-for="metric in entityDetail.metrics || []" :key="metric.label_zh || metric.label"><dt>{{ metric.label_zh || metric.label }}</dt><dd>{{ metric.value }}</dd></div></dl>
    <section v-if="entityDetail.related_events?.length" class="drawer-mini-section"><h3>关联事件</h3><p>{{ entityDetail.related_events.join(' / ') }}</p></section>
    <section v-if="entityDetail.decision_basis_zh" class="drawer-mini-section"><h3>决策依据</h3><p>{{ entityDetail.decision_basis_zh }}</p></section>
    <div class="drawer-action-row"><button v-for="action in entityDetail.actions || []" :key="action.key" type="button" :disabled="action.enabled === false" @click="$emit('entity-action', action, entityDetail)">{{ action.label_zh }}</button></div>
  </aside>
  <aside v-if="runDetailsOpen" class="feature-drawer entity-detail-drawer" data-testid="run-details-drawer">
    <button class="drawer-close" type="button" @click="$emit('close-run')"><X :size="16" /> 关闭</button>
    <div class="section-kicker">Lifecycle Run Details</div><h2>{{ lifecycleAudit?.run?.run_id || selectedRunId || '当前运行' }}</h2><p>只读检查点详情：不重新执行模型、不修改确定性结果。</p>
    <dl v-if="lifecycleAudit?.run" class="drawer-metric-grid"><div><dt>状态</dt><dd>{{ lifecycleAudit.run.status }}</dd></div><div><dt>当前阶段</dt><dd>{{ lifecycleAudit.run.current_phase }}</dd></div><div><dt>Attempt</dt><dd>{{ lifecycleAudit.run.current_attempt_id || '--' }}</dd></div><div><dt>恢复点</dt><dd>{{ lifecycleAudit.run.terminal_reason || lifecycleAudit.run.next_attempt_at || '--' }}</dd></div></dl>
    <section v-if="lifecycleAudit?.steps?.length" class="drawer-mini-section"><h3>阶段 Hash 与耗时</h3><div v-for="step in lifecycleAudit.steps" :key="step.step_id" class="drawer-step-row"><strong>{{ step.step_key }} · {{ step.status }}</strong><span>{{ step.duration_ms }} ms · {{ String(step.input_hash || '').slice(0, 12) }} → {{ String(step.output_hash || '').slice(0, 12) }}</span><small v-if="step.error_code">{{ step.error_code }}</small></div></section>
  </aside>
  <aside v-if="notificationOpen" class="feature-drawer notification-drawer" data-testid="war-room-notification-drawer">
    <button class="drawer-close" type="button" @click="$emit('close-notifications')"><X :size="16" /> 关闭</button>
    <div class="section-kicker">CONTINUOUS INTELLIGENCE</div><h2>通知中心</h2>
    <div class="drawer-action-row"><button type="button" @click="continuousIntelligence.readAllNotifications()">全部标记已读</button><button type="button" @click="$emit('open-intelligence')">进入持续情报</button></div>
    <div class="notification-list"><button v-for="item in [...continuousIntelligence.notifications.value].reverse()" :key="item.notification_id" type="button" :class="{ unread: !item.read_at }" @click="continuousIntelligence.readNotification(item.notification_id)"><span>{{ item.severity }} · {{ item.event_type }}</span><strong>{{ item.title }}</strong><small>{{ item.body }}</small></button><p v-if="!continuousIntelligence.notifications.value.length" class="sandbox-note">暂无持续情报告警通知。</p></div>
  </aside>
  <aside v-if="upcomingFeature" class="feature-drawer"><button class="drawer-close" type="button" @click="$emit('close-upcoming')"><X :size="16" /> 关闭</button><div class="section-kicker"><Info :size="16" /> 即将推出</div><h2>{{ upcomingFeature.title }}</h2><p>{{ upcomingFeature.body }}</p><p class="sandbox-note">当前按钮已明确标记为说明入口，不再作为无反馈控件处理。</p></aside>
  <aside v-if="decisionDrawer" class="feature-drawer decision-drawer"><button class="drawer-close" type="button" @click="$emit('close-decision')"><X :size="16" /> 关闭</button><div class="section-kicker"><ListChecks :size="16" /> Agent 决策详情</div><h2>{{ decisionDrawer.title }}</h2><p>{{ decisionDrawer.rationale }}</p><dl><div><dt>国家 Agent</dt><dd>{{ decisionDrawer.country }}</dd></div><div><dt>置信度</dt><dd>{{ decisionDrawer.confidence }}</dd></div><div><dt>驱动因素</dt><dd>{{ decisionDrawer.drivers }}</dd></div><div><dt>预期代价</dt><dd>{{ decisionDrawer.tradeoff }}</dd></div></dl></aside>
</template>

<script setup>
import { FileSearch, Info, ListChecks, Search, X } from 'lucide-vue-next'
defineProps({ toastMessage: String, commandSearchOpen: Boolean, commandQuery: String, commandSearchResults: Array, entityTypeLabel: Function, entityDetail: Object, runDetailsOpen: Boolean, lifecycleAudit: Object, selectedRunId: String, notificationOpen: Boolean, continuousIntelligence: Object, upcomingFeature: Object, decisionDrawer: Object })
defineEmits(['close-command', 'update-query', 'activate-command', 'close-entity', 'entity-action', 'close-run', 'close-notifications', 'open-intelligence', 'close-upcoming', 'close-decision'])
</script>
