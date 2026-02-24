<template>
  <div>
    <h2 class="page-title">工具管理</h2>
    <el-card>
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px">
        <span style="color: #606266">共 {{ store.total }} 个工具，启用 {{ store.enabledTotal }} 个</span>
        <el-button :loading="store.loading" @click="store.load()">刷新</el-button>
      </div>
      <el-table :data="store.items" size="small" v-loading="store.loading">
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
import { onMounted } from 'vue'
import { useToolsStore } from '../stores/tools'

const store = useToolsStore()

const onToggle = async (toolName: string, enabled: boolean) => {
  try {
    await store.toggle(toolName, enabled)
    const item = store.items.find((t) => t.name === toolName)
    ElMessage.success(`${toolName} 已${item?.enabled ? '启用' : '禁用'}`)
  } catch (error) {
    ElMessage.error(`切换失败: ${String(error)}`)
  }
}

onMounted(() => store.load())
</script>
