#!/usr/bin/env python3
"""Build-time transforms: the three formats the Alpha Read READING renderer can't draw
(`hot-text`, `match`, `msq`) -> single-select `choice` QTI 3.0, built FRESH from the v2 bundle row.

Per RULES.md the reading renderer draws ONLY single-select `qti-choice-interaction` +
`qti-order-interaction`. hot-text / match draw BLANK; msq renders single-select-only (R2). Stan's
call: transform them to choice now (renderer parity later) so every question RENDERS + SCORES.

SOURCE OF TRUTH = the v2 bundle row (the structured fields), NOT Mayank's QTI XML for these types.
The keys + options are taken VERBATIM from the bundle (these are graded items — never invented):
  * hot-text: stem = `question`; options = the SELECTABLE token TEXTS; correct = the option whose
              token id is in `answer`. >1 correct token -> single-best fallback (pick first), logged.
  * match:    ONE article with N single-select sub-items (one per row to sort). For each row:
              stem = "<question> — <row text>"; options = the category LABELS; correct = that row's
              `correct_category_id`. The article's test references all N sub-items (stays ONE article).
  * msq:      ONE single-select choice (LOSSY). Same options; stem reworded to "Choose the BEST
              answer."; correct = the FIRST id in `answer`. Loses the multi-answer nature — counted +
              logged so the lossiness is visible.

Every emitted item carries the SCORE outcome declaration + key-match response processing (mirrors
g3v2_demo_bridge.py / push_to_timeback._ebsr_split), single-select cardinality, max-choices="1", and
the SAME `<qti-assessment-stimulus-ref>` the original Mayank item used (passed in by the caller so
the passage stays attached). No network, no file writes — pure string builders.
"""
from xml.sax.saxutils import escape as _esc

# ── canonical QTI 3.0 fragments (mirror g3v2_demo_bridge.py's tested shape) ──────────────────────
_NS = ("<?xml version='1.0' encoding='UTF-8'?>\n"
       '<qti-assessment-item xmlns="http://www.imsglobal.org/xsd/imsqtiasi_v3p0" '
       'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
       'xsi:schemaLocation="http://www.imsglobal.org/xsd/imsqtiasi_v3p0 '
       'https://purl.imsglobal.org/spec/qti/v3p0/schema/xsd/imsqti_asiv3p0_v1p0.xsd" '
       'identifier="{iid}" title="{title}" adaptive="false" time-dependent="false" '
       'tool-name="alpha-read-packager" tool-version="reading-transform">\n')

_SCORE_DECL = (
    '  <qti-outcome-declaration identifier="SCORE" cardinality="single" base-type="float" '
    'normal-maximum="1.0">\n'
    '    <qti-default-value><qti-value>0</qti-value></qti-default-value>\n'
    '  </qti-outcome-declaration>\n'
    '  <qti-outcome-declaration identifier="MAXSCORE" cardinality="single" base-type="float">\n'
    '    <qti-default-value><qti-value>1.0</qti-value></qti-default-value>\n'
    '  </qti-outcome-declaration>\n')

# single-select key-match scoring: RESPONSE == <key> -> SCORE 1 else 0 (R5: a SCORE outcome on
# every item; correct pick -> green check + XP).
_RP_KEY = (
    '  <qti-response-processing><qti-response-condition><qti-response-if>\n'
    '    <qti-match><qti-variable identifier="RESPONSE"/>'
    '<qti-base-value base-type="identifier">{key}</qti-base-value></qti-match>\n'
    '    <qti-set-outcome-value identifier="SCORE">'
    '<qti-base-value base-type="float">1</qti-base-value></qti-set-outcome-value>\n'
    '  </qti-response-if><qti-response-else>\n'
    '    <qti-set-outcome-value identifier="SCORE">'
    '<qti-base-value base-type="float">0</qti-base-value></qti-set-outcome-value>\n'
    '  </qti-response-else></qti-response-condition></qti-response-processing>\n')


def _stimulus_ref_xml(sref):
    """The same <qti-assessment-stimulus-ref> the original Mayank item carried (resolved by the
    caller from items/<id>.xml). Keeps the passage attached so the transformed item isn't orphaned."""
    if not sref:
        return ""
    return ('  <qti-assessment-stimulus-ref identifier="%s" href="stimuli/%s.xml"/>\n'
            % (_esc(sref), _esc(sref)))


def _choice_item(iid, title, stem, options, correct_id, sref):
    """Assemble ONE single-select choice QTI 3.0 item.

    options    : list of (identifier, text) — preserved verbatim from the bundle.
    correct_id : the identifier (from `options`) that is keyed correct.
    sref       : the stimulus-ref identifier to re-attach (or None).
    """
    b = _NS.format(iid=_esc(iid), title=_esc(title))
    b += ('  <qti-response-declaration identifier="RESPONSE" cardinality="single" '
          'base-type="identifier">\n    <qti-correct-response>\n'
          '      <qti-value>%s</qti-value>\n'
          '    </qti-correct-response>\n  </qti-response-declaration>\n' % _esc(correct_id))
    b += _SCORE_DECL
    b += _stimulus_ref_xml(sref)
    b += '  <qti-item-body>\n    <div class="stem"><p>%s</p></div>\n' % _esc(stem)
    b += '    <qti-choice-interaction response-identifier="RESPONSE" max-choices="1">\n'
    for oid, otext in options:
        b += ('      <qti-simple-choice identifier="%s"><p>%s</p></qti-simple-choice>\n'
              % (_esc(oid), _esc(otext)))
    b += '    </qti-choice-interaction>\n  </qti-item-body>\n'
    b += _RP_KEY.format(key=_esc(correct_id))
    b += '</qti-assessment-item>\n'
    return b


# ── per-format transforms ───────────────────────────────────────────────────────────────────────

def transform_hot_text(iid, row, sref):
    """hot-text -> ONE single-select choice.

    options = the SELECTABLE token TEXTS; the option identifier IS the token id (so the correct
    option maps directly back to the bundle `answer`). correct = the option whose token id is in
    `answer`. If `answer` has >1 correct token, single-best fallback (first answer that is a
    selectable token), and we flag it via the returned `lossy` bool.

    Returns (item_xml, lossy_bool) or None if the row has no usable tokens/answer.
    """
    question = row.get("question") or "Choose the correct sentence."
    tokens = row.get("tokens") or []
    answer = row.get("answer") or []
    # options = selectable token texts, keyed by their bundle token id (verbatim).
    options = [(t["id"], t.get("text") or "") for t in tokens
               if t.get("selectable", True) and t.get("id")]
    if not options:
        return None
    opt_ids = {oid for oid, _ in options}
    # correct = first answer id that is an actual selectable option.
    correct = next((a for a in answer if a in opt_ids), None)
    if correct is None:
        return None
    lossy = len([a for a in answer if a in opt_ids]) > 1   # multi-token answer -> single-best
    title = "HotText (transformed to single-select)"
    xml = _choice_item(iid, title, question, options, correct, sref)
    return xml, lossy


def transform_msq(iid, row, sref):
    """msq -> ONE single-select choice (LOSSY).

    Keep the SAME options (`answer_options`, keyed by their `key`). Reword the stem to ask for the
    single best. correct = the FIRST id in `answer`. This drops the multi-answer nature on purpose
    (Stan's transform-now call) — the caller COUNTS + LOGS every msq so the lossiness is visible.

    Returns (item_xml, n_correct_dropped) or None if no options/answer.
    """
    opts = row.get("answer_options") or []
    answer = row.get("answer") or []
    options = [(o.get("key"), o.get("text") or "") for o in opts if o.get("key") is not None]
    if not options or not answer:
        return None
    opt_ids = {oid for oid, _ in options}
    correct = next((a for a in answer if a in opt_ids), None)
    if correct is None:
        return None
    base_q = (row.get("question") or "").strip()
    stem = (base_q + "  (Choose the BEST answer.)") if base_q else "Choose the BEST answer."
    n_correct = len([a for a in answer if a in opt_ids])
    title = "MSQ (transformed to single-best single-select)"
    xml = _choice_item(iid, title, stem, options, correct, sref)
    return xml, n_correct           # n_correct>1 == lossy (the dropped-answers count)


def transform_match(iid, row, sref):
    """match -> ONE article's worth of N single-select sub-items (one per row to sort).

    For each thing in `items`: stem = "<question> — <thing text>"; options = the category LABELS
    (identifier = category id, verbatim); correct = that thing's `correct_category_id`. The caller
    references ALL N sub-items in the SAME article's test so it stays ONE article.

    Returns a list of (sub_item_id, sub_item_xml) — one per sortable row — or None if the match has
    no categories or no items (the malformed stray match).
    """
    question = (row.get("question") or "Sort each item into the correct group.").strip()
    cats = row.get("categories") or []
    things = row.get("items") or []
    if not cats or not things:
        return None
    options = [(c["id"], c.get("label") or "") for c in cats if c.get("id")]
    cat_ids = {oid for oid, _ in options}
    if not options:
        return None
    out = []
    for n, thing in enumerate(things, 1):
        tid = thing.get("id") or ("row%d" % n)
        correct = thing.get("correct_category_id")
        if correct not in cat_ids:
            # row points at a category that doesn't exist — skip this row, keep the rest.
            continue
        sub_id = "%s-m%02d" % (iid, n)
        stem = "%s — %s" % (question, (thing.get("text") or "").strip())
        title = "Match row %d (transformed to single-select)" % n
        xml = _choice_item(sub_id, title, stem, options, correct, sref)
        out.append((sub_id, xml))
    return out or None
