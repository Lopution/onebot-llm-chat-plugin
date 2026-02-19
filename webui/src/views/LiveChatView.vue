<template>
  <div>
    <h2 style="margin: 0 0 12px 0; font-size: 20px; font-weight: 600">WebUI 测试对话</h2>

    <el-card style="margin-bottom: 12px">
      <template #header>会话参数</template>
      <el-row :gutter="8">
        <el-col :span="8">
          <el-input v-model="sessionId" placeholder="session_id (private:webui_admin)" />
        </el-col>
        <el-col :span="8">
          <el-input v-model="userId" placeholder="user_id (webui_admin)" />
        </el-col>
        <el-col :span="8">
          <el-input v-model="groupId" placeholder="group_id (可选，群聊测试)" />
        </el-col>
      </el-row>
      <div style="margin-top: 10px; display: flex; align-items: center; gap: 8px">
        <el-tag :type="connected ? 'success' : 'info'">
          {{ connected ? 'WebSocket 已连接' : 'WebSocket 未连接（将走 HTTP）' }}
        </el-tag>
        <el-button size="small" @click="toggleConnection">
          {{ connected ? '断开连接' : '连接 WebSocket' }}
        </el-button>
        <el-button size="small" @click="clearMessages">清空对话</el-button>
      </div>
    </el-card>

    <el-card>
      <template #header>对话面板</template>
      <div class="chat-box">
        <div v-for="item in messages" :key="item.id" class="chat-item">
          <el-tag size="small" :type="item.role === 'assistant' ? 'success' : item.role === 'error' ? 'danger' : 'info'">
            {{ item.role === 'assistant' ? 'Mika' : item.role === 'error' ? '错误' : 'You' }}
          </el-tag>
          <span class="chat-time">{{ item.time }}</span>
          <div class="chat-text">{{ item.text }}</div>
        </div>
      </div>
      <div style="display: flex; gap: 8px; margin-top: 10px">
        <el-input
          v-model="inputText"
          placeholder="输入测试消息，按 Enter 发送"
          @keyup.enter="send"
        />
        <el-button type="primary" :loading="sending" @click="send">发送</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onBeforeUnmount, ref } from 'vue'
import { buildLiveChatWsUrl, sendLiveChatMessage } from '../api/client'

interface ChatLine {
  id: string
  role: 'user' | 'assistant' | 'error'
  text: string
  time: string
}

const sessionId = ref('private:webui_admin')
const userId = ref('webui_admin')
const groupId = ref('')
const inputText = ref('')
const sending = ref(false)
const connected = ref(false)
const messages = ref<ChatLine[]>([])
const ws = ref<WebSocket | null>(null)

const nowText = () => new Date().toLocaleTimeString()

const appendMessage = (role: ChatLine['role'], text: string) => {
  messages.value.push({
    id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    role,
    text,
    time: nowText(),
  })
}

const clearMessages = () => {
  messages.value = []
}

const closeSocket = () => {
  if (ws.value) {
    ws.value.close()
    ws.value = null
  }
  connected.value = false
}

const connectSocket = () => {
  closeSocket()
  const socket = new WebSocket(buildLiveChatWsUrl())
  socket.onopen = () => {
    connected.value = true
    ElMessage.success('WebSocket 已连接')
  }
  socket.onmessage = (event) => {
    try {
      const payload = JSON.parse(String(event.data || '{}'))
      if (payload.type === 'reply') {
        appendMessage('assistant', String(payload.reply || ''))
        return
      }
      if (payload.type === 'error') {
        appendMessage('error', String(payload.message || 'unknown error'))
      }
    } catch {
      appendMessage('error', '收到无法解析的消息')
    }
  }
  socket.onerror = () => {
    appendMessage('error', 'WebSocket 连接失败，已回退 HTTP 模式')
  }
  socket.onclose = () => {
    connected.value = false
    ws.value = null
  }
  ws.value = socket
}

const toggleConnection = () => {
  if (connected.value) {
    closeSocket()
    ElMessage.info('WebSocket 已断开')
    return
  }
  connectSocket()
}

const send = async () => {
  const text = inputText.value.trim()
  if (!text) {
    return
  }
  appendMessage('user', text)
  inputText.value = ''

  if (connected.value && ws.value) {
    ws.value.send(
      JSON.stringify({
        request_id: `req-${Date.now()}`,
        message: text,
        session_id: sessionId.value.trim() || 'private:webui_admin',
        user_id: userId.value.trim() || 'webui_admin',
        group_id: groupId.value.trim(),
      }),
    )
    return
  }

  sending.value = true
  try {
    const result = await sendLiveChatMessage(
      text,
      sessionId.value.trim() || 'private:webui_admin',
      userId.value.trim() || 'webui_admin',
      groupId.value.trim(),
    )
    appendMessage('assistant', result.reply || '')
  } catch (error) {
    appendMessage('error', String(error))
  } finally {
    sending.value = false
  }
}

onBeforeUnmount(() => {
  closeSocket()
})
</script>

<style scoped>
.chat-box {
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  min-height: 360px;
  max-height: 520px;
  overflow-y: auto;
  padding: 10px;
  background: #fafafa;
}

.chat-item {
  margin-bottom: 8px;
}

.chat-time {
  margin-left: 8px;
  font-size: 12px;
  color: #909399;
}

.chat-text {
  margin-top: 4px;
  white-space: pre-wrap;
  line-height: 1.5;
}
</style>
