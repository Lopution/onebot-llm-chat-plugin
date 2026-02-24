<template>
  <div>
    <h2 class="page-title">会话管理</h2>

    <el-card>
      <div style="display: flex; gap: 8px; align-items: center">
        <el-input
          v-model="localQuery"
          placeholder="按会话键搜索（如 group:1034119139）"
          clearable
          @keyup.enter="onSearch"
          @clear="onSearch"
        />
        <el-button type="primary" @click="onSearch">搜索</el-button>
        <el-button @click="store.load()">刷新</el-button>
      </div>
    </el-card>

    <el-row :gutter="12" style="margin-top: 12px">
      <el-col :span="10">
        <el-card>
          <template #header>
            会话列表
            <span style="float: right; color: #909399">共 {{ store.total }} 条</span>
          </template>
          <el-table
            :data="store.items"
            size="small"
            v-loading="store.loading"
            highlight-current-row
            row-key="session_key"
            @row-click="onSelectSession"
          >
            <el-table-column prop="session_key" label="会话键" min-width="220" />
            <el-table-column prop="message_count" label="消息数" width="90" />
            <el-table-column label="最后消息" width="160">
              <template #default="{ row }">{{ formatTimestamp(row.last_message_at) }}</template>
            </el-table-column>
          </el-table>
          <div style="margin-top: 10px; display: flex; justify-content: flex-end">
            <el-pagination
              layout="prev, pager, next"
              :current-page="store.page"
              :page-size="store.pageSize"
              :total="store.total"
              @current-change="store.changePage"
            />
          </div>
        </el-card>
      </el-col>

      <el-col :span="14">
        <el-card>
          <template #header>
            会话详情
            <el-button
              type="danger"
              size="small"
              style="float: right"
              :disabled="!store.selectedKey"
              @click="clearCurrentSession"
            >
              清空会话上下文
            </el-button>
          </template>

          <div v-if="!store.detail" style="color: #909399">请选择左侧会话查看详情。</div>
          <template v-else>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="会话键">{{ store.detail.session_key }}</el-descriptions-item>
              <el-descriptions-item label="快照消息数">{{ store.detail.snapshot_message_count }}</el-descriptions-item>
              <el-descriptions-item label="归档消息数">{{ store.detail.message_count }}</el-descriptions-item>
              <el-descriptions-item label="用户消息数">{{ store.detail.user_message_count }}</el-descriptions-item>
              <el-descriptions-item label="助手消息数">{{ store.detail.assistant_message_count }}</el-descriptions-item>
              <el-descriptions-item label="工具消息数">{{ store.detail.tool_message_count }}</el-descriptions-item>
              <el-descriptions-item label="长期记忆数">{{ store.detail.memory_count }}</el-descriptions-item>
              <el-descriptions-item label="话题摘要数">{{ store.detail.topic_count }}</el-descriptions-item>
              <el-descriptions-item label="最后消息时间">{{ formatTimestamp(store.detail.last_message_at) }}</el-descriptions-item>
              <el-descriptions-item label="更新于">{{ formatDateTime(store.detail.updated_at) }}</el-descriptions-item>
            </el-descriptions>

            <el-divider content-position="left">最近消息预览</el-divider>
            <el-table :data="store.detail.preview || []" size="small">
              <el-table-column prop="role" label="角色" width="100" />
              <el-table-column prop="content" label="内容" min-width="280" />
              <el-table-column label="时间" width="160">
                <template #default="{ row }">{{ formatTimestamp(row.timestamp) }}</template>
              </el-table-column>
            </el-table>
          </template>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, ref } from 'vue'
import { useSessionStore } from '../stores/session'
import type { SessionListItem } from '../api/types'

const store = useSessionStore()
const localQuery = ref(store.query)

const formatTimestamp = (value: unknown): string => {
  const num = Number(value)
  if (!Number.isFinite(num) || num <= 0) return '-'
  return new Date(num * 1000).toLocaleString()
}

const formatDateTime = (value: unknown): string => {
  const text = String(value || '').trim()
  return text || '-'
}

const onSearch = () => {
  store.search(localQuery.value)
}

const onSelectSession = (row: SessionListItem) => {
  store.select(row.session_key)
}

const clearCurrentSession = async () => {
  if (!store.selectedKey) return
  const confirmed = await ElMessageBox.confirm(
    `确认清空会话 ${store.selectedKey} 的上下文与归档消息吗？`,
    '确认清空',
  )
    .then(() => true)
    .catch(() => false)
  if (!confirmed) return
  await store.clearCurrent()
  ElMessage.success('会话上下文已清空')
}

onMounted(() => {
  store.load()
})
</script>
