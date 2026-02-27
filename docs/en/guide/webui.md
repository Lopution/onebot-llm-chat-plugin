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

## Quick setup wizard (recommended)

At the top of the Config page, WebUI provides a **Quick setup wizard** to get you running in 2-3 steps:

1. LLM: `LLM_PROVIDER / LLM_BASE_URL / LLM_API_KEY (or list) / LLM_MODEL / LLM_FAST_MODEL`
2. Identity: `MIKA_MASTER_ID / MIKA_MASTER_NAME / MIKA_BOT_DISPLAY_NAME`
3. Optional: Search `SEARCH_PROVIDER / SEARCH_API_KEY`
4. Optional: WebUI token `MIKA_WEBUI_TOKEN`

After saving, a restart is usually required for changes to fully take effect.

## Basic/Advanced and search

On the Config page:

- Use the Basic/Advanced toggle to hide rarely-used settings by default.
- Use the search box to filter settings by `key / description / hint / ENV KEY`.

Each field shows its `ENV KEY` and default value (the default is shown via tooltip and never leaks secrets).

## Effective config snapshot

WebUI can show an **effective config snapshot** (defaults + derived values + warnings), useful for debugging and issue reports.

## Which env file does WebUI read/write?

WebUI selects the env file with this precedence:

1. If `DOTENV_PATH` is set: read/write that file.
2. Else if `ENVIRONMENT=prod` and `.env.prod` exists: read/write `.env.prod`.
3. Else: read/write `.env`.

Deployment tip:
- If you run with `.env.prod`, set `DOTENV_PATH=/path/to/.env.prod` in your startup script/service to avoid editing the wrong file from WebUI.
