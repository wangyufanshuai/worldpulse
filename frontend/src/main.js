import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import ProjectHomeView from './views/ProjectHomeView.vue'
import ResearchWorkspaceView from './views/ResearchWorkspaceView.vue'
import './styles.css'

const router = createRouter({
  history: createWebHistory('/studio/'),
  routes: [
    { path: '/', name: 'home', component: ProjectHomeView },
    { path: '/projects/:projectId', name: 'workspace', component: ResearchWorkspaceView, props: true }
  ]
})

createApp(App).use(router).mount('#app')
