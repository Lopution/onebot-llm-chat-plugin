<template>
  <el-dialog :model-value="visible" title="编辑用户档案" width="720px" @close="$emit('close')">
    <el-form :model="editor" label-width="90px">
      <el-form-item label="昵称"><el-input v-model="editor.nickname" /></el-form-item>
      <el-form-item label="真实姓名"><el-input v-model="editor.real_name" /></el-form-item>
      <el-form-item label="身份"><el-input v-model="editor.identity" /></el-form-item>
      <el-form-item label="职业"><el-input v-model="editor.occupation" /></el-form-item>
      <el-form-item label="年龄"><el-input v-model="editor.age" /></el-form-item>
      <el-form-item label="地区"><el-input v-model="editor.location" /></el-form-item>
      <el-form-item label="生日"><el-input v-model="editor.birthday" /></el-form-item>
      <el-form-item label="喜好"><el-input v-model="editor.preferencesText" placeholder="用英文逗号分隔" /></el-form-item>
      <el-form-item label="不喜欢"><el-input v-model="editor.dislikesText" placeholder="用英文逗号分隔" /></el-form-item>
      <el-form-item label="扩展JSON"><el-input v-model="editor.extraInfoText" type="textarea" :rows="4" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('close')">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { reactive, ref, watch } from 'vue'
import type { UserProfileListItem } from '../api/types'

const props = defineProps<{
  visible: boolean
  profile: UserProfileListItem | null
}>()

const emit = defineEmits<{
  close: []
  save: [payload: Record<string, unknown>]
}>()

const saving = ref(false)

const editor = reactive({
  nickname: '',
  real_name: '',
  identity: '',
  occupation: '',
  age: '',
  location: '',
  birthday: '',
  preferencesText: '',
  dislikesText: '',
  extraInfoText: '{}',
})

watch(
  () => props.profile,
  (profile) => {
    if (!profile) return
    editor.nickname = profile.nickname || ''
    editor.real_name = profile.real_name || ''
    editor.identity = profile.identity || ''
    editor.occupation = profile.occupation || ''
    editor.age = profile.age || ''
    editor.location = profile.location || ''
    editor.birthday = profile.birthday || ''
    editor.preferencesText = (profile.preferences || []).join(', ')
    editor.dislikesText = (profile.dislikes || []).join(', ')
    editor.extraInfoText = JSON.stringify(profile.extra_info || {}, null, 2)
  },
  { immediate: true },
)

const parseCsvList = (value: string): string[] =>
  value.split(',').map((item) => item.trim()).filter((item) => item.length > 0)

const save = async () => {
  saving.value = true
  try {
    let extraInfo: Record<string, unknown> = {}
    try {
      extraInfo = JSON.parse(editor.extraInfoText || '{}')
    } catch {
      ElMessage.error('扩展 JSON 格式错误')
      return
    }
    emit('save', {
      nickname: editor.nickname,
      real_name: editor.real_name,
      identity: editor.identity,
      occupation: editor.occupation,
      age: editor.age,
      location: editor.location,
      birthday: editor.birthday,
      preferences: parseCsvList(editor.preferencesText),
      dislikes: parseCsvList(editor.dislikesText),
      extra_info: extraInfo,
    })
  } finally {
    saving.value = false
  }
}
</script>
