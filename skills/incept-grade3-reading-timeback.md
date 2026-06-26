---
name: incept-grade3-reading-timeback
description: >
  Fetch the LIVE, password-protected docs for Incept's Grade-3 Reading TimeBack courses (what each course is,
  how it works, the full question report, compliance state, tooling) before working on them. The docs are
  stored encrypted and edited to update — this skill pulls + decrypts the latest, so never rely on a stale copy.
  Part of the Incept Reading skill library (see skills/README.md); its sibling is incept-grade5-reading-timeback.
---

# Incept · Grade-3 Reading (TimeBack) — course skill

When a task touches Incept's Grade-3 Reading TimeBack courses, FETCH + DECRYPT the current docs first, then act.

## Source (password-protected — the docs are encrypted at rest)
```
COURSE_DOCS = github-gist  StanHus/b6028696a2ce9a11aba72b3c7e109eb7   (file: course-docs.enc)
PASSWORD    = incept-g3reading-18fe3ee797
```
The gist holds only AES-256-CBC ciphertext — unreadable without the password above. The password lives in this
skill (intended); protection is against anyone who has the ciphertext but not the skill. This is the shared
**Incept Reading library** gist: it carries the registry plus a per-grade deep doc (G3 here, G5 in the sibling
skill). Live-service upgrade: point `COURSE_DOCS` at a small Vercel endpoint (or Supabase) that checks the
password in a header and returns the docs — swap only the fetch block below; the password stays here.

## Fetch + decrypt (writes REGISTRY.md + SUMMARY_AGENT.qmd + SUMMARY_AGENT_G5.qmd into the cwd)
```
curl -s https://gist.githubusercontent.com/StanHus/b6028696a2ce9a11aba72b3c7e109eb7/raw/course-docs.enc \
  | openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -base64 -pass pass:incept-g3reading-18fe3ee797 \
  | tar xzf -
# no curl: gh gist view b6028696a2ce9a11aba72b3c7e109eb7 -f course-docs.enc | openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -base64 -pass pass:incept-g3reading-18fe3ee797 | tar xzf -
```
- **REGISTRY.md** — every Incept Reading course (G3 v1/v2 + G5): sourcedId, title, status, what-it-is + how they work + tooling. Read first.
- **SUMMARY_AGENT.qmd** — full handoff for `grade3-reading-ela-rex-clone` (the G3 deliverable): cloning→now timeline, structure, the per-question report for all 835 items, the 8-non-negotiable verdicts, open items.
- **SUMMARY_AGENT_G5.qmd** — sibling G5 deep doc (read via the incept-grade5-reading-timeback skill).

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
  `examples/audit_compliance.py` in the `timeback-alpha-read-packager` repo.
- Honesty: MAP 0/313 → no RIT/"proven-growth" claim until a real in-cohort pilot.
