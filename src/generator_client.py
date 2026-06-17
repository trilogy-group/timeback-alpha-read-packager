"""generator_client.py — STREAM S2 of the Grade-3 Reading course orchestrator.

ONE job: turn an r2 generation *request* (built by gen_request.py) into a
Mayank-shaped *BuildResult* — the exact dict his `qti-sdk build` emits per item:

    {
        "item_id":      str,            # stable identifier for THIS request
        "item_xml":     str,            # the full <qti-assessment-item> XML
        "stimulus_xml": str | None,     # the full <qti-assessment-stimulus> XML, or None
        "stimulus_id":  str | None,     # stimulus identifier, or None
        "metadata":     {"interaction_type": ..., "feedback_type": ...},
    }

That dict is what `course_orchestrator.py` hands to arpack's parse layer
(from_qti_xml / from_qti_stimulus_xml / from_timeback_build_output), so the shape
here is the contract with arpack — not negotiable.

Two backends, one-line swap:

  generate(request, backend="stub")  (DEFAULT)
      Reads Mayank's REAL fixture (manifest + items/*.xml + stimuli/*.xml) and
      returns a real item+stimulus for the request. Cycles through his 4 items /
      2 stimuli and REWRITES the ids to be deterministic per request, so the
      pipeline gets unique-but-reproducible ids and runs end-to-end on real-shaped
      QTI TODAY. No network, no file writes.

  generate(request, backend="real")
      The documented interface for the live Mayank generator / InceptBench POST.
      Raises NotImplementedError with the exact request body it WILL send. One swap.

Determinism / idempotency: the same request always yields the same item_id and
stimulus_id (hash of the request's identifying fields), so re-running the
orchestrator converges instead of piling up duplicate ids.

No file writes. Pure function of (request, fixture-on-disk).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Where Mayank's real fixture lives (the stub's source of truth).
# Overridable via env for tests; defaults to the checked-in fixture.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
# After the src/ restructure this module lives in src/, so the fixtures/ folder is one
# level UP (a sibling of src/, not a child). The ".." keeps the checked-in Mayank fixture
# resolvable regardless of the caller's CWD.
DEFAULT_FIXTURE_DIR = os.environ.get(
    "ALPHA_READ_FIXTURE_DIR",
    os.path.join(_HERE, "..", "fixtures", "qti_sample_2026-06-16"),
)


# ===========================================================================
# Request normalization — accept a dict, a dataclass, or anything with __dict__
# ===========================================================================
def _as_dict(request: Any) -> Dict[str, Any]:
    """Coerce whatever gen_request.py hands us into a plain dict.

    We deliberately don't import gen_request (sibling stream, may not exist yet):
    we only need a stable, hashable view of the request's identifying fields.
    """
    if request is None:
        return {}
    if isinstance(request, dict):
        return request
    # dataclass / object with attributes
    if hasattr(request, "__dict__"):
        return dict(vars(request))
    # last resort: a string/scalar request id
    return {"_raw": request}


def _stable_request_key(request: Any) -> str:
    """A deterministic key for THIS request.

    Idempotency hinges on this: same request fields -> same key -> same ids on
    re-run. We prefer an explicit request id if present, else hash the
    identifying subset (topic/standard/format/band/...), else hash the whole
    request canonically.
    """
    d = _as_dict(request)

    # 1) explicit id wins (gen_request.py may stamp one)
    for k in ("request_id", "id", "rid"):
        v = d.get(k)
        if v:
            return str(v)

    # 2) hash the fields that DEFINE what is being asked for
    identifying = {}
    for k in (
        "topic", "lexile_band", "band", "genre", "structure_schema",
        "standard", "substandard_id", "kct", "map_goal_area",
        "format", "interaction_type", "difficulty", "lesson_id",
        "lesson_title", "role", "index", "ordinal",
    ):
        if k in d and d[k] is not None:
            identifying[k] = d[k]

    payload = identifying if identifying else d
    blob = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _request_format(request: Any) -> Optional[str]:
    """Pull the requested format/interaction so the stub can pick a matching
    fixture archetype (mcq vs msq) when possible."""
    d = _as_dict(request)
    fmt = d.get("format") or d.get("interaction_type")
    if isinstance(fmt, dict):
        fmt = fmt.get("type") or fmt.get("name")
    return str(fmt).lower() if fmt else None


def _wants_stimulus(request: Any) -> Optional[bool]:
    """Does the request reference a passage/stimulus? None == 'no preference'."""
    d = _as_dict(request)
    stim = d.get("stimulus")
    if isinstance(stim, dict):
        return bool(stim.get("ref") or stim.get("identifier") or stim.get("id"))
    if stim is not None:
        return bool(stim)
    return None


# ===========================================================================
# Fixture loading (the STUB's real-QTI source)
# ===========================================================================
class _Fixture:
    """Lazily-loaded, cached view of Mayank's build-output fixture.

    Holds the raw XML strings for his 4 items and 2 stimuli plus the manifest
    metadata, so the stub can hand back REAL Mayank XML (id-rewritten) with zero
    re-reads after the first request.
    """

    _cache: Dict[str, "_Fixture"] = {}

    def __init__(self, fixture_dir: str):
        self.dir = fixture_dir
        manifest_path = os.path.join(fixture_dir, "manifest.json")
        if not os.path.isfile(manifest_path):
            raise FileNotFoundError(
                f"generator_client stub: Mayank fixture manifest not found at "
                f"{manifest_path}. Set ALPHA_READ_FIXTURE_DIR or check the fixture."
            )
        # Mayank's manifest can carry a UTF-8 BOM; utf-8-sig strips it transparently.
        with open(manifest_path, "r", encoding="utf-8-sig") as fh:
            manifest = json.load(fh)

        self.records: List[Dict[str, Any]] = []
        for entry in manifest.get("items", []):
            item_rel = entry.get("item_xml") or entry.get("item")
            item_abs = os.path.join(fixture_dir, item_rel)
            item_xml = self._read(item_abs, f"item {entry.get('item_id')!r}")

            stim_xml = None
            stim_rel = entry.get("stimulus_xml")
            if stim_rel:
                stim_abs = os.path.join(fixture_dir, stim_rel)
                stim_xml = self._read(stim_abs, f"stimulus for {entry.get('item_id')!r}")

            self.records.append({
                "item_id": entry.get("item_id"),
                "item_xml": item_xml,
                "stimulus_xml": stim_xml,
                "stimulus_id": entry.get("stimulus_id"),
                "metadata": dict(entry.get("metadata") or {}),
            })

        if not self.records:
            raise ValueError(
                f"generator_client stub: fixture manifest at {manifest_path} has no items."
            )

    @staticmethod
    def _read(path: str, what: str) -> str:
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"generator_client stub: {what} XML missing on disk: {path}"
            )
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()

    @classmethod
    def load(cls, fixture_dir: str) -> "_Fixture":
        key = os.path.abspath(fixture_dir)
        if key not in cls._cache:
            cls._cache[key] = cls(fixture_dir)
        return cls._cache[key]

    # -- archetype selection -------------------------------------------------
    def pick(self, request: Any) -> Dict[str, Any]:
        """Choose a fixture record for this request.

        Preference order:
          1. format (mcq/msq) AND stimulus-preference match, if the request asks;
          2. format match only;
          3. deterministic cycle across all 4 by the request key.
        Always deterministic for a given request (so re-runs are stable).
        """
        recs = self.records
        fmt = _request_format(request)        # 'mcq' | 'msq' | 'choiceinteraction' | None
        wants_stim = _wants_stimulus(request)  # True | False | None

        def fmt_of(r: Dict[str, Any]) -> str:
            # fixture item_ids are 'sample-mcq-...' / 'sample-msq-...'
            iid = (r["item_id"] or "").lower()
            if "msq" in iid:
                return "msq"
            if "mcq" in iid:
                return "mcq"
            return (r["metadata"].get("interaction_type") or "").lower()

        def stim_of(r: Dict[str, Any]) -> bool:
            return bool(r["stimulus_xml"])

        want_fmt = None
        if fmt:
            if "msq" in fmt or "multiple" in fmt:
                want_fmt = "msq"
            elif "mcq" in fmt or "single" in fmt or "choice" in fmt:
                want_fmt = "mcq"

        pool = recs
        if want_fmt is not None:
            narrowed = [r for r in recs if fmt_of(r) == want_fmt]
            if narrowed:
                pool = narrowed
        if wants_stim is not None:
            narrowed2 = [r for r in pool if stim_of(r) == wants_stim]
            if narrowed2:
                pool = narrowed2

        # deterministic index into the chosen pool
        key = _stable_request_key(request)
        idx = int(hashlib.sha1(key.encode("utf-8")).hexdigest(), 16) % len(pool)
        return pool[idx]


# ===========================================================================
# Deterministic id minting + XML id-rewrite
# ===========================================================================
def _mint_item_id(request: Any) -> str:
    return "g3item-" + _stable_request_key(request)[:16]


def _mint_stimulus_id(request: Any, src_stimulus_id: Optional[str]) -> str:
    # tie the stimulus id to the request too, so it's unique per request and
    # deterministic on re-run; keep the 'stim_' prefix Mayank/arpack expect.
    seed = _stable_request_key(request) + "|" + (src_stimulus_id or "")
    return "stim_g3-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def _rewrite_root_identifier(xml: str, new_id: str) -> str:
    """Replace the FIRST identifier="..." attribute (the root element's id)."""
    return re.sub(r'identifier="[^"]*"', f'identifier="{new_id}"', xml, count=1)


def _rewrite_stimulus_link(item_xml: str, old_sid: Optional[str], new_sid: str) -> str:
    """Repoint the item's <qti-assessment-stimulus-ref> at the new stimulus id.

    Rewrites both the ref's identifier and its href (which is 'stimuli/<id>.xml').
    """
    def _repl(m: re.Match) -> str:
        tag = m.group(0)
        tag = re.sub(r'identifier="[^"]*"', f'identifier="{new_sid}"', tag)
        tag = re.sub(r'href="[^"]*"', f'href="stimuli/{new_sid}.xml"', tag)
        return tag

    return re.sub(r"<qti-assessment-stimulus-ref\b[^>]*/?>", _repl, item_xml, count=1)


# ===========================================================================
# STUB backend
# ===========================================================================
def _generate_stub(request: Any, fixture_dir: str) -> Dict[str, Any]:
    fixture = _Fixture.load(fixture_dir)
    src = fixture.pick(request)

    new_item_id = _mint_item_id(request)
    item_xml = _rewrite_root_identifier(src["item_xml"], new_item_id)

    new_stim_id: Optional[str] = None
    stimulus_xml: Optional[str] = None
    if src["stimulus_xml"]:
        new_stim_id = _mint_stimulus_id(request, src["stimulus_id"])
        stimulus_xml = _rewrite_root_identifier(src["stimulus_xml"], new_stim_id)
        # Mayank bakes the source hash into the cosmetic title ("Stimulus stim_<hash>");
        # retarget it at the new id so the package carries no dangling source reference.
        if src["stimulus_id"]:
            stimulus_xml = stimulus_xml.replace(
                f"Stimulus {src['stimulus_id']}", f"Stimulus {new_stim_id}"
            )
        item_xml = _rewrite_stimulus_link(item_xml, src["stimulus_id"], new_stim_id)

    metadata = dict(src["metadata"])
    metadata.setdefault("interaction_type", "choiceInteraction")
    metadata.setdefault("feedback_type", "nonadaptive")
    # provenance breadcrumb (does NOT serialize into the Alpha Read package;
    # arpack ignores unknown metadata keys — handy for the RUN_REPORT).
    metadata["_source"] = "stub:mayank_fixture"
    metadata["_source_item_id"] = src["item_id"]

    return {
        "item_id": new_item_id,
        "item_xml": item_xml,
        "stimulus_xml": stimulus_xml,
        "stimulus_id": new_stim_id,
        "metadata": metadata,
    }


# ===========================================================================
# REAL backend — documented interface, intentionally not wired.
# ===========================================================================
#: Where the live generator lives. Swap to taste when wiring the REAL backend.
REAL_GENERATOR_ENDPOINT = os.environ.get(
    "ALPHA_READ_GENERATOR_URL",
    "https://generator.incept.example/v1/build",  # placeholder — confirm with Mayank
)


def _real_request_body(request: Any) -> Dict[str, Any]:
    """The exact JSON we WILL POST to Mayank's generator / InceptBench.

    This is the r2 request (built by gen_request.py) wrapped for the build API.
    Standards / kct / map_goal_area are generator-TARGETING metadata: they steer
    generation but do NOT serialize into the Alpha Read package.
    """
    return {
        "request": _as_dict(request),
        "output": {
            "format": "qti-3.0",
            "stimulus_mode": "separate",   # mirrors his `--stimulus-mode separate`
        },
        "quantity": _as_dict(request).get("quantity", 1),
    }


def _generate_real(request: Any) -> Dict[str, Any]:
    body = _real_request_body(request)
    raise NotImplementedError(
        "generator_client REAL backend is not wired yet (the STUB runs the whole "
        "pipeline on Mayank's real QTI today; this real backend is the not-yet-wired "
        "one-line swap when his generator is live).\n"
        "WHEN WIRED it will:\n"
        f"  POST {REAL_GENERATOR_ENDPOINT}\n"
        "  Content-Type: application/json\n"
        f"  body = {json.dumps(body, indent=2, default=str)}\n"
        "and map the response back into the SAME BuildResult dict the stub returns:\n"
        "  {item_id, item_xml, stimulus_xml, stimulus_id, metadata{interaction_type,feedback_type}}\n"
        "No other call site changes — course_orchestrator only sees that dict."
    )


# ===========================================================================
# Public entry point
# ===========================================================================
def generate(
    request: Any,
    backend: str = "stub",
    *,
    fixture_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate ONE Mayank-shaped BuildResult for an r2 generation request.

    Args:
        request:  an r2 request (dict or gen_request object). Only its
                  identifying fields are read; unknown fields are ignored.
        backend:  "stub" (default, real fixture XML, no network) or "real"
                  (documented POST, NotImplemented until wired).
        fixture_dir: override the stub's fixture source (else the checked-in
                  Mayank fixture, or $ALPHA_READ_FIXTURE_DIR).

    Returns:
        {item_id, item_xml, stimulus_xml, stimulus_id, metadata}

    Idempotent: same request -> same ids -> re-runs converge.
    """
    backend = (backend or "stub").lower()
    if backend == "stub":
        return _generate_stub(request, fixture_dir or DEFAULT_FIXTURE_DIR)
    if backend == "real":
        return _generate_real(request)
    raise ValueError(f"generator_client.generate: unknown backend {backend!r} "
                     f"(expected 'stub' or 'real')")


# ---------------------------------------------------------------------------
# Self-proof: run `python generator_client.py` to see it return real Mayank XML.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sample_requests = [
        {  # MCQ tied to a passage
            "lesson_id": "L1", "topic": "Why leaves change color",
            "band": "B", "lexile_band": "480-540", "genre": "informational",
            "structure_schema": "cause-effect", "format": "mcq",
            "stimulus": {"ref": "passage-leaves"}, "role": "quiz",
        },
        {  # MSQ, no passage
            "lesson_id": "L1", "topic": "Main idea practice",
            "band": "A", "lexile_band": "400-460", "genre": "informational",
            "format": "msq", "role": "guiding",
        },
        {  # same as the first request -> must reproduce identical ids
            "lesson_id": "L1", "topic": "Why leaves change color",
            "band": "B", "lexile_band": "480-540", "genre": "informational",
            "structure_schema": "cause-effect", "format": "mcq",
            "stimulus": {"ref": "passage-leaves"}, "role": "quiz",
        },
    ]

    print("=" * 78)
    print("generator_client.generate(backend='stub') — real Mayank XML, id-rewritten")
    print("=" * 78)
    results = []
    for i, req in enumerate(sample_requests):
        r = generate(req, backend="stub")
        results.append(r)
        print(f"\n--- request #{i} (topic={req['topic']!r}, format={req['format']}) ---")
        print(f"item_id      : {r['item_id']}")
        print(f"stimulus_id  : {r['stimulus_id']}")
        print(f"metadata     : {r['metadata']}")
        print(f"item_xml[0:1]: well-formed={r['item_xml'].lstrip().startswith('<?xml')}, "
              f"len={len(r['item_xml'])}, "
              f"identifier-rewritten={('identifier=\"' + r['item_id'] + '\"') in r['item_xml']}")
        if r["stimulus_xml"]:
            print(f"stim_xml     : len={len(r['stimulus_xml'])}, "
                  f"identifier-rewritten={('identifier=\"' + r['stimulus_id'] + '\"') in r['stimulus_xml']}, "
                  f"item-ref-repointed={r['stimulus_id'] in r['item_xml']}")

    # idempotency proof
    print("\n" + "-" * 78)
    same = results[0]["item_id"] == results[2]["item_id"] and \
        results[0]["stimulus_id"] == results[2]["stimulus_id"]
    print(f"IDEMPOTENT (req#0 ids == req#2 ids, identical request): {same}")
    distinct = results[0]["item_id"] != results[1]["item_id"]
    print(f"DISTINCT  (req#0 id != req#1 id, different request):    {distinct}")

    # show a slice of real rewritten XML so a human can eyeball it
    print("\n" + "-" * 78)
    print("First 1100 chars of request#0's item_xml (REAL Mayank QTI, id-rewritten):")
    print("-" * 78)
    print(results[0]["item_xml"][:1100])

    # REAL backend: prove the documented interface
    print("\n" + "=" * 78)
    print("generator_client.generate(backend='real') — documented, intentionally unwired")
    print("=" * 78)
    try:
        generate(sample_requests[0], backend="real")
    except NotImplementedError as e:
        print(str(e))
