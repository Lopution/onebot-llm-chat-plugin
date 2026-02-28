<template>
  <div class="app-bg">
    <el-container style="height: 100vh; background: transparent;">
      <el-aside width="220px" class="acrylic-panel" style="margin: 16px 0 16px 16px; height: calc(100vh - 32px); display: flex; flex-direction: column;">
        <div style="padding: 24px; font-weight: 700; font-size: 18px;">Mika WebUI</div>
      <el-menu :default-active="activePath" router>
        <el-menu-item index="/dashboard">仪表盘</el-menu-item>
        <el-menu-item index="/logs">实时日志</el-menu-item>
        <el-menu-item index="/config">配置</el-menu-item>
        <el-menu-item index="/persona">人设</el-menu-item>
        <el-menu-item index="/sessions">会话管理</el-menu-item>
        <el-menu-item index="/profiles">用户档案</el-menu-item>
        <el-menu-item index="/knowledge">知识库</el-menu-item>
        <el-menu-item index="/memory">长期记忆</el-menu-item>
        <el-menu-item index="/tools">工具管理</el-menu-item>
        <el-menu-item index="/live-chat">测试对话</el-menu-item>
        <el-menu-item index="/backup">备份恢复</el-menu-item>
      </el-menu>
      </el-aside>
      <el-container style="background: transparent;">
        <el-header class="acrylic-panel" style="margin: 16px 16px 0 16px; display: flex; align-items: center;">
        <el-input
          v-model="token"
          placeholder="WebUI Token（可选）"
          clearable
          style="max-width: 360px"
          @change="saveToken"
        />
        </el-header>
        <el-main style="padding: 16px; overflow-y: auto;">
          <router-view />
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const activePath = computed(() => route.path)
const token = ref(localStorage.getItem('mika_webui_token') || '')

const saveToken = () => {
  const value = token.value.trim()
  if (value) {
    localStorage.setItem('mika_webui_token', value)
  } else {
    localStorage.removeItem('mika_webui_token')
  }
}
</script>
