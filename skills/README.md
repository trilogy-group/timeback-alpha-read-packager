# Incept Reading — skill library

Agent skills for working on Incept's live TimeBack Reading courses. Each skill **fetches + decrypts the
current course docs first** (from one shared, password-protected gist) so an agent never works off a stale
copy, then points it at the live course, the APIs, and the deterministic certifier.

| Skill | Grade | Live course(s) | Deep doc |
|---|---|---|---|
| [`incept-grade3-reading-timeback`](incept-grade3-reading-timeback.md) | 3 | `grade3-reading-ela-rex-clone-v2` (deliverable) · `grade3-reading-ela-rex-clone` (v1, frozen) | `SUMMARY_AGENT.qmd` |
| [`incept-grade5-reading-timeback`](incept-grade5-reading-timeback.md) | 5 | `g5-reading-merged-pp-9802` | `SUMMARY_AGENT_G5.qmd` |

## The course library

The full registry of every Incept Reading course (sourcedId · title · status · what-it-is) lives in
**`REGISTRY.md`**, carried inside the shared docs gist. Headline courses:

- **G3 v1** — `grade3-reading-ela-rex-clone` — the originally-delivered, now-frozen reference. SUBMIT-READY.
- **G3 v2** — `grade3-reading-ela-rex-clone-v2` — the current G3 deliverable (re-synced to Praveen's latest source).
- **G5** — `g5-reading-merged-pp-9802` — Grade-5 Reading, live; Unit-1 cross-family blind-certified.

## Shared mechanism (why both skills look alike)

- One AES-256-CBC encrypted gist (`StanHus/b6028696a2ce9a11aba72b3c7e109eb7`, file `course-docs.enc`)
  carries `REGISTRY.md` + `SUMMARY_AGENT.qmd` (G3) + `SUMMARY_AGENT_G5.qmd` (G5).
- The decrypt password lives in each skill **by design** — protection is against anyone holding the
  ciphertext but not the skill. Share the skill only inside the team.
- APIs: `api.alpha-1edtech.ai` (OneRoster/PowerPath) · `qti.alpha-1edtech.ai` (QTI) · `caliper.alpha-1edtech.ai`.
- The only authority for "done" is the deterministic certifier `examples/audit_compliance.py` (and a live
  read-back) — never an agent's claim and never an HTTP 200.

## Honesty (applies to every course)

MAP is 0/313 for our cohort → **no RIT / "proven growth"** claim until a real in-cohort pilot. All machine
content is `humanApproved:false`. Every verdict is **PASS-with-named-gaps**, never a bare PASS.
