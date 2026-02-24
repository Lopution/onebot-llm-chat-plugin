import { createRouter, createWebHistory } from 'vue-router'
import { getWebUiBasePath } from '../api/http'

const webUiBasePath = getWebUiBasePath()
const historyBase = webUiBasePath === '/' ? '/' : `${webUiBasePath}/`

const router = createRouter({
  history: createWebHistory(historyBase),
  routes: [
    { path: '/', redirect: '/dashboard' },
    { path: '/dashboard', component: () => import('../views/DashboardView.vue') },
    { path: '/logs', component: () => import('../views/LogView.vue') },
    { path: '/config', component: () => import('../views/ConfigView.vue') },
    { path: '/persona', component: () => import('../views/PersonaView.vue') },
    { path: '/sessions', component: () => import('../views/SessionView.vue') },
    { path: '/knowledge', component: () => import('../views/KnowledgeView.vue') },
    { path: '/memory', component: () => import('../views/MemoryView.vue') },
    { path: '/tools', component: () => import('../views/ToolsView.vue') },
    { path: '/profiles', component: () => import('../views/UserProfileView.vue') },
    { path: '/backup', component: () => import('../views/BackupView.vue') },
    { path: '/live-chat', component: () => import('../views/LiveChatView.vue') },
  ],
})

export default router
