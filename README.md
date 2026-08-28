# Context Skills

Choose manually; this MVP does not auto-classify a task or transfer a task between
the two skills.

| Choose | Use it for | Local copy path |
| --- | --- | --- |
| Lite | One primary agent, low-risk multi-turn recovery, and a compact Markdown checkpoint. | `skills/context-lite/` |
| Strict | Multi-agent work, external side effects, auditability, frozen acceptance, or independent validation. | `skills/context-strict/` |

Read the [v1.1 design specification](docs/specs/context-skills-v1.1.md) for the
full boundary. Both skills are independently installable. The root Strict sources
remain the compatibility and development source during migration; run
`python3 scripts/sync_context_strict_skill.py` before validating or publishing the
`skills/context-strict/` distribution. Transfer is not implemented in this MVP.
