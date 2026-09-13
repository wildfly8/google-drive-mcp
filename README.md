# Google Drive Agentic Retrieval MCP

Read-only agentic retrieval over Google Drive and Google Docs/Sheets/Slides,
served by a stateless MCP on Cloud Run, for any MCP-compatible reasoning agent.

This repository is developed with [Spec-Kit](https://github.com/github/spec-kit)
spec-driven development. Governing principles live in
[`.specify/memory/constitution.md`](.specify/memory/constitution.md) and bind
every subsequent spec, plan, task list, and implementation.

## Constitution (ratified v1.0.0)

Google Drive is the sole source of truth. The MCP is a secure, deterministic,
ephemeral evidence-acquisition layer. The calling agent owns reasoning and the
retrieval loop. v1 is read-only, single Google identity per deployment, and
does not require an application-owned RAG index.

See the constitution for the full invariant set (Articles I–XV).

## Connecting ChatGPT / Claude / Cursor

This is standard **MCP Streamable HTTP** (`POST /mcp`). The host model — not this server — parses the user question and chooses `drive_ls` / `drive_find` / `drive_read` / `drive_grep` arguments. `tools/list` advertises when to use each tool and positive/negative examples.

**Auth:** send `Authorization: Bearer <MCP_AUTH_TOKEN>`. That is a static MCP caller secret. It is not Google OAuth and not [MCP OAuth 2.1](https://modelcontextprotocol.io/specification/2025-03-26/basic/authorization) (no authorization-code login on this origin).

| Host | How to attach this server |
| --- | --- |
| **Cursor** (Cloud Agent / HTTP MCP) | Server URL + encrypted `Authorization: Bearer` header. Repo allow-list in `.cursor/environment.json` is not the same as installing the header. |
| **Claude Code** | `claude mcp add --transport http google-drive-mcp <url>/mcp --header "Authorization: Bearer <token>"` |
| **ChatGPT Desktop / Codex** | Streamable HTTP `url` plus `bearer_token_env_var` pointing at an env var that holds `MCP_AUTH_TOKEN` |
| **claude.ai / ChatGPT web custom connectors** | Only if that UI can send a static Bearer (request headers). Connectors that require an OAuth redirect against this Cloud Run URL will fail until MCP OAuth is specified (MAJOR, Article XIV). |

Do not put the token in the MCP URL or in tool arguments.

## Spec-Driven Development

Cursor skills are installed under `.cursor/skills/`. Use them in this order:

0. `/speckit-constitution` — project principles (done: v1.0.0)
1. `/speckit-specify` — what to build (done: access control + retrieval core)
2. `/speckit-clarify` — optional; de-risk underspecified areas (done: session 2026-09-08)
3. `/speckit-plan` — how to build it (done: access control + retrieval core)
4. `/speckit-tasks` — actionable implementation tasks (done: both features)
5. `/speckit-analyze` — optional; cross-artifact consistency (done: 2026-09-08; remediations and plan sync applied)
6. `/speckit-implement` — execute the tasks
7. `/speckit-converge` — compare the codebase to spec/plan/tasks and append remaining work

Feature specs (ready for implementation):

- [Access Control Boundary](specs/001-access-control/spec.md) — who may act, and on what authority
- [Retrieval Core](specs/002-retrieval-core/spec.md) — discover, read, exact-search once a call is cleared

Repeat implement and converge until converge reports **Converged**.

The Specify CLI (`specify-cli` 1.0.4) initialized this project with the
`cursor-agent` integration and bash scripts. Refresh managed files with
`specify integration upgrade` after upgrading the CLI.

Shared pickup state for the next Cloud Agent:

- `.specify/memory/project-status.md` — current SDD phase
- `.cursor/rules/spec-kit-sdd.mdc` — always-on constitution and next-step rules
- `.cursor/environment.json` — installs `uv` and `specify-cli` on Cloud Agent boot

## Out of v1 scope

Multi-tenant access, write capability, persistent caches, and
semantic/vector retrieval are MAJOR constitutional changes (Article XIV)
and MUST be specified before any implementation work.
