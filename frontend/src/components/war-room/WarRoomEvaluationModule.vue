<template>
  <section class="evaluation-center" data-testid="evaluation-center">
    <div class="evaluation-toolbar"><div><span class="section-kicker">CROSS-MODE ENGINEERING V1</span><h3>跨模式基准评估</h3><p class="sandbox-note">Mock 标准批次是唯一安全门禁；Live 观察批次只用于成本与质量观测。</p></div><button class="primary" type="button" data-testid="evaluation-create-standard" :disabled="loading" @click="$emit('create-standard')">创建 Mock 标准批次</button></div>
    <div class="evaluation-grid"><article><span>标准套件</span><strong>{{ suite?.version || '--' }}</strong><small>{{ suite?.case_count || 0 }} 个工程案例</small></article><article><span>当前批次</span><strong>{{ latest?.status || '未运行' }}</strong><small>{{ latest?.completed_members || 0 }}/{{ latest?.total_members || 0 }} Members</small></article><article><span>安全门禁</span><strong :class="latest?.safety_status === 'passed' ? 'passed' : 'blocked'">{{ latest?.safety_status || 'pending' }}</strong><small>数值权威字段接受数：{{ latest?.metrics?.numeric_authority_accepted ?? 0 }}</small></article><article><span>正式报告资格</span><strong>{{ report?.mode_eligibility?.hybrid ? 'Hybrid 可用' : '等待评估' }}</strong><small>Negotiation {{ report?.mode_eligibility?.negotiation ? '可用' : '不可用' }}</small></article></div>
    <div class="evaluation-members"><button v-for="member in members.slice(0, 24)" :key="member.member_id" type="button" :class="['evaluation-member', member.status]" @click="$emit('inspect', latest.batch_id)"><span>{{ member.engine_mode }}</span><b>{{ member.case_id.replace('eval_', '') }}</b><small>seed {{ member.seed }} · {{ member.status }}</small></button></div>
    <p v-if="error" class="error-text">{{ error }}</p><p v-else class="sandbox-note">所有子运行复用 v2 lifecycle、确定性引擎、一致性审计和 Replay；不会把评估结果写入用户项目历史。</p>
  </section>
</template>
<script setup>
defineProps({ suite: Object, latest: Object, report: Object, members: { type: Array, default: () => [] }, loading: Boolean, error: String })
defineEmits(['create-standard', 'inspect'])
</script>
