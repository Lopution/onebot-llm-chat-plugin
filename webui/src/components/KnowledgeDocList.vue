<template>
  <el-table :data="documents" size="small" style="width: 100%">
    <el-table-column prop="doc_id" label="文档 ID" min-width="180" />
    <el-table-column prop="title" label="标题" min-width="160" />
    <el-table-column prop="chunk_count" label="切片数" width="90" />
    <el-table-column label="操作" width="180">
      <template #default="{ row }">
        <el-button link type="primary" @click="$emit('view', row.doc_id)">查看切片</el-button>
        <el-button link type="danger" @click="$emit('delete', row.doc_id)">删除</el-button>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup lang="ts">
defineProps<{ documents: Array<Record<string, any>> }>()
defineEmits<{
  (event: 'view', docId: string): void
  (event: 'delete', docId: string): void
}>()
</script>
