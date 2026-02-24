<template>
  <el-space direction="vertical" fill :size="16">
    <el-card>
      <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px">
        <h2 style="margin: 0">人设管理</h2>
        <el-button type="primary" @click="openCreate">新建人设</el-button>
      </div>
    </el-card>

    <el-card>
      <el-table :data="store.items" v-loading="store.loading" size="small">
        <el-table-column prop="id" label="ID" width="72" />
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'">
              {{ row.is_active ? '启用中' : '未启用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="人设内容" min-width="360">
          <template #default="{ row }">
            <div style="white-space: pre-wrap; line-height: 1.5">
              {{ previewPrompt(row.character_prompt) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="300">
          <template #default="{ row }">
            <el-space>
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button
                size="small" type="success" plain
                :disabled="row.is_active"
                @click="activate(row.id)"
              >设为启用</el-button>
              <el-popconfirm title="确认删除该人设？" @confirm="remove(row.id)">
                <template #reference>
                  <el-button size="small" type="danger" plain>删除</el-button>
                </template>
              </el-popconfirm>
            </el-space>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="720px">
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="例如：圣园未花" />
        </el-form-item>
        <el-form-item label="角色定义（character_prompt）">
          <el-input v-model="form.character_prompt" type="textarea" :rows="12" />
        </el-form-item>
        <el-form-item label="立即启用">
          <el-switch v-model="form.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-space>
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" @click="submitPersona">保存</el-button>
        </el-space>
      </template>
    </el-dialog>
  </el-space>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { usePersonaStore } from '../stores/persona'
import type { Persona } from '../api/types'

type PersonaForm = { id?: number; name: string; character_prompt: string; is_active: boolean }

const store = usePersonaStore()
const dialogVisible = ref(false)
const dialogTitle = ref('新建人设')
const form = ref<PersonaForm>({ name: '', character_prompt: '', is_active: false })

const previewPrompt = (text: string) => {
  const normalized = String(text || '').trim()
  return normalized.length <= 120 ? normalized : `${normalized.slice(0, 120)}...`
}

const resetForm = () => { form.value = { name: '', character_prompt: '', is_active: false } }

const openCreate = () => { dialogTitle.value = '新建人设'; resetForm(); dialogVisible.value = true }

const openEdit = (persona: Persona) => {
  dialogTitle.value = '编辑人设'
  form.value = { id: persona.id, name: persona.name, character_prompt: persona.character_prompt, is_active: !!persona.is_active }
  dialogVisible.value = true
}

const submitPersona = async () => {
  const payload = { name: form.value.name.trim(), character_prompt: form.value.character_prompt.trim(), is_active: !!form.value.is_active }
  if (!payload.name || !payload.character_prompt) { ElMessage.warning('名称和角色定义不能为空'); return }
  try {
    if (form.value.id) { await store.update(form.value.id, payload); ElMessage.success('人设已更新') }
    else { await store.create(payload); ElMessage.success('人设已创建') }
    dialogVisible.value = false
  } catch (error) { ElMessage.error((error as Error).message || '保存失败') }
}

const activate = async (id: number) => {
  try { await store.activate(id); ElMessage.success('已切换启用人设') }
  catch (error) { ElMessage.error((error as Error).message || '切换失败') }
}

const remove = async (id: number) => {
  try { await store.remove(id); ElMessage.success('已删除') }
  catch (error) { ElMessage.error((error as Error).message || '删除失败') }
}

onMounted(() => store.load())
</script>
