#!/usr/bin/env python3
"""
arpack — Alpha Read PACKager  (Stan's track, B0039)

Turn a course skeleton + question items into a COMPLETE, contract-valid Alpha Read
course package (OneRoster v1p2 + QTI 3.0), ready to push to TimeBack.

Pipeline:  ingest -> assemble -> validate -> emit   (push is a separate, guarded step)
The contract is the triple-verified live production export (Alpha Read - Grade 3,
course 4c49bc61). Every invariant below was observed across 120 lessons / 1077 items.

Usage:
  python3 arpack.py --selftest                  # build+validate a sample, no I/O to TimeBack
  python3 arpack.py build skeleton.json out/    # assemble + validate + emit a package
  (push is intentionally NOT implemented here — see PUSH_NOTES at the bottom; it must
   only ever run against a course whose title starts with the throwaway prefix.)

INPUT skeleton schema (the contract for what feeds the packager):
{
  "course": {"title","courseCode","grades":["3"],"subjects":["Reading"],
             "org_sourcedId","contentGrade":"3"},
  "units": [
    {"title","sortOrder", "lessons": [
      {"vendorId": 3000001, "title", "xp": 12,
       "guiding": [                                   # 3..6 of these
         {"stimulus": {"title","html"},
          "item": {"title","prompt","choices":[a,b,c,d],"correct_index":0}}],
       "quiz": [                                       # EXACTLY 4
         {"title","prompt","choices":[a,b,c,d],"correct_index":0}]
      }]}]
}
Drop forever (no home in production): skillCode, lessonCode, any video/media.
"""
import json, os, re, sys
from xml.etree import ElementTree as ET

# ---- input adapter: ingest Mayank's NATIVE raw QTI 3.0 item XML (zero reshaping) ----
QTI_NS = "{http://www.imsglobal.org/xsd/imsqtiasi_v3p0}"
QTI_ITEM_BASE = "https://qti.alpha-1edtech.ai/api/assessment-items/"   # live item-ref host
# Vendored from Ilma's incept-timeback-plugin (authoritative, nightly-tested). HTML must be sanitized
# to valid XHTML before it leaves arpack — partial reimplementations are a known render-bug source.
try:
    from sanitize_html import full_sanitize as _full_sanitize
except Exception:
    _full_sanitize = None
def _sani(html):
    return _full_sanitize(html) if (_full_sanitize and html) else (html or "")
def _sani_prompt(prompt):
    """Sanitize a question STEM to XHTML for questionStructure.prompt. Bare text (the common case
    from parsed QTI / the simple skeleton spec) is wrapped in <p class="stem_paragraph"> — the live
    production convention (create-mcq.md) — so the stem is block-level valid XHTML, never naked text
    that the SAX parser can mangle. Already-marked-up HTML is sanitized as-is."""
    p = (prompt or "").strip()
    if not p:
        return ""
    looks_html = p.startswith("<") and p.endswith(">")
    return _sani(p) if looks_html else f'<p class="stem_paragraph">{_sani(p)}</p>'
_FEEDBACK_LOCALNAMES = {"qti-feedback-inline", "qti-feedback-block", "qti-rubric-block",
                        "qti-modal-feedback"}
_BLOCK_LOCALNAMES = {"p", "div", "br", "h1", "h2", "h3", "h4", "li", "blockquote", "tr"}

# r2 FORMAT -> QTI INTERACTION map (all 7 MAP-format families accepted; 'choice' stays the default
# so the live export's single-select items keep working unchanged).
#   mcq          -> qti-choice-interaction (single-select)
#   msq          -> qti-choice-interaction (multi-select)
#   fill-in      -> qti-text-entry-interaction
#   hot-text     -> qti-hottext-interaction
#   drag-to-order-> qti-order-interaction
#   match        -> qti-associate-interaction / qti-match-interaction
#   ebsr         -> two qti-choice-interactions (Part A claim + Part B evidence)
QTI_INTERACTION_BY_TAG = {
    "qti-choice-interaction": "choice",
    "qti-text-entry-interaction": "text-entry",
    "qti-extended-text-interaction": "extended-text",
    "qti-hottext-interaction": "hottext",
    "qti-order-interaction": "order",
    "qti-associate-interaction": "associate",
    "qti-match-interaction": "match",
    "qti-inline-choice-interaction": "inline-choice",
    "qti-gap-match-interaction": "gap-match",
}
# r2 logical format name -> the QTI interaction "type" we tag the item with
R2_FORMAT_TO_TYPE = {
    "mcq": "choice", "msq": "choice", "multiple-choice": "choice", "multi-select": "choice",
    "fill-in": "text-entry", "fill-in-the-blank": "text-entry", "text-entry": "text-entry",
    "hot-text": "hottext", "hottext": "hottext",
    "drag-to-order": "order", "order": "order",
    "match": "match", "associate": "match",
    "ebsr": "ebsr", "two-part": "ebsr",
}
# every type we accept as a fully-formed item (the validator must not hard-reject these)
ACCEPTED_ITEM_TYPES = {"choice", "text-entry", "extended-text", "hottext", "order",
                       "associate", "match", "inline-choice", "gap-match", "ebsr",
                       "select-point"}

# ── Ilma CRITICAL RULE 1: the API's JSON->XML converter is LOSSY ──────────────────
# JSON POST is SAFE for EXACTLY these 4 interaction families — the API faithfully
# round-trips their JSON dict (verified across 3 AP builds + interaction-types.md).
JSON_SAFE_TYPES = {"choice", "extended-text", "order", "text-entry"}
# EVERYTHING ELSE renders broken / scores wrong if JSON-modelled (the converter silently
# drops directedPair / hottext / gap-text / inline-choice / composite children). These MUST
# be emitted verbatim as the raw-XML envelope {"format":"xml","xml":<rawXml>} and pushed via
# XML POST. EBSR is composite (two response-decls) -> XML-only too. Anything in
# ACCEPTED_ITEM_TYPES that is NOT json-safe is, by definition, xml-only.
XML_ONLY_TYPES = ACCEPTED_ITEM_TYPES - JSON_SAFE_TYPES   # hottext/match/associate/ebsr/
                                                         # inline-choice/gap-match/select-point

def _is_xml_only(spec):
    """The ONE decision point for the Ilma RULE 1 split, evaluated per ITEM (not just per type).
    A type in XML_ONLY_TYPES is always XML-only. ADDITIONALLY a MULTI-blank text-entry is XML-only:
    text-entry is JSON-safe ONLY for a single blank (one RESPONSE -> one input box). A fill-in with
    >1 blank has >1 inline qti-text-entry-interaction + >1 response-declaration, which the documented
    single-interaction JSON model cannot carry — the converter merges the blanks into one synonym pool
    and drops the inline placeholders (verified: sample-fill-in-multi). Ship its verbatim XML instead.
    `spec` is either a parsed-item struct or the adapted struct (both carry 'format'/'text_blanks')."""
    fmt = spec.get("format", "choice")
    if fmt in XML_ONLY_TYPES:
        return True
    if fmt == "text-entry" and (spec.get("text_blanks") or 1) > 1:
        return True
    return False

def _localname(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag

def _strip_ns(root):
    """Drop the namespace off every tag so lookups work regardless of prefix / default-ns quirks."""
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root

def _norm(s):
    """Collapse whitespace + strip (entities are already decoded by ElementTree)."""
    return re.sub(r"\s+", " ", s).strip() if s else ""

def _visible_text(el):
    """Full visible text of an element MINUS feedback/scaffolding subtrees. Reassembles answer
    text split AROUND nested children (.text + every descendant text/tail), inserts spaces at
    block boundaries so adjacent <p> don't fuse, and keeps a feedback element's .tail while
    dropping its body. This is the fix for the sc.text-only fragility."""
    parts = []
    def walk(node):
        parts.append(node.text or "")
        for child in node:
            ln = _localname(child.tag)
            if ln in _FEEDBACK_LOCALNAMES:
                parts.append(child.tail or "")        # skip feedback body, keep trailing text
            else:
                block = ln in _BLOCK_LOCALNAMES
                if block: parts.append(" ")
                walk(child)
                if block: parts.append(" ")
                parts.append(child.tail or "")
    walk(el)
    return _norm("".join(parts))

def _detect_format(root):
    """Infer the r2/QTI format of an assessment-item from its interaction element(s).
    Returns one of ACCEPTED_ITEM_TYPES. Two qti-choice-interactions == EBSR (Part A + Part B).
    Unknown/absent interaction defaults to 'choice' so legacy single-select items are untouched."""
    interactions = [el for el in root.iter() if _localname(el.tag) in QTI_INTERACTION_BY_TAG]
    tags = [_localname(el.tag) for el in interactions]
    if tags.count("qti-choice-interaction") >= 2 and len(set(tags)) == 1:
        return "ebsr"                                  # 2x choice == 2-part EBSR
    if interactions:
        return QTI_INTERACTION_BY_TAG[_localname(interactions[0].tag)]
    return "choice"

def _read_metadata(root):
    """Pass-through whatever rich metadata the item carries (r2: kct, ccss, teks, case_guid,
    map_goal, dok, p_m_target, genre, construct, distractor_family, ...). Reads qti-metadata-entry
    key/value pairs. PRESERVE everything, REQUIRE nothing — live export items have empty {}."""
    md = {}
    for entry in root.iter("qti-metadata-entry"):
        k = entry.attrib.get("key")
        if k:
            md[k] = _norm(entry.text) if entry.text else ""
    return md

def _read_choices(root):
    """All qti-simple-choice options across every choice-interaction (covers mcq/msq/ebsr)."""
    return [{"id": sc.attrib.get("identifier"), "text": _visible_text(sc)}
            for sc in root.iter("qti-simple-choice")]


def _read_prompt(root):
    """The item STEM, tolerant of two real shapes seen in the wild:
      * the live export (1077/1077): <qti-prompt> INSIDE the interaction.
      * Mayank's incept-qti-sdk 0.5.7: NO <qti-prompt>; stem in <qti-item-body>/<div class="stem">.
    Prefer an explicit <qti-prompt> (don't regress live items), else fall back to the stem div, else
    to the item-body's own direct text/markup that sits OUTSIDE any interaction (last-ditch). Returns
    fully-reassembled visible text (feedback subtrees dropped), never the empty string when a stem
    exists. _visible_text walks the whole subtree, so a <p>-wrapped stem is read correctly."""
    prompt_el = root.find(".//qti-prompt")
    if prompt_el is not None:
        txt = _visible_text(prompt_el)
        if txt:
            return txt
    # Mayank's stem: <div class="stem"> (any element carrying class*="stem"), under the item body.
    body = root.find(".//qti-item-body")
    scope = body if body is not None else root
    for div in scope.iter():
        if _localname(div.tag) == "div" and "stem" in (div.attrib.get("class") or "").split():
            txt = _visible_text(div)
            if txt:
                return txt
    # last-ditch: item-body text that is NOT inside an interaction or a choice (e.g. a bare <p> stem
    # with no class). Excise interactions + simple-choices so option text never leaks into the prompt.
    if body is not None:
        from copy import deepcopy
        clone = deepcopy(body)
        for parent in clone.iter():
            for child in list(parent):
                ln = _localname(child.tag)
                if ln in QTI_INTERACTION_BY_TAG or ln == "qti-simple-choice":
                    parent.remove(child)
        txt = _visible_text(clone)
        if txt:
            return txt
    return ""


def _opts_under(interaction):
    """Parse the option elements (simple-choice / hottext / order-choice / gap-text / associable)
    inside one interaction element, in document order, preserving ids + reassembled visible text."""
    opt_tags = ("qti-simple-choice", "qti-hottext", "qti-simple-associable-choice",
                "qti-gap-text", "qti-inline-choice")
    return [{"id": el.attrib.get("identifier"), "text": _visible_text(el)}
            for el in interaction.iter() if _localname(el.tag) in opt_tags]


def _correct_for(root, response_identifier):
    """Ordered correct-response values for a given response-declaration identifier (EBSR has one per
    part). Falls back to the first/only correct-response when the id isn't matched."""
    for rd in root.iter("qti-response-declaration"):
        if rd.attrib.get("identifier") == response_identifier:
            return [_norm(v.text) for v in rd.iter("qti-value") if v.text and _norm(v.text)]
    vals = [_norm(v.text) for v in root.findall(".//qti-correct-response/qti-value")]
    return [v for v in vals if v]


def _read_ebsr_parts(root):
    """Parse a 2-part EBSR item into [{choices, choice_ids, correct_indices, response_identifier}, …].
    Each qti-choice-interaction is one part (Part A claim, Part B evidence); its response-identifier
    couples it to its own correct-response so the two answer keys never cross-contaminate."""
    parts = []
    for inter in [el for el in root.iter() if _localname(el.tag) == "qti-choice-interaction"]:
        rid = inter.attrib.get("response-identifier") or inter.attrib.get("responseIdentifier")
        opts = _opts_under(inter)
        ids = [o["id"] for o in opts]
        corr = _correct_for(root, rid)
        parts.append({
            "choices": [o["text"] for o in opts],
            "choice_ids": ids,
            "correct_indices": [ids.index(c) for c in corr if c in ids],
            "response_identifier": rid,
        })
    return parts

def from_qti_xml(xml):
    """Parse one raw QTI 3.0 assessment-item (Mayank's SDK output) -> internal struct.
    Hardened against: feedback nested in choices (answer in .text AND/OR tails), multi-paragraph /
    entity-laden / inline-markup choice & prompt text, MISSING <qti-prompt> (Mayank's stem lives in
    <div class="stem"> — handled by _read_prompt), non-4-choice, missing or multi-value
    correct-response, and namespace/prefix quirks. role is AUTO-INFERRED: 'guiding' if
    it carries a stimulus-ref, else 'quiz'. format is AUTO-DETECTED from the interaction element(s).
    Rich r2 metadata is passed through verbatim. No tagging needed."""
    root = _strip_ns(ET.fromstring(xml.encode() if isinstance(xml, str) else xml))
    # correct response: collect ALL qti-value, order preserved; explicit list build, never `or _Empty()`.
    correct_ids = [_norm(v.text) for v in root.findall(".//qti-correct-response/qti-value")]
    correct_ids = [c for c in correct_ids if c]
    stim = root.find(".//qti-assessment-stimulus-ref")
    prompt = _read_prompt(root)            # <qti-prompt> OR <div class="stem"> (Mayank's SDK shape)
    choices = _read_choices(root)
    fmt = _detect_format(root)
    # max-choices (single vs multi select): qti-choice-interaction max-choices="0" == unlimited.
    ci = root.find(".//qti-choice-interaction")
    max_choices = None
    if ci is not None:
        mc = ci.attrib.get("max-choices")
        max_choices = int(mc) if (mc and mc.isdigit()) else (0 if mc == "0" else None)
    out = {
        "identifier": root.attrib.get("identifier"),
        "title": root.attrib.get("title") or "",
        "role": "guiding" if stim is not None else "quiz",
        "format": fmt,                 # one of ACCEPTED_ITEM_TYPES (mcq/msq both -> 'choice')
        "max_choices": max_choices,    # None=unknown, 1=single, 0/>1=multi
        "stimulus_ref": (stim.attrib.get("href") if stim is not None else None),
        "stimulus_id":  (stim.attrib.get("identifier") if stim is not None else None),  # carries real id
        "prompt": prompt,
        "choices": choices,
        "correct_id": correct_ids[0] if correct_ids else None,
        "correct_ids": correct_ids,    # full list; single-select uses [0], nothing silently dropped
        "metadata": _read_metadata(root),   # r2 rich metadata, passed through; {} for legacy items
        "rawXml": xml if isinstance(xml, str) else xml.decode("utf-8", "replace"),
    }
    # format-specific extras (only populated for the formats that need them)
    if fmt == "ebsr":
        out["ebsr_parts"] = _read_ebsr_parts(root)          # [Part A claim, Part B evidence]
    elif fmt == "text-entry":
        out["answers"] = _read_text_answers(root)           # accepted literal answer strings (flat)
        by_blank = _read_text_answers_by_blank(root)        # per-blank split for MULTI-blank items
        # number of distinct answer blanks (RESPONSE / RESPONSE_BLANK_N declarations). A single-blank
        # fill-in is JSON-safe (1 RESPONSE -> 1 input box); a MULTI-blank fill-in has >1 inline
        # interaction + >1 response-declaration which the documented single-interaction JSON model
        # CANNOT represent — the converter merges the blanks into one synonym pool AND drops the inline
        # interaction placeholders (verified on sample-fill-in-multi). Ilma RULE 1 spirit: when the JSON
        # model is lossy, ship the verbatim XML. So mark multi-blank text-entry XML-only.
        out["text_blanks"] = len(by_blank) if by_blank is not None else 1
        if by_blank is not None:
            out["answers_by_blank"] = by_blank              # [[b1 synonyms], [b2 synonyms], …]
    return out


def _text_blank_decls(root):
    """The fill-in answer DECLARATIONS in document order. A single-blank item has ONE
    <qti-response-declaration identifier="RESPONSE"> (base-type string); a MULTI-blank item has one
    <qti-response-declaration identifier="RESPONSE_BLANK_N"> per blank. Returns a list of
    {identifier, values:[accepted strings]} so blank N's key never bleeds into blank M."""
    decls = []
    for rd in root.iter("qti-response-declaration"):
        bt = rd.attrib.get("base-type") or rd.attrib.get("baseType")
        ident = rd.attrib.get("identifier") or ""
        if bt not in (None, "string"):
            continue
        if not re.match(r"^RESPONSE(_BLANK_\d+)?$", ident):
            continue
        vals = [_norm(v.text) for v in rd.iter("qti-value") if v.text and _norm(v.text)]
        decls.append({"identifier": ident, "values": vals})
    return decls


def _read_text_answers(root):
    """FLAT accepted answer strings for a fill-in (qti-text-entry) item: every correct-response value
    across every blank, document order (back-compat — single-blank returns its synonyms, multi-blank
    returns blank1+blank2+… concatenated). Per-blank fidelity is in _read_text_answers_by_blank."""
    decls = _text_blank_decls(root)
    if decls:
        return [v for d in decls for v in d["values"]]
    # last-ditch: items with a non-standard response-decl identifier — read the raw correct-responses.
    return [_norm(v.text) for v in root.findall(".//qti-correct-response/qti-value")
            if v.text and _norm(v.text)]


def _read_text_answers_by_blank(root):
    """PER-BLANK accepted answers for a fill-in item: [[blank1 synonyms], [blank2 synonyms], …].
    A multi-blank item (>1 RESPONSE_BLANK_N declaration) keeps each blank's accepted set SEPARATE so
    the emitter never merges 'cat'(blank1) and 'dog'(blank2) into one synonym pool (which would wrongly
    accept 'dog' in blank1). Returns None for a single-blank item (no per-blank split needed)."""
    decls = _text_blank_decls(root)
    multi = len(decls) > 1 or any(
        re.match(r"^RESPONSE_BLANK_\d+$", d["identifier"]) for d in decls)
    return [d["values"] for d in decls] if multi else None


def from_qti_stimulus_xml(xml):
    """Parse one raw QTI 3.0 STIMULUS XML (Mayank emits stimuli/<id>.xml) -> {identifier, title, html}.
    The API wants the HTML that lives inside <qti-stimulus-body>; we serialise that body's children
    (the real <div>/<p>/<h1>… passage markup), strip namespaces, and return it. Title falls back to
    the first heading or the identifier. img-src S3 validation is enforced separately by validate()."""
    root = _strip_ns(ET.fromstring(xml.encode() if isinstance(xml, str) else xml))
    body = root.find(".//qti-stimulus-body")
    html = ""
    if body is not None:
        inner = "".join(ET.tostring(ch, encoding="unicode") for ch in body)
        if not inner and (body.text or "").strip():
            inner = body.text
        # After _strip_ns the tags have NO prefix, so ET only re-emits bare `xmlns="..."`/`xmlns:x="..."`
        # declarations — scrub ONLY those. (Do NOT regex out `\w+:` globally: that mangles https:// and
        # every other colon-bearing attribute value — verified it ate the scheme off <a href>/<img src>.)
        html = re.sub(r'\s+xmlns(:\w+)?="[^"]*"', "", inner).strip()
    return {"identifier": root.attrib.get("identifier"),
            "title": root.attrib.get("title") or _first_heading(html) or root.attrib.get("identifier"),
            "html": html}


def _first_heading(html):
    m = re.search(r"<h[12][^>]*>(.*?)</h[12]>", html or "", re.S)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else None


def adapt_qti_item(parsed):
    """Bridge from_qti_xml() into the assembler shape. FAIL-CLOSED on the answer key, and CARRY the
    vendor ids through (identifier / stimulus_id / choice_ids) so assemble reuses Mayank's real ids
    instead of minting non-ingestible ones. Rich r2 metadata + format + rawXml ride through untouched.

    Ilma RULE 1 split (via _is_xml_only — per ITEM, not just per type):
      * XML-only formats (hottext/match/associate/ebsr/inline-choice/gap-match/select-point) AND
        MULTI-blank text-entry are emitted as the verbatim rawXml envelope, so the ONLY thing they
        MUST carry is a non-empty rawXml — we do NOT re-derive or membership-check their answer key
        (that would re-model the very thing RULE 1 forbids; EBSR's two parts can even reuse choice ids
        like A/B; a multi-blank fill-in's per-blank keys can't be merged into one synonym pool).
      * JSON-safe 'choice' (mcq/msq): the correct id(s) must be real option identifiers.
      * JSON-safe non-choice (SINGLE-blank text-entry / order / extended-text): must HAVE an answer
        key, in its own shape (accepted strings / full ordering), not forced into the choice-id space."""
    fmt = parsed.get("format", "choice")
    ids = [c["id"] for c in parsed["choices"]]
    out = {"identifier": parsed.get("identifier"), "stimulus_id": parsed.get("stimulus_id"),
           "title": parsed["title"], "prompt": parsed["prompt"], "format": fmt,
           "max_choices": parsed.get("max_choices"),
           "text_blanks": parsed.get("text_blanks"),
           "answers": parsed.get("answers"),
           "answers_by_blank": parsed.get("answers_by_blank"),
           "choices": [c["text"] for c in parsed["choices"]],
           "choice_ids": ids,
           "correct_ids": parsed.get("correct_ids") or [],
           "metadata": parsed.get("metadata") or {},
           "rawXml": parsed.get("rawXml")}
    if _is_xml_only(parsed):
        # XML-only (incl. multi-blank text-entry): rawXml is the source of truth (answer key +
        # interaction(s) live inside it). Require non-empty rawXml; do not re-model the key.
        if not parsed.get("rawXml") or not str(parsed["rawXml"]).strip():
            raise ValueError(f"{parsed.get('identifier')}: {fmt} is XML-only (Ilma RULE 1) but "
                             "from_qti_xml retained no rawXml")
        out["correct_index"] = 0
    elif fmt == "choice":
        cid = parsed.get("correct_id")
        if cid is None or cid not in ids:
            raise ValueError(f"{parsed.get('identifier')}: correct_id {cid!r} not among choices {ids}")
        out["correct_index"] = ids.index(cid)
        # multi-select (msq): every correct id must be a real option
        bad = [c for c in (parsed.get("correct_ids") or []) if c not in ids]
        if bad:
            raise ValueError(f"{parsed.get('identifier')}: correct_ids {bad} not among choices {ids}")
        out["correct_indices"] = [ids.index(c) for c in (parsed.get("correct_ids") or [cid])]
    else:
        # JSON-safe non-choice (text-entry/order/extended-text): must HAVE an answer key
        if not parsed.get("correct_ids"):
            raise ValueError(f"{parsed.get('identifier')}: {fmt} item has no correct-response value")
        out["correct_index"] = 0
        if fmt == "order":
            # drag-to-order is JSON-safe: the answer key is the FULL ordering of option ids, not a
            # single index. Map each correct id to its option index so _item emits the complete
            # ordered correctResponse (every option ranked) — else the order key is truncated to one
            # value and the validator's "must rank ALL options" gate fails (verified on the all-7
            # fixture's sample-order-summative/partial-credit, whose key is the entire sequence).
            bad = [c for c in parsed["correct_ids"] if c not in ids]
            if bad:
                raise ValueError(f"{parsed.get('identifier')}: order key id(s) {bad} not among "
                                 f"choices {ids}")
            out["correct_indices"] = [ids.index(c) for c in parsed["correct_ids"]]
    return out

# ---- input adapter: ingest Anirudh's NATIVE expedition table (zero reshaping) ----
# Re-exported here so feeders have ONE import surface. The adapter lives in its own module
# (skeleton_adapter.py) so it can be tested in isolation; it is optional at runtime.
try:
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from skeleton_adapter import from_skeleton_table   # noqa: F401  (re-exported for feeders)
except ImportError:
    from_skeleton_table = None   # adapter module absent → arpack still assembles/validates fine

# ---- contract constants (DO NOT loosen without a fresh export check) -----------
ALLOWED_HTML_TAGS = {"div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "em", "b", "i",
                     "u", "sub", "sup", "br", "hr", "blockquote", "ul", "ol", "li", "span",
                     "a", "table", "thead", "tbody", "tr", "td", "th", "img", "figure",
                     "figcaption", "caption"}
# Presentation MathML — Mayank's incept-qti-sdk 0.5.7 emits inline <math> for chemistry/sci
# (e.g. CO2, H2CO3) in BOTH stimulus bodies and choices. It is NOT media and must NOT be flagged
# by the tag-vocab gate. Verified present in fixtures/qti_sample_2026-06-16 (stim_20c1a57c2496).
MATHML_TAGS = {"math", "mrow", "mi", "mo", "mn", "msub", "msup", "msubsup", "mfrac", "msqrt",
               "mroot", "mtext", "mspace", "mover", "munder", "munderover", "mtable", "mtr",
               "mtd", "mfenced", "mstyle", "menclose", "semantics", "annotation"}
ALLOWED_HTML_TAGS |= MATHML_TAGS
# <img> is the ONE media tag we permit — and ONLY with an S3 src (Mayank's rule). All other
# embedded media stays banned (Alpha Read renders passage + items; no audio/video/iframe).
MEDIA_TAGS = {"audio", "video", "source", "iframe", "object", "embed"}
GUIDING_MIN, GUIDING_MAX = 3, 6
QUIZ_ITEMS = 4
CHOICES_PER_ITEM = 4                                     # enforced ONLY for single-select 'choice' items
COURSE_MARKERS = {"primaryApp": "alpha_read"}            # also mirrored in metadata
THROWAWAY_PREFIX = "STAN-PROBE-DELETEME"

# ---- S3 image convention (Stream S3) -------------------------------------------
# UNCONFIRMED — no explicit org skill/doc states the bucket/url pattern (searched trilogy-group
# repos + the local contract investigation: live course has ZERO media, product spec only says the
# app "never rewrites media URLs" and uses "signed media URLs"). SAFE DEFAULT per Mayank's note:
# every <img> src MUST be an https S3 URL. Accepts virtual-hosted, path-style, and CloudFront-over-S3
# forms; flags anything else (data:, http:, relative, foreign host). Tighten the bucket once confirmed.
_S3_IMG_SRC = re.compile(
    r"^https://("
    r"[a-z0-9.\-]+\.s3[.\-][a-z0-9.\-]*amazonaws\.com/"     # virtual-hosted: bucket.s3[.region].amazonaws.com/
    r"|s3[.\-][a-z0-9.\-]*amazonaws\.com/[a-z0-9.\-]+/"     # path-style:     s3[.region].amazonaws.com/bucket/
    r"|[a-z0-9.\-]+\.cloudfront\.net/"                       # CloudFront in front of an S3 origin
    r")",
    re.IGNORECASE,
)

def _img_srcs(html):
    """Every <img src="..."> value in a chunk of HTML (attribute order / quote style tolerant)."""
    return re.findall(r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']*)[\"']", html or "", re.IGNORECASE)

def validate_img_src(html):
    """Return a list of non-S3 <img> srcs found in `html` (empty == all images are S3-hosted, or
    there are no images). This is the img-src validator the brief asks for."""
    return [src for src in _img_srcs(html) if not _S3_IMG_SRC.match(src.strip())]

def _aid(vendor_id): return f"article_{vendor_id}"        # id coupling invariant

# ---- assemble ------------------------------------------------------------------
def assemble(skel):
    c = skel["course"]
    course = {
        "sourcedId": c.get("sourcedId") or f"arpack-{re.sub(r'[^a-z0-9]+','-',c['title'].lower())}",
        "status": "active", "title": c["title"], "courseCode": c["courseCode"],
        "grades": c["grades"], "subjects": c["subjects"],
        "org": {"sourcedId": c["org_sourcedId"]},
        # ROOT primaryApp is the AUTHORITATIVE app-ownership setter (Ramish breaking change,
        # >=2026-06-30: metadata.primaryApp no longer confers ownership). Must be the exact active
        # applications.sourcedId — "alpha_read", confirmed from the live prod export. Never null
        # (null on a PUT CLEARS ownership), never an alias/case variant (-> 422 InvalidData).
        "primaryApp": "alpha_read",                       # ← the one real ownership switch
        "metadata": {
            # metadata.primaryApp is now INERT (stored, not ownership). Mirrored here only so the
            # package still reads sanely on pre-cutover servers; it is forward-safe to drop. The
            # validator treats ROOT primaryApp as the hard gate and metadata.primaryApp as optional.
            "primaryApp": "alpha_read", "isAlphaRead": True,   # markers
            "publishStatus": "published", "timebackVisible": True,  # visibility gates
            "AlphaLearn": {"publishStatus": "active", "DailyXPGoal": 25},
            "courseType": "base", "contentGrade": c.get("contentGrade", "3"),
            "goals": {"dailyXp": 25, "dailyLessons": 1, "dailyAccuracy": 80,
                      "dailyActiveMinutes": 25, "dailyMasteredUnits": 2},
            # NB: metadata.metrics{} is SERVER-DERIVED — never authored here.
        },
    }
    components, resources, comp_resources = [], [], []
    qti = {"stimuli": [], "items": [], "tests": []}
    for u in skel["units"]:
        cid = f"unit-{u['sortOrder']}"
        components.append({"sourcedId": cid, "status": "active", "title": u["title"],
                           "sortOrder": u["sortOrder"], "course": {"sourcedId": course["sourcedId"]}})
        for li, lesson in enumerate(u["lessons"], 1):
            aid = _aid(lesson["vendorId"])
            # --- QTI test: guiding sections (1 stim + 1 item) then 1 quiz section (4 items)
            # LIVE-SHAPE assembler: sections carry `qti-assessment-item-ref` with FULL hrefs
            # (https://qti.alpha-1edtech.ai/api/assessment-items/<id>); vendor item/stimulus/choice
            # ids are REUSED when carried so the refs resolve on Mayank's service, minted otherwise.
            sections = []
            for gi, g in enumerate(lesson.get("guiding", []), 1):
                it = g["item"]
                sid = it.get("stimulus_id") or g["stimulus"].get("identifier") or f"guiding_{lesson['vendorId']}_{gi}"
                qti["stimuli"].append({"identifier": sid, "title": g["stimulus"]["title"],
                                       "content": _sani(g["stimulus"]["html"])})
                iid = it.get("identifier") or f"{sid}_item"
                qti["items"].append(_item(iid, it, stimulus_id=sid))
                sections.append({"identifier": f"test_{sid}", "title": f"Guiding {gi}",
                                 "visible": True, "required": True, "fixed": False, "sequence": gi,
                                 "qti-assessment-item-ref": [{"identifier": iid,
                                                              "href": f"{iid}.xml"}]})
            quiz_refs = []
            for qi, q in enumerate(lesson.get("quiz", []), 1):
                iid = q.get("identifier") or f"quiz_{lesson['vendorId']}_{qi}"
                qti["items"].append(_item(iid, q, stimulus_id=None))
                quiz_refs.append({"identifier": iid, "href": f"{iid}.xml"})
            sections.append({"identifier": "test_quiz", "title": "Quiz",
                             "visible": True, "required": True, "fixed": False,
                             "sequence": len(lesson.get("guiding", [])) + 1,
                             "qti-assessment-item-ref": quiz_refs})
            # test metadata: verified live shape {grade, measuredReadingGrade, lexileLevel}.
            # Per-lesson values ride in from the skeleton shell when present (Anirudh's band/lexile
            # seeds them; Mayank's per-item lexile may overwrite later); else fall back to grade 3.
            test_md = {"grade": str(lesson.get("grade", "3")),
                       "measuredReadingGrade": str(lesson.get("measuredReadingGrade", lesson.get("grade", "3")))}
            if lesson.get("lexileLevel"):
                test_md["lexileLevel"] = str(lesson["lexileLevel"])
            qti["tests"].append({"identifier": aid, "title": lesson["title"], "qtiVersion": "3.0",
                                 "metadata": test_md,
                                 "qti-outcome-declaration": [{"identifier": "SCORE", "cardinality": "single", "baseType": "float"}],
                                 "qti-test-part": [{"identifier": "test_part_0", "navigationMode": "linear",
                                                    "submissionMode": "individual",
                                                    "qti-assessment-section": sections}]})
            # --- OneRoster resource: WRAPPED in {"resource":{…}}, with roles[] + metadata.sourcedId
            # mirror (the live ingestible shape — the unwrapped form is rejected by OneRoster ingest).
            resources.append({"resource": {
                "sourcedId": aid, "status": "active", "title": lesson["title"], "roles": [],
                "importance": "primary", "vendorResourceId": str(lesson["vendorId"]),
                "metadata": {"sourcedId": aid, "lessonType": "alpha-read-article", "type": "qti",
                             "subType": "qti-test", "questionType": "custom",
                             "xp": lesson.get("xp", 12),
                             "url": f"https://qti.alpha-1edtech.ai/api/assessment-tests/{aid}"}}})
            comp_resources.append({"sourcedId": f"cr_{cid}_{aid}", "status": "active",
                                   "courseComponent": {"sourcedId": cid}, "resource": {"sourcedId": aid},
                                   "sortOrder": li, "title": lesson["title"],
                                   "metadata": {"lessonType": "alpha-read-article"}})
    return {"course": course, "components": components, "resources": resources,
            "componentResources": comp_resources, "qti": qti}

def _xml_envelope_item(iid, spec, stimulus_id):
    """Build the RAW-XML envelope for a NON-JSON-safe interaction (Ilma RULE 1).

    For hottext / match / associate / ebsr / inline-choice / gap-match / select-point the API's
    JSON->XML converter is LOSSY — it silently drops the directedPair/hottext/gap-text/inline-choice/
    composite children, so the item renders broken and scores wrong. The ONLY safe push is to send
    Mayank's ORIGINAL item XML verbatim via XML POST: {"format":"xml","xml":<rawXml>}.

    We therefore carry `spec["rawXml"]` (retained by from_qti_xml) through UNTOUCHED — no JSON
    modelling, no responseProcessing template (we never author the invented 'map_response'), no
    re-derivation of options/answer-key. The XML already contains the response-declarations,
    interaction(s), and response-processing exactly as Mayank built them. We attach the routing
    `type` (so the assembler/test-section logic and the validator can branch) and, when this is a
    guiding item, the stimulusRef (which the README sends as the JSON `stimulus` field beside the
    envelope; the embedded <qti-assessment-stimulus-ref> in the rawXml also carries the link)."""
    raw = spec.get("rawXml")
    if not raw or not str(raw).strip():
        raise ValueError(f"{iid}: {spec.get('format')!r} is XML-only (Ilma RULE 1) but carries no "
                         f"rawXml — from_qti_xml must RETAIN the original item XML for this type")
    item = {"identifier": iid, "title": spec.get("title", iid), "type": spec.get("format"),
            "format": "xml", "xml": raw}
    md = spec.get("metadata")
    if md:                                               # pass-through r2 metadata (kct/ccss/teks/…)
        item["metadata"] = md
    if stimulus_id:
        item["stimulusRef"] = {"identifier": stimulus_id,
                               "href": f"https://qti.alpha-1edtech.ai/api/stimuli/{stimulus_id}"}
    return item


def _item(iid, spec, stimulus_id):
    """Build one ingestible QTI assessment-item.

    Handles all 7 r2 formats with the Ilma RULE 1 split (decided per ITEM by _is_xml_only):
      * JSON-SAFE (choice/order/extended-text/SINGLE-blank text-entry) -> JSON dict (the live
        live-export shape, verified against its 1077 items + Ilma's create-mcq.md JSON template).
      * NON-JSON-SAFE (hottext/match/associate/ebsr/inline-choice/gap-match/select-point AND
        MULTI-blank text-entry) -> the raw-XML envelope {"format":"xml","xml":<rawXml>} carried
        verbatim from the parsed item, via _xml_envelope_item(). The API's JSON->XML converter
        corrupts these — XML POST is the ONLY safe path. We do NOT JSON-model them and do NOT author
        any responseProcessing template.

    Vendor choice ids are REUSED when carried; minted deterministically otherwise. r2 metadata rides
    through verbatim (never authored, never stripped). stimulus_id (when present) emits the live
    stimulusRef {identifier, href}."""
    fmt = spec.get("format", "choice")
    if _is_xml_only(spec):
        return _xml_envelope_item(iid, spec, stimulus_id)
    item = {"identifier": iid, "title": spec.get("title", iid), "type": fmt, "qtiVersion": "3.0",
            "timeDependent": False, "adaptive": False}
    # Item-level SCORE outcome declaration — present in BOTH Ilma's JSON MCQ template
    # (create-mcq.md) AND Mayank's native incept-qti-sdk items (sample-*.xml carry a SCORE float
    # outcome decl). Without it the platform scores 0 ("Score always 0 -> missing SCORE outcome
    # declaration", create-test.md). JSON-safe and required for every interaction type we emit.
    item["outcomeDeclarations"] = [{"identifier": "SCORE", "cardinality": "single",
                                    "baseType": "float"}]
    md = spec.get("metadata")
    if md:                                              # pass-through r2 metadata (kct/ccss/teks/…)
        item["metadata"] = md

    if fmt == "text-entry":
        # fill-in: accepted answer strings, not choice ids.
        answers = spec.get("answers") or spec.get("correct_ids") or []
        item["responseDeclarations"] = [{"identifier": "RESPONSE", "cardinality": "single",
                                         "baseType": "string", "correctResponse": {"value": answers}}]
        item["responseProcessing"] = {"templateType": "match_correct"}
        # interaction.type MUST be present + match the response declaration (create-mcq.md HARD
        # RULE: "type at root AND interaction.type must both be set — mismatch causes silent
        # failures"). responseIdentifier couples the interaction to its RESPONSE decl. The STEM
        # rides in questionStructure.prompt (create-frq.md JSON shape) — without it the fill-in
        # renders a bare input box with no question. Sanitized to XHTML.
        item["interaction"] = {"type": "text-entry", "responseIdentifier": "RESPONSE",
                               "expectedLength": None,
                               "questionStructure": {"prompt": _sani_prompt(spec.get("prompt"))}}
    else:
        # JSON-safe option-based families: choice (mcq/msq) · order. (hottext/match/associate are
        # XML-only and were already routed to _xml_envelope_item above; they never reach here.)
        choices = spec["choices"]
        cids = spec.get("choice_ids") or [f"{iid}_c{n}" for n in range(len(choices))]
        opts = [{"identifier": cids[n], "content": _sani(ch)} for n, ch in enumerate(choices)]
        corr_idx = spec.get("correct_indices") or [spec.get("correct_index", 0)]
        corr = [opts[i]["identifier"] for i in corr_idx]
        multi = (fmt == "order" or len(corr) > 1
                 or (spec.get("max_choices") not in (None, 1)))
        cardinality = "ordered" if fmt == "order" else ("multiple" if multi else "single")
        item["responseDeclarations"] = [{"identifier": "RESPONSE", "cardinality": cardinality,
                                         "baseType": "identifier", "correctResponse": {"value": corr}}]
        item["responseProcessing"] = {"templateType": "match_correct"}
        # interaction.type MUST be set + match root type (create-mcq.md HARD RULE: "type at root
        # AND interaction.type must both be 'choice' — mismatch causes silent failures").
        # responseIdentifier couples the interaction to its RESPONSE response-declaration.
        # The STEM + options live inside `questionStructure` — Ilma's authoritative JSON template
        # (create-mcq.md) puts BOTH there; a bare `interaction.choices` with no prompt emits an item
        # with NO question stem (the renderer shows four naked options). prompt is sanitized to XHTML.
        inter = {"type": fmt, "responseIdentifier": "RESPONSE",
                 "shuffle": fmt not in ("order",),
                 "questionStructure": {"prompt": _sani_prompt(spec.get("prompt")),
                                       "choices": opts}}
        if fmt == "choice":
            inter["maxChoices"] = 1 if cardinality == "single" else 0
        item["interaction"] = inter

    if stimulus_id:
        # live shape: stimulusRef carries BOTH the real identifier and the href.
        item["stimulusRef"] = {"identifier": stimulus_id,
                               "href": f"https://qti.alpha-1edtech.ai/api/stimuli/{stimulus_id}"}
    return item

# ---- per-format item invariants (Stream S2: all 7 r2 formats accepted) ----------
def _opt_ids(interaction):
    # Options live in interaction.questionStructure.choices (Ilma's JSON template shape, create-mcq.md).
    # Fall back to a flat interaction.choices for resilience against either shape.
    interaction = interaction or {}
    qs = interaction.get("questionStructure") or {}
    choices = qs.get("choices") or interaction.get("choices") or []
    return {c.get("identifier") for c in choices}

def _stem_of(interaction):
    """The question STEM string for one interaction (questionStructure.prompt). '' if absent."""
    return ((interaction or {}).get("questionStructure") or {}).get("prompt") or ""

def _envelope_is_multiblank_textentry(i):
    """True if `i` is a text-entry item legitimately wearing the raw-XML envelope because it is
    MULTI-blank (>1 RESPONSE_BLANK_N response-declaration in its rawXml). Single-blank text-entry is
    JSON-safe and must NOT wear the envelope; this lets the validator tell the two apart so it neither
    (a) forces a real multi-blank envelope back through the JSON gate, nor (b) silently lets a genuine
    single-blank text-entry hide inside an envelope."""
    if i.get("type") != "text-entry":
        return False
    raw = i.get("xml") or ""
    return len(re.findall(r'identifier="RESPONSE_BLANK_\d+"', raw)) > 1

def _validate_xml_envelope(i):
    """Fail-closed checks on a NON-JSON-safe item emitted as the raw-XML envelope
    {"format":"xml","xml":<rawXml>, "type":<fmt>, "identifier":...} (Ilma RULE 1).

    For these types we DON'T require the JSON option structure (responseDeclarations/interaction/
    questionStructure) — the answer key + interaction live inside the verbatim XML, and JSON-modelling
    them is exactly the corruption RULE 1 forbids. Instead we check the envelope is well-formed:
      * format == 'xml' and a non-empty xml string is present,
      * the xml parses as well-formed QTI (ET.fromstring) and its root is <qti-assessment-item>,
      * the root carries an identifier (the API extracts id/title from it; missing id -> 500),
      * and the envelope id is consistent with the XML's own identifier (no silent ref mismatch)."""
    iid = i.get("identifier", "?")
    fmt = i.get("type")
    errs = []
    raw = i.get("xml")
    if i.get("format") != "xml":
        errs.append(f"{iid}: {fmt} is XML-only (Ilma RULE 1) but item has no format:'xml' envelope")
        return errs
    if not raw or not str(raw).strip():
        errs.append(f"{iid}: {fmt} XML envelope has empty 'xml' (rawXml not carried through)")
        return errs
    try:
        root = ET.fromstring(raw.encode() if isinstance(raw, str) else raw)
    except Exception as e:                               # not well-formed -> API parser 500s on POST
        errs.append(f"{iid}: {fmt} rawXml is not well-formed QTI XML: {str(e)[:80]}")
        return errs
    if _localname(root.tag) != "qti-assessment-item":
        errs.append(f"{iid}: {fmt} rawXml root is <{_localname(root.tag)}>, expected "
                    "<qti-assessment-item>")
    xml_id = root.attrib.get("identifier")
    if not xml_id:                                       # API extracts id from the XML; absent -> 500
        errs.append(f"{iid}: {fmt} rawXml has no identifier attribute on <qti-assessment-item>")
    elif iid != "?" and xml_id != iid:
        errs.append(f"{iid}: envelope identifier != rawXml identifier {xml_id!r} (ref mismatch)")
    # media safety still applies inside rawXml: any embedded <img> MUST be an https S3 URL.
    for bad in validate_img_src(raw):
        errs.append(f"{iid}: {fmt} rawXml img src not an https S3 URL: {bad!r}")
    return errs


def _validate_item(i):
    """Fail-closed per-format checks on ONE assembled item. Returns a list of error strings.
    ACCEPTS all 7 r2 formats and enforces the RIGHT invariant per format, with the Ilma RULE 1 split:
      * NON-JSON-safe (hottext/match/associate/ebsr/inline-choice/gap-match/select-point) -> validated
        as a raw-XML envelope (well-formed QTI + identifier present); NOT as a JSON option structure.
      * JSON-safe (choice/order/text-entry/extended-text) -> the answer key must be present AND
        resolvable to real option ids (or, for fill-in, to non-empty accepted strings)."""
    iid = i.get("identifier", "?")
    fmt = i.get("type")
    errs = []
    if fmt not in ACCEPTED_ITEM_TYPES:
        errs.append(f"{iid}: type {fmt!r} not an accepted r2 format {sorted(ACCEPTED_ITEM_TYPES)}")
        return errs

    # Ilma RULE 1: XML-only types ride through as the raw-XML envelope. The API's JSON->XML converter
    # corrupts these, so we accept (and require) the verbatim XML, not the JSON model. A MULTI-blank
    # text-entry (legitimately XML-only at the item level — see _is_xml_only) also wears the envelope:
    # detect it by the envelope marker itself (format:'xml' + a text-entry carrying >1 RESPONSE_BLANK_N
    # in its rawXml). Any item actually wearing the envelope is validated AS an envelope.
    if fmt in XML_ONLY_TYPES or (i.get("format") == "xml" and _envelope_is_multiblank_textentry(i)):
        return _validate_xml_envelope(i)

    # A genuinely JSON-safe item (choice/order/extended-text/SINGLE-blank text-entry) must NOT wear the
    # raw-XML envelope. Catch the inverted-shape mistake explicitly and fail CLOSED with a message
    # instead of crashing on the missing responseDeclarations below.
    if i.get("format") == "xml":
        errs.append(f"{iid}: JSON-safe type {fmt!r} must NOT use the raw-XML envelope (emit JSON); "
                    f"the XML envelope is only for {sorted(XML_ONLY_TYPES)} + multi-blank text-entry")
        return errs
    # Every JSON-safe item carries a RESPONSE response-declaration with a correctResponse. A missing
    # one is a malformed item (e.g. a forged/dropped key) — fail CLOSED, never KeyError.
    if not i.get("responseDeclarations"):
        errs.append(f"{iid}: {fmt} item has no responseDeclarations (malformed JSON item)")
        return errs

    if fmt == "text-entry":
        # fill-in: accepted answer STRINGS (non-empty); no choice-id space.
        cv = i["responseDeclarations"][0]["correctResponse"]["value"]
        if not cv or any((s is None or str(s).strip() == "") for s in cv):
            errs.append(f"{iid}: fill-in (text-entry) needs >=1 non-empty accepted answer")
        if not _stem_of(i.get("interaction", {})).strip():
            errs.append(f"{iid}: fill-in (text-entry) has no question stem (questionStructure.prompt)")
        return errs

    # JSON-safe option-based families: choice (mcq/msq) · order (hottext/match are XML-only above)
    inter = i.get("interaction", {})
    opts = _opt_ids(inter)
    cv = i["responseDeclarations"][0]["correctResponse"]["value"]
    card = i["responseDeclarations"][0].get("cardinality")
    if not opts:
        errs.append(f"{iid}: {fmt} item has no options/choices")
    if not _stem_of(inter).strip():                     # live items ALWAYS carry a stem; empty == broken render
        errs.append(f"{iid}: {fmt} item has no question stem (questionStructure.prompt)")
    if not cv:
        errs.append(f"{iid}: {fmt} item has no correct response")
    if any(c not in opts for c in cv):
        errs.append(f"{iid}: correct value(s) {[c for c in cv if c not in opts]} not among its options")

    if fmt == "choice":
        if card == "single":                            # mcq: exactly one key, 4 options (live parity)
            if len(cv) != 1:
                errs.append(f"{iid}: mcq (single-select) must have exactly 1 correct option")
            if len(opts) < 2:                           # Ilma: API accepts 2-6+ (True/False ok); >=2 is the real floor
                errs.append(f"{iid}: mcq needs >=2 choices, has {len(opts)}")
        else:                                           # msq: >=1 key, >=2 options
            if len(cv) < 1:
                errs.append(f"{iid}: msq (multi-select) must have >=1 correct option")
            if len(opts) < 2:
                errs.append(f"{iid}: msq needs >=2 choices")
    elif fmt == "order":                                # drag-to-order: key is the full ordering
        if card != "ordered":
            errs.append(f"{iid}: drag-to-order must use cardinality 'ordered'")
        if len(cv) != len(opts):
            errs.append(f"{iid}: order key must rank ALL {len(opts)} options, has {len(cv)}")
    return errs


# ---- validate (fail-closed; returns list of errors) ----------------------------
def validate(pkg):
    errs = []
    md = pkg["course"]["metadata"]
    # --- app ownership (Ramish breaking change, deploys >= 2026-06-30) ----------------
    # ROOT course.primaryApp is the ONE authoritative ownership setter. It must be a NON-EMPTY
    # STRING that EXACTLY matches an active applications.sourcedId — the canonical value for our
    # course is "alpha_read" (confirmed from the live production export course_4c49bc61_raw.json,
    # root primaryApp="alpha_read"). Aliases / case / spacing variants -> 422 InvalidData on the
    # server, so we fail-closed on anything but the exact string here. We also explicitly reject
    # None ("primaryApp:null" CLEARS ownership on a PUT — we must never emit it) and the empty /
    # non-string forms (both 422 on the server) with self-documenting messages.
    pa = pkg["course"].get("primaryApp")
    if pa is None:
        errs.append("course.primaryApp is null/absent — ROOT primaryApp is the ONLY ownership "
                    "setter (>=2026-06-30); null CLEARS ownership and 422s. Must be 'alpha_read'.")
    elif not isinstance(pa, str) or pa == "":
        errs.append(f"course.primaryApp must be a non-empty string == 'alpha_read' (got {pa!r}); "
                    "non-string/empty -> 422 InvalidData on the server.")
    elif pa != "alpha_read":
        errs.append(f"course.primaryApp {pa!r} != 'alpha_read' — must EXACTLY match the active "
                    "applications.sourcedId (no alias/case/spacing variants; mismatch -> 422).")
    # metadata.primaryApp is now INERT (>=2026-06-30 it no longer confers ownership; it is stored
    # as plain metadata). It is therefore OPTIONAL and forward-safe: the package stays valid if it
    # is dropped entirely. We still mirror it in assemble() for pre-cutover servers, but if it IS
    # present it must not carry a *wrong* value (a stale non-'alpha_read' string would be confusing
    # dead metadata) — absence is fine, only a present-and-wrong value is flagged.
    if "primaryApp" in md and md.get("primaryApp") != "alpha_read":
        errs.append(f"course.metadata.primaryApp present but != 'alpha_read' (inert metadata; "
                    f"drop it or set 'alpha_read') — got {md.get('primaryApp')!r}")
    for k, v in {"isAlphaRead": True,
                 "publishStatus": "published", "timebackVisible": True}.items():
        if md.get(k) != v: errs.append(f"course.metadata.{k} != {v!r}")
    if "metrics" in md: errs.append("course.metadata.metrics must NOT be authored (server-derived)")

    # OneRoster resources are WRAPPED: {"resource": {...}} with roles[] + metadata.sourcedId (live shape).
    # Read ids defensively: a malformed/unwrapped entry must FAIL CLOSED with a clear message below,
    # never crash the validator with a KeyError (a crash isn't a fail-closed gate).
    res_ids = {e["resource"]["sourcedId"]
               for e in pkg["resources"]
               if isinstance(e, dict) and isinstance(e.get("resource"), dict)
               and "sourcedId" in e["resource"]}
    test_ids = {t["identifier"] for t in pkg["qti"]["tests"]}
    if res_ids != test_ids: errs.append("resource ids must == test ids (id coupling)")
    for entry in pkg["resources"]:
        r = entry.get("resource") if isinstance(entry, dict) else None
        if not isinstance(r, dict):
            errs.append("resource entry not wrapped in {'resource':{…}}"); continue
        m = r.get("metadata", {})
        if "roles" not in r: errs.append(f"{r.get('sourcedId')}: resource missing roles[]")
        if m.get("sourcedId") != r.get("sourcedId"): errs.append(f"{r.get('sourcedId')}: metadata.sourcedId not mirrored")
        if m.get("lessonType") != "alpha-read-article": errs.append(f"{r.get('sourcedId')}: lessonType wrong")
        if not m.get("url", "").endswith(r.get("sourcedId", "\0")): errs.append(f"{r.get('sourcedId')}: url not id-coupled")

    # DUPLICATE-ID HARD GATE: the res_ids/test_ids check above is a SET comparison and cannot see
    # count collisions. Two lessons sharing a vendorId (hand-authored skeleton) or qti_dir_resolver
    # deriving the same vendorId for two groups produce duplicate item/stimulus/resource/test ids
    # that a real OneRoster/QTI push REJECTS. Fail closed here so validate() is the one true gate
    # (read defensively — a malformed entry was already flagged above; never KeyError).
    for label, ids in (
        ("item", [i.get("identifier") for i in pkg["qti"]["items"]
                  if isinstance(i, dict) and i.get("identifier")]),
        ("stimulus", [s.get("identifier") for s in pkg["qti"]["stimuli"]
                      if isinstance(s, dict) and s.get("identifier")]),
        ("test", [t.get("identifier") for t in pkg["qti"]["tests"]
                  if isinstance(t, dict) and t.get("identifier")]),
        ("resource", [e["resource"]["sourcedId"] for e in pkg["resources"]
                      if isinstance(e, dict) and isinstance(e.get("resource"), dict)
                      and "sourcedId" in e["resource"]]),
    ):
        dupes = sorted({x for x in ids if ids.count(x) > 1})
        if dupes:
            errs.append(f"duplicate {label} id(s): {dupes}")

    # stimuli: tag vocab + media ban + S3-only <img> src (Mayank's rule: images must be S3 URLs).
    for s in pkg["qti"]["stimuli"]:
        content = s.get("content", "")
        for tag in re.findall(r"<\s*([a-zA-Z0-9]+)", content):
            t = tag.lower()
            if t in MEDIA_TAGS: errs.append(f"{s['identifier']}: media tag <{t}> not allowed")
            elif t not in ALLOWED_HTML_TAGS: errs.append(f"{s['identifier']}: tag <{t}> outside allowed vocab")
        for bad in validate_img_src(content):
            errs.append(f"{s['identifier']}: img src not an https S3 URL: {bad!r}")
        try:                                            # G1: content must be well-formed XHTML post-sanitize
            ET.fromstring(f"<_r>{content}</_r>")
        except Exception as e:
            errs.append(f"{s['identifier']}: content not well-formed XHTML (sanitize gate): {str(e)[:70]}")

    # items: per-format invariants (all 7 r2 formats), each fail-closed on its answer key.
    items = {i["identifier"]: i for i in pkg["qti"]["items"]}
    for i in pkg["qti"]["items"]:
        errs.extend(_validate_item(i))
        # item STEM is embedded HTML — same gates as stimulus content (G1 well-formed XHTML + S3-only img).
        stems = [_stem_of(i.get("interaction", {}))]
        stems += [_stem_of(x) for x in (i.get("interactions") or [])]
        for stem in stems:
            if not stem:
                continue
            for bad in validate_img_src(stem):
                errs.append(f"{i['identifier']}: prompt img src not an https S3 URL: {bad!r}")
            try:                                        # G1: stem must be well-formed XHTML post-sanitize
                ET.fromstring(f"<_r>{stem}</_r>")
            except Exception as e:
                errs.append(f"{i['identifier']}: prompt not well-formed XHTML (sanitize gate): {str(e)[:70]}")

    # tests: live section shape (qti-assessment-item-ref + full hrefs); 3-6 guiding + exactly 4 quiz;
    # guiding items carry a stimulus-ref, quiz items must NOT.
    for t in pkg["qti"]["tests"]:
        secs = t["qti-test-part"][0]["qti-assessment-section"]
        guiding = [s for s in secs if s["title"].startswith("Guiding")]
        quiz = [s for s in secs if s["title"] == "Quiz"]
        if not (GUIDING_MIN <= len(guiding) <= GUIDING_MAX):
            errs.append(f"{t['identifier']}: {len(guiding)} guiding sections (need {GUIDING_MIN}-{GUIDING_MAX})")
        if len(quiz) != 1 or len(quiz[0]["qti-assessment-item-ref"]) != QUIZ_ITEMS:
            errs.append(f"{t['identifier']}: need exactly 1 quiz section with {QUIZ_ITEMS} items")
        def _refs(s): return s.get("qti-assessment-item-ref", [])
        for s in guiding:
            if len(_refs(s)) != 1:
                errs.append(f"{t['identifier']}/{s['identifier']}: guiding needs 1 item")
                continue
            ref = _refs(s)[0]
            if ref["identifier"] not in ref.get("href", ""):
                errs.append(f"{ref['identifier']}: item-ref href not id-coupled")
            if "stimulusRef" not in items.get(ref["identifier"], {}):
                errs.append(f"{ref['identifier']}: guiding item missing stimulus-ref")
        for ref in _refs(quiz[0] if quiz else {"qti-assessment-item-ref": []}):
            if ref["identifier"] not in ref.get("href", ""):
                errs.append(f"{ref['identifier']}: item-ref href not id-coupled")
            if "stimulusRef" in items.get(ref["identifier"], {}):
                errs.append(f"{ref['identifier']}: quiz item must NOT have a stimulus-ref")
    return errs

# ---- emit ----------------------------------------------------------------------
def emit(pkg, outdir):
    for sub in ("oneroster", "qti/stimuli", "qti/items", "qti/tests"):
        os.makedirs(os.path.join(outdir, sub), exist_ok=True)
    json.dump(pkg["course"], open(f"{outdir}/oneroster/course.json", "w"), indent=1)
    json.dump(pkg["components"], open(f"{outdir}/oneroster/components.json", "w"), indent=1)
    json.dump(pkg["resources"], open(f"{outdir}/oneroster/resources.json", "w"), indent=1)
    json.dump(pkg["componentResources"], open(f"{outdir}/oneroster/componentResources.json", "w"), indent=1)
    for s in pkg["qti"]["stimuli"]: json.dump(s, open(f"{outdir}/qti/stimuli/{s['identifier']}.json", "w"), indent=1)
    for i in pkg["qti"]["items"]:   json.dump(i, open(f"{outdir}/qti/items/{i['identifier']}.json", "w"), indent=1)
    for t in pkg["qti"]["tests"]:   json.dump(t, open(f"{outdir}/qti/tests/{t['identifier']}.json", "w"), indent=1)
    manifest = {"course": pkg["course"]["sourcedId"], "units": len(pkg["components"]),
                "lessons": len(pkg["resources"]), "stimuli": len(pkg["qti"]["stimuli"]),
                "items": len(pkg["qti"]["items"]), "tests": len(pkg["qti"]["tests"])}
    json.dump(manifest, open(f"{outdir}/manifest.json", "w"), indent=1)
    return manifest

# ---- selftest ------------------------------------------------------------------
SAMPLE = {
  "course": {"title": "STAN-PROBE-DELETEME Reading G3", "courseCode": "ALPHAREAD-PROBE",
             "grades": ["3"], "subjects": ["Reading"], "org_sourcedId": "powerpath-ui-org"},
  "units": [{"title": "Animals & Classification", "sortOrder": 1, "lessons": [
     {"vendorId": 9000001, "title": "What Makes a Mammal?", "xp": 12,
      "guiding": [
        {"stimulus": {"title": "Section 1", "html": "<div><h1>Mammals</h1><p>Mammals have <strong>fur</strong> and feed milk.</p></div>"},
         "item": {"title": "Q1", "prompt": "What do mammals feed their young?", "choices": ["Milk","Seeds","Rocks","Water"], "correct_index": 0}},
        {"stimulus": {"title": "Section 2", "html": "<div><p>A whale is a mammal that lives in the sea.</p></div>"},
         "item": {"title": "Q2", "prompt": "Where does a whale live?", "choices": ["The sea","A tree","A cave","The sky"], "correct_index": 0}},
        {"stimulus": {"title": "Section 3", "html": "<div><p>Bats are mammals that can fly.</p></div>"},
         "item": {"title": "Q3", "prompt": "What can bats do?", "choices": ["Fly","Swim fast","Breathe water","Glow"], "correct_index": 0}},
      ],
      "quiz": [
        {"title": "QZ1", "prompt": "Mammals have...", "choices": ["Fur","Scales","Feathers","Shells"], "correct_index": 0},
        {"title": "QZ2", "prompt": "A whale is a...", "choices": ["Mammal","Fish","Bird","Bug"], "correct_index": 0},
        {"title": "QZ3", "prompt": "Bats can...", "choices": ["Fly","Dig","Swim","Sing"], "correct_index": 0},
        {"title": "QZ4", "prompt": "Mammals feed young with...", "choices": ["Milk","Sand","Air","Leaves"], "correct_index": 0},
      ]}]}]}

def main(argv):
    if "--selftest" in argv:
        pkg = assemble(SAMPLE); errs = validate(pkg)
        print("SELFTEST:", "PASS ✅" if not errs else "FAIL ❌")
        for e in errs: print("  -", e)
        print(json.dumps({"units": len(pkg["components"]), "lessons": len(pkg["resources"]),
                          "stimuli": len(pkg["qti"]["stimuli"]), "items": len(pkg["qti"]["items"])}))
        return 0 if not errs else 1
    if len(argv) >= 3 and argv[1] == "build":
        skel = json.load(open(argv[2])); out = argv[3] if len(argv) > 3 else "out"
        # `build` needs a MATERIALIZED skeleton (each lesson has guiding[]+quiz[] items). A shell
        # skeleton (guiding_count/_needs_items, no items) is the ORCHESTRATOR's input — it generates
        # the items. Pre-check so a shell yields a clean message instead of a raw KeyError traceback.
        shells = [l.get("vendorId", "?")
                  for u in (skel.get("units") or []) if isinstance(u, dict)
                  for l in (u.get("lessons") or []) if isinstance(l, dict)
                  and ("guiding" not in l or "quiz" not in l)]
        if shells:
            print("UNMATERIALIZED SKELETON ❌ — lessons lack guiding/quiz items: "
                  f"{shells}\n  This is a lesson-shell skeleton (for course_orchestrator.py, "
                  "which GENERATES the items). Run:\n    python3 src/course_orchestrator.py "
                  f"{argv[2]} {out}\n  or pass a MATERIALIZED skeleton "
                  "(see examples/sample_materialized.json).")
            return 1
        pkg = assemble(skel); errs = validate(pkg)
        json.dump({"ok": not errs, "errors": errs}, open("/tmp/arpack_validation.json", "w"), indent=1)
        if errs:
            print("VALIDATION FAILED ❌ (nothing emitted):"); [print("  -", e) for e in errs]; return 1
        print("VALIDATION PASS ✅  ->", emit(pkg, out)); return 0
    print(__doc__); return 0

# ---- PUSH_NOTES (NOT implemented; deliberate) ----------------------------------
# Push paths (admin access removes the Infisical dep for the OneRoster half):
#   Path A: TimeBack admin "Manage Courses" import (if it ingests a package) — TBD.
#   Path B: AlphaBuild authoring + "Sync All Lesson Plans" (proven the live course was built this way).
#   Path C: direct API — QTI leaves via POST /stimuli,/assessment-items,/assessment-tests (no import
#           endpoint exists, so QTI is POSTed regardless), OneRoster via /ims/oneroster.
# SAFETY RAIL for any future push(): assert pkg["course"]["title"].startswith("STAN-PROBE-DELETEME")
#   before a single write — there is no "prod" mode. And run POST /validate on every QTI item first.

if __name__ == "__main__":
    sys.exit(main(sys.argv))
