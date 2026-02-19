<template>
  <div>
    <h2 style="margin: 0 0 12px 0; font-size: 20px; font-weight: 600">会话管理</h2>

    <el-card>
      <div style="display: flex; gap: 8px; align-items: center">
        <el-input
          v-model="query"
          placeholder="按会话键搜索（如 group:1034119139）"
          clearable
          @keyup.enter="onSearch"
          @clear="onSearch"
        />
        <el-button type="primary" @click="onSearch">搜索</el-button>
        <el-button @click="refreshSessions">刷新</el-button>
      </div>
    </el-card>

    <el-row :gutter="12" style="margin-top: 12px">
      <el-col :span="10">
        <el-card>
          <template #header>
            会话列表
            <span style="float: right; color: #909399">共 {{ total }} 条</span>
          </template>
          <el-table
            :data="sessions"
            size="small"
            v-loading="loading"
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
              :current-page="page"
              :page-size="pageSize"
              :total="total"
              @current-change="onPageChange"
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
              :disabled="!selectedSession"
              @click="clearCurrentSession"
            >
              清空会话上下文
            </el-button>
          </template>

          <div v-if="!detail" style="color: #909399">请选择左侧会话查看详情。</div>
          <template v-else>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="会话键">{{ detail.session_key }}</el-descriptions-item>
              <el-descriptions-item label="快照消息数">{{ detail.snapshot_message_count }}</el-descriptions-item>
              <el-descriptions-item label="归档消息数">{{ detail.message_count }}</el-descriptions-item>
              <el-descriptions-item label="用户消息数">{{ detail.user_message_count }}</el-descriptions-item>
              <el-descriptions-item label="助手消息数">{{ detail.assistant_message_count }}</el-descriptions-item>
              <el-descriptions-item label="工具消息数">{{ detail.tool_message_count }}</el-descriptions-item>
              <el-descriptions-item label="长期记忆数">{{ detail.memory_count }}</el-descriptions-item>
              <el-descriptions-item label="话题摘要数">{{ detail.topic_count }}</el-descriptions-item>
              <el-descriptions-item label="最后消息时间">{{ formatTimestamp(detail.last_message_at) }}</el-descriptions-item>
              <el-descriptions-item label="更新于">{{ formatDateTime(detail.updated_at) }}</el-descriptions-item>
            </el-descriptions>

            <el-divider content-position="left">最近消息预览</el-divider>
            <el-table :data="detail.preview || []" size="small">
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
import type { SessionDetail, SessionListItem } from '../api/client'
import { clearSession, getSessionDetail, listSessions } from '../api/client'

const loading = ref(false)
const sessions = ref<SessionListItem[]>([])
const detail = ref<SessionDetail | null>(null)
const selectedSession = ref('')
const query = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const formatTimestamp = (value: unknown): string => {
  const num = Number(value)
  if (!Number.isFinite(num) || num <= 0) {
    return '-'
  }
  return new Date(num * 1000).toLocaleString()
}

const formatDateTime = (value: unknown): string => {
  const text = String(value || '').trim()
  if (!text) {
    return '-'
  }
  return text
}

const refreshSessions = async () => {
  loading.value = true
  try {
    const data = await listSessions(page.value, pageSize.value, query.value)
    sessions.value = data.items || []
    total.value = Number(data.total || 0)
    if (selectedSession.value) {
      const exists = sessions.value.some((item) => item.session_key === selectedSession.value)
      if (!exists) {
        selectedSession.value = ''
        detail.value = null
      }
    }
    if (!selectedSession.value && sessions.value.length > 0) {
      selectedSession.value = sessions.value[0].session_key
      await loadSessionDetail()
    }
  } finally {
    loading.value = false
  }
}

const loadSessionDetail = async () => {
  if (!selectedSession.value) {
    detail.value = null
    return
  }
  detail.value = await getSessionDetail(selectedSession.value, 10)
}

const onSearch = async () => {
  page.value = 1
  await refreshSessions()
}

const onPageChange = async (newPage: number) => {
  page.value = newPage
  await refreshSessions()
}

const onSelectSession = async (row: SessionListItem) => {
  selectedSession.value = row.session_key
  await loadSessionDetail()
}

const clearCurrentSession = async () => {
  if (!selectedSession.value) {
    return
  }
  const confirmed = await ElMessageBox.confirm(
    `确认清空会话 ${selectedSession.value} 的上下文与归档消息吗？`,
    '确认清空',
  )
    .then(() => true)
    .catch(() => false)
  if (!confirmed) {
    return
  }
  await clearSession(selectedSession.value, true, true)
  ElMessage.success('会话上下文已清空')
  selectedSession.value = ''
  detail.value = null
  await refreshSessions()
}

onMounted(async () => {
  await refreshSessions()
})
</script>
