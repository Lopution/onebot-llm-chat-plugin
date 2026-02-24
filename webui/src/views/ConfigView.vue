<template>
  <div>
    <h2 style="margin: 0 0 12px 0; font-size: 20px; font-weight: 600">配置编辑</h2>
    <el-alert
      title="修改后通常需要重启服务生效"
      type="warning"
      :closable="false"
      style="margin: 12px 0"
    />

    <ConfigSection
      v-for="section in store.sections"
      :key="section.name"
      :title="section.name"
      :fields="visibleFields(section)"
      :model="form"
    >
      <template #header-extra v-if="shouldShowMessageAdvancedToggle(section)">
        <el-switch
          v-model="showMessageAdvanced"
          inline-prompt
          active-text="高级"
          inactive-text="基础"
          size="small"
        />
      </template>
    </ConfigSection>

    <div style="display: flex; gap: 8px; margin-top: 12px">
      <el-button type="primary" :loading="saving" @click="onSave">保存配置</el-button>
      <el-button :loading="reloading" @click="onReload">热重载</el-button>
      <el-button @click="onExport">导出 JSON</el-button>
      <el-button @click="triggerImport">导入 JSON</el-button>
      <input
        ref="importFileInput"
        type="file"
        accept="application/json"
        style="display: none"
        @change="onImportFileSelected"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref, watch } from 'vue'
import ConfigSection from '../components/ConfigSection.vue'
import { useConfigStore } from '../stores/config'

const store = useConfigStore()
const form = reactive<Record<string, any>>({})
const saving = ref(false)
const reloading = ref(false)
const importFileInput = ref<HTMLInputElement | null>(null)
const showMessageAdvanced = ref(false)

watch(
  () => store.sections,
  (sections) => {
    for (const section of sections) {
      for (const field of section.fields) {
        if (!(field.key in form)) {
          if (field.type === 'array' || field.type === 'object') {
            form[field.key] = JSON.stringify(field.value ?? '')
          } else {
            form[field.key] = field.value
          }
        }
      }
    }
  },
  { immediate: true },
)

const shouldShowMessageAdvancedToggle = (section: { name: string; fields: Array<{ advanced?: boolean }> }) => {
  return section.name === '消息发送' && section.fields.some((field) => field.advanced)
}

const visibleFields = (section: { name: string; fields: Array<{ advanced?: boolean }> }) => {
  if (section.name !== '消息发送') {
    return section.fields
  }
  if (showMessageAdvanced.value) {
    return section.fields
  }
  return section.fields.filter((field) => !field.advanced)
}

const onSave = async () => {
  saving.value = true
  try {
    await store.save(form)
    ElMessage.success('配置已写入 .env（请重启生效）')
  } catch (error) {
    ElMessage.error(String(error))
  } finally {
    saving.value = false
  }
}

const onReload = async () => {
  reloading.value = true
  try {
    await store.reload()
    await store.load()
    for (const section of store.sections) {
      for (const field of section.fields) {
        if (field.type === 'array' || field.type === 'object') {
          form[field.key] = JSON.stringify(field.value ?? '')
        } else {
          form[field.key] = field.value
        }
      }
    }
    ElMessage.success('已从 .env 热重载配置')
  } catch (error) {
    ElMessage.error(String(error))
  } finally {
    reloading.value = false
  }
}

const onExport = async () => {
  try {
    const data = await store.export(false)
    const blob = new Blob([JSON.stringify(data.config || {}, null, 2)], {
      type: 'application/json',
    })
    const href = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = href
    anchor.download = 'mika-config-export.json'
    anchor.click()
    URL.revokeObjectURL(href)
    ElMessage.success('配置已导出')
  } catch (error) {
    ElMessage.error(String(error))
  }
}

const triggerImport = () => {
  importFileInput.value?.click()
}

const onImportFileSelected = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) {
    return
  }
  try {
    const text = await file.text()
    const parsed = JSON.parse(text)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      ElMessage.error('导入文件必须是 JSON 对象')
      return
    }
    await store.import(parsed as Record<string, unknown>, true)
    await store.load()
    for (const section of store.sections) {
      for (const field of section.fields) {
        if (field.type === 'array' || field.type === 'object') {
          form[field.key] = JSON.stringify(field.value ?? '')
        } else {
          form[field.key] = field.value
        }
      }
    }
    ElMessage.success('配置导入成功')
  } catch (error) {
    ElMessage.error(`配置导入失败: ${String(error)}`)
  } finally {
    input.value = ''
  }
}

onMounted(async () => {
  await store.load()
})
</script>
