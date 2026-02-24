<template>
  <div>
    <h2 class="page-title">长期记忆管理</h2>
    <el-row :gutter="12" style="margin-top: 12px">
      <el-col :span="8">
        <el-card>
          <template #header>会话列表</template>
          <el-menu :default-active="store.selectedSession" @select="store.selectSession">
            <el-menu-item v-for="session in store.sessions" :key="session.session_key" :index="session.session_key">
              {{ session.session_key }} ({{ session.count }})
            </el-menu-item>
          </el-menu>
        </el-card>
      </el-col>
      <el-col :span="16">
        <el-card>
          <template #header>
            记忆条目
            <el-button style="float: right" size="small" @click="cleanup">清理过期</el-button>
          </template>
          <MemoryFactList :facts="store.facts" @delete="removeFact" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted } from 'vue'
import { useMemoryStore } from '../stores/memory'
import MemoryFactList from '../components/MemoryFactList.vue'

const store = useMemoryStore()

const removeFact = async (id: number) => {
  await store.removeFact(id)
  ElMessage.success('已删除')
}

const cleanup = async () => {
  const confirmed = await ElMessageBox.confirm('清理 90 天前低召回记忆？', '确认')
    .then(() => true).catch(() => false)
  if (!confirmed) return
  const result = await store.cleanup(90)
  ElMessage.success(`清理完成：${(result as any).deleted || 0}`)
}

onMounted(async () => {
  try {
    await store.loadSessions()
    await store.loadFacts()
  } catch (error) {
    ElMessage.error(`加载记忆数据失败: ${String(error)}`)
  }
})
</script>
