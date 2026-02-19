<template>
  <div>
    <h2 style="margin: 0 0 12px 0; font-size: 20px; font-weight: 600">备份恢复</h2>

    <el-card style="margin-bottom: 12px">
      <template #header>导出备份</template>
      <div style="color: #606266; margin-bottom: 8px">
        导出 Zip：包含上下文数据库、当前 .env 与 prompts 目录。
      </div>
      <el-button type="primary" @click="exportBackup">下载备份</el-button>
    </el-card>

    <el-card>
      <template #header>导入恢复</template>
      <div style="color: #606266; margin-bottom: 8px">
        仅支持上传 Zip 备份包。可选择是否立即应用导入后的 .env 到当前运行时。
      </div>
      <el-switch v-model="applyRuntime" active-text="导入后热应用配置" />
      <div style="margin-top: 10px; display: flex; gap: 8px">
        <el-button @click="pickFile">选择备份文件</el-button>
        <span style="line-height: 32px; color: #909399">{{ selectedFileName || '未选择文件' }}</span>
      </div>
      <div style="margin-top: 12px">
        <el-button type="danger" :disabled="!selectedFile" :loading="importing" @click="importSelected">
          开始导入
        </el-button>
      </div>
      <input
        ref="fileInput"
        type="file"
        accept=".zip,application/zip"
        style="display: none"
        @change="onFileChange"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, ref } from 'vue'
import { buildBackupExportUrl, importBackup } from '../api/client'

const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const applyRuntime = ref(true)
const importing = ref(false)
const selectedFileName = computed(() => selectedFile.value?.name || '')

const exportBackup = () => {
  const url = buildBackupExportUrl()
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.click()
}

const pickFile = () => {
  fileInput.value?.click()
}

const onFileChange = (event: Event) => {
  const input = event.target as HTMLInputElement
  selectedFile.value = input.files?.[0] || null
}

const importSelected = async () => {
  if (!selectedFile.value) {
    return
  }
  const confirmed = await ElMessageBox.confirm(
    '导入会覆盖数据库、prompts 与 .env，请确认已经做好当前数据备份。',
    '确认导入',
    { type: 'warning' },
  )
    .then(() => true)
    .catch(() => false)
  if (!confirmed) {
    return
  }

  importing.value = true
  try {
    const result = await importBackup(selectedFile.value, applyRuntime.value)
    ElMessage.success(
      `导入完成：db=${Boolean(result.restored_db)} env=${Boolean(result.restored_env)} prompts=${Number(
        result.restored_prompts || 0,
      )}`,
    )
  } catch (error) {
    ElMessage.error(`导入失败: ${String(error)}`)
  } finally {
    importing.value = false
  }
}
</script>
