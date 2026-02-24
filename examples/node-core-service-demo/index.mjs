const baseUrl = process.env.CORE_URL || "http://127.0.0.1:8080";
const token = process.env.CORE_TOKEN || "";

const payload = {
  envelope: {
    schema_version: 1,
    session_id: "group:demo",
    platform: "demo_node",
    protocol: "http",
    message_id: "node-demo-1",
    timestamp: Date.now() / 1000,
    author: {
      id: "node-user",
      nickname: "node-demo",
      role: "member",
    },
    content_parts: [{ kind: "text", text: "hello from node demo" }],
    meta: {
      intent: "group",
      group_id: "demo",
      user_id: "node-user",
    },
  },
  dispatch: false,
};

const headers = {
  "Content-Type": "application/json",
};
if (token) {
  headers.Authorization = `Bearer ${token}`;
}

const response = await fetch(`${baseUrl.replace(/\/+$/, "")}/v1/events`, {
  method: "POST",
  headers,
  body: JSON.stringify(payload),
});

const body = await response.json().catch(() => ({}));
console.log("status:", response.status);
console.log(JSON.stringify(body, null, 2));
