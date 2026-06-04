<template>
  <div class="app-shell">
    <header class="studio-header">
      <RouterLink to="/" class="brand">
        <span class="brand-mark"></span>
        <span>
          <strong>WorldPulse Studio</strong>
          <small>项目制全球局势研究系统</small>
        </span>
      </RouterLink>
      <nav>
        <a href="/" target="_blank">旧看板</a>
        <a href="/api/health" target="_blank">API</a>
        <a href="https://github.com/wangyufanshuai/worldpulse" target="_blank">GitHub</a>
      </nav>
    </header>
    <RouterView />
  </div>
</template>
