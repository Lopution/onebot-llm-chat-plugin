<template>
  <div>
    <h2 style="margin: 0 0 16px 0; font-size: 20px; font-weight: 600">仪表盘</h2>
    <el-space wrap style="margin-bottom: 16px">
      <el-tag :type="healthTagType">
        状态: {{ dashboard.health.health_status || dashboard.health.status || '-' }}
      </el-tag>
      <el-tag>DB: {{ dashboard.health.database || '-' }}</el-tag>
      <el-tag>Client: {{ dashboard.health.mika_client || '-' }}</el-tag>
    </el-space>
    <el-row :gutter="12">
      <el-col :span="6">
        <el-card shadow="never">
          <div class="stat-label">请求总数</div>
          <div class="stat-value">{{ dashboard.metrics.requests_total || 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div class="stat-label">工具调用</div>
          <div class="stat-value">{{ dashboard.metrics.tool_calls_total || 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div class="stat-label">记忆条数</div>
          <div class="stat-value">{{ dashboard.stats.memory_count || 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div class="stat-label">知识块数</div>
          <div class="stat-value">{{ dashboard.stats.knowledge_count || 0 }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" style="margin-top: 12px">
      <template #header>24h 时序指标（每小时）</template>
      <el-table :data="recentTimeline" size="small">
        <el-table-column label="时间" min-width="160">
          <template #default="{ row }">{{ formatBucket(row.timestamp) }}</template>
        </el-table-column>
        <el-table-column prop="messages" label="消息数" width="100" />
        <el-table-column prop="llm_count" label="LLM请求" width="100" />
        <el-table-column prop="llm_p50_ms" label="P50(ms)" width="100" />
        <el-table-column prop="llm_p95_ms" label="P95(ms)" width="100" />
        <el-table-column prop="total_tokens" label="Tokens" width="120" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'

const dashboard = useDashboardStore()

const healthTagType = computed(() => {
  const status = String(dashboard.health.health_status || dashboard.health.status || '').toLowerCase()
  if (status === 'healthy' || status === 'ok') return 'success'
  if (status === 'degraded') return 'warning'
  return 'danger'
})

const recentTimeline = computed(() => {
  const points = dashboard.timeline || []
  return points.slice(-12).reverse()
})

const formatBucket = (value: unknown) => {
  const num = Number(value)
  if (!Number.isFinite(num) || num <= 0) {
    return '-'
  }
  return new Date(num * 1000).toLocaleString()
}

onMounted(async () => {
  await dashboard.refresh()
})
</script>
