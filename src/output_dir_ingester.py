#!/usr/bin/env python3
"""
output_dir_ingester — Stream S2: the OUTPUT_DIR (manifest-driven) ingester for arpack.

Mayank's incept-qti-sdk (0.5.7) writes a *build output directory*:

    <output_dir>/
      manifest.json          # the index — item_id -> {item_xml, stimulus_xml, stimulus_id, metadata}
      items/<id>.xml         # one qti-assessment-item per file
      stimuli/stim_<hex>.xml # one qti-assessment-stimulus per passage

WE adapt to HIS shape; he tags nothing extra. This module reads HIS manifest.json, parses each
item (via the hardened arpack.from_qti_xml) and its linked stimulus (via arpack.from_qti_stimulus_xml),
LINKS them per the manifest (not by guessing from ids), carries the manifest metadata
(interaction_type / feedback_type) through, and returns a NORMALIZED list of {item, stimulus}
records ready for the assembler.

    from_timeback_build_output(dir) -> {"records": [...], "groups": [...]|None, "warnings": [...]}

Lesson grouping is NOT Mayank's job and is NOT done here unless he hands us the signal:
  * manifest entries with NO lesson_id  -> records returned UNGROUPED ("groups": None).
    The skeleton/qti_dir_resolver groups later (by stimulus-ref graph / id-block cadence).
  * manifest entries WITH a lesson_id   -> we ALSO return "groups": [{lesson_id, records:[...]}],
    grouped by that id, in first-seen order, records in manifest order within each group.
Either way the flat "records" list is always present and complete — grouping is additive.

DESIGN RULES (so this composes with the rest of arpack without surprises):
  * Single source of truth for parsing: arpack.from_qti_xml / from_qti_stimulus_xml. We do NOT
    re-implement QTI parsing here; if his XML shape shifts, the fix lands in arpack and we inherit it.
  * Link by the MANIFEST, fall back to the item's own embedded stimulus-ref only if the manifest
    omits the stimulus_xml. The manifest is authoritative.
  * Fail-LOUD on a broken manifest (missing item_xml, item file not found, item XML unparseable,
    a declared stimulus file missing). Fail-SOFT (warn, keep going) on a *recoverable* mismatch
    (e.g. manifest stimulus_id disagrees with the parsed stimulus identifier — we keep the parsed
    one and note it). Never silently drop a record.
  * Read-only. Returns code's output; writes nothing.

A "record" (one per manifest item entry) is:
  {
    "item_id":          <manifest item_id>,
    "item":             <arpack.from_qti_xml(...) struct: prompt/choices/correct_ids/format/...>,
    "stimulus":         <arpack.from_qti_stimulus_xml(...) struct {identifier,title,html}> | None,
    "stimulus_id":      <resolved stimulus identifier> | None,
    "interaction_type": <manifest metadata.interaction_type, e.g. "choiceInteraction"> | None,
    "feedback_type":    <manifest metadata.feedback_type,  e.g. "nonadaptive"> | None,
    "lesson_id":        <manifest lesson_id if present> | None,
    "role":             "guiding" if it has a stimulus else "quiz"  (mirrors arpack's inference),
  }
"""
import json
import os

# Single parsing source of truth — the hardened arpack adapters.
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from arpack import from_qti_xml, from_qti_stimulus_xml  # noqa: E402

_MANIFEST_NAME = "manifest.json"
# manifest keys we accept for the per-item lesson grouping signal (Mayank may add any one of these;
# today's manifest carries NONE of them -> ungrouped, which is correct).
_LESSON_ID_KEYS = ("lesson_id", "lessonId", "article_id", "articleId", "lesson")


def _read(path):
    # Mayank's incept-qti-sdk writes its build output with a leading BOM, and the ENCODING varies by
    # how the SDK's stdout was redirected: the 4-item sample manifest is UTF-8-BOM, but the all-7
    # manifest is UTF-16-LE-BOM (PowerShell '>' default on Windows). XML item/stimulus files are
    # ASCII/UTF-8. "WE adapt; he changes nothing" — so sniff the BOM and decode accordingly. A
    # UTF-16/UTF-8-BOM-blind utf-8-sig read raises UnicodeDecodeError on the 0xFF 0xFE bytes.
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):          # UTF-16 LE / BE (BOM-detected by the codec)
        return data.decode("utf-16")
    if data[:3] == b"\xef\xbb\xbf":                      # UTF-8 with BOM
        return data[3:].decode("utf-8")
    return data.decode("utf-8")                          # plain UTF-8 / ASCII


def _norm_path(output_dir, rel):
    """Resolve a manifest-relative path. Manifests may use either '/' or '\\' separators (the sample
    even has a Windows-style 'output_dir'); normalise both to the local OS so it works either way."""
    if rel is None:
        return None
    rel = str(rel).replace("\\", "/")
    return os.path.normpath(os.path.join(output_dir, rel))


def _lesson_id_of(entry):
    """Pull a lesson grouping id from a manifest entry, checking the top level AND its metadata
    block, across the accepted aliases. None if Mayank tagged no lesson (the common case today)."""
    md = entry.get("metadata") or {}
    for k in _LESSON_ID_KEYS:
        for src in (entry, md):
            v = src.get(k)
            if v is not None and str(v).strip() != "":
                return str(v).strip()
    return None


def from_timeback_build_output(output_dir):
    """Ingest one incept-qti-sdk build output directory (its manifest.json + items/ + stimuli/).

    Returns {"records": [...], "groups": [...]|None, "warnings": [...]} (see module docstring).
    Fail-loud on a structurally broken manifest; fail-soft (warn) on a recoverable mismatch.
    """
    if not os.path.isdir(output_dir):
        raise ValueError(f"{output_dir}: not a directory")
    manifest_path = os.path.join(output_dir, _MANIFEST_NAME)
    if not os.path.isfile(manifest_path):
        raise ValueError(f"{output_dir}: no {_MANIFEST_NAME} (is this an incept-qti-sdk build output?)")

    manifest = json.loads(_read(manifest_path))
    entries = manifest.get("items")
    if not isinstance(entries, list):
        raise ValueError(f"{manifest_path}: manifest has no 'items' list")

    # parse every stimulus ONCE (a passage may be shared across items), keyed by its real identifier.
    stim_cache = {}      # parsed_identifier -> stimulus struct
    stim_by_relpath = {} # the path the manifest pointed at -> stimulus struct (for direct linkage)

    def _load_stimulus(rel):
        if rel is None:
            return None
        abspath = _norm_path(output_dir, rel)
        if abspath in stim_by_relpath:
            return stim_by_relpath[abspath]
        if not os.path.isfile(abspath):
            raise ValueError(f"manifest declares stimulus '{rel}' but file is missing: {abspath}")
        s = from_qti_stimulus_xml(_read(abspath))
        stim_by_relpath[abspath] = s
        if s.get("identifier"):
            stim_cache[s["identifier"]] = s
        return s

    records, warnings = [], []
    for n, entry in enumerate(entries):
        item_id = entry.get("item_id") or entry.get("identifier")
        item_rel = entry.get("item_xml") or entry.get("item")
        if not item_rel:
            raise ValueError(f"manifest item[{n}] (item_id={item_id!r}) has no 'item_xml'")
        item_abs = _norm_path(output_dir, item_rel)
        if not os.path.isfile(item_abs):
            raise ValueError(f"manifest item[{n}] (item_id={item_id!r}) item_xml missing: {item_abs}")
        try:
            parsed_item = from_qti_xml(_read(item_abs))
        except Exception as e:                                   # noqa: BLE001 - want the file name in the msg
            raise ValueError(f"manifest item[{n}] (item_id={item_id!r}) failed to parse {item_abs}: {e}")

        meta = entry.get("metadata") or {}
        interaction_type = meta.get("interaction_type")
        feedback_type = meta.get("feedback_type")
        lesson_id = _lesson_id_of(entry)

        # link the stimulus: manifest is authoritative. Prefer the manifest's stimulus_xml path;
        # fall back to the item's own embedded stimulus-ref href ONLY if the manifest omits it.
        stim, resolved_sid = None, entry.get("stimulus_id")
        if entry.get("stimulus_xml"):
            stim = _load_stimulus(entry["stimulus_xml"])
        elif parsed_item.get("stimulus_ref"):
            # manifest omitted the path but the item points at a passage — resolve relative to the
            # item file's directory (Mayank's hrefs are 'stimuli/<id>.xml', item-relative).
            href = parsed_item["stimulus_ref"]
            cand = _norm_path(os.path.dirname(item_abs), href)
            if os.path.isfile(cand):
                stim = from_qti_stimulus_xml(_read(cand))
                stim_by_relpath[cand] = stim
                if stim.get("identifier"):
                    stim_cache[stim["identifier"]] = stim
                warnings.append(f"{item_id}: stimulus linked via item's embedded ref "
                                f"(manifest had no stimulus_xml): {href}")
            else:
                warnings.append(f"{item_id}: item references stimulus '{href}' but no file found "
                                f"and manifest declared none")

        # reconcile the stimulus id. Trust the PARSED identifier (it's what the XML actually is);
        # warn if the manifest's stimulus_id disagrees, but never drop the record over it.
        if stim is not None:
            parsed_sid = stim.get("identifier")
            if resolved_sid and parsed_sid and resolved_sid != parsed_sid:
                warnings.append(f"{item_id}: manifest stimulus_id {resolved_sid!r} != parsed "
                                f"stimulus identifier {parsed_sid!r}; using parsed")
            resolved_sid = parsed_sid or resolved_sid
        elif resolved_sid:
            # manifest named a stimulus_id but we resolved no passage — surface it, don't crash.
            warnings.append(f"{item_id}: manifest names stimulus_id {resolved_sid!r} but no "
                            f"stimulus_xml resolved; record carries no passage")
            resolved_sid = None

        records.append({
            "item_id": item_id or parsed_item.get("identifier"),
            "item": parsed_item,
            "stimulus": stim,
            "stimulus_id": resolved_sid,
            "interaction_type": interaction_type,
            "feedback_type": feedback_type,
            "lesson_id": lesson_id,
            # role mirrors arpack's own inference so downstream grouping agrees with the parser.
            "role": "guiding" if stim is not None or parsed_item.get("stimulus_ref") else "quiz",
        })

    # grouping: ONLY if Mayank gave a lesson_id on (some) entries. Otherwise ungrouped — the
    # skeleton/qti_dir_resolver does the grouping later. We never invent a lesson boundary here.
    groups = None
    if any(r["lesson_id"] for r in records):
        order, buckets = [], {}
        for r in records:
            lid = r["lesson_id"] or "__ungrouped__"
            if lid not in buckets:
                buckets[lid] = []
                order.append(lid)
        for r in records:
            buckets[r["lesson_id"] or "__ungrouped__"].append(r)
        groups = [{"lesson_id": (None if lid == "__ungrouped__" else lid), "records": buckets[lid]}
                  for lid in order]

    return {"records": records, "groups": groups, "warnings": warnings}


# ───────────────────────── self-test / proof against the fixture ────────────────
def _prove(output_dir):
    """Run from_timeback_build_output on a fixture and assert the brief's acceptance criteria:
    all items + stimuli ingest; prompts/choices/correct-sets non-blank and correct."""
    res = from_timeback_build_output(output_dir)
    records = res["records"]
    ok = True

    def chk(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            print("  FAIL:", msg)

    # every manifest item became a record
    n_items = len(json.loads(_read(os.path.join(output_dir, _MANIFEST_NAME)))["items"])
    chk(len(records) == n_items, f"expected {n_items} records, got {len(records)}")

    # distinct stimuli that actually parsed (de-dup by identifier)
    sids = {r["stimulus_id"] for r in records if r["stimulus"] is not None}
    chk(len(sids) == 2, f"expected 2 distinct stimuli ingested, got {len(sids)}: {sids}")

    for r in records:
        it = r["item"]
        # prompt non-blank — THE bug the fixture surfaced (<div class='stem'>, no <qti-prompt>)
        chk(bool(it["prompt"].strip()), f"{r['item_id']}: prompt is BLANK")
        # choices present + non-blank
        chk(len(it["choices"]) >= 2, f"{r['item_id']}: <2 choices")
        chk(all(c["text"].strip() for c in it["choices"]), f"{r['item_id']}: a choice text is blank")
        # correct set non-empty, every id is a real choice id
        cids = {c["id"] for c in it["choices"]}
        chk(bool(it["correct_ids"]), f"{r['item_id']}: empty correct set")
        chk(all(c in cids for c in it["correct_ids"]),
            f"{r['item_id']}: correct id(s) {it['correct_ids']} not all in choices {sorted(cids)}")
        # carried metadata
        chk(r["interaction_type"] == "choiceInteraction", f"{r['item_id']}: interaction_type not carried")
        chk(r["feedback_type"] == "nonadaptive", f"{r['item_id']}: feedback_type not carried")

    # no lesson_id in this manifest -> ungrouped
    chk(res["groups"] is None, "expected ungrouped (manifest has no lesson_id)")
    print("PROVE:", "PASS" if ok else "FAIL")
    return ok, res


if __name__ == "__main__":
    import sys
    # fixtures/ is the PARENT's sibling now that this module lives in src/ — ".." up first.
    default = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "fixtures", "qti_sample_2026-06-16")
    src = sys.argv[1] if len(sys.argv) > 1 else default
    ok, res = _prove(src)
    # human-readable ingest dump for the fixture
    for r in res["records"]:
        it = r["item"]
        print(f"\n[{r['item_id']}]  role={r['role']}  fmt={it['format']}  "
              f"interaction={r['interaction_type']}  feedback={r['feedback_type']}")
        print(f"  prompt : {it['prompt']}")
        print(f"  choices: " + " | ".join(f"{c['id']}:{c['text']}" for c in it["choices"]))
        print(f"  correct: {it['correct_ids']}  (max_choices={it['max_choices']})")
        if r["stimulus"] is not None:
            s = r["stimulus"]
            print(f"  passage: [{r['stimulus_id']}] {s['title']!r}")
    for w in res["warnings"]:
        print("WARN:", w)
    sys.exit(0 if ok else 1)
