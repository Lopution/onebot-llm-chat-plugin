<template>
  <div>
    <h2 style="margin: 0 0 12px 0; font-size: 20px; font-weight: 600">实时日志</h2>
    <el-space style="margin-bottom: 12px">
      <el-tag :type="connected ? 'success' : 'warning'">
        {{ connected ? 'SSE 已连接' : 'SSE 未连接' }}
      </el-tag>
      <el-select
        v-model="minLevel"
        size="small"
        style="width: 140px"
        @change="handleLevelChange"
      >
        <el-option
          v-for="option in logLevelOptions"
          :key="option"
          :label="`最小级别: ${option}`"
          :value="option"
        />
      </el-select>
      <el-button size="small" @click="reconnect">重连</el-button>
      <el-button size="small" @click="clearLogs">清空视图</el-button>
    </el-space>

    <el-table :data="logs" size="small" height="560">
      <el-table-column label="ID" prop="id" width="80" />
      <el-table-column label="时间" width="180">
        <template #default="{ row }">
          {{ formatTimestamp(row.timestamp) }}
        </template>
      </el-table-column>
      <el-table-column label="级别" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="levelType(row.level)">{{ row.level }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="消息" min-width="400">
        <template #default="{ row }">
          <span style="white-space: pre-wrap">{{ row.message }}</span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { buildLogSseUrlWithTicket, getLogHistory } from '../api/modules/log'

type LogItem = {
  id: number
  timestamp: number
  level: string
  message: string
}

type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'

const logLevelOptions: LogLevel[] = ['DEBUG', 'INFO', 'WARNING', 'ERROR']

const logs = ref<LogItem[]>([])
const connected = ref(false)
const minLevel = ref<LogLevel>('INFO')
let eventSource: EventSource | null = null
let flushTimer: number | null = null
const pendingLogs: LogItem[] = []
const seenLogIds = new Set<number>()
const MAX_VISIBLE_LOGS = 500

const levelType = (level: string) => {
  const normalized = String(level || '').toUpperCase()
  if (normalized === 'ERROR' || normalized === 'EXCEPTION' || normalized === 'CRITICAL') return 'danger'
  if (normalized === 'WARNING') return 'warning'
  if (normalized === 'SUCCESS') return 'success'
  return 'info'
}

const formatTimestamp = (value: number) => {
  if (!value) return '-'
  const date = new Date(value * 1000)
  return date.toLocaleString()
}

const flushPendingLogs = () => {
  flushTimer = null
  if (!pendingLogs.length) {
    return
  }
  logs.value.push(...pendingLogs.splice(0))
  if (logs.value.length > MAX_VISIBLE_LOGS) {
    logs.value.splice(0, logs.value.length - MAX_VISIBLE_LOGS)
  }
}

const scheduleFlush = () => {
  if (flushTimer !== null) {
    return
  }
  flushTimer = window.setTimeout(flushPendingLogs, 120)
}

const pushLog = (item: LogItem) => {
  if (item.id > 0 && seenLogIds.has(item.id)) {
    return
  }
  if (item.id > 0) {
    seenLogIds.add(item.id)
    if (seenLogIds.size > MAX_VISIBLE_LOGS * 2) {
      const entries = Array.from(seenLogIds)
      const toRemove = entries.slice(0, entries.length - MAX_VISIBLE_LOGS)
      for (const id of toRemove) {
        seenLogIds.delete(id)
      }
    }
  }
  pendingLogs.push(item)
  scheduleFlush()
}

const loadHistory = async () => {
  const payload = await getLogHistory(100, 0, minLevel.value)
  const events = Array.isArray(payload.events) ? payload.events : []
  const mapped = events
    .map((entry) => ({
      id: Number(entry.id || 0),
      timestamp: Number(entry.timestamp || 0),
      level: String(entry.level || 'INFO').toUpperCase(),
      message: String(entry.message || ''),
    }))
    .filter((entry) => entry.id > 0)
  logs.value = mapped.slice(-MAX_VISIBLE_LOGS)
  seenLogIds.clear()
  for (const item of logs.value) {
    seenLogIds.add(item.id)
  }
}

const disconnect = () => {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
  connected.value = false
}

const connect = async () => {
  disconnect()
  const url = await buildLogSseUrlWithTicket(minLevel.value)
  const source = new EventSource(url)
  eventSource = source
  source.onopen = () => {
    connected.value = true
  }
  source.onerror = () => {
    connected.value = false
  }
  source.addEventListener('log', (event) => {
    try {
      const data = JSON.parse((event as MessageEvent).data)
      pushLog({
        id: Number(data.id || 0),
        timestamp: Number(data.timestamp || 0),
        level: String(data.level || 'INFO').toUpperCase(),
        message: String(data.message || ''),
      })
    } catch {
      // ignore malformed events
    }
  })
}

const reconnect = () => {
  connect()
  ElMessage.success('日志流已重连')
}

const clearLogs = () => {
  logs.value = []
  seenLogIds.clear()
  pendingLogs.length = 0
  if (flushTimer !== null) {
    window.clearTimeout(flushTimer)
    flushTimer = null
  }
}

const handleLevelChange = async () => {
  clearLogs()
  connect()
  try {
    await loadHistory()
  } catch (error) {
    ElMessage.warning(`加载日志历史失败: ${String(error)}`)
  }
}

onMounted(() => {
  connect()
  void loadHistory().catch((error) => {
    ElMessage.warning(`加载日志历史失败: ${String(error)}`)
  })
})

onBeforeUnmount(() => {
  pendingLogs.length = 0
  seenLogIds.clear()
  if (flushTimer !== null) {
    window.clearTimeout(flushTimer)
    flushTimer = null
  }
  disconnect()
})
</script>
