<template>
  <div>
    <h2 style="margin: 0 0 12px 0; font-size: 20px; font-weight: 600">工具管理</h2>
    <el-card>
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px">
        <span style="color: #606266">共 {{ total }} 个工具，启用 {{ enabledTotal }} 个</span>
        <el-button :loading="loading" @click="refresh">刷新</el-button>
      </div>
      <el-table :data="tools" size="small" v-loading="loading">
        <el-table-column prop="name" label="工具名" min-width="180" />
        <el-table-column label="来源" width="120">
          <template #default="{ row }">
            <el-tag size="small">{{ row.source }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="260" />
        <el-table-column label="启用" width="120">
          <template #default="{ row }">
            <el-switch
              :model-value="Boolean(row.enabled)"
              @change="(value: string | number | boolean) => onToggle(row.name, Boolean(value))"
            />
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, ref } from 'vue'
import { listTools, toggleTool, type ToolItem } from '../api/client'

const loading = ref(false)
const tools = ref<ToolItem[]>([])
const total = ref(0)
const enabledTotal = ref(0)

const refresh = async () => {
  loading.value = true
  try {
    const data = await listTools(true)
    tools.value = data.tools || []
    total.value = Number(data.total || tools.value.length)
    enabledTotal.value = Number(data.enabled_total || tools.value.filter((item) => item.enabled).length)
  } finally {
    loading.value = false
  }
}

const onToggle = async (toolName: string, enabled: boolean) => {
  const index = tools.value.findIndex((item) => item.name === toolName)
  const previous = index >= 0 ? Boolean(tools.value[index].enabled) : !enabled
  if (index >= 0) {
    tools.value[index].enabled = enabled
  }
  try {
    const result = await toggleTool(toolName, enabled)
    ElMessage.success(`${result.name} 已${result.enabled ? '启用' : '禁用'}`)
    await refresh()
  } catch (error) {
    if (index >= 0) {
      tools.value[index].enabled = previous
    }
    ElMessage.error(`切换失败: ${String(error)}`)
  }
}

onMounted(async () => {
  await refresh()
})
</script>
