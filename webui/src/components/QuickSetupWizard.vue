<template>
  <el-card shadow="never" style="margin: 12px 0">
    <template #header>
      <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px">
        <strong>快速配置向导</strong>
        <el-switch
          v-model="expanded"
          inline-prompt
          active-text="展开"
          inactive-text="收起"
          size="small"
        />
      </div>
    </template>

    <div v-if="expanded">
      <el-steps :active="activeStep" finish-status="success" align-center style="margin-bottom: 16px">
        <el-step title="LLM" />
        <el-step title="身份" />
        <el-step title="可选项" />
      </el-steps>

      <el-form label-position="top">
        <div v-show="activeStep === 0">
          <el-form-item label="LLM Provider">
            <el-select v-model="draft.llm_provider" style="width: 100%" placeholder="请选择">
              <el-option
                v-for="(opt, idx) in llmProviderOptions"
                :key="opt"
                :label="llmProviderLabels[idx] || opt"
                :value="opt"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="LLM Base URL">
            <el-input v-model="draft.llm_base_url" placeholder="https://.../v1 或 .../openai/" />
          </el-form-item>

          <el-form-item label="API Key 模式">
            <el-radio-group v-model="draft.key_mode">
              <el-radio-button label="single">单 Key</el-radio-button>
              <el-radio-button label="list">Key 列表</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <el-form-item v-if="draft.key_mode === 'single'" label="LLM_API_KEY">
            <el-input v-model="draft.llm_api_key" type="password" show-password placeholder="••••••••" />
          </el-form-item>

          <el-form-item v-else label="LLM_API_KEY_LIST">
            <el-input
              v-model="draft.llm_api_key_list"
              type="textarea"
              :rows="2"
              placeholder='["key1","key2"] 或 key1,key2'
            />
          </el-form-item>

          <el-form-item label="主模型 (LLM_MODEL)">
            <el-input v-model="draft.llm_model" placeholder="例如 gemini-3-pro-high / gpt-4o / ..." />
          </el-form-item>

          <el-form-item label="快速模型 (LLM_FAST_MODEL)">
            <el-input v-model="draft.llm_fast_model" placeholder="用于摘要/抽取等轻量任务" />
          </el-form-item>
        </div>

        <div v-show="activeStep === 1">
          <el-form-item label="管理员 QQ (MIKA_MASTER_ID)">
            <el-input v-model="draft.mika_master_id" placeholder="例如 123456789" />
          </el-form-item>
          <el-form-item label="管理员昵称 (MIKA_MASTER_NAME)">
            <el-input v-model="draft.mika_master_name" placeholder="Sensei" />
          </el-form-item>
          <el-form-item label="Bot 显示名称 (MIKA_BOT_DISPLAY_NAME)">
            <el-input v-model="draft.mika_bot_display_name" placeholder="Mika" />
          </el-form-item>
        </div>

        <div v-show="activeStep === 2">
          <el-form-item label="搜索 Provider (SEARCH_PROVIDER)">
            <el-select v-model="draft.search_provider" style="width: 100%" placeholder="可选">
              <el-option
                v-for="(opt, idx) in searchProviderOptions"
                :key="opt"
                :label="searchProviderLabels[idx] || opt"
                :value="opt"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="搜索 API Key (SEARCH_API_KEY)">
            <el-input v-model="draft.search_api_key" type="password" show-password placeholder="可选" />
          </el-form-item>

          <el-form-item label="WebUI Token (MIKA_WEBUI_TOKEN)">
            <el-input v-model="draft.mika_webui_token" type="password" show-password placeholder="可选" />
          </el-form-item>
        </div>
      </el-form>

      <div style="display: flex; gap: 8px; justify-content: space-between; margin-top: 12px">
        <div style="display: flex; gap: 8px">
          <el-button :disabled="activeStep === 0" @click="activeStep -= 1">上一步</el-button>
          <el-button :disabled="activeStep === 2" type="primary" plain @click="activeStep += 1">下一步</el-button>
        </div>

        <div style="display: flex; gap: 8px">
          <el-button type="primary" @click="applyToForm">应用到表单</el-button>
          <el-button type="success" @click="applyAndSave">应用并保存</el-button>
        </div>
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { ConfigSection } from '../api/types'

const props = defineProps<{
  model: Record<string, any>
  sections: ConfigSection[]
  onSave: () => Promise<void>
}>()

const expanded = ref(true)
const activeStep = ref(0)

const allFields = computed(() => props.sections.flatMap((s) => s.fields))
const fieldByKey = computed(() => {
  const m = new Map<string, any>()
  for (const f of allFields.value) m.set(f.key, f)
  return m
})

const llmProviderOptions = computed(() => fieldByKey.value.get('llm_provider')?.options || [])
const llmProviderLabels = computed(() => fieldByKey.value.get('llm_provider')?.labels || [])
const searchProviderOptions = computed(() => fieldByKey.value.get('search_provider')?.options || [])
const searchProviderLabels = computed(() => fieldByKey.value.get('search_provider')?.labels || [])

const draft = reactive({
  llm_provider: '',
  llm_base_url: '',
  llm_api_key: '',
  llm_api_key_list: '',
  llm_model: '',
  llm_fast_model: '',
  key_mode: 'single' as 'single' | 'list',
  mika_master_id: '',
  mika_master_name: '',
  mika_bot_display_name: '',
  search_provider: '',
  search_api_key: '',
  mika_webui_token: '',
})

watch(
  () => ({
    llm_provider: props.model.llm_provider,
    llm_base_url: props.model.llm_base_url,
    llm_model: props.model.llm_model,
    llm_fast_model: props.model.llm_fast_model,
    mika_master_id: props.model.mika_master_id,
    mika_master_name: props.model.mika_master_name,
    mika_bot_display_name: props.model.mika_bot_display_name,
    search_provider: props.model.search_provider,
  }),
  (model) => {
    draft.llm_provider = String(model.llm_provider ?? draft.llm_provider ?? '')
    draft.llm_base_url = String(model.llm_base_url ?? draft.llm_base_url ?? '')
    draft.llm_model = String(model.llm_model ?? draft.llm_model ?? '')
    draft.llm_fast_model = String(model.llm_fast_model ?? draft.llm_fast_model ?? '')
    draft.mika_master_id = String(model.mika_master_id ?? draft.mika_master_id ?? '')
    draft.mika_master_name = String(model.mika_master_name ?? draft.mika_master_name ?? '')
    draft.mika_bot_display_name = String(model.mika_bot_display_name ?? draft.mika_bot_display_name ?? '')
    draft.search_provider = String(model.search_provider ?? draft.search_provider ?? '')
    // secrets: don't prefill
  },
  { immediate: true },
)

const applyToForm = () => {
  props.model.llm_provider = draft.llm_provider
  props.model.llm_base_url = draft.llm_base_url
  props.model.llm_model = draft.llm_model
  props.model.llm_fast_model = draft.llm_fast_model

  if (draft.key_mode === 'single') {
    if (draft.llm_api_key) props.model.llm_api_key = draft.llm_api_key
    props.model.llm_api_key_list = '[]' // clear list explicitly
  } else {
    if (draft.llm_api_key_list) props.model.llm_api_key_list = draft.llm_api_key_list
    // keep llm_api_key unchanged unless user explicitly sets it elsewhere
  }

  props.model.mika_master_id = draft.mika_master_id
  props.model.mika_master_name = draft.mika_master_name
  props.model.mika_bot_display_name = draft.mika_bot_display_name

  props.model.search_provider = draft.search_provider
  if (draft.search_api_key) props.model.search_api_key = draft.search_api_key
  if (draft.mika_webui_token) props.model.mika_webui_token = draft.mika_webui_token
}

const applyAndSave = async () => {
  applyToForm()
  await props.onSave()
}
</script>
