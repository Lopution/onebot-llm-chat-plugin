<template>
  <el-table :data="facts" size="small" style="width: 100%">
    <el-table-column prop="id" label="ID" width="70" />
    <el-table-column prop="user_id" label="用户" width="120" />
    <el-table-column prop="fact" label="事实" min-width="260" />
    <el-table-column prop="recall_count" label="召回" width="80" />
    <el-table-column label="操作" width="90">
      <template #default="{ row }">
        <el-button link type="danger" @click="$emit('delete', row.id)">删除</el-button>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup lang="ts">
defineProps<{ facts: Array<Record<string, any>> }>()
defineEmits<{
  (event: 'delete', id: number): void
}>()
</script>
