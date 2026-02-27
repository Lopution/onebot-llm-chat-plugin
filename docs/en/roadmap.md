# Roadmap (Summary)

This is a reader-oriented summary. For the full Chinese roadmap, see `docs/roadmap.md`.

## Direction

- Keep a single core codebase that works well for personal daily use and is also suitable for open source.
- Prefer incremental refactors with clear rollback points.
- Treat the dev repo as the source of truth; deployment repo is for real runtime validation.

## Near-term focus

- Multimodal context association (align with AstrBot-style UX)
- Stability first: self-heal for empty replies / oversize requests
- Observability: per-request trace that answers "why it behaved differently this time"

