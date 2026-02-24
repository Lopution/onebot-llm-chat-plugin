import { onBeforeUnmount, ref } from 'vue'

interface ChatLine {
  id: string
  role: 'user' | 'assistant' | 'error'
  text: string
  time: string
}

export function useLiveChatConnection() {
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

  const connectSocket = (wsUrl: string) => {
    closeSocket()
    const socket = new WebSocket(wsUrl)
    socket.onopen = () => {
      connected.value = true
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

  const sendViaSocket = (payload: Record<string, unknown>): boolean => {
    if (connected.value && ws.value) {
      ws.value.send(JSON.stringify(payload))
      return true
    }
    return false
  }

  onBeforeUnmount(() => {
    closeSocket()
  })

  return {
    connected,
    messages,
    appendMessage,
    clearMessages,
    closeSocket,
    connectSocket,
    sendViaSocket,
  }
}

export type { ChatLine }
