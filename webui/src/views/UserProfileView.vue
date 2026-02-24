<template>
  <div>
    <h2 class="page-title">用户档案</h2>

    <el-card>
      <div style="display: flex; gap: 8px; align-items: center">
        <el-input
          v-model="localQuery"
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
            <span style="float: right; color: #909399">共 {{ store.total }} 条</span>
          </template>
          <el-table
            :data="store.items"
            row-key="platform_user_id"
            size="small"
            v-loading="store.loading"
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
              :current-page="store.page"
              :page-size="store.pageSize"
              :total="store.total"
              @current-change="store.changePage"
            />
          </div>
        </el-card>
      </el-col>

      <el-col :span="14">
        <el-card>
          <template #header>
            档案详情
            <div style="float: right; display: inline-flex; gap: 8px">
              <el-button size="small" :disabled="!store.selectedId" @click="editorVisible = true">编辑</el-button>
              <el-button size="small" type="danger" :disabled="!store.selectedId" @click="removeProfile">删除</el-button>
            </div>
          </template>
          <div v-if="!store.detail" style="color: #909399">请选择左侧用户档案。</div>
          <el-descriptions v-else :column="2" border size="small">
            <el-descriptions-item label="平台ID">{{ store.detail.platform_user_id }}</el-descriptions-item>
            <el-descriptions-item label="昵称">{{ store.detail.nickname || '-' }}</el-descriptions-item>
            <el-descriptions-item label="真实姓名">{{ store.detail.real_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="身份">{{ store.detail.identity || '-' }}</el-descriptions-item>
            <el-descriptions-item label="职业">{{ store.detail.occupation || '-' }}</el-descriptions-item>
            <el-descriptions-item label="年龄">{{ store.detail.age || '-' }}</el-descriptions-item>
            <el-descriptions-item label="地区">{{ store.detail.location || '-' }}</el-descriptions-item>
            <el-descriptions-item label="生日">{{ store.detail.birthday || '-' }}</el-descriptions-item>
            <el-descriptions-item label="喜好">{{ (store.detail.preferences || []).join('，') || '-' }}</el-descriptions-item>
            <el-descriptions-item label="不喜欢">{{ (store.detail.dislikes || []).join('，') || '-' }}</el-descriptions-item>
            <el-descriptions-item label="更新于">{{ store.detail.updated_at || '-' }}</el-descriptions-item>
            <el-descriptions-item label="创建于">{{ store.detail.created_at || '-' }}</el-descriptions-item>
            <el-descriptions-item label="扩展信息" :span="2">
              <pre style="margin: 0">{{ prettyExtraInfo }}</pre>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>

    <UserProfileEditor
      :visible="editorVisible"
      :profile="store.detail"
      @close="editorVisible = false"
      @save="onEditorSave"
    />
  </div>
</template>

<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { useUserProfileStore } from '../stores/userProfile'
import type { UserProfileListItem } from '../api/types'
import UserProfileEditor from '../components/UserProfileEditor.vue'

const store = useUserProfileStore()
const localQuery = ref(store.query)
const editorVisible = ref(false)

const prettyExtraInfo = computed(() => {
  if (!store.detail?.extra_info || Object.keys(store.detail.extra_info).length === 0) return '-'
  try { return JSON.stringify(store.detail.extra_info, null, 2) } catch { return '-' }
})

const onSearch = () => store.search(localQuery.value)
const onSelect = (row: UserProfileListItem) => store.select(row.platform_user_id)

const onEditorSave = async (payload: Record<string, unknown>) => {
  if (!store.selectedId) return
  try {
    await store.update(store.selectedId, payload)
    editorVisible.value = false
    ElMessage.success('档案已更新')
  } catch (error) {
    ElMessage.error(`保存失败: ${String(error)}`)
  }
}

const removeProfile = async () => {
  if (!store.selectedId) return
  const confirmed = await ElMessageBox.confirm(`确认删除档案 ${store.selectedId}？`, '确认删除')
    .then(() => true).catch(() => false)
  if (!confirmed) return
  await store.remove(store.selectedId)
  ElMessage.success('档案已删除')
}

onMounted(() => store.load())
</script>
