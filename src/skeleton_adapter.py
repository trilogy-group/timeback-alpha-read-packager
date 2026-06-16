#!/usr/bin/env python3
"""
skeleton_adapter — Anirudh SKELETON adapter for arpack (Stream S3, zero reshaping by Anirudh)

Anirudh owns an expedition -> standards mapping: ~10 expeditions, each with a band (A/B/C),
genre, NWEA-MAP standards, and a 'new-at-band' note. He sends it as a CSV or JSON *table*.
He must NOT reshape it to arpack's nested units[] schema. This module adapts HIS table to
the units[] layer that arpack.assemble() consumes.

WHAT IT EMITS (the units[] layer arpack needs):
  [{ "title", "sortOrder", "band", "lexile_band":[lo,hi], "genre",
     "coverage": {"standards":[...], "new_at_band":[...], "expedition_id":...},
     "lessons": [ {"vendorId", "title", "lexileLevel", "_needs_items": True}, ... ] }]
arpack.assemble() reads .title/.sortOrder/.lessons[].vendorId/.title; the rest rides along as
non-serialized COVERAGE metadata (standards are NOT stored in production — verified 0/1077 items
carry them — so they stay coverage-only and never enter the package).

GROUND-TRUTH RECONCILIATION (verified against the live Grade-3 export, course 4c49bc61):
  * Real per-lesson lexileLevel spans 530..740, NOT the 400..600 the band table implies. So band
    -> lexile_band is only a DEFAULT/fallback. An explicit `lexile` column (per row) ALWAYS wins,
    and any item-level lexile that arrives later via Mayank overrides this again.
  * sortOrder follows band order A -> B -> C, then the row's own sortOrder/order, then file order.
  * Standards / genre / band / expedition are stored NOWHERE in the package -> coverage only.

THE PER-LESSON GAP: Anirudh gives expedition-level rows, not per-lesson rows. So we synthesise
lesson SHELLS (title + vendorId + lexile), `lessons_per_expedition` of them (default 4 ~= the live
mean of 4.44), each flagged `_needs_items` so Mayank's QTI items fill them. If a row already names
its lessons (a `lessons` cell or a child list), we use those verbatim and skip synthesis.

MINIMAL COLUMN CONTRACT (everything else is optional / tolerated / ignored):
  REQUIRED (exactly one of):
    expedition            -- the expedition/unit name (aka title/unit/name/topic)
  STRONGLY RECOMMENDED:
    band                  -- A | B | C  (aka level/tier/readingBand); drives sortOrder + default lexile
  OPTIONAL (used if present, tolerated if absent):
    lexile                -- e.g. "560" or "560L" or "560-600"  (overrides band default)
    genre                 -- free text, coverage only
    sortOrder / order     -- explicit ordering within a band
    standards             -- ; or , or | separated  (aka nweaStandards/maps/skills); coverage only
    new_at_band           -- ; or , or | separated  (aka newAtBand/new); coverage only
    lessons               -- N (a count) OR a ;/,/| list of lesson titles for this expedition
    lessons_per_expedition / lessonsPerExpedition  -- per-row override of the global default
    lexile_lo / lexile_hi -- explicit band range, overrides the band default range
  TOLERATED: any extra columns (ignored), header case/spacing/underscores/hyphens, BOM, blank rows.
"""
import csv, io, json, re

# Band -> default lexile range. DEFAULTS ONLY — an explicit lexile column always overrides.
# Ranges are the Anirudh band model; real lessons run hotter (530-740), so these are floors to
# seed shells before Mayank's items (which carry the true per-item lexile) land.
BAND_LEXILE = {"A": (400, 460), "B": (480, 540), "C": (560, 600)}
BAND_ORDER = {"A": 0, "B": 1, "C": 2}
DEFAULT_LESSONS_PER_EXPEDITION = 4          # live mean is 4.44 lessons/unit; 4 is the median
VENDOR_ID_BASE = 3000001                    # matches the live article_3000001.. numbering

# ---- header normalisation: tolerate case / spaces / underscores / hyphens / aliases ----
def _norm(h):
    return re.sub(r"[^a-z0-9]+", "", (h or "").strip().lower())

# every alias on the left maps to a canonical key on the right
_ALIASES = {
    "expedition": "expedition", "unit": "expedition", "title": "expedition",
    "name": "expedition", "topic": "expedition", "expeditionname": "expedition",
    "band": "band", "level": "band", "tier": "band", "readingband": "band",
    "lexile": "lexile", "lexilelevel": "lexile", "lexilerange": "lexile",
    "lexilelo": "lexile_lo", "lexilemin": "lexile_lo", "lexilelow": "lexile_lo",
    "lexilehi": "lexile_hi", "lexilemax": "lexile_hi", "lexilehigh": "lexile_hi",
    "genre": "genre", "texttype": "genre",
    "sortorder": "sort_order", "order": "sort_order", "sequence": "sort_order", "seq": "sort_order",
    "standards": "standards", "nweastandards": "standards", "maps": "standards",
    "mapstandards": "standards", "skills": "standards", "standard": "standards",
    "newatband": "new_at_band", "new": "new_at_band", "newskills": "new_at_band",
    "lessons": "lessons", "lessontitles": "lessons",
    "lessonsperexpedition": "lessons_per_expedition", "lessoncount": "lessons_per_expedition",
    "lessonsper": "lessons_per_expedition", "numlessons": "lessons_per_expedition",
    "expeditionid": "expedition_id", "id": "expedition_id", "code": "expedition_id",
}

def _canon_row(row):
    """Map a raw dict row (arbitrary headers) to canonical keys; drop unknown columns."""
    out = {}
    for k, v in row.items():
        ck = _ALIASES.get(_norm(k))
        if ck and (v is not None) and str(v).strip() != "":
            out.setdefault(ck, str(v).strip())     # first non-empty wins on alias collision
    return out

def _split_multi(s):
    """Split a ; , | or newline separated cell into a clean list."""
    if not s:
        return []
    return [p.strip() for p in re.split(r"[;|,\n]+", str(s)) if p.strip()]

def _parse_lexile(s):
    """'560' / '560L' / '560-600' / '560 to 600' -> (lo, hi) ints, or None if unparseable."""
    if not s:
        return None
    nums = [int(n) for n in re.findall(r"\d+", str(s))]
    if not nums:
        return None
    return (nums[0], nums[-1]) if len(nums) >= 2 else (nums[0], nums[0])

def _band_of(s):
    """Normalise a band cell to 'A'/'B'/'C' (tolerate 'Band A', 'a', 'tier-b', numbers 1/2/3)."""
    if not s:
        return None
    t = str(s).strip().upper()
    # strip the words 'BAND'/'TIER'/'LEVEL' so 'Band C' doesn't match the A in BAND
    t = re.sub(r"\b(BAND|TIER|LEVEL)\b", " ", t).strip()
    m = re.search(r"[ABC]", t)
    if m:
        return m.group(0)
    return {"1": "A", "2": "B", "3": "C"}.get(t)


def from_skeleton_table(table, *, lessons_per_expedition=DEFAULT_LESSONS_PER_EXPEDITION,
                        vendor_id_base=VENDOR_ID_BASE):
    """Ingest Anirudh's expedition->standards table -> arpack units[] layer (lesson SHELLS).

    `table` may be:
      * a CSV string (with a header row), OR
      * a path to a .csv file, OR
      * a list[dict] (already-parsed rows, e.g. from JSON), OR
      * a JSON string of list[dict] or {"expeditions"/"rows"/"units": [...]}.
    Returns: list of unit dicts ready for arpack.assemble() (see module docstring for the shape).
    The lesson shells carry no items — they are placeholders Mayank's QTI items slot into.
    """
    rows = _load_rows(table)
    canon = [_canon_row(r) for r in rows]
    canon = [r for r in canon if r.get("expedition")]          # drop blank / junk rows

    units = []
    next_vid = vendor_id_base
    for idx, r in enumerate(canon):
        band = _band_of(r.get("band"))
        # lexile band: explicit lexile col > explicit lo/hi cols > band default > unknown
        lx = _parse_lexile(r.get("lexile"))
        if lx is None and (r.get("lexile_lo") or r.get("lexile_hi")):
            lo = _parse_lexile(r.get("lexile_lo")) or (None,)
            hi = _parse_lexile(r.get("lexile_hi")) or (None,)
            lo = lo[0] if lo and lo[0] is not None else None
            hi = hi[-1] if hi and hi[-1] is not None else lo
            lx = (lo, hi) if lo is not None else None
        if lx is None and band in BAND_LEXILE:
            lx = BAND_LEXILE[band]
        # a representative per-lesson lexile to seed shells (midpoint of the band)
        seed_lexile = str(round(sum(lx) / 2)) if lx else None

        # lessons: explicit titles win; else a count; else the global default
        lpe = lessons_per_expedition
        lessons_cell = r.get("lessons")
        explicit_titles = []
        if lessons_cell:
            if re.fullmatch(r"\d+", lessons_cell.strip()):
                lpe = int(lessons_cell.strip())
            else:
                explicit_titles = _split_multi(lessons_cell)
        if r.get("lessons_per_expedition") and re.fullmatch(r"\d+", str(r["lessons_per_expedition"]).strip()):
            lpe = int(str(r["lessons_per_expedition"]).strip())

        titles = explicit_titles or [f"{r['expedition']} — Lesson {n}" for n in range(1, lpe + 1)]
        lessons = []
        for n, lt in enumerate(titles, 1):
            lessons.append({
                "vendorId": next_vid,
                "title": lt,
                "lexileLevel": seed_lexile,        # default; Mayank's item lexile overrides later
                "grade": "3", "measuredReadingGrade": "3",
                "_needs_items": True,              # SHELL: guiding/quiz to be filled by Mayank's QTI
            })
            next_vid += 1

        units.append({
            "title": r["expedition"],
            "_band": band,
            "_explicit_order": _parse_int(r.get("sort_order")),
            "_file_idx": idx,
            "band": band,
            "lexile_band": list(lx) if lx else None,
            "genre": r.get("genre"),
            "coverage": {                          # NOT serialized into the package — coverage only
                "standards": _split_multi(r.get("standards")),
                "new_at_band": _split_multi(r.get("new_at_band")),
                "expedition_id": r.get("expedition_id"),
                "band": band, "genre": r.get("genre"),
            },
            "lessons": lessons,
        })

    # sortOrder: band (A->B->C) -> explicit row order -> original file order; stable + 1-based
    units.sort(key=lambda u: (BAND_ORDER.get(u["_band"], 99),
                              u["_explicit_order"] if u["_explicit_order"] is not None else 1_000_000,
                              u["_file_idx"]))
    for i, u in enumerate(units, 1):
        u["sortOrder"] = i
        for tmp in ("_band", "_explicit_order", "_file_idx"):
            u.pop(tmp, None)
    return units


# ---- loaders -------------------------------------------------------------------
def _load_rows(table):
    if isinstance(table, list):
        return table
    if isinstance(table, dict):
        for k in ("expeditions", "rows", "units", "data"):
            if isinstance(table.get(k), list):
                return table[k]
        return [table]
    s = table
    # a path?
    if isinstance(s, str) and "\n" not in s and len(s) < 1024:
        try:
            with open(s, encoding="utf-8-sig") as fh:
                s = fh.read()
        except (OSError, ValueError):
            pass
    s = s.lstrip("﻿")
    st = s.strip()
    if st.startswith("[") or st.startswith("{"):
        try:
            return _load_rows(json.loads(st))
        except json.JSONDecodeError:
            pass
    # CSV delimiter: pick the known delimiter that actually appears in the HEADER line. Do NOT
    # trust csv.Sniffer — on a single-column or ambiguous file it happily picks a letter (e.g. 'p'
    # in 'expedition') and shreds the headers. Count real delimiters; default to comma.
    header = s.splitlines()[0] if s.splitlines() else ""
    delim = max((",", "\t", ";", "|"), key=lambda d: header.count(d))
    if header.count(delim) == 0:
        delim = ","            # single-column file: any delimiter is fine, comma is the safe default
    return list(csv.DictReader(io.StringIO(s), delimiter=delim))


def _parse_int(s):
    if s is None:
        return None
    m = re.search(r"-?\d+", str(s))
    return int(m.group(0)) if m else None


# ---- selftest ------------------------------------------------------------------
_SAMPLE_CSV = """Expedition,Band,Lexile,Genre,Sort Order,Standards,New at Band,Lessons
Animal Classification,A,420,Informational,2,"Main Idea; Key Details","Sequencing",5
Norse Myths,B,500-540,Myth,1,"Theme; Character",Compare/Contrast,3
Ancient Rome,C,580,Informational,3,"Cause & Effect|Main Idea",Inference,
Poetry Appreciation,A,,Poetry,1,Figurative Language,,4
"""

def _selftest():
    units = from_skeleton_table(_SAMPLE_CSV)
    ok = True
    def chk(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            print("  FAIL:", msg)
    # 4 units, ordered A,A,B,C by band then explicit order
    chk(len(units) == 4, f"expected 4 units got {len(units)}")
    chk([u["band"] for u in units] == ["A", "A", "B", "C"], "band order A,A,B,C")
    chk([u["sortOrder"] for u in units] == [1, 2, 3, 4], "sortOrder is 1..4 contiguous")
    # within band A, explicit Sort Order 1 (Poetry) precedes 2 (Animal)
    band_a = [u["title"] for u in units if u["band"] == "A"]
    chk(band_a == ["Poetry Appreciation", "Animal Classification"], f"band-A order wrong: {band_a}")
    # lexile: explicit 420 used; range 500-540 parsed; band default for empty Poetry -> 400-460
    by_t = {u["title"]: u for u in units}
    chk(by_t["Animal Classification"]["lexile_band"] == [420, 420], "explicit lexile 420")
    chk(by_t["Norse Myths"]["lexile_band"] == [500, 540], "range lexile 500-540")
    chk(by_t["Ancient Rome"]["lexile_band"] == [580, 580], "explicit lexile 580")
    chk(by_t["Poetry Appreciation"]["lexile_band"] == [400, 460], "band-A default lexile")
    # lesson counts: explicit 5 / 3, default 4 for Ancient Rome (blank), explicit 4 for Poetry
    chk(len(by_t["Animal Classification"]["lessons"]) == 5, "5 lessons (explicit count)")
    chk(len(by_t["Norse Myths"]["lessons"]) == 3, "3 lessons")
    chk(len(by_t["Ancient Rome"]["lessons"]) == DEFAULT_LESSONS_PER_EXPEDITION, "default lessons")
    chk(len(by_t["Poetry Appreciation"]["lessons"]) == 4, "4 lessons")
    # vendorIds: globally unique, contiguous across the whole set, start at base
    # (assigned in file order BEFORE the band re-sort, so per-unit order may not be ascending)
    vids = [l["vendorId"] for u in units for l in u["lessons"]]
    chk(len(vids) == len(set(vids)), "vendorIds unique")
    chk(min(vids) == VENDOR_ID_BASE, "vendorId base")
    chk(sorted(vids) == list(range(min(vids), min(vids) + len(vids))), "vendorIds contiguous")
    # standards parsed as list, kept as coverage only (never a top-level serialized field)
    chk(by_t["Animal Classification"]["coverage"]["standards"] == ["Main Idea", "Key Details"], "standards split")
    chk(by_t["Ancient Rome"]["coverage"]["standards"] == ["Cause & Effect", "Main Idea"], "pipe-split standards")
    chk("standards" not in by_t["Animal Classification"], "standards not at unit top-level")
    chk(all(l.get("_needs_items") for u in units for l in u["lessons"]), "all lessons flagged _needs_items")
    # explicit lesson titles path
    units2 = from_skeleton_table([{"expedition": "X", "band": "B",
                                   "lessons": "Intro; Middle; End"}])
    chk([l["title"] for l in units2[0]["lessons"]] == ["Intro", "Middle", "End"], "explicit titles")
    # JSON-string input path + alias headers (unit/level/maps)
    units3 = from_skeleton_table('[{"unit":"Q","level":"Band C","maps":"S1;S2"}]')
    chk(units3[0]["band"] == "C", "alias level->band, 'Band C'->C")
    chk(units3[0]["coverage"]["standards"] == ["S1", "S2"], "alias maps->standards")
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if _selftest() else 1)
