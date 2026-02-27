# Upgrade Guide (Breaking Changes)

## Legacy env keys are removed (fail-fast)

These legacy keys are removed; if present, startup will fail:

| Legacy | New |
|--------|-----|
| `MIKA_API_KEY` | `LLM_API_KEY` |
| `MIKA_API_KEY_LIST` | `LLM_API_KEY_LIST` |
| `MIKA_BASE_URL` | `LLM_BASE_URL` |
| `MIKA_MODEL` | `LLM_MODEL` |
| `MIKA_FAST_MODEL` | `LLM_FAST_MODEL` |
| `SERPER_API_KEY` | `SEARCH_API_KEY` |
| `MIKA_HISTORY_IMAGE_ENABLE_COLLAGE` | `MIKA_HISTORY_COLLAGE_ENABLED` |

Recommended migration:
1. Recreate `.env` from `.env.example`
2. Fill the minimum required keys: `LLM_API_KEY` + `MIKA_MASTER_ID`
3. Run:

```bash
python3 scripts/doctor.py
```

