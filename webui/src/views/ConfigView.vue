<template>
  <div>
    <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap">
      <h2 style="margin: 0 0 12px 0; font-size: 20px; font-weight: 600">配置编辑</h2>

      <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap">
        <el-input
          v-model="searchQuery"
          clearable
          placeholder="搜索配置（key/说明/提示）"
          style="width: 280px"
        />
        <el-switch
          v-model="showAdvanced"
          inline-prompt
          active-text="高级"
          inactive-text="基础"
          size="small"
        />
      </div>
    </div>
    <el-alert
      title="修改后通常需要重启服务生效"
      type="warning"
      :closable="false"
      style="margin: 12px 0"
    />

    <QuickSetupWizard :model="form" :sections="store.sections" :onSave="onSave" />

    <el-card shadow="never" style="margin: 12px 0">
      <template #header>
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px">
          <strong>生效配置与警告</strong>
          <div style="display: flex; align-items: center; gap: 8px">
            <el-button size="small" :loading="effectiveLoading" @click="loadEffective">刷新</el-button>
            <el-switch
              v-model="effectiveExpanded"
              inline-prompt
              active-text="展开"
              inactive-text="收起"
              size="small"
            />
          </div>
        </div>
      </template>

      <div v-if="effectiveExpanded">
        <el-alert
          v-if="effectiveError"
          :title="effectiveError"
          type="error"
          :closable="false"
          style="margin-bottom: 12px"
        />

        <div v-else-if="effectiveSnapshot">
          <div style="display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap">
            <el-button size="small" @click="copyEffective">复制快照 JSON</el-button>
            <div v-if="effectiveSnapshot.profile" style="font-size: 12px; color: var(--el-text-color-secondary)">
              profile: <code>{{ effectiveSnapshot.profile }}</code>
            </div>
          </div>

          <div v-if="effectiveWarnings.length">
            <div style="font-weight: 600; margin-bottom: 8px">警告</div>
            <div v-for="(item, idx) in effectiveWarnings" :key="idx" style="margin-bottom: 10px">
              <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap">
                <el-tag
                  :type="item.level === 'warning' ? 'danger' : 'info'"
                  size="small"
                >
                  {{ item.code || item.level }}
                </el-tag>
                <span>{{ item.message }}</span>
              </div>
              <div v-if="item.hint" style="font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px">
                {{ item.hint }}
              </div>
            </div>
          </div>
          <el-alert v-else title="没有检测到明显的配置冲突/风险" type="success" :closable="false" />

          <el-divider style="margin: 12px 0" />

          <div style="font-weight: 600; margin-bottom: 8px">Derived（脱敏）</div>
          <pre class="json-block">{{ effectiveDerivedJson }}</pre>
        </div>

        <el-alert v-else title="尚未加载快照" type="info" :closable="false" />
      </div>
      <div v-else style="font-size: 12px; color: var(--el-text-color-secondary)">
        展开后可查看当前运行时“实际生效配置”与冲突/风险提示。
      </div>
    </el-card>

    <ConfigSection
      v-for="section in visibleSections"
      :key="section.name"
      :title="section.name"
      :fields="section.fields"
      :model="form"
    />

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
import { computed, onMounted, reactive, ref, watch } from 'vue'
import ConfigSection from '../components/ConfigSection.vue'
import QuickSetupWizard from '../components/QuickSetupWizard.vue'
import { getEffectiveConfigSnapshot } from '../api/modules/config'
import { useConfigStore } from '../stores/config'

const store = useConfigStore()
const form = reactive<Record<string, any>>({})
const saving = ref(false)
const reloading = ref(false)
const importFileInput = ref<HTMLInputElement | null>(null)
const showAdvanced = ref(false)
const searchQuery = ref('')
const envPath = computed(() => store.envPath || '')

const effectiveExpanded = ref(false)
const effectiveLoading = ref(false)
const effectiveError = ref('')
const effectiveSnapshot = ref<any | null>(null)

const envLabel = computed(() => {
  const raw = String(envPath.value || '').trim()
  if (!raw) return '.env'
  return raw.replaceAll('\\', '/').split('/').pop() || raw
})

const toFormValue = (field: any) => {
  const v = field?.value
  if (field?.type === 'array' || field?.type === 'object') {
    if (typeof v === 'string') {
      return v
    }
    if (v === null || v === undefined) {
      return ''
    }
    try {
      return JSON.stringify(v, null, 2)
    } catch (error) {
      return ''
    }
  }
  return v
}

const syncFormFromSections = (sections: any[], onlyMissing: boolean) => {
  for (const section of sections || []) {
    for (const field of section.fields || []) {
      if (!field?.key) continue
      if (onlyMissing && field.key in form) continue
      form[field.key] = toFormValue(field)
    }
  }
}

watch(
  () => store.sections,
  (sections) => {
    syncFormFromSections(sections as any[], true)
  },
  { immediate: true },
)

const visibleSections = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  const allowAdvanced = showAdvanced.value

  return (store.sections || [])
    .map((section) => {
      const fields = (section.fields || []).filter((field: any) => {
        if (!allowAdvanced && field.advanced) {
          return false
        }
        if (!query) {
          return true
        }
        const haystack = `${field.key ?? ''} ${field.description ?? ''} ${field.hint ?? ''} ${field.env_key ?? ''}`
          .toLowerCase()
          .trim()
        return haystack.includes(query)
      })
      return { ...section, fields }
    })
    .filter((section) => section.fields.length > 0)
})

const effectiveWarnings = computed(() => {
  const items = effectiveSnapshot.value?.warnings
  return Array.isArray(items) ? items : []
})

const effectiveDerivedJson = computed(() => {
  const derived = effectiveSnapshot.value?.derived || {}
  return JSON.stringify(derived, null, 2)
})

const loadEffective = async () => {
  effectiveLoading.value = true
  effectiveError.value = ''
  try {
    const data = await getEffectiveConfigSnapshot()
    effectiveSnapshot.value = data
  } catch (error) {
    effectiveError.value = `加载失败: ${String(error)}`
  } finally {
    effectiveLoading.value = false
  }
}

const copyEffective = async () => {
  try {
    const text = JSON.stringify(effectiveSnapshot.value || {}, null, 2)
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch (error) {
    ElMessage.error(`复制失败: ${String(error)}`)
  }
}

watch(
  () => effectiveExpanded.value,
  async (expanded) => {
    if (expanded && !effectiveSnapshot.value && !effectiveLoading.value) {
      await loadEffective()
    }
  },
)

const onSave = async () => {
  saving.value = true
  try {
    await store.save(form)
    ElMessage.success(`配置已写入 ${envLabel.value}（请重启生效）`)
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
    syncFormFromSections(store.sections as any[], false)
    ElMessage.success(`已从 ${envLabel.value} 热重载配置`)
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
    syncFormFromSections(store.sections as any[], false)
    ElMessage.success('配置导入成功')
  } catch (error) {
    ElMessage.error(`配置导入失败: ${String(error)}`)
  } finally {
    input.value = ''
  }
}

onMounted(async () => {
  await store.load()
  try {
    await store.loadEnvPath()
  } catch (error) {
    ElMessage.error(`加载 env 路径失败: ${String(error)}`)
  }
})
</script>

<style scoped>
.json-block {
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  line-height: 1.4;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
}
</style>
