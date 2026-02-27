# Troubleshooting

## Startup fails with legacy keys

Symptoms:
- `ValidationError` mentions `MIKA_API_KEY` / `SERPER_API_KEY`

Cause:
- Legacy env keys are removed (fail-fast; no silent compatibility).

Fix:
- Remove legacy keys from `.env` / `.env.prod`, and use:
  - `LLM_API_KEY` / `LLM_API_KEY_LIST`
  - `SEARCH_API_KEY`

## WebUI 403 / 401

- 403: token is required for non-loopback access when `MIKA_WEBUI_TOKEN` is empty
- 401: invalid token

## HTTP 200 but empty reply

Common causes:
- upstream/gateway returns `content=null` with HTTP 200
- capability mismatch (tools/images not supported by the proxy)
- request body too large (multi-image + base64)

Suggested checks:
- try another model/provider to confirm
- force capability overrides if needed:
  - `MIKA_LLM_SUPPORTS_IMAGES=true/false`
  - `MIKA_LLM_SUPPORTS_TOOLS=true/false`

