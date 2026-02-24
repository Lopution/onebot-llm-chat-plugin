<template>
  <div>
    <h2 class="page-title">知识库管理</h2>
    <el-row :gutter="12" style="margin-top: 12px">
      <el-col :span="8">
        <el-card>
          <template #header>语料库</template>
          <el-select v-model="store.selectedCorpus" style="width: 100%" @change="store.loadDocuments()">
            <el-option
              v-for="item in store.corpora"
              :key="item.corpus_id"
              :label="`${item.corpus_id} (${item.doc_count}/${item.chunk_count})`"
              :value="item.corpus_id"
            />
          </el-select>
        </el-card>
      </el-col>
      <el-col :span="16">
        <el-card>
          <template #header>文档列表</template>
          <KnowledgeDocList :documents="store.documents" @view="store.loadChunks" @delete="onDelete" />
        </el-card>
      </el-col>
    </el-row>

    <el-card style="margin-top: 12px">
      <template #header>文档导入</template>
      <el-input v-model="ingestTitle" placeholder="标题（可选）" style="margin-bottom: 8px" />
      <el-input v-model="ingestContent" type="textarea" :rows="6" placeholder="粘贴 Markdown/TXT 内容" />
      <el-button type="primary" style="margin-top: 8px" @click="ingest">导入</el-button>
    </el-card>

    <el-card v-if="store.chunks.length" style="margin-top: 12px">
      <template #header>切片预览</template>
      <el-table :data="store.chunks" size="small">
        <el-table-column prop="chunk_id" label="Chunk" width="80" />
        <el-table-column prop="content" label="内容" min-width="300" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, ref } from 'vue'
import { useKnowledgeStore } from '../stores/knowledge'
import KnowledgeDocList from '../components/KnowledgeDocList.vue'

const store = useKnowledgeStore()
const ingestTitle = ref('')
const ingestContent = ref('')

const onDelete = async (docId: string) => {
  await store.removeDocument(docId)
  ElMessage.success('文档已删除')
}

const ingest = async () => {
  if (!ingestContent.value.trim()) { ElMessage.warning('请填写文档内容'); return }
  await store.ingest(ingestTitle.value, ingestContent.value)
  ElMessage.success('导入完成')
  ingestContent.value = ''
}

onMounted(async () => {
  try {
    await store.loadCorpora()
    await store.loadDocuments()
  } catch (error) {
    ElMessage.error(`加载知识库失败: ${String(error)}`)
  }
})
</script>
