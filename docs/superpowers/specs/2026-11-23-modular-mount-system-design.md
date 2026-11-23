# Modular Mount System — Design

Date: 2026-23-11
Status: awaiting approval
Depends on: ease-of-install phase (wave-1 merged; wave-2 bootstrap/README merges after v0.2.0 is published — this design assumes both have landed by implementation time).

## Intent and the why

A home server should be a **platform for purposes**, not a pile of twenty
idle services. The user's vision, in their own words: while the server is
a Minecraft server, the Minecraft **module** can be **dismounted** — its
state (world data, answers, configuration) frozen and preserved — and a
new module **mounted** in its place. One machine, maximum utility, no
wasted services, nothing lost when a purpose is paused. And the module
catalog grows by **community contribution**: a good module is two
well-formed YAML files.

Prior-art research (Nov 2026): the additive app-store platforms (CasaOS,
Runtipi, Cosmos, Umbrel, YunoHost) install many services side by side and
leave them running; the Ansible homelab deployers (HomelabOS, ansible-nas,
mash-playbook) do the same declaratively. Nobody offers
mount/dismount-with-preserved-state. That is this project's identity.

## Goals

1. **Trustworthy transitions.** The engine that stops, swaps, and starts
   stacks must be safe: atomic locking, real rollback, interruption
   recovery. (Today: racy read-modify-write lock, rollback that is a
   single best-effort `up -d`, no Ctrl-C recovery — audit findings.)
2. **Mount/dismount vocabulary and multi-mount.** `platypus mount <m>`,
   `platypus dismount <m>`; more than one module may be mounted at once,
   guarded by declared port claims and mount-time conflict detection.
   "Main vs companion" is a recommendation label, not an engine limit.
3. **Contribution-friendly modules.** A documented module spec, a
   scaffolding command, and CI checks so strangers can contribute modules
   confidently.
4. **Community project scaffolding.** CONTRIBUTING, CHANGELOG, SECURITY
   policy — the standard gates for a public project that wants
   contributors.

## Non-goals

- Becoming an app-store platform: no web catalog, no web UI for mounting.
  The project stays CLI-first; the dashboard is not redesigned — keeping
  its module-state reader **correct** under state v2 is maintenance that
  phase 2 explicitly includes (no redesign, no new dashboard features).
- Multi-host / cluster management.
- Dashboard redesign or its security overhaul (separately scheduled).
- Touching the Ansible layer or the bootstrap flow.
- Renaming runtime data directories (`/opt/platypus/roles/<name>/` keeps
  its path; user data is never moved by a rename).

## Approaches considered

1. **Single active module only** (today's model sharpened): simplest and
   conflict-free, but it cannot express "Pi-hole always mounted, plus a
   heavy purpose right now" — the vision explicitly wants one server to
   serve multiple purposes. Rejected.
2. **Full mounted-set engine in one step:** the honest end state, but it
   would be built on today's unsafe transition engine and land as one
   large, hard-to-review change. Rejected as a first step.
3. **Phased build (chosen):** trust foundation first, then the
   mount/dismount world, then community mechanics. Each phase ships
   working, testable software and the phases can be merged independently.

## Design

### Phase 1 — Trustworthy transition engine

- **Atomic lock.** An `O_EXCL` lock file at
  `/opt/platypus/transition.lock` (pid, target, started_at) replaces the
  read-modify-write of `state.yml`. Stale detection: PID liveness plus a
  maximum age; a stale lock is reported and recoverable via
  `--force-unlock`.
- **Interruption recovery.** `KeyboardInterrupt`/`BaseException` and
  `SIGTERM` release the lock and attempt the same rollback path as an
   engine error; a crash leaves the lock, and the next run detects it,
   reports the last known state, and offers recovery.
- **Real rollback.** Rollback now: `compose down` the partially started
   new stack, restore the previous Caddy route state, re-`up` the old
   stack, and run the module's optional new `rollback:` hooks with the
   module's answers (e.g. undo Nextcloud's `maintenance:mode --on`).
   Authored `rollback:` hooks are added only where a module needs
   explicit undo — initially just Nextcloud; other modules' stacks are
   fully undone by the engine's own down/up steps.
- **Release shape.** Phase 1 ships as **0.2.1** (pure bugfixes to the
   transition engine: safe to release independently, before any
   mount/vocabulary change); phase 2 is the **0.3.0** release; phase 3
   rides 0.3.x. `CHANGELOG.md` therefore starts with the 0.2.0 entry,
   not 0.3.0.
- **State and answer durability.** `state.yml` writes gain fsync and a
   one-generation backup; answers are saved only after a successful
   mount, not on failure (today a failed first mount freezes a typo
   forever — audit finding).
- **Engine test suite.** Unit tests for lock acquisition/staleness,
   rollback composition, interruption, and state migration — the
   audit's "zero tests on the most destructive code" gap closes here.

### Phase 2 — The mount/dismount world

- **Vocabulary.** User-facing language becomes **module**,
  **mount/dismount**. Commands and semantics:
  - `platypus mount <module>` — additive: validates claims against the
    mounted set, then starts exactly this module. Existing mounted
    modules keep running.
  - `platypus dismount <module>` — stops and freezes exactly one module.
  - `platypus switch <module>` — **pure alias of `mount`, deprecated
    spelling.** It is additive like `mount` and no longer implies
    replacing anything (the old replace behavior is simply
    `dismount <old>` followed by `mount <new>`); docs mark it as the
    legacy name for `mount`.
  - `platypus status` — mounted set, dormant modules (frozen, with data
    sizes), history.
  - `platypus reconfigure <module>` — a first-class engine operation:
    for a **mounted** module it re-runs the question form, validates the
    new answers (including conflict re-check against the *other* mounted
    modules), re-renders the compose file, recreates the stack and its
    Caddy section through the locked transition path; for a **dormant**
    module it only rewrites `answers.yml` atomically (applied at the
    next mount).
  - `platypus module init <name>` (phase 3).
  - The old `platypus-server` alias keeps its surface; docs drop the
    "role" wording.
- **Declared claims.** `template.yml` gains a structured section:
  `ports:` (host ports this module binds), `weight: main|companion`
  (recommendation label only). Every existing module is migrated with
  its claims; the four broken Caddy routes from the audit (container
  hostnames a host Caddy cannot resolve) are fixed to
  `localhost:{answers[...]}` host-port routes in the same migration.
- **Enforced validation.** `questions.yml`'s currently-dead `validate`
  field is enforced at two points: at question time (interactive input)
  and at mount time against the **effective answer set** (saved answers,
  whether from an earlier session or a hand edit). A mount with invalid
  answers is refused *before anything is stopped*, with a pointer to
  `platypus reconfigure <module>`. "Existing installs keep working"
  means migrations and layouts stay compatible — not that a broken
  saved answer silently starts a broken stack.
- **Conflict detection.** `mount` computes the new module's claims
  against the mounted set: overlapping host port → refuse with an
  actionable message and a pointer to
  `platypus reconfigure <module>` to pick another port. Port claims may
  carry a protocol suffix (`53/udp`, `21027/udp`) matching compose's own
  syntax; two modules clash only on same-port-same-protocol.
- **Enforced validation.** `questions.yml`'s currently-dead `validate`
  field is enforced (integer ranges, regex) at question time — bad ports
  and out-of-range values are rejected before anything is stopped.
- **Mounted-set state.** `state.yml` migrates to schema v2:
  `mounted: [names]` (from v1: `active` becomes a one-element mounted
  list; automatic, with a backup of the old file). Dismount stops and
  freezes exactly one module; mount starts exactly one; the managed
  Caddy snippet gains/loses that module's section only. The dashboard's
  module-state reader (`dashboard/app.py` recipe endpoint) is updated in
  this phase to read `mounted` with a v1 fallback — correctness
  maintenance, not a redesign; no legacy mirror key is kept in the file.
- **Source directory naming.** The packaged templates move
  `recipe/roles/` → `recipe/modules/` so contributor-facing paths match
  the vocabulary. Runtime dirs keep their paths (compat).

### Phase 3 — Community mechanics

- **Module authoring spec** (`docs/modules.md`): required keys
  (`name`, `version`, `description`, `ports`, `weight`, `questions`,
  `compose_template`, optional `caddy`, `shutdown`, hooks), the claim
  rules, and a worked example.
- **`platypus module init <name>`**: scaffolds `template.yml` +
  `questions.yml` with commented placeholders that already pass the
  checks.
- **CI module checks.** A job step validates every
  `recipe/modules/*/` pair: YAML parses, required keys present,
  question ids unique, `validate` fields well-formed, declared `ports`
  cover every port the compose template publishes, `weight` value
  legal. A failing community module fails CI before review.
- **Project scaffolding.** `CONTRIBUTING.md` (how to add a module, how
  the checks run), `CHANGELOG.md` (starting with the 0.2.0 entry),
  `SECURITY.md` (report path; notes the known phase-2 dashboard
  limitations honestly).

## Constraints

- Existing installs keep working: runtime layout and answers unchanged;
  `state.yml` migrates automatically; every old command alias still runs.
- Python 3.10+, pipx install, CI green on all existing jobs.
- Ansible layer and bootstrap untouched.
- Version 0.3.0 for the mount system release.

## Prerequisites on the author (human steps)

- v0.2.0 published and wave-2 (bootstrap + README) merged, as already
  scheduled — the mount-system branch builds **on top of wave-2** (its
  README is the surface phase 2 rewrites), so this is a hard
  precondition for implementation, not just rollout.
- Optionally enable GitHub Discussions and add an issue template for
  module proposals when phase 3 lands.

## What's left to the builder

- Lock file exact naming/age threshold; recovery message wording.
- `state.yml` v2 exact YAML shape and migration helper location.
- Conflict/refusal message wording and exit codes.
- The `validate` mini-language (range/regex) exact syntax.
- `module init` placeholder content.
- CI check implementation (regex vs parsed checks) within the pinned
  rule list.
- Companion/main classification of the seven existing modules beyond
  the ports facts (recommendation only).
