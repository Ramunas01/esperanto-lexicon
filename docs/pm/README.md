# docs/pm — project-management workspace

Process/coordination docs for the Esperanto-lexicon project, kept separate from
the technical docs (`docs/*.md`) and from `CLAUDE.md` (the canonical source of
truth, which this never supersedes).

## Layout

| Path | What lives here |
|---|---|
| `briefs/` | Advisor→PM task briefs (input specs). One file per initiative. |
| `progress/` | **Living session-restore logs.** One per initiative; the crash-recovery record. |
| `programmer/` | Self-contained Programmer-agent hand-off briefs — only when a job needs a separate agent. |

## How we work

- **Design** happens in chat (human + Opus advisor). **Implementation** happens
  here via Claude Code, on a branch, through a PR — no merge without review.
- **Human review gates are real.** When a brief says STOP, the PM produces
  reviewable artifacts and halts; it never writes past the gate (e.g. never
  writes `lexicon_v2.db`, never changes an existing entry's
  `tier`/`word`/`cefr_level`/`source`) without an approved worksheet.
- **One initiative = one branch + one `progress/<name>.md`.** The progress log
  is updated at every phase boundary so a fresh session can resume from it
  alone.

## Session restore

If a session/terminal is lost, a new session recovers by:
1. Reading `progress/<initiative>.md` (status, what's done, "To resume" block).
2. Reading the matching `briefs/<initiative>.md` for the full spec.
3. Re-running the idempotent, no-DB-write steps listed under "To resume".

The PM also keeps a private memory index; the `progress/` logs are the in-repo,
human-visible mirror of that state.

## Execution model (WSL stability)

- The PM runs light, sequential work **foreground** — no backgrounded fan-out,
  no concurrent agents (that combination has crashed WSL under memory
  pressure).
- Genuinely heavy or parallel jobs get a written brief in `programmer/`, and the
  human launches a dedicated Programmer agent per job in its own shell.

## Active initiatives

- **common-gapfill** — turn the TinyStories `common_gap` queue into lexicon
  coverage through a human review gate, then re-measure the customs corpus.
  See [`progress/common-gapfill.md`](progress/common-gapfill.md).
