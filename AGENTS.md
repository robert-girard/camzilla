# Camzilla Agent Guide

## Purpose and sources of truth

Camzilla is a public, self-hosted camera viewer and edge object-detection project. Use the documentation according to its role:

1. [`doc/PRD-home-security-ai-alerts.md`](doc/PRD-home-security-ai-alerts.md) defines user outcomes, product scope, release tiers, feature requirements, non-goals, and product-level success criteria. Read it before changing what the product should do, moving a feature between releases, or interpreting acceptance intent. Update it when an accepted decision changes product scope or behavior.
2. [`doc/design-doc-home-security-ai-alerts.md`](doc/design-doc-home-security-ai-alerts.md) defines the current technical direction: deployment targets, component boundaries, streaming/inference data flow, concurrency, technology choices, and cross-cutting security constraints. Read it before changing architecture, dependencies, protocols, service boundaries, or deployment topology. Update it when a durable technical decision changes; use an ADR when alternatives and consequences deserve a standalone record.
3. [`doc/implementation-plan.md`](doc/implementation-plan.md) is the executable roadmap: phase order, task checklists, exclusions, test work, exit criteria, open decisions, and current status. Read it at the start of every implementation task, use it to constrain the active phase, and update its checkboxes/discoveries with the implementing change.
4. [`cam_info/README.md`](cam_info/README.md) contains sanitized facts about the first physical camera: environment variable names, ONVIF/RTSP behavior, profiles, codecs, PTZ limitations, GStreamer findings, and diagnostic helpers. Read it only when working on camera discovery, streaming, media handling, PTZ, or hardware smoke tests. It describes one device and must not become a general product contract or a CI dependency.

Explicit user direction takes precedence. The PRD governs product intent; the implementation plan governs accepted sequencing and completion; the design governs the current technical approach. These documents should agree. If implementation exposes a conflict, do not silently choose one: make the smallest consistent update to every affected document and note a material tradeoff in an ADR. Do not silently expand the active phase; record newly discovered work in the appropriate phase or deferred-work section.

Phase 1 will add a root `README.md` as the operational entry point. Once present, keep its dev/prod quick starts, configuration reference, test commands, security warnings, and troubleshooting steps synchronized with validated behavior. The README explains how to use the system; it does not replace the product, design, or planning sources above.

## Security and privacy

- Treat camera credentials, webhook URLs, tokens, LAN addresses, MAC addresses, captures, and information visible in frames as sensitive.
- Never print, log, commit, paste into tests, or expose through an API an authenticated RTSP URL or secret value.
- Do not read or display `.env` contents. Use documented variable names and `.env.example`; presence/validation checks must redact values.
- Use neutral examples such as `camera.local`, `192.0.2.10`, and `front-door`. Keep real deployment configuration in ignored local files or external secrets.
- Never commit real snapshots, recordings, model calibration images taken in the home, generated `go2rtc` configuration containing credentials, or database contents.
- Bind services to loopback by default during the no-auth phases. LAN exposure must be an explicit configuration choice. Never expose the `go2rtc` administrative API directly.
- Ensure exception messages, health endpoints, metrics, browser payloads, and CI artifacts cannot contain credentials or camera URLs.
- Do not rewrite Git history, force-push, rotate credentials, move the camera, or send real notifications without explicit user approval.

## Architecture guardrails

- Keep camera, inference-backend, and notifier contracts independent of vendor SDKs.
- In Phase 1, `go2rtc` owns the upstream RTSP connection and provides local restreams to the browser and inference pipeline.
- Use bounded queues and a latest-frame-wins policy for inference. Do not allow unbounded frame backlogs.
- Do not rely on `fork` for loaded ML/NPU runtimes. Prefer service/process isolation and explicit startup; validate RKNN lifecycle behavior on the Orange Pi.
- Detection coordinates crossing the API boundary are normalized to the source image and include source dimensions, capture/result timestamps, model identity, and backend identity.
- Keep secrets out of persisted application configuration. Persist only secret references when persistence is introduced.
- Ultralytics is accepted for the MVP under AGPL-3.0. Preserve the inference interface so a differently licensed backend can be substituted later. Record the provenance and license of every model and dataset.

## Development and testing

- The intended local inner loop is Docker Compose development mode with source synchronization: Vite HMR for the frontend and FastAPI/Uvicorn reload for the backend. Dependency or container-definition changes require rebuilds.
- Production Compose uses immutable images, no source mounts, no reloaders, explicit health checks, and architecture-specific inference images/dependencies.
- Unit and integration tests must not require the physical camera. Use synthetic frames, a redistributable recorded fixture, and fake camera/inference/notifier adapters.
- Hardware tests are opt-in and must skip cleanly when the camera, GPU, or NPU is unavailable.
- Frontend browser flows use Playwright against deterministic fixtures. Use the repository's Playwright skill/CLI workflow when performing interactive browser validation.
- Every bug fix should add a regression test when practical. Update phase checkboxes only after the relevant test and acceptance criterion pass.
- GitHub Actions is the CI platform. Deployment workflows are deferred until explicitly planned.

## Keeping the implementation plan current

- Treat `doc/implementation-plan.md` as live project state, not a one-time planning artifact. Review the active phase before starting work and again before handing work back.
- Mark a task `[~]` when implementation begins. Mark it `[x]` only after the work is present and its stated validation passes. Use `[!]` only for a real blocker and add a concise explanation plus the condition needed to unblock it.
- Add newly discovered required work to the correct phase before implementing it. If it is outside the active phase, place it in a later phase or deferred work instead of expanding scope silently.
- Keep task wording outcome-oriented and independently verifiable. Split a task when part is complete and part remains; never mark a partially completed compound task as done.
- Update relevant test tasks and exit criteria as implementation progresses. Mark a phase exit criterion complete only when there is concrete test, measurement, or documented smoke-test evidence.
- Record material deviations from the plan in the confirmed decisions/review section or an ADR, and reconcile affected PRD/design statements in the same logical change.
- Preserve completed checklist history rather than deleting it. Update the plan's `Last updated` date when task state, phase scope, decisions, or exit criteria materially change.
- Commit plan status changes with the implementation and tests they describe. A documentation-only follow-up is acceptable only when correcting stale status or recording a discovery made after the implementing commit.

## Git and commit workflow

- Commit implementation work locally in reasonably small, logical chunks. Each commit should represent one coherent change that can be reviewed and reverted independently.
- Prefer commits that leave the repository buildable and the relevant tests passing. Do not accumulate an entire phase into one commit, and do not commit knowingly broken intermediate states unless the user explicitly requests checkpoint commits.
- Keep implementation, its focused tests, and directly related documentation or plan-checkbox updates in the same commit. Put unrelated refactors, formatting sweeps, dependency upgrades, generated artifacts, and security cleanup in separate commits.
- When a dependency changes, commit its manifest and lockfile together. When a schema changes, commit its migration and compatibility tests with the corresponding model change.
- Before committing, inspect `git status`, review the staged diff, run the narrowest relevant checks, and scan staged content for secrets, private camera data, captures, and authenticated URLs.
- Stage paths deliberately. Never include unrelated user changes, local configuration, debug output, recordings, model binaries, database files, or editor artifacts merely because they are present in the working tree.
- Use concise imperative commit subjects. Prefer Conventional Commit prefixes where they fit, such as `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `build:`, and `ci:`. Explain non-obvious motivation or tradeoffs in the commit body.
- Suggested boundaries include repository scaffolding, a domain contract plus tests, one adapter plus contract tests, one UI behavior plus tests, one CI concern, or one documentation/ADR decision.
- Do not amend, squash, rebase, delete, or otherwise rewrite commits that may belong to the user without explicit approval. Do not push commits or tags unless the user asks; local commits are the default during implementation.

## Maintaining this file

Keep `AGENTS.md` short, stable, and operational. Update it when a change affects how future agents should work, including:

- validated bootstrap, lint, test, build, or run commands;
- repository layout or ownership boundaries;
- cross-cutting security constraints;
- durable architecture decisions;
- required validation for a hardware-specific subsystem.

Do not use this file for sprint status, implementation notes, temporary workarounds, or long design discussions; those belong in `doc/implementation-plan.md`, an ADR, or an issue. Add a nested `AGENTS.md` only when a subtree needs durable instructions that do not apply to the rest of the repository. A nested file must state its scope and inherit, rather than duplicate, root guidance.

When adding a command, run it first and document prerequisites and whether it is local-only, CI-safe, or hardware-dependent. When changing an instruction, remove obsolete guidance in the same change.
