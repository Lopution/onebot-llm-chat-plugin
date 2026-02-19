<template>
  <el-card style="margin-bottom: 16px" shadow="never">
    <template #header>
      <div class="config-section-header">
        <strong>{{ title }}</strong>
        <slot name="header-extra" />
      </div>
    </template>

    <div v-for="(field, idx) in fields" :key="field.key" class="config-row">
      <!-- 左侧：标签 + 说明 -->
      <div class="config-label">
        <div class="config-label-text">{{ field.description || field.key }}</div>
        <div v-if="field.hint" class="config-hint">{{ field.hint }}</div>
      </div>

      <!-- 右侧：控件 -->
      <div class="config-input">
        <!-- 有 options 的字段 → 下拉选择 -->
        <el-select
          v-if="field.options && field.options.length"
          v-model="model[field.key]"
          style="width: 100%"
          placeholder="请选择"
        >
          <el-option
            v-for="(opt, oi) in field.options"
            :key="opt"
            :label="field.labels && field.labels[oi] ? field.labels[oi] : opt"
            :value="opt"
          />
        </el-select>

        <!-- bool → 开关 -->
        <el-switch
          v-else-if="field.type === 'boolean'"
          v-model="model[field.key]"
        />

        <!-- 数字 → 数字输入 -->
        <el-input-number
          v-else-if="field.type === 'integer' || field.type === 'number'"
          v-model="model[field.key]"
          :controls="false"
          style="width: 100%"
        />

        <!-- 数组/对象 → textarea -->
        <el-input
          v-else-if="field.type === 'array' || field.type === 'object'"
          v-model="model[field.key]"
          type="textarea"
          :rows="2"
          placeholder="JSON 或逗号分隔"
        />

        <!-- 密钥字段 → 密码输入 -->
        <el-input
          v-else-if="field.secret"
          v-model="model[field.key]"
          type="password"
          show-password
          placeholder="••••••••"
        />

        <!-- 默认 → 文本输入 -->
        <el-input v-else v-model="model[field.key]" />
      </div>

      <el-divider v-if="idx < fields.length - 1" style="margin: 0" />
    </div>
  </el-card>
</template>

<script setup lang="ts">
interface ConfigField {
  key: string
  type: string
  description?: string
  hint?: string
  options?: string[]
  labels?: string[]
  secret?: boolean
  advanced?: boolean
}

defineProps<{
  title: string
  fields: ConfigField[]
  model: Record<string, any>
}>()
</script>

<style scoped>
.config-row {
  padding: 12px 0;
}

.config-row:first-child {
  padding-top: 0;
}

.config-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.config-label {
  margin-bottom: 8px;
}

.config-label-text {
  font-size: 14px;
  font-weight: 500;
  color: var(--el-text-color-primary);
}

.config-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
  line-height: 1.4;
}

.config-input {
  max-width: 480px;
}
</style>
