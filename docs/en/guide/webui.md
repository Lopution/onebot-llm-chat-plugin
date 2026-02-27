# WebUI

WebUI provides a GUI for configuration, logs, status, and maintenance tasks.

## Enable WebUI

In your `.env` / `.env.prod`:

```env
MIKA_WEBUI_ENABLED=true
# empty = loopback only; set a token for remote access
MIKA_WEBUI_TOKEN="CHANGE_ME"
MIKA_WEBUI_BASE_PATH="/webui"
```

Notes:
- If `MIKA_WEBUI_TOKEN` is empty, only loopback clients (`127.0.0.1/localhost`) can access WebUI.
- For remote access, use a strong random token and prefer HTTPS via reverse proxy.

## Default URL

With `HOST=0.0.0.0`, `PORT=8080`, `MIKA_WEBUI_BASE_PATH=/webui`:

- `http://127.0.0.1:8080/webui/`

## Effective config snapshot

WebUI can show an **effective config snapshot** (defaults + derived values + warnings), useful for debugging and issue reports.

