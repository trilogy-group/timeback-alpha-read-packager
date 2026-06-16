"""gen_request.py — Stream S1 of the Grade-3 Reading course orchestrator.

Turns ONE lesson (a skeleton_adapter lesson shell + its unit context) into the
**r2 generation request** the course_orchestrator fans out to generator_client:

    build_lesson_request(lesson, unit) -> {
        "lesson_id":   <stable id>,
        "stage0":      <Stage-0 passage request>,    # one passage per lesson
        "items": [     <per-item generation request>, ... ]   # guiding[] + 4 quiz[]
    }

WHAT THIS MODULE OWNS (and what it deliberately does NOT):
  * It is **generator-targeting metadata only**. Standards / KCT / MAP goal area /
    distractor specs / DOK steer Mayank's generator (or InceptBench) toward the right
    item — they are NOT serialized into the Alpha Read package. arpack.assemble() reads
    title/sortOrder/lessons; everything here rides as a request, then the *returned QTI*
    is what gets packaged. (See arpack.from_qti_xml: rich r2 metadata passes through the
    QTI verbatim; this module just asks for it.)
  * It writes NO files and imports NOTHING from arpack (no coupling; pure data builder).
  * It is **deterministic**: same lesson in -> same request out (idempotent ids). The
    orchestrator depends on this so a re-run converges instead of duplicating items.

BAND MODEL (mirrors skeleton_adapter.BAND_LEXILE exactly — kept local to avoid an import
cycle; the values are a fixed contract, not config):
    Band A -> lexile 400-460   |  Band B -> 480-540  |  Band C -> 560-600
Band also drives warmth, illustration_level, novelty, scaffolds, and DOK ceiling — an
8-year-old at Band A gets a warmer, more illustrated, lower-novelty passage with heavier
scaffolds than a Band C reader. (Child-safety / age-appropriateness is a north-star gate.)

COUNTS (mirror arpack contract constants — GUIDING_MIN/MAX = 3..6, QUIZ_ITEMS = 4):
    guiding items: default 3 (a stimulus-anchored, scaffolded teach item per lesson)
    quiz items:    fixed 4 (the cold assessment; arpack enforces exactly 4)
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

# --- fixed contract constants (mirrors of arpack / skeleton_adapter; NOT config) -------
# Band -> default lexile band. Identical to skeleton_adapter.BAND_LEXILE. An explicit
# per-lesson lexile (lesson["lexileLevel"]) ALWAYS wins over this default.
BAND_LEXILE: Dict[str, tuple] = {"A": (400, 460), "B": (480, 540), "C": (560, 600)}

# Mirrors arpack.GUIDING_MIN / GUIDING_MAX / QUIZ_ITEMS. We ask for the floor of guiding
# (3) by default — re-balanceable per lesson — and exactly the required 4 quiz items.
DEFAULT_GUIDING_COUNT = 3
GUIDING_MIN, GUIDING_MAX = 3, 6
QUIZ_ITEMS = 4

GRADE = 3
SUBJECT = "Language"
STANDARD_FRAMEWORK = "CCSS"

# Per-band knobs for a Grade-3 (8-year-old) reader. These are warmth / age-appropriateness
# dials, NOT lexile (lexile is handled above). Lower bands = warmer, more illustrated, less
# novel, more scaffolded.
BAND_PROFILE: Dict[str, Dict[str, Any]] = {
    "A": {
        "warmth": "high",                  # encouraging, gentle tone; short sentences
        "illustration_level": "rich",      # heavy illustration support
        "novelty": "low",                  # familiar everyday topics, concrete
        "length_words": 180,               # short passage
        "dok_ceiling": 2,                  # recall + basic skill; no DOK-3 at Band A
        "p_m_target": 0.75,                # target item difficulty (proportion-correct)
        "scaffolds": {
            "vocab_preview": True,         # pre-teach hard words
            "sentence_starters": True,     # stems for constructed responses
            "rebus_or_picture_support": True,
            "chunked_text": True,          # passage broken into small labelled chunks
            "audio_support": True,         # read-aloud available
        },
    },
    "B": {
        "warmth": "medium",
        "illustration_level": "moderate",
        "novelty": "medium",
        "length_words": 260,
        "dok_ceiling": 3,
        "p_m_target": 0.65,
        "scaffolds": {
            "vocab_preview": True,
            "sentence_starters": False,
            "rebus_or_picture_support": False,
            "chunked_text": True,
            "audio_support": True,
        },
    },
    "C": {
        "warmth": "medium",
        "illustration_level": "light",
        "novelty": "high",
        "length_words": 340,
        "dok_ceiling": 3,
        "p_m_target": 0.6,
        "scaffolds": {
            "vocab_preview": False,
            "sentence_starters": False,
            "rebus_or_picture_support": False,
            "chunked_text": False,
            "audio_support": True,
        },
    },
}

# Genre (free text in Anirudh's table) -> a structure schema for the Stage-0 passage.
# These are the four CCSS-aligned informational/narrative structures a Grade-3 passage can
# carry. We map common genre words; anything unknown falls back to 'sequence' (the safest,
# most universally-teachable structure for a grade-3 reader).
_GENRE_STRUCTURE: Dict[str, str] = {
    "informational": "cause-effect",
    "informative": "cause-effect",
    "expository": "cause-effect",
    "science": "cause-effect",
    "nonfiction": "compare",
    "biography": "sequence",
    "history": "sequence",
    "historical": "sequence",
    "narrative": "sequence",
    "story": "sequence",
    "fiction": "sequence",
    "fable": "problem-solution",
    "folktale": "problem-solution",
    "persuasive": "problem-solution",
    "opinion": "problem-solution",
    "procedural": "sequence",
    "how-to": "sequence",
    "compare": "compare",
    "comparison": "compare",
}
DEFAULT_STRUCTURE = "sequence"
STRUCTURE_SCHEMAS = {"cause-effect", "problem-solution", "compare", "sequence"}

# The 5 reading Knowledge-Component Types we steer items across (generator-targeting only).
# A lesson's guiding+quiz set is spread over these so a single lesson exercises a range of
# comprehension skills rather than four near-duplicate recall items.
KCT_CYCLE = ["KCT1", "KCT2", "KCT3", "KCT4", "KCT5"]
KCT_DESC = {
    "KCT1": "key ideas & details — locate explicit information",
    "KCT2": "inference — draw a conclusion supported by the text",
    "KCT3": "vocabulary in context — word meaning from surrounding text",
    "KCT4": "text structure — identify how the passage is organized",
    "KCT5": "integration — connect ideas across the passage",
}
# KCT -> NWEA MAP Reading goal area (generator-targeting; not serialized).
KCT_MAP_GOAL = {
    "KCT1": "Informational Text: Key Ideas",
    "KCT2": "Literature & Informational: Inference",
    "KCT3": "Vocabulary Acquisition & Use",
    "KCT4": "Informational Text: Craft & Structure",
    "KCT5": "Literature & Informational: Integration of Ideas",
}

# Allowed Alpha Read item formats. quiz is single-select MCQ by default (cleanest cold
# measurement); guiding items get a small variety so the teach phase isn't monotone.
QUIZ_FORMAT = "mcq"
GUIDING_FORMAT_CYCLE = ["mcq", "hot-text", "drag-to-order"]
ALLOWED_FORMATS = {"mcq", "msq", "fill-in", "hot-text", "drag-to-order", "match", "ebsr"}


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
def _band_of(lesson: Dict[str, Any], unit: Optional[Dict[str, Any]]) -> str:
    """Band 'A'/'B'/'C'. Lesson wins, then unit, then default to 'B' (the safe middle)."""
    for src in (lesson, unit or {}):
        for key in ("band", "_band"):
            b = src.get(key)
            if b:
                b = str(b).strip().upper()
                if b in BAND_LEXILE:
                    return b
    return "B"


def _lexile_band(lesson: Dict[str, Any], unit: Optional[Dict[str, Any]], band: str) -> List[int]:
    """[lo, hi] lexile band. Priority: explicit unit lexile_band > band default.
    A per-lesson scalar lexileLevel (Mayank's true level) recenters the band around it."""
    lo_hi = None
    if unit and isinstance(unit.get("lexile_band"), (list, tuple)) and len(unit["lexile_band"]) == 2:
        lo_hi = [int(unit["lexile_band"][0]), int(unit["lexile_band"][1])]
    if lo_hi is None:
        lo_hi = list(BAND_LEXILE[band])
    # If the lesson shell carries a concrete lexileLevel, recenter the band around it
    # (keep the band's width) so the passage targets the lesson's real level.
    lvl = lesson.get("lexileLevel")
    try:
        lvl = int(str(lvl).rstrip("Ll")) if lvl not in (None, "") else None
    except (TypeError, ValueError):
        lvl = None
    if lvl is not None:
        half = (lo_hi[1] - lo_hi[0]) // 2
        lo_hi = [lvl - half, lvl + half]
    return lo_hi


def _structure_of(lesson: Dict[str, Any], unit: Optional[Dict[str, Any]]) -> str:
    """structure_schema for the passage. Explicit lesson/unit structure wins; else derive
    from genre; else the default. Always returns a member of STRUCTURE_SCHEMAS."""
    for src in (lesson, unit or {}):
        s = src.get("structure") or src.get("structure_schema")
        if s and str(s).strip().lower() in STRUCTURE_SCHEMAS:
            return str(s).strip().lower()
    genre = (lesson.get("genre") or (unit or {}).get("genre") or "").strip().lower()
    for key, schema in _GENRE_STRUCTURE.items():
        if key in genre:
            return schema
    return DEFAULT_STRUCTURE


def _topic_of(lesson: Dict[str, Any], unit: Optional[Dict[str, Any]]) -> str:
    """A human topic string for the passage — the lesson title, contextualized by its unit."""
    title = (lesson.get("title") or "").strip()
    unit_title = (unit or {}).get("title", "").strip()
    if unit_title and unit_title.lower() not in title.lower():
        return f"{title} (unit: {unit_title})"
    return title or unit_title or "Untitled lesson"


def _lesson_id(lesson: Dict[str, Any], unit: Optional[Dict[str, Any]]) -> str:
    """Stable, deterministic lesson id. Prefers the skeleton vendorId (already stable and
    matches the live article_<id> numbering); falls back to a content hash so a lesson with
    no vendorId still gets a reproducible id (idempotency requirement)."""
    vid = lesson.get("vendorId") or lesson.get("id")
    if vid:
        return f"lesson_{vid}"
    basis = f"{(unit or {}).get('title', '')}|{lesson.get('title', '')}|{lesson.get('sortOrder', '')}"
    return "lesson_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def _item_id(lesson_id: str, role: str, n: int) -> str:
    """Deterministic per-item request id: lesson_<vid>_<role><n>. The generator may return
    its own QTI identifiers; this is the *request* id the orchestrator keys on for idempotent
    collection (re-run -> same slot, no duplicate)."""
    return f"{lesson_id}_{role}{n}"


def _standard_for(kct: str, lesson: Dict[str, Any], unit: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """CCSS standard block for an item. If the unit's coverage names explicit standards we
    pass the first through as the substandard_id; otherwise we attach a representative
    Grade-3 Reading-Informational CCSS substandard keyed by KCT. Generator-targeting only."""
    coverage = (unit or {}).get("coverage") or {}
    explicit = coverage.get("standards") or []
    # Representative CCSS Grade-3 substandards by comprehension skill (KCT).
    by_kct = {
        "KCT1": ("CCSS.ELA-LITERACY.RI.3.1",
                 "Ask and answer questions, referring explicitly to the text."),
        "KCT2": ("CCSS.ELA-LITERACY.RI.3.1",
                 "Refer to the text as the basis for inferences."),
        "KCT3": ("CCSS.ELA-LITERACY.RI.3.4",
                 "Determine the meaning of words and phrases in a grade-3 text."),
        "KCT4": ("CCSS.ELA-LITERACY.RI.3.8",
                 "Describe the logical connection between sentences and paragraphs."),
        "KCT5": ("CCSS.ELA-LITERACY.RI.3.9",
                 "Compare and contrast key points in two texts on the same topic."),
    }
    sub_id, desc = by_kct.get(kct, by_kct["KCT1"])
    if explicit:
        sub_id = str(explicit[0])
    return {"framework": STANDARD_FRAMEWORK, "substandard_id": sub_id, "description": desc}


def _distractor_spec(kct: str, band: str) -> Dict[str, Any]:
    """Distractor design spec for an MCQ/MSQ item. The distractor 'family' tracks the skill
    being tested so wrong answers are plausible-but-diagnostic, never obvious throwaways."""
    family = {
        "KCT1": "plausible-detail-from-passage",     # a real detail, but not the answer
        "KCT2": "surface-reading-misconception",     # what a literal reader would pick
        "KCT3": "near-synonym-wrong-context",        # right-ish word, wrong sense
        "KCT4": "structure-confusion",               # confuses cause/effect order etc.
        "KCT5": "single-point-not-integrated",       # true of one part, not the whole
    }.get(kct, "plausible-detail-from-passage")
    return {
        "family": family,
        "near_neighbour": True,         # at least one distractor is a close near-neighbour
        "no_obvious_wrong": True,       # no joke/throwaway options (esp. for 8-year-olds)
        "count": 3,                     # 3 distractors + 1 key = 4 choices
    }


# --------------------------------------------------------------------------------------
# Stage-0 passage request
# --------------------------------------------------------------------------------------
def build_passage_request(lesson: Dict[str, Any], unit: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The r2 **Stage-0 passage** request: ONE shared stimulus per lesson, sized & warmed by
    band, structured by genre. The guiding items anchor to this passage; quiz items may be
    cold (no stimulus) or anchored, per the item requests below."""
    band = _band_of(lesson, unit)
    profile = BAND_PROFILE[band]
    return {
        "topic": _topic_of(lesson, unit),
        "lexile_band": _lexile_band(lesson, unit, band),     # [lo, hi]
        "genre": (lesson.get("genre") or (unit or {}).get("genre") or "informational"),
        "structure_schema": _structure_of(lesson, unit),     # cause-effect|problem-solution|compare|sequence
        "length_words": profile["length_words"],
        "warmth": profile["warmth"],
        "illustration_level": profile["illustration_level"],
        "novelty": profile["novelty"],
        # echo the band so the orchestrator/generator never has to re-derive it
        "band": band,
        "grade": GRADE,
    }


# --------------------------------------------------------------------------------------
# per-item generation request
# --------------------------------------------------------------------------------------
def build_item_request(
    lesson: Dict[str, Any],
    unit: Optional[Dict[str, Any]],
    *,
    role: str,                  # "guiding" | "quiz"
    n: int,                     # 1-based index within its role
    lesson_id: str,
    stimulus_ref: Optional[str],
    kct: str,
    fmt: str,
) -> Dict[str, Any]:
    """One r2 item generation request (quantity:1). `role` decides whether it anchors to the
    Stage-0 stimulus (guiding -> yes) and how heavily it's scaffolded (guiding gets the band's
    full scaffolds; quiz is a colder measurement with scaffolds stripped to read-aloud only)."""
    band = _band_of(lesson, unit)
    profile = BAND_PROFILE[band]
    is_guiding = role == "guiding"

    # DOK ramps a little with item index but never exceeds the band ceiling.
    dok = min(profile["dok_ceiling"], 1 + (n - 1) // 2 + (0 if is_guiding else 1))
    dok = max(1, min(dok, profile["dok_ceiling"]))

    # Scaffolds: guiding items get the band's full scaffold set; quiz items are a cold
    # measurement — keep only audio_support (accessibility), strip teaching scaffolds.
    if is_guiding:
        scaffolds = dict(profile["scaffolds"])
    else:
        scaffolds = {k: (v if k == "audio_support" else False)
                     for k, v in profile["scaffolds"].items()}

    req: Dict[str, Any] = {
        "request_id": _item_id(lesson_id, role, n),
        "role": role,                        # guiding -> teach (anchored), quiz -> assess (cold)
        "grade": GRADE,
        "subject": SUBJECT,
        "standard": _standard_for(kct, lesson, unit),
        "kct": kct,
        "kct_description": KCT_DESC.get(kct, ""),
        "map_goal_area": KCT_MAP_GOAL.get(kct, ""),
        "stimulus": {"ref": stimulus_ref} if (is_guiding and stimulus_ref) else None,
        "format": fmt,
        "difficulty": {"dok": dok, "p_m_target": profile["p_m_target"]},
        "scaffolds": scaffolds,
        "quantity": 1,
    }
    # distractor spec only applies to selection formats
    if fmt in ("mcq", "msq", "ebsr"):
        req["distractor_spec"] = _distractor_spec(kct, band)
    return req


# --------------------------------------------------------------------------------------
# top-level: one lesson -> full request bundle
# --------------------------------------------------------------------------------------
def build_lesson_request(
    lesson: Dict[str, Any],
    unit: Optional[Dict[str, Any]] = None,
    *,
    guiding_count: int = DEFAULT_GUIDING_COUNT,
    quiz_count: int = QUIZ_ITEMS,
) -> Dict[str, Any]:
    """The S1 entry point. Given a skeleton lesson shell + its unit context, build:
        - the Stage-0 passage request (one shared stimulus),
        - `guiding_count` guiding item requests (stimulus-anchored, scaffolded),
        - `quiz_count` quiz item requests (cold MCQ measurement),
    cycling KCTs across the items so a lesson exercises a spread of reading skills.

    Deterministic: same inputs -> identical output (stable request ids). The orchestrator
    fans these out to generator_client.generate() in parallel and collects the returned QTI
    into the lesson's {guiding[], quiz[]}.

    The `stimulus.ref` here is a *logical* ref (the lesson's own stimulus slot); the real
    stimulus identifier is whatever the generator returns and arpack threads through.
    """
    guiding_count = max(GUIDING_MIN, min(guiding_count, GUIDING_MAX))
    lesson_id = _lesson_id(lesson, unit)
    stimulus_ref = f"{lesson_id}_stimulus"

    stage0 = build_passage_request(lesson, unit)

    items: List[Dict[str, Any]] = []
    # guiding items: cycle KCT1.. and the guiding format variety, all anchored to the passage
    for i in range(guiding_count):
        items.append(build_item_request(
            lesson, unit,
            role="guiding", n=i + 1, lesson_id=lesson_id,
            stimulus_ref=stimulus_ref,
            kct=KCT_CYCLE[i % len(KCT_CYCLE)],
            fmt=GUIDING_FORMAT_CYCLE[i % len(GUIDING_FORMAT_CYCLE)],
        ))
    # quiz items: 4 cold single-select MCQ, KCTs spread (offset so they don't echo guiding 1:1)
    for i in range(quiz_count):
        items.append(build_item_request(
            lesson, unit,
            role="quiz", n=i + 1, lesson_id=lesson_id,
            stimulus_ref=stimulus_ref,            # quiz items may still reference the passage
            kct=KCT_CYCLE[(i + 1) % len(KCT_CYCLE)],
            fmt=QUIZ_FORMAT,
        ))

    return {
        "lesson_id": lesson_id,
        "title": lesson.get("title", ""),
        "band": stage0["band"],
        "stimulus_ref": stimulus_ref,
        "stage0": stage0,
        "items": items,
        "counts": {"guiding": guiding_count, "quiz": quiz_count},
    }


# --------------------------------------------------------------------------------------
# example (printed when run directly) — one Band-A lesson, no file writes
# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    import json

    # A Band-A lesson shell as skeleton_adapter would emit it, with its unit context.
    example_unit = {
        "title": "Animals and Their Homes",
        "band": "A",
        "genre": "informational",
        "lexile_band": [400, 460],
        "sortOrder": 0,
        "coverage": {
            "standards": ["CCSS.ELA-LITERACY.RI.3.1"],
            "new_at_band": ["main idea", "key details"],
        },
    }
    example_lesson = {
        "vendorId": 3000001,
        "title": "Why Beavers Build Dams",
        "lexileLevel": "430",
        "grade": "3",
        "measuredReadingGrade": "3",
        "genre": "informational",
        "_needs_items": True,
    }

    bundle = build_lesson_request(example_lesson, example_unit)
    print("=== r2 generation request for one Band-A lesson ===")
    print(json.dumps(bundle, indent=2))
