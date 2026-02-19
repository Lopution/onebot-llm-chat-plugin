<template>
  <div>
    <h2 style="margin: 0 0 12px 0; font-size: 20px; font-weight: 600">知识库管理</h2>
    <el-row :gutter="12" style="margin-top: 12px">
      <el-col :span="8">
        <el-card>
          <template #header>语料库</template>
          <el-select v-model="selectedCorpus" style="width: 100%" @change="refreshDocuments">
            <el-option
              v-for="item in corpora"
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
          <KnowledgeDocList :documents="documents" @view="loadChunks" @delete="removeDocument" />
        </el-card>
      </el-col>
    </el-row>

    <el-card style="margin-top: 12px">
      <template #header>文档导入</template>
      <el-input v-model="ingestTitle" placeholder="标题（可选）" style="margin-bottom: 8px" />
      <el-input v-model="ingestContent" type="textarea" :rows="6" placeholder="粘贴 Markdown/TXT 内容" />
      <el-button type="primary" style="margin-top: 8px" @click="ingest">导入</el-button>
    </el-card>

    <el-card v-if="chunks.length" style="margin-top: 12px">
      <template #header>切片预览</template>
      <el-table :data="chunks" size="small">
        <el-table-column prop="chunk_id" label="Chunk" width="80" />
        <el-table-column prop="content" label="内容" min-width="300" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, ref } from 'vue'
import {
  deleteDocument,
  ingestKnowledge,
  listChunks,
  listCorpora,
  listDocuments,
} from '../api/client'
import KnowledgeDocList from '../components/KnowledgeDocList.vue'

const corpora = ref<Array<any>>([])
const selectedCorpus = ref('default')
const documents = ref<Array<any>>([])
const chunks = ref<Array<any>>([])
const ingestTitle = ref('')
const ingestContent = ref('')

const refreshCorpora = async () => {
  corpora.value = await listCorpora()
  if (!corpora.value.length) {
    corpora.value = [{ corpus_id: 'default', doc_count: 0, chunk_count: 0 }]
  }
  if (!selectedCorpus.value) {
    selectedCorpus.value = corpora.value[0].corpus_id
  }
}

const refreshDocuments = async () => {
  documents.value = await listDocuments(selectedCorpus.value)
  chunks.value = []
}

const loadChunks = async (docId: string) => {
  chunks.value = await listChunks(selectedCorpus.value, docId)
}

const removeDocument = async (docId: string) => {
  await deleteDocument(selectedCorpus.value, docId)
  ElMessage.success('文档已删除')
  await refreshCorpora()
  await refreshDocuments()
}

const ingest = async () => {
  if (!ingestContent.value.trim()) {
    ElMessage.warning('请填写文档内容')
    return
  }
  await ingestKnowledge({
    corpus_id: selectedCorpus.value,
    title: ingestTitle.value,
    content: ingestContent.value,
  })
  ElMessage.success('导入完成')
  ingestContent.value = ''
  await refreshCorpora()
  await refreshDocuments()
}

onMounted(async () => {
  await refreshCorpora()
  await refreshDocuments()
})
</script>
