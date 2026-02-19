<template>
  <div>
    <h2 style="margin: 0 0 12px 0; font-size: 20px; font-weight: 600">长期记忆管理</h2>
    <el-row :gutter="12" style="margin-top: 12px">
      <el-col :span="8">
        <el-card>
          <template #header>会话列表</template>
          <el-menu :default-active="selectedSession" @select="onSelectSession">
            <el-menu-item v-for="session in sessions" :key="session.session_key" :index="session.session_key">
              {{ session.session_key }} ({{ session.count }})
            </el-menu-item>
          </el-menu>
        </el-card>
      </el-col>
      <el-col :span="16">
        <el-card>
          <template #header>
            记忆条目
            <el-button
              style="float: right"
              size="small"
              @click="cleanup"
            >清理过期</el-button>
          </template>
          <MemoryFactList :facts="facts" @delete="removeFact" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, ref } from 'vue'
import { cleanupMemory, deleteMemory, listMemoryFacts, listMemorySessions } from '../api/client'
import MemoryFactList from '../components/MemoryFactList.vue'

const sessions = ref<Array<any>>([])
const selectedSession = ref('')
const facts = ref<Array<any>>([])

const refreshSessions = async () => {
  sessions.value = await listMemorySessions()
  if (!selectedSession.value && sessions.value.length) {
    selectedSession.value = sessions.value[0].session_key
  }
}

const refreshFacts = async () => {
  if (!selectedSession.value) {
    facts.value = []
    return
  }
  facts.value = await listMemoryFacts(selectedSession.value)
}

const onSelectSession = async (value: string) => {
  selectedSession.value = value
  await refreshFacts()
}

const removeFact = async (id: number) => {
  await deleteMemory(id)
  ElMessage.success('已删除')
  await refreshFacts()
  await refreshSessions()
}

const cleanup = async () => {
  const confirmed = await ElMessageBox.confirm('清理 90 天前低召回记忆？', '确认')
    .then(() => true)
    .catch(() => false)
  if (!confirmed) return
  const result = await cleanupMemory(90)
  ElMessage.success(`清理完成：${result.deleted || 0}`)
  await refreshSessions()
  await refreshFacts()
}

onMounted(async () => {
  await refreshSessions()
  await refreshFacts()
})
</script>
