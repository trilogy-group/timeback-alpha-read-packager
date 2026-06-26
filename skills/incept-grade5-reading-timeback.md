---
name: incept-grade5-reading-timeback
description: >
  Fetch the LIVE, password-protected docs for Incept's Grade-5 Reading TimeBack course (what it is, how it
  works, the unit/cert map, compliance state, tooling) before working on it. The docs are stored encrypted
  and edited to update — this skill pulls + decrypts the latest, so never rely on a stale copy.
  Part of the Incept Reading skill library (see skills/README.md); its sibling is incept-grade3-reading-timeback.
---

# Incept · Grade-5 Reading (TimeBack) — course skill

When a task touches Incept's Grade-5 Reading TimeBack course, FETCH + DECRYPT the current docs first, then act.

## Source (password-protected — the docs are encrypted at rest)
```
COURSE_DOCS = github-gist  StanHus/b6028696a2ce9a11aba72b3c7e109eb7   (file: course-docs.enc)
PASSWORD    = incept-g3reading-18fe3ee797
```
The gist holds only AES-256-CBC ciphertext — unreadable without the password above. The password lives in this
skill (intended); protection is against anyone who has the ciphertext but not the skill. This is the shared
**Incept Reading library** gist (same one the G3 skill uses): it carries the registry plus a per-grade deep doc.
Live-service upgrade: point `COURSE_DOCS` at a small Vercel endpoint (or Supabase) that checks the password in a
header and returns the docs — swap only the fetch block below; the password stays here.

## Fetch + decrypt (writes REGISTRY.md + SUMMARY_AGENT.qmd + SUMMARY_AGENT_G5.qmd into the cwd)
```
curl -s https://gist.githubusercontent.com/StanHus/b6028696a2ce9a11aba72b3c7e109eb7/raw/course-docs.enc \
  | openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -base64 -pass pass:incept-g3reading-18fe3ee797 \
  | tar xzf -
# no curl: gh gist view b6028696a2ce9a11aba72b3c7e109eb7 -f course-docs.enc | openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -base64 -pass pass:incept-g3reading-18fe3ee797 | tar xzf -
```
- **REGISTRY.md** — every Incept Reading course (G3 v1/v2 + G5): sourcedId, title, status, what-it-is + how they work + tooling. Read first.
- **SUMMARY_AGENT_G5.qmd** — full handoff for `g5-reading-merged-pp-9802` (the G5 deliverable): the two-unit build, the unit/cert map, the live-state facts, the named gaps, tooling.
- **SUMMARY_AGENT.qmd** — sibling G3 deep doc (read via the incept-grade3-reading-timeback skill).

## The course at a glance (read the deep doc for the rest)
- **`g5-reading-merged-pp-9802`** — Grade 5 Reading, live on TimeBack (powerpath-100). **81 lessons / 772 items**,
  built by merging Incept's two live G5 courses with rendering restored and the ≥90% mastery gate enforced.
- **Unit 1 (172 items) is cross-family blind-CERTIFIED** — every item carries a `_cert` proving it requires
  reading the passage (a different model family than generated it could not recover the answer passage-blind).
  This is the anti-leak bar; Unit 1 clears it.
- **Unit 2 (600 items)** carries the richer MCQ/MSQ/EBSR machinery (the MAP select-and-justify signature);
  its anti-leak re-gate is the named open item (see gaps). Status disclosed in unit/course `metadata`, never
  in a title a student reads.
- Verdict is **PASS-with-named-gaps**, never a bare PASS. Open items: CCSS backfill on items (a metadata
  follow-up via `--ccss-map`), Unit-2 anti-leak re-gate, separately-assembled mastery/MAP/spaced forms.

## Updating the docs (re-encrypt, re-push — the skill always pulls latest)
```
tar czf - REGISTRY.md SUMMARY_AGENT.qmd SUMMARY_AGENT_G5.qmd \
  | openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt -base64 -pass pass:incept-g3reading-18fe3ee797 > course-docs.enc
gh gist edit b6028696a2ce9a11aba72b3c7e109eb7 course-docs.enc
```

## Then act
- Courses: `alpha.timeback.com/app/course/{sourcedId}`. APIs: `api.alpha-1edtech.ai` (OneRoster/PowerPath),
  `qti.alpha-1edtech.ai` (QTI), `caliper.alpha-1edtech.ai`. Auth: `examples/push_to_timeback.py` `mint_token()` + `/tmp/timeback.env`.
- Deterministic certifier (the only authority for "done", never an agent's claim or an HTTP 200):
  `examples/audit_compliance.py` in the `timeback-alpha-read-packager` repo. Anti-leak authority:
  the cross-family blind solver (`generator/g5/`), never a self-certified `anti_leak:pass` or an InceptBench score.
- Honesty: MAP 0/313 → no RIT/"proven-growth" claim until a real in-cohort pilot. All machine items
  `humanApproved:false`; passages are machine-authored-cold unless actually sourced.
