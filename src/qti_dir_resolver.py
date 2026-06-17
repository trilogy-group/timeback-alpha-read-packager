#!/usr/bin/env python3
"""
qti_dir_resolver — Stream S4: LOOSE-ITEM GROUPING for arpack  (Mayank-facing ingest)

Mayank emits LOOSE QTI 3.0 XML files (one per assessment-item) plus the passage
(qti-assessment-stimulus) XMLs. He should NOT have to reshape anything into our
skeleton. This module groups his loose files into arpack lessons and hands back a
`skel["units"][i]["lessons"]` list that drops straight into arpack.assemble().

  from_qti_dir(dir) -> {"lessons": [...]}    # arpack lesson dicts, ready to nest under a unit

────────────────────────────────────────────────────────────────────────────────
WHAT THE LIVE EXPORT PROVED (1077 items / 120 lessons / 597 stimuli), drives the design:

  • A guiding item ALWAYS carries  <qti-assessment-stimulus-ref href="stimuli/<sid>">.
    A quiz item NEVER carries one.  → role is self-describing (no tag needed). [held for every item in the export we sampled]
  • guiding item id == guiding_<A>_<B>;  its stimulus id == guiding_<A>  (the id prefix).
    1 guiding item ↔ 1 unique stimulus, and NO stimulus is shared across lessons. [597/597]
  • Quiz items (quiz_<n>) carry ZERO grouping signal in their payload — no lessonId,
    no article tag, empty metadata.  They can ONLY be grouped by an EXTERNAL signal
    (a tag, the folder they sit in, or contiguous id-block ordering).
  • Per lesson: 3–6 guiding + EXACTLY 4 quiz.  The trailing id-block number
    (guiding 2nd num + quiz num) is contiguous within a lesson, guiding-then-quiz. [120/120]
  • Standards / skill codes are stored NOWHERE.  Don't ask Mayank for them.

THE MINIMUM WE ASK OF MAYANK  (ranked; the resolver accepts the strongest present):
  S0  one folder per lesson, his loose item XMLs + the passage XMLs inside it.   ← ASK FOR THIS
      Nothing else. No renaming, no manifest, no tags. The folder IS the lesson.
  (optional)  a 1-line lesson.json sidecar {"title","vendorId"} to name the test
              nicely; absent → we derive title from the first passage's <h1>/title
              and vendorId from the smallest id-block number.

FALLBACKS when a folder holds MORE than one lesson (a flat dump of everything):
  S1  explicit tag        — qti-metadata-entry key="lessonId"/"articleId" (if Mayank ever adds it)
  S2  stimulus-ref graph  — clusters guiding items; quizzes still need S3 to attach
  S3  id-block contiguity — partition by the contiguous trailing-number runs (3–6 guiding +4 quiz)
Resolution is fail-LOUD: if a group is not exactly {3..6 guiding, 4 quiz} we raise with the offenders,
never emit a malformed lesson. arpack.validate() is the second, independent gate.
────────────────────────────────────────────────────────────────────────────────
"""
import glob
import json
import os
import re
from xml.etree import ElementTree as ET

# import the (already verified) single-item + answer-key adapter from arpack
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from arpack import (  # noqa: E402
    from_qti_xml, adapt_qti_item, QTI_NS,
    GUIDING_MIN, GUIDING_MAX, QUIZ_ITEMS,
)

_NUMS = re.compile(r"(\d+)")
_LESSON_TAG_KEYS = ("lessonId", "articleId", "lesson_id", "article_id")


# ───────────────────────── stimulus (passage) parsing ──────────────────────────
def _parse_stimulus(xml):
    """Pull {identifier,title,html} out of a raw qti-assessment-stimulus XML.
    html = the inner XML of <qti-stimulus-body> (arpack/validate enforces the tag vocab)."""
    root = ET.fromstring(xml.encode() if isinstance(xml, str) else xml)
    body = root.find(".//" + QTI_NS + "qti-stimulus-body")
    html = ""
    if body is not None:
        # serialise children (the actual <div>/<p>/<h1>… passage markup), strip namespaces
        inner = "".join(ET.tostring(ch, encoding="unicode") for ch in body)
        if not inner and (body.text or "").strip():
            inner = body.text
        html = re.sub(r"\sxmlns(:\w+)?=\"[^\"]*\"", "", inner).replace("ns0:", "").strip()
    return {"identifier": root.attrib.get("identifier"),
            "title": root.attrib.get("title") or _first_heading(html) or root.attrib.get("identifier"),
            "html": html}


def _first_heading(html):
    m = re.search(r"<h[12][^>]*>(.*?)</h[12]>", html or "", re.S)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else None


def _lesson_tag(xml):
    """Return an explicit lesson grouping id if Mayank tagged it (S1), else None."""
    for k in _LESSON_TAG_KEYS:
        m = re.search(r'qti-metadata-entry key="%s">([^<]+)<' % re.escape(k), xml)
        if m:
            return m.group(1).strip()
    return None


# ───────────────────────── load a directory of loose XMLs ──────────────────────
def _load_xml_files(folder):
    """Read every *.xml under `folder` (non-recursive). Classify each as item|stimulus.
    Returns (items, stimuli) where each is a list of (filename, parsed_struct, raw_xml)."""
    items, stimuli = [], []
    for path in sorted(glob.glob(os.path.join(folder, "*.xml"))):
        raw = open(path, encoding="utf-8").read()
        head = raw[:400]
        if "qti-assessment-stimulus" in head and "qti-assessment-stimulus-ref" not in head:
            stimuli.append((os.path.basename(path), _parse_stimulus(raw), raw))
        elif "qti-assessment-item" in head:
            items.append((os.path.basename(path), from_qti_xml(raw), raw))
        # silently ignore anything else (e.g. a stray qti-assessment-test the SDK also dropped)
    return items, stimuli


def _block_num(parsed):
    """The trailing id-block number used for in-lesson ordering & S3 contiguity grouping.
    guiding_<A>_<B> -> B ; quiz_<N> -> N."""
    nums = _NUMS.findall(parsed["identifier"] or "")
    return int(nums[-1]) if nums else 0


def _stim_id_of(parsed):
    """For a guiding item, the stimulus id it points at: href 'stimuli/<sid>' or just '<sid>'."""
    href = parsed.get("stimulus_ref") or ""
    return href.rsplit("/", 1)[-1] if href else None


# ───────────────────────── group a flat item list into lessons ─────────────────
def _group_items(items):
    """items: list of (fname, parsed, raw). Return list of {guiding:[...], quiz:[...]} groups,
    each ordered by id-block number, using the strongest available signal.

    A single per-lesson folder is the happy path: ONE group, no inference needed.
    For a flat multi-lesson dump we fall to S1 tag → S3 id-block contiguity (S2 only confirms
    guiding↔passage, it cannot place quizzes, so contiguity is the real multi-lesson splitter)."""
    guiding = [(f, p, r) for (f, p, r) in items if p["role"] == "guiding"]
    quiz = [(f, p, r) for (f, p, r) in items if p["role"] == "quiz"]

    # S1 — explicit tag wins outright (works for guiding AND quiz)
    tags = {}
    tagged = True
    for f, p, r in items:
        t = _lesson_tag(r)
        if t is None:
            tagged = False
            break
        tags.setdefault(t, {"guiding": [], "quiz": []})[p["role"]].append((f, p, r))
    if tagged and tags:
        return [_order_group(g) for g in tags.values()]

    # Happy path — the folder already IS one lesson: 3..6 guiding + 4 quiz, no inference.
    if GUIDING_MIN <= len(guiding) <= GUIDING_MAX and len(quiz) == QUIZ_ITEMS:
        return [_order_group({"guiding": guiding, "quiz": quiz})]

    # S3 — flat multi-lesson dump. The live export proved the trailing id-block stream is
    # ONE unbroken global run (lesson N+1's first guiding number == lesson N's last quiz +1),
    # so numeric GAP detection cannot find the seam. The reliable seam is the ROLE CADENCE:
    # ordered by id-block, every lesson is  guiding…guiding, quiz×4  — a boundary is exactly
    # the transition from a quiz back to a guiding. Split there. (Requires the contract's
    # "exactly 4 quiz per lesson"; _lesson_from_group fails loud if a run violates it.)
    everything = sorted(items, key=lambda t: _block_num(t[1]))
    groups, cur, seen_quiz = [], [], False
    for f, p, r in everything:
        if p["role"] == "guiding" and seen_quiz:           # quiz→guiding == new lesson
            groups.append(cur); cur = []; seen_quiz = False
        if p["role"] == "quiz":
            seen_quiz = True
        cur.append((f, p, r))
    if cur:
        groups.append(cur)
    out = []
    for grp in groups:
        out.append(_order_group({
            "guiding": [t for t in grp if t[1]["role"] == "guiding"],
            "quiz": [t for t in grp if t[1]["role"] == "quiz"],
        }))
    return out


def _order_group(g):
    g["guiding"] = sorted(g["guiding"], key=lambda t: _block_num(t[1]))
    g["quiz"] = sorted(g["quiz"], key=lambda t: _block_num(t[1]))
    return g


# ───────────────────────── assemble one lesson dict ────────────────────────────
def _lesson_from_group(group, stim_by_id, vendor_id, title):
    """Turn one grouped {guiding,quiz} into an arpack lesson dict (parses the generator's native grouping)."""
    g_specs, missing = [], []
    for f, p, r in group["guiding"]:
        sid = _stim_id_of(p)
        s = stim_by_id.get(sid)
        if s is None:
            missing.append(f"{p['identifier']} -> passage '{sid}' not found in folder")
            continue
        g_specs.append({"stimulus": {"title": s["title"], "html": s["html"]},
                        "item": adapt_qti_item(p)})        # adapt_qti_item is fail-closed on answer key
    if missing:
        raise ValueError("guiding item(s) missing their passage XML:\n  " + "\n  ".join(missing))
    q_specs = [adapt_qti_item(p) for (f, p, r) in group["quiz"]]

    # contract gate (independent of arpack.validate, but cheap + early + names the offender)
    if not (GUIDING_MIN <= len(g_specs) <= GUIDING_MAX):
        raise ValueError(f"lesson {vendor_id}: {len(g_specs)} guiding (need {GUIDING_MIN}-{GUIDING_MAX}); "
                         f"ids={[t[1]['identifier'] for t in group['guiding']]}")
    if len(q_specs) != QUIZ_ITEMS:
        raise ValueError(f"lesson {vendor_id}: {len(q_specs)} quiz (need exactly {QUIZ_ITEMS}); "
                         f"ids={[t[1]['identifier'] for t in group['quiz']]}")
    return {"vendorId": vendor_id, "title": title, "xp": 12, "guiding": g_specs, "quiz": q_specs}


# ───────────────────────── public entry points ─────────────────────────────────
def from_qti_lesson_folder(folder):
    """One folder == one lesson (the asked-for minimum). Returns a single arpack lesson dict.
    Title/vendorId come from an optional lesson.json sidecar, else are derived from the content."""
    items, stimuli = _load_xml_files(folder)
    if not items:
        raise ValueError(f"{folder}: no QTI assessment-item XMLs found")
    stim_by_id = {s["identifier"]: s for _, s, _ in stimuli}
    groups = _group_items(items)
    if len(groups) != 1:
        raise ValueError(f"{folder}: expected ONE lesson here, inferred {len(groups)} "
                         f"(flat multi-lesson dump? put each lesson in its own folder, "
                         f"or use from_qti_dir on the parent)")
    group = groups[0]

    side = os.path.join(folder, "lesson.json")
    meta = json.load(open(side)) if os.path.exists(side) else {}
    vendor_id = meta.get("vendorId")
    if vendor_id is None:                                   # derive: smallest guiding stimulus number
        nums = [_block_num(t[1]) for t in group["guiding"]]
        vendor_id = min(nums) if nums else 0
    title = meta.get("title")
    if not title and group["guiding"]:                     # derive from first passage heading/title
        first_sid = _stim_id_of(group["guiding"][0][1])
        title = (stim_by_id.get(first_sid) or {}).get("title") or f"Lesson {vendor_id}"
    return _lesson_from_group(group, stim_by_id, vendor_id, title or f"Lesson {vendor_id}")


def from_qti_dir(directory):
    """Ingest Mayank's drop -> {"lessons": [arpack lesson dict, ...]} for arpack.assemble().

    Layout it accepts, strongest first (NO reshaping required from Mayank):
      A) parent/<lesson_folder>/*.xml      one folder per lesson  (RECOMMENDED, zero ambiguity)
      B) parent/*.xml                      a single lesson's loose files directly in `directory`
      C) flat multi-lesson dump            many lessons' files in one folder → split by tag/id-block

    The returned lessons go under whatever unit the caller chooses, e.g.:
        skel["units"] = [{"title": "...", "sortOrder": 1, "lessons": from_qti_dir(d)["lessons"]}]
    """
    subfolders = [os.path.join(directory, n) for n in sorted(os.listdir(directory))
                  if os.path.isdir(os.path.join(directory, n))]
    has_subfolder_xml = any(glob.glob(os.path.join(sf, "*.xml")) for sf in subfolders)
    own_xml = glob.glob(os.path.join(directory, "*.xml"))

    lessons = []
    if has_subfolder_xml and not own_xml:
        # Layout A — one folder per lesson
        for sf in subfolders:
            if glob.glob(os.path.join(sf, "*.xml")):
                lessons.append(from_qti_lesson_folder(sf))
    else:
        # Layout B or C — files live directly in `directory`
        items, stimuli = _load_xml_files(directory)
        if not items:
            raise ValueError(f"{directory}: no item XMLs and no per-lesson subfolders with XMLs")
        stim_by_id = {s["identifier"]: s for _, s, _ in stimuli}
        for group in _group_items(items):
            nums = [_block_num(t[1]) for t in group["guiding"]]
            vendor_id = min(nums) if nums else 0
            first_sid = _stim_id_of(group["guiding"][0][1]) if group["guiding"] else None
            title = (stim_by_id.get(first_sid) or {}).get("title") or f"Lesson {vendor_id}"
            lessons.append(_lesson_from_group(group, stim_by_id, vendor_id, title))

    # stable lesson order by vendorId
    lessons.sort(key=lambda L: L["vendorId"])
    return {"lessons": lessons}


# ───────────────────────── self-test against /tmp fixture (optional) ────────────
if __name__ == "__main__":
    import arpack
    src = _sys.argv[1] if len(_sys.argv) > 1 else "/tmp/mayank_drop"
    res = from_qti_dir(src)
    skel = {
        "course": {"title": "STAN-PROBE-DELETEME Reading G3", "courseCode": "ALPHAREAD-PROBE",
                   "grades": ["3"], "subjects": ["Reading"], "org_sourcedId": "powerpath-ui-org"},
        "units": [{"title": "Ingested from Mayank drop", "sortOrder": 1, "lessons": res["lessons"]}],
    }
    pkg = arpack.assemble(skel)
    errs = arpack.validate(pkg)
    print("lessons:", len(res["lessons"]),
          "| guiding counts:", [len(L["guiding"]) for L in res["lessons"]],
          "| quiz counts:", [len(L["quiz"]) for L in res["lessons"]])
    print("VALIDATE:", "PASS" if not errs else "FAIL")
    for e in errs:
        print("  -", e)
    _sys.exit(0 if not errs else 1)
