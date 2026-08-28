# Context Skills

Choose manually; this MVP does not auto-classify a task or transfer a task between
the two skills.

| Choose | Use it for | Local copy path |
| --- | --- | --- |
| Lite | One primary agent, low-risk multi-turn recovery, and a compact Markdown checkpoint. | `skills/context-lite/` |
| Strict | Multi-agent work, external side effects, auditability, frozen acceptance, or independent validation. | Repository root: `./` (entry: `./SKILL.md`) |

Read the [v1.1 design specification](docs/specs/context-skills-v1.1.md) for the
full boundary. `context-lite` is standalone Markdown; the existing root Strict skill
and its Python runtime remain separate. Transfer is not implemented in this MVP.
