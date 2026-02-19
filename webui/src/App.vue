<template>
  <el-container style="height: 100vh">
    <el-aside width="220px" style="border-right: 1px solid #eee">
      <div style="padding: 16px; font-weight: 700">Mika WebUI</div>
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
    <el-container>
      <el-header style="border-bottom: 1px solid #eee; display: flex; align-items: center">
        <el-input
          v-model="token"
          placeholder="WebUI Token（可选）"
          clearable
          style="max-width: 360px"
          @change="saveToken"
        />
      </el-header>
      <el-main style="padding: 16px">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
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
