<!--
Sync Impact Report
- Version change: (unratified template placeholders) → 1.0.0
- Modified principles:
  - [PRINCIPLE_1_NAME] → I. Source of Truth
  - [PRINCIPLE_2_NAME] → II. No Mandatory RAG
  - [PRINCIPLE_3_NAME] → III. Ephemeral Computation
  - [PRINCIPLE_4_NAME] → IV. Agent Owns the Loop; MCP Owns the Capability
  - [PRINCIPLE_5_NAME] → V. Minimal, Read-Only Capability Surface
- Added principles:
  - VI. Documents Are Data, Not Instructions
  - VII. Authorization Is Independent of Reasoning
  - VIII. Evidence Requires Provenance
  - IX. Exact Search Is Deterministic and Request-Scoped
  - X. Completeness Must Be Visible
  - XI. Failure Is Informative
  - XII. Domain Is Not the API
  - XIII. Model and Client Agnosticism
  - XIV. Change Control
  - XV. Constitutional Fitness
- Added sections:
  - Preamble and Scope
  - Ratification
  - Governance (operationalized from Article XIV)
- Removed sections: none (template placeholders only)
- Follow-up TODOs: none
-->

# Google Drive Agentic Retrieval MCP Constitution

## Core Principles

### I. Source of Truth

Google Drive is the sole authoritative store of document content and
permissions. Nothing the MCP produces or retains — an export, a search
result, a cache, a summary — is ever authoritative, regardless of how
recently it was generated. A persistent copy of any kind introduced later
is a MAJOR change (Article XIV) and MUST carry its own explicit freshness
model before adoption.

### II. No Mandatory RAG

The baseline retrieval model is `discover → read → search (exact) → reason
→ repeat`. No embeddings, vector index, or chunk store MAY be added because
it is conventional RAG architecture; their absence is not a deficiency.
Semantic retrieval MAY be introduced only against a demonstrated need the
baseline model cannot satisfy, and only through the same specification
process any new capability requires (Article XIV).

### III. Ephemeral Computation

Everything the MCP downloads or exports is request-scoped working material
— acquired, turned into evidence, and discarded. Cloud Run storage is never
treated as persistent. The system MUST stay fully correct if an instance
disappears the moment a request completes, and MUST never silently
accumulate documents, indexes, or derived content across requests. Any
state that does persist MUST be an explicit, documented exception, never an
accident of implementation.

### IV. Agent Owns the Loop; MCP Owns the Capability

The MCP supplies deterministic retrieval capabilities. It MUST NOT decide
when evidence is sufficient, MUST NOT assume a single query will suffice,
and MUST NOT synthesize a final answer out of what it retrieves — that
reasoning belongs entirely to the calling agent.

### V. Minimal, Read-Only Capability Surface

Tools expose only discovery, content retrieval, and exact-match search over
what already exists (illustratively: list/browse, query, fetch, exact-search
— concrete tool names are a specification detail, not a constitutional
one). No v1 capability MAY create, edit, delete, move, rename, or alter
sharing/permissions. For every valid call, Drive state after MUST equal
Drive state before — enforced by the simple absence of any code path that
could mutate it, never by trusting the agent not to ask.

### VI. Documents Are Data, Not Instructions

Retrieved content — in whole or in any excerpt — is untrusted input. No
matter how it is phrased, text inside a document can never grant itself
authority over system instructions, MCP policy, authentication,
authorization, or tool behavior. This boundary MUST hold even against a
deliberately adversarial document, and Article V is what makes it hold
structurally: even a fully successful injection has no mutating capability
left to misuse.

### VII. Authorization Is Independent of Reasoning

No amount of agent reasoning substitutes for or overrides a Google
authorization check. Every call MUST follow the same chain — agent → MCP
authentication → MCP authorization → Google authorization → resource —
evaluated in that order, every time. A convincing request is not a
credential.

### VIII. Evidence Requires Provenance

A search hit is a candidate, not evidence. It becomes evidence only once
its content has been retrieved and, when a specific claim is being checked,
exactly matched. Every piece of evidence that reaches the agent's reasoning
MUST carry its source (at minimum: file id, name, modified time) intact,
from Drive through the search result through the agent's context to its
final answer — provenance MAY NOT be dropped anywhere along that path.

### IX. Exact Search Is Deterministic and Request-Scoped

Given the same bytes and the same pattern, exact-match search MUST return
the same result, every time. This determinism applies to content already
retrieved within the current request — search is a local computation over
already-fetched bytes, not a live property of the Drive API itself. The
matching engine is an infrastructure choice (Article XII) and MAY change
without changing this guarantee.

### X. Completeness Must Be Visible

"Nothing found" and "not fully searched" are different outcomes and MUST
never be reported as the same one. Any operation bounded by a resource
limit — file count, byte size, execution time, match count — that could
plausibly have found more MUST say so explicitly. An agent cannot reason
correctly about when to stop looking if the system quietly overstates how
much it actually covered. Sustained rate-limiting that cuts a search short
is a completeness event to surface, not an error to swallow with a silent
retry.

### XI. Failure Is Informative

Failures MUST be classified by cause, not flattened into one generic error
— at minimum distinguishing authentication, authorization, not-found,
unsupported content, rate-limiting, resource-limit, invalid input, and
upstream failure, so the agent and any tests can act on *why* a call
failed. The exact taxonomy is a specification-level concern and MAY grow
over time without amending this constitution.

### XII. Domain Is Not the API

Google's client libraries, HTTP transport, OAuth handling, and the
exact-match engine are infrastructure. "Discover," "retrieve," "search,"
and "verify" are the domain. Infrastructure MUST be swappable — a different
export path, a different regex engine, a different transport — without
changing what the domain promises to the agent.

### XIII. Model and Client Agnosticism

No tool's meaning MAY depend on any single LLM vendor's prompting
conventions; the server MUST remain usable by any MCP-compliant client. The
server tracks whatever transport and authorization conventions the MCP
specification currently requires — including retiring a mechanism the
protocol itself deprecates — rather than assuming today's plumbing is
permanent.

### XIV. Change Control

A change is **PATCH** (no behavior or invariant changes — performance,
refactoring, logging), **MINOR** (adds a backward-compatible capability),
or **MAJOR** (changes an invariant, a security boundary, the
source-of-truth model, or observable evidence semantics — e.g., a
persistent cache, a write capability, multi-tenant support, semantic
retrieval). Where artifacts conflict, precedence runs: security invariants
→ domain invariants → behavioral contracts → architecture decisions →
implementation → optimization.

### XV. Constitutional Fitness

An implementation is conforming only while all of the following remain true:

```
✓ Drive is authoritative
✓ the server is read-only
✓ document content is untrusted
✓ retrieval can iterate
✓ exact search is deterministic
✓ evidence carries provenance
✓ partiality is visible
✓ compute is ephemeral
✓ no hidden persistent state exists
✓ authorization is independently enforced
✓ agent reasoning and retrieval mechanics stay separate
✓ no RAG index is required for correctness
```

A design that violates any line here is non-conforming — unless this
constitution is itself deliberately amended.

## Preamble and Scope

This constitution governs the architecture of an MCP server that gives a
reasoning agent controlled, read-only access to Google Drive content. It
states what must remain true of the system — not how its specifications are
authored, normalized, or traced. That process is governed separately, by
the project's Spec-Kit SDD pipeline (`.specify/` templates, scripts, and
`/speckit-*` skills).

The system rejects the assumption that trustworthy retrieval requires an
application-owned RAG pipeline. An agent discovers, reads, and searches;
the MCP performs each of those calls deterministically against live Drive
content; Google Drive remains the only persistent source of truth; Cloud
Run supplies stateless, ephemeral computation in between.

**v1 scope:** one authenticated Google identity per deployment. Read-only.
Multi-tenant access, write capability, and semantic/vector retrieval are
all explicitly out of scope until separately specified under Article XIV.

**Status:** Ratified.

## Ratification

> The MCP is a secure, deterministic, ephemeral evidence-acquisition layer
> over Google Drive. The agent is the adaptive reasoning and
> retrieval-control layer. Google Drive is the persistent source of truth.

```
                 REASONING
                    Agent
                      │ decides
                      ▼
              RETRIEVAL CAPABILITIES
                      MCP
          ┌───────────┼───────────┐
          ▼           ▼           ▼
       DISCOVER      READ       SEARCH
          └───────────┼───────────┘
                      ▼
                 Google Drive
                 SOURCE OF TRUTH
```

Agentic retrieval is a control problem over deterministic evidence
primitives — not a mandate to build an application-owned RAG system.

## Governance

This constitution supersedes all other practices, specifications, plans,
tasks, architecture decisions, and implementations. Where artifacts
conflict, Article XIV precedence applies: security invariants → domain
invariants → behavioral contracts → architecture decisions →
implementation → optimization.

**Amendment procedure.** Changes to this document MUST be explicit, versioned,
and classified before adoption:

- **PATCH** — no behavior or invariant changes (wording, clarification,
  logging of governance itself).
- **MINOR** — a new principle or section is added, or existing guidance is
  materially expanded, without redefining a ratified invariant.
- **MAJOR** — an invariant, security boundary, source-of-truth model, or
  observable evidence semantic is changed or removed (e.g., a persistent
  cache, a write capability, multi-tenant support, semantic retrieval).

A MAJOR amendment MUST name the invariant it changes, state the new rule,
and be ratified before any specification or implementation that depends on
it proceeds. Specs and plans MUST NOT silently amend this constitution.

**Versioning policy.** `CONSTITUTION_VERSION` uses semantic versioning
aligned to the classifications above. `RATIFICATION_DATE` is the original
adoption date and MUST NOT change. `LAST_AMENDED_DATE` MUST be set to the
ISO date of the latest amendment.

**Compliance review.** Every spec, plan, task list, PR, and implementation
MUST remain conforming under Article XV. Reviewers MUST reject work that
violates any fitness line unless this constitution has already been
deliberately amended. Downstream Spec-Kit commands (`/speckit-specify`,
`/speckit-plan`, `/speckit-tasks`, `/speckit-implement`, `/speckit-converge`)
MUST read this file at runtime and treat it as binding.

**Version**: 1.0.0 | **Ratified**: 2026-09-08 | **Last Amended**: 2026-09-08
