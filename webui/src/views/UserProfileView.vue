<template>
  <div>
    <h2 style="margin: 0 0 12px 0; font-size: 20px; font-weight: 600">用户档案</h2>

    <el-card>
      <div style="display: flex; gap: 8px; align-items: center">
        <el-input
          v-model="query"
          placeholder="搜索平台ID / 昵称 / 身份 / 地区"
          clearable
          @keyup.enter="onSearch"
          @clear="onSearch"
        />
        <el-button type="primary" @click="onSearch">搜索</el-button>
      </div>
    </el-card>

    <el-row :gutter="12" style="margin-top: 12px">
      <el-col :span="10">
        <el-card>
          <template #header>
            档案列表
            <span style="float: right; color: #909399">共 {{ total }} 条</span>
          </template>
          <el-table
            :data="items"
            row-key="platform_user_id"
            size="small"
            v-loading="loading"
            highlight-current-row
            @row-click="onSelect"
          >
            <el-table-column prop="platform_user_id" label="平台ID" min-width="150" />
            <el-table-column prop="nickname" label="昵称" min-width="120" />
            <el-table-column prop="identity" label="身份" min-width="120" />
          </el-table>
          <div style="margin-top: 10px; display: flex; justify-content: flex-end">
            <el-pagination
              layout="prev, pager, next"
              :current-page="page"
              :page-size="pageSize"
              :total="total"
              @current-change="onPageChange"
            />
          </div>
        </el-card>
      </el-col>

      <el-col :span="14">
        <el-card>
          <template #header>
            档案详情
            <div style="float: right; display: inline-flex; gap: 8px">
              <el-button size="small" :disabled="!selectedId" @click="openEditor">编辑</el-button>
              <el-button size="small" type="danger" :disabled="!selectedId" @click="removeProfile">删除</el-button>
            </div>
          </template>
          <div v-if="!detail" style="color: #909399">请选择左侧用户档案。</div>
          <el-descriptions v-else :column="2" border size="small">
            <el-descriptions-item label="平台ID">{{ detail.platform_user_id }}</el-descriptions-item>
            <el-descriptions-item label="昵称">{{ detail.nickname || '-' }}</el-descriptions-item>
            <el-descriptions-item label="真实姓名">{{ detail.real_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="身份">{{ detail.identity || '-' }}</el-descriptions-item>
            <el-descriptions-item label="职业">{{ detail.occupation || '-' }}</el-descriptions-item>
            <el-descriptions-item label="年龄">{{ detail.age || '-' }}</el-descriptions-item>
            <el-descriptions-item label="地区">{{ detail.location || '-' }}</el-descriptions-item>
            <el-descriptions-item label="生日">{{ detail.birthday || '-' }}</el-descriptions-item>
            <el-descriptions-item label="喜好">{{ (detail.preferences || []).join('，') || '-' }}</el-descriptions-item>
            <el-descriptions-item label="不喜欢">{{ (detail.dislikes || []).join('，') || '-' }}</el-descriptions-item>
            <el-descriptions-item label="更新于">{{ detail.updated_at || '-' }}</el-descriptions-item>
            <el-descriptions-item label="创建于">{{ detail.created_at || '-' }}</el-descriptions-item>
            <el-descriptions-item label="扩展信息" :span="2">
              <pre style="margin: 0">{{ prettyExtraInfo }}</pre>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="editorVisible" title="编辑用户档案" width="720px">
      <el-form :model="editor" label-width="90px">
        <el-form-item label="昵称">
          <el-input v-model="editor.nickname" />
        </el-form-item>
        <el-form-item label="真实姓名">
          <el-input v-model="editor.real_name" />
        </el-form-item>
        <el-form-item label="身份">
          <el-input v-model="editor.identity" />
        </el-form-item>
        <el-form-item label="职业">
          <el-input v-model="editor.occupation" />
        </el-form-item>
        <el-form-item label="年龄">
          <el-input v-model="editor.age" />
        </el-form-item>
        <el-form-item label="地区">
          <el-input v-model="editor.location" />
        </el-form-item>
        <el-form-item label="生日">
          <el-input v-model="editor.birthday" />
        </el-form-item>
        <el-form-item label="喜好">
          <el-input v-model="editor.preferencesText" placeholder="用英文逗号分隔" />
        </el-form-item>
        <el-form-item label="不喜欢">
          <el-input v-model="editor.dislikesText" placeholder="用英文逗号分隔" />
        </el-form-item>
        <el-form-item label="扩展JSON">
          <el-input v-model="editor.extraInfoText" type="textarea" :rows="4" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEditor">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'
import {
  deleteUserProfile,
  getUserProfile,
  listUserProfiles,
  updateUserProfile,
  type UserProfileListItem,
} from '../api/client'

type ProfileDetail = UserProfileListItem & {
  created_at?: string
  updated_at?: string
}

const loading = ref(false)
const saving = ref(false)
const query = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const items = ref<UserProfileListItem[]>([])
const selectedId = ref('')
const detail = ref<ProfileDetail | null>(null)
const editorVisible = ref(false)

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

const prettyExtraInfo = computed(() => {
  if (!detail.value?.extra_info || Object.keys(detail.value.extra_info).length === 0) {
    return '-'
  }
  try {
    return JSON.stringify(detail.value.extra_info, null, 2)
  } catch {
    return '-'
  }
})

const parseCsvList = (value: string): string[] =>
  value
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0)

const refresh = async () => {
  loading.value = true
  try {
    const data = await listUserProfiles(page.value, pageSize.value, query.value)
    items.value = data.items || []
    total.value = Number(data.total || 0)
    if (selectedId.value) {
      const exists = items.value.some((item) => item.platform_user_id === selectedId.value)
      if (!exists) {
        selectedId.value = ''
        detail.value = null
      }
    }
    if (!selectedId.value && items.value.length > 0) {
      selectedId.value = items.value[0].platform_user_id
      await loadDetail(selectedId.value)
    }
  } finally {
    loading.value = false
  }
}

const loadDetail = async (platformUserId: string) => {
  detail.value = (await getUserProfile(platformUserId)) as ProfileDetail
}

const onSearch = async () => {
  page.value = 1
  await refresh()
}

const onPageChange = async (newPage: number) => {
  page.value = newPage
  await refresh()
}

const onSelect = async (row: UserProfileListItem) => {
  selectedId.value = row.platform_user_id
  await loadDetail(row.platform_user_id)
}

const openEditor = () => {
  if (!detail.value) {
    return
  }
  editor.nickname = detail.value.nickname || ''
  editor.real_name = detail.value.real_name || ''
  editor.identity = detail.value.identity || ''
  editor.occupation = detail.value.occupation || ''
  editor.age = detail.value.age || ''
  editor.location = detail.value.location || ''
  editor.birthday = detail.value.birthday || ''
  editor.preferencesText = (detail.value.preferences || []).join(', ')
  editor.dislikesText = (detail.value.dislikes || []).join(', ')
  editor.extraInfoText = JSON.stringify(detail.value.extra_info || {}, null, 2)
  editorVisible.value = true
}

const saveEditor = async () => {
  if (!selectedId.value) {
    return
  }
  saving.value = true
  try {
    let extraInfo: Record<string, unknown> = {}
    try {
      extraInfo = JSON.parse(editor.extraInfoText || '{}')
    } catch {
      ElMessage.error('扩展 JSON 格式错误')
      return
    }
    const payload = {
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
    }
    detail.value = (await updateUserProfile(selectedId.value, payload)) as ProfileDetail
    editorVisible.value = false
    ElMessage.success('档案已更新')
    await refresh()
  } catch (error) {
    ElMessage.error(`保存失败: ${String(error)}`)
  } finally {
    saving.value = false
  }
}

const removeProfile = async () => {
  if (!selectedId.value) {
    return
  }
  const confirmed = await ElMessageBox.confirm(`确认删除档案 ${selectedId.value}？`, '确认删除')
    .then(() => true)
    .catch(() => false)
  if (!confirmed) {
    return
  }
  await deleteUserProfile(selectedId.value)
  ElMessage.success('档案已删除')
  selectedId.value = ''
  detail.value = null
  await refresh()
}

onMounted(async () => {
  await refresh()
})
</script>
