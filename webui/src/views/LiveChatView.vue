<template>
  <div>
    <h2 class="page-title">WebUI 测试对话</h2>

    <el-card style="margin-bottom: 12px">
      <template #header>会话参数</template>
      <el-row :gutter="8">
        <el-col :span="8"><el-input v-model="sessionId" placeholder="session_id (private:webui_admin)" /></el-col>
        <el-col :span="8"><el-input v-model="userId" placeholder="user_id (webui_admin)" /></el-col>
        <el-col :span="8"><el-input v-model="groupId" placeholder="group_id (可选，群聊测试)" /></el-col>
      </el-row>
      <div style="margin-top: 10px; display: flex; align-items: center; gap: 8px">
        <el-tag :type="chat.connected.value ? 'success' : 'info'">
          {{ chat.connected.value ? 'WebSocket 已连接' : 'WebSocket 未连接（将走 HTTP）' }}
        </el-tag>
        <el-button size="small" @click="toggleConnection">
          {{ chat.connected.value ? '断开连接' : '连接 WebSocket' }}
        </el-button>
        <el-button size="small" @click="chat.clearMessages()">清空对话</el-button>
      </div>
    </el-card>

    <el-card>
      <template #header>对话面板</template>
      <div class="chat-box">
        <div v-for="item in chat.messages.value" :key="item.id" class="chat-item">
          <el-tag size="small" :type="item.role === 'assistant' ? 'success' : item.role === 'error' ? 'danger' : 'info'">
            {{ item.role === 'assistant' ? 'Mika' : item.role === 'error' ? '错误' : 'You' }}
          </el-tag>
          <span class="chat-time">{{ item.time }}</span>
          <div class="chat-text">{{ item.text }}</div>
        </div>
      </div>
      <div style="display: flex; gap: 8px; margin-top: 10px">
        <el-input v-model="inputText" placeholder="输入测试消息，按 Enter 发送" @keyup.enter="send" />
        <el-button type="primary" :loading="sending" @click="send">发送</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { ref } from 'vue'
import { buildLiveChatWsUrl, sendLiveChatMessage } from '../api/modules/live-chat'
import { useLiveChatConnection } from '../composables/useLiveChatConnection'

const chat = useLiveChatConnection()

const sessionId = ref('private:webui_admin')
const userId = ref('webui_admin')
const groupId = ref('')
const inputText = ref('')
const sending = ref(false)

const toggleConnection = async () => {
  if (chat.connected.value) {
    chat.closeSocket()
    ElMessage.info('WebSocket 已断开')
    return
  }
  const wsUrl = await buildLiveChatWsUrl()
  chat.connectSocket(wsUrl)
  ElMessage.success('WebSocket 已连接')
}

const send = async () => {
  const text = inputText.value.trim()
  if (!text) return
  chat.appendMessage('user', text)
  inputText.value = ''

  const sent = chat.sendViaSocket({
    request_id: `req-${Date.now()}`,
    message: text,
    session_id: sessionId.value.trim() || 'private:webui_admin',
    user_id: userId.value.trim() || 'webui_admin',
    group_id: groupId.value.trim(),
  })
  if (sent) return

  sending.value = true
  try {
    const result = await sendLiveChatMessage(
      text,
      sessionId.value.trim() || 'private:webui_admin',
      userId.value.trim() || 'webui_admin',
      groupId.value.trim(),
    )
    chat.appendMessage('assistant', result.reply || '')
  } catch (error) {
    chat.appendMessage('error', String(error))
  } finally {
    sending.value = false
  }
}
</script>
