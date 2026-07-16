<template>
  <div v-if="auth.state.ready && auth.user.value" class="app-shell">
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
        <label class="organization-switcher" data-testid="organization-switcher">
          <Building2 :size="14" />
          <select :value="organization.currentId.value" :disabled="organization.state.loading" data-testid="organization-select" @change="switchOrganization">
            <option v-for="item in organization.state.organizations" :key="item.organization_id" :value="item.organization_id">{{ item.name }} · {{ item.member_role }}</option>
          </select>
        </label>
        <span class="session-role" data-testid="session-role">{{ roleLabel }}</span>
        <button type="button" class="session-logout" data-testid="session-logout" @click="signOut">退出</button>
      </nav>
    </header>
    <RouterView :key="organization.state.epoch" />
  </div>
  <main v-else-if="auth.state.ready" class="login-shell" data-testid="login-screen">
    <form class="login-card" @submit.prevent="submitLogin">
      <span class="brand-mark"><Globe2 :size="24" /></span>
      <div class="section-kicker">WorldPulse V1.7 · 生产运维控制平面</div>
      <h1>登录可信决策指挥台</h1>
      <p>本地账户、服务端 Session、CSRF 与角色权限均由后端强制执行。</p>
      <label>用户名<input v-model="credentials.username" autocomplete="username" data-testid="login-username" /></label>
      <label>密码<input v-model="credentials.password" type="password" autocomplete="current-password" data-testid="login-password" /></label>
      <button class="primary" type="submit" :disabled="auth.state.loading" data-testid="login-submit">{{ auth.state.loading ? '验证中…' : '登录' }}</button>
      <p v-if="auth.state.error" class="error-text" data-testid="login-error">{{ auth.state.error }}</p>
    </form>
  </main>
  <main v-else class="login-shell"><div class="login-card">正在检查本地 Session…</div></main>
</template>

<script setup>
import { computed, onMounted, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { Activity, Building2, Github, Globe2, LayoutDashboard } from 'lucide-vue-next'
import { useAuthSession } from './composables/useAuthSession'
import { useOrganizationContext } from './composables/useOrganizationContext'

const router = useRouter()
const auth = useAuthSession()
const organization = useOrganizationContext()
const credentials = reactive({ username: '', password: '' })
const roleLabel = computed(() => ({ admin: '管理员', analyst: '分析员', reviewer: '审阅者', viewer: '只读' }[auth.role.value] || auth.role.value))

async function submitLogin() {
  try {
    await auth.signIn(credentials.username, credentials.password)
    await organization.load()
  } catch { /* rendered by state */ }
}

async function switchOrganization(event) {
  await organization.select(event.target.value)
  await router.push('/')
}

async function signOut() {
  await auth.signOut()
  organization.clear()
  await router.push('/')
}

onMounted(async () => {
  await auth.initialize()
  if (auth.user.value) await organization.load()
})
</script>
