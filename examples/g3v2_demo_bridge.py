#!/usr/bin/env python3
"""DEMO bridge: Anirudh's `grade3-reading-v2` JSONL -> QTI 3.0 -> arpack course package.

This is a one-off DEMO adapter for the grade3-reading-v2 sample schema, not the production
transform — Mayank's incept-qti-sdk owns the real JSONL->QTI step. It exists to prove the loop:
real generated content -> our packager -> a TimeBack content surface that QC-trusts the result.

It reuses arpack's tested path: generate QTI per type -> from_qti_xml -> adapt_qti_item ->
_item (JSON for choice/order/text-entry; raw-XML envelope for hot-text/match/ebsr, Ilma RULE 1) ->
assemble -> validate -> emit.

Sample input (7 items, one per format):
  gh gist view c9e51aea3e780172c6e8c8f7c9d80233 -f g3r_sample.jsonl > /tmp/g3r_sample.jsonl

Run (offline build + validate + emit):
  python3 examples/g3v2_demo_bridge.py /tmp/g3r_sample.jsonl out/

Upload to the platform3 content-alpha DEMO tenant (proven; real TimeBack QC, sandbox tenant —
NOT the live Alpha Read app). For each generated item XML:
  BASE=https://platform3-andymontgomery-9773s-projects.vercel.app/content/alpha/implementation/api
  TOK=$(curl -fsS -X POST "$BASE/dev/mint?tenantId=demo" | jq -r .token)
  curl -fsS -X POST "$BASE/tenants/demo/alpha/content/imports/qti-package" \
    -H "Authorization: Bearer $TOK" -H "Content-Type: application/xml" \
    -H "Idempotency-Key: $(shasum -a 256 item.xml | cut -d' ' -f1)" --data-binary @item.xml
  # read back: GET .../items/{content_id}/trust  -> expect trust_status:"trusted"
  #            GET .../items/{content_id}/student-view  -> answer keys hidden
Live Alpha Read (production) is the separate, cred-gated push via Ilma's /timeback skill.
"""
import json, os, sys
from xml.sax.saxutils import escape

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))
import arpack

NS = ('<?xml version=\'1.0\' encoding=\'UTF-8\'?>\n'
      '<qti-assessment-item xmlns="http://www.imsglobal.org/xsd/imsqtiasi_v3p0" '
      'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
      'xsi:schemaLocation="http://www.imsglobal.org/xsd/imsqtiasi_v3p0 '
      'https://purl.imsglobal.org/spec/qti/v3p0/schema/xsd/imsqti_asiv3p0_v1p0.xsd" '
      'identifier="{iid}" title="{title}" adaptive="false" time-dependent="false" '
      'tool-name="alpha-read-packager" tool-version="v2-bridge">\n')
SCORE_DECL = ('  <qti-outcome-declaration identifier="SCORE" cardinality="single" base-type="float" normal-maximum="1.0">\n'
              '    <qti-default-value><qti-value>0</qti-value></qti-default-value>\n  </qti-outcome-declaration>\n'
              '  <qti-outcome-declaration identifier="MAXSCORE" cardinality="single" base-type="float">\n'
              '    <qti-default-value><qti-value>1.0</qti-value></qti-default-value>\n  </qti-outcome-declaration>\n')
RP_KEY = ('  <qti-response-processing><qti-response-condition><qti-response-if>\n'
          '    <qti-match><qti-variable identifier="RESPONSE"/><qti-base-value base-type="identifier">{key}</qti-base-value></qti-match>\n'
          '    <qti-set-outcome-value identifier="SCORE"><qti-base-value base-type="float">1</qti-base-value></qti-set-outcome-value>\n'
          '  </qti-response-if><qti-response-else>\n'
          '    <qti-set-outcome-value identifier="SCORE"><qti-base-value base-type="float">0</qti-base-value></qti-set-outcome-value>\n'
          '  </qti-response-else></qti-response-condition></qti-response-processing>\n')
RP_CORRECT = ('  <qti-response-processing><qti-response-condition><qti-response-if>\n'
              '    <qti-match><qti-variable identifier="RESPONSE"/><qti-correct identifier="RESPONSE"/></qti-match>\n'
              '    <qti-set-outcome-value identifier="SCORE"><qti-base-value base-type="float">1</qti-base-value></qti-set-outcome-value>\n'
              '  </qti-response-if><qti-response-else>\n'
              '    <qti-set-outcome-value identifier="SCORE"><qti-base-value base-type="float">0</qti-base-value></qti-set-outcome-value>\n'
              '  </qti-response-else></qti-response-condition></qti-response-processing>\n')


def itype(d):
    if d.get("type"):
        return d["type"]
    p = d.get("cell_key", "").split("|")
    return p[1] if len(p) > 1 else "unknown"


def _stem(q):
    return '  <qti-item-body>\n    <div class="stem"><p>%s</p></div>\n' % escape(q)


def mcq_xml(iid, d, multi=False):
    opts = d["answer_options"]
    correct = d["answer"] if isinstance(d["answer"], list) else [d["answer"]]
    card = "multiple" if multi else "single"
    cr = "".join("      <qti-value>%s</qti-value>\n" % escape(k) for k in correct)
    b = NS.format(iid=iid, title="MSQ" if multi else "MCQ")
    b += '  <qti-response-declaration identifier="RESPONSE" cardinality="%s" base-type="identifier">\n    <qti-correct-response>\n%s    </qti-correct-response>\n  </qti-response-declaration>\n' % (card, cr)
    b += SCORE_DECL + _stem(d["question"])
    b += '    <qti-choice-interaction response-identifier="RESPONSE" max-choices="%d">\n' % (len(opts) if multi else 1)
    for o in opts:
        b += '      <qti-simple-choice identifier="%s"><p>%s</p></qti-simple-choice>\n' % (escape(o["key"]), escape(o["text"]))
    b += '    </qti-choice-interaction>\n  </qti-item-body>\n'
    b += (RP_CORRECT if multi else RP_KEY.format(key=escape(correct[0])))
    return b + "</qti-assessment-item>\n"


def order_xml(iid, d):
    cr = "".join("      <qti-value>%s</qti-value>\n" % escape(s) for s in d["correct_order"])
    b = NS.format(iid=iid, title="Order")
    b += '  <qti-response-declaration identifier="RESPONSE" cardinality="ordered" base-type="identifier">\n    <qti-correct-response>\n%s    </qti-correct-response>\n  </qti-response-declaration>\n' % cr
    b += SCORE_DECL + _stem(d["question"])
    b += '    <qti-order-interaction response-identifier="RESPONSE" shuffle="true">\n'
    for s in d["items"]:
        b += '      <qti-simple-choice identifier="%s"><p>%s</p></qti-simple-choice>\n' % (escape(s["id"]), escape(s["content"]))
    b += '    </qti-order-interaction>\n  </qti-item-body>\n' + RP_CORRECT
    return b + "</qti-assessment-item>\n"


def hottext_xml(iid, d):
    cr = "".join("      <qti-value>%s</qti-value>\n" % escape(t) for t in d["answer"])
    b = NS.format(iid=iid, title="HotText")
    b += '  <qti-response-declaration identifier="RESPONSE" cardinality="single" base-type="identifier">\n    <qti-correct-response>\n%s    </qti-correct-response>\n  </qti-response-declaration>\n' % cr
    b += SCORE_DECL + _stem(d["question"])
    spans = " ".join('<qti-hottext identifier="%s">%s</qti-hottext>' % (escape(t["id"]), escape(t["text"])) for t in d["tokens"])
    b += '    <qti-hottext-interaction response-identifier="RESPONSE" max-choices="%d">\n      <p>%s</p>\n    </qti-hottext-interaction>\n  </qti-item-body>\n' % (d.get("max_selections", 1), spans)
    return b + RP_CORRECT + "</qti-assessment-item>\n"


def match_xml(iid, d):
    items, cats = d["items"], d["categories"]
    cr = "".join("      <qti-value>%s %s</qti-value>\n" % (escape(it["id"]), escape(it["correct_category_id"])) for it in items)
    b = NS.format(iid=iid, title="Match")
    b += '  <qti-response-declaration identifier="RESPONSE" cardinality="multiple" base-type="directedPair">\n    <qti-correct-response>\n%s    </qti-correct-response>\n  </qti-response-declaration>\n' % cr
    b += SCORE_DECL + _stem(d["question"])
    b += '    <qti-match-interaction response-identifier="RESPONSE" max-associations="%d" shuffle="true" class="qti-choices-top">\n      <qti-simple-match-set>\n' % len(items)
    for it in items:
        b += '        <qti-simple-associable-choice identifier="%s" match-max="1"><p>%s</p></qti-simple-associable-choice>\n' % (escape(it["id"]), escape(it["text"]))
    b += '      </qti-simple-match-set>\n      <qti-simple-match-set>\n'
    for c in cats:
        b += '        <qti-simple-associable-choice identifier="%s" match-max="%d"><p>%s</p></qti-simple-associable-choice>\n' % (escape(c["id"]), len(items), escape(c["label"]))
    b += '      </qti-simple-match-set>\n    </qti-match-interaction>\n  </qti-item-body>\n' + RP_CORRECT
    return b + "</qti-assessment-item>\n"


def ebsr_xml(iid, d):
    a, bp = d["part_a"], d["part_b"]
    b = NS.format(iid=iid, title="EBSR")
    for rid, part in (("RESPONSE_1", a), ("RESPONSE_2", bp)):
        b += '  <qti-response-declaration identifier="%s" cardinality="single" base-type="identifier">\n    <qti-correct-response><qti-value>%s</qti-value></qti-correct-response>\n  </qti-response-declaration>\n' % (rid, escape(part["answer"]))
    b += ('  <qti-outcome-declaration identifier="SCORE" cardinality="single" base-type="float" normal-maximum="2.0"><qti-default-value><qti-value>0</qti-value></qti-default-value></qti-outcome-declaration>\n'
          '  <qti-outcome-declaration identifier="MAXSCORE" cardinality="single" base-type="float"><qti-default-value><qti-value>2.0</qti-value></qti-default-value></qti-outcome-declaration>\n'
          '  <qti-outcome-declaration identifier="SCORE_1" cardinality="single" base-type="float" normal-maximum="1.0"><qti-default-value><qti-value>0</qti-value></qti-default-value></qti-outcome-declaration>\n'
          '  <qti-outcome-declaration identifier="SCORE_2" cardinality="single" base-type="float" normal-maximum="1.0"><qti-default-value><qti-value>0</qti-value></qti-default-value></qti-outcome-declaration>\n')
    b += '  <qti-item-body>\n    <div class="stem"><p>Read the passage and answer both parts.</p></div>\n'
    for rid, part, label in (("RESPONSE_1", a, "Part A."), ("RESPONSE_2", bp, "Part B.")):
        b += '    <qti-choice-interaction response-identifier="%s" max-choices="1">\n      <qti-prompt><p><strong class="part-label">%s</strong> %s</p></qti-prompt>\n' % (rid, label, escape(part["question"]))
        for o in part["answer_options"]:
            b += '      <qti-simple-choice identifier="%s"><p>%s</p></qti-simple-choice>\n' % (escape(o["key"]), escape(o["text"]))
        b += '    </qti-choice-interaction>\n'
    b += '  </qti-item-body>\n  <qti-response-processing>\n'
    for rid, part, sc in (("RESPONSE_1", a, "SCORE_1"), ("RESPONSE_2", bp, "SCORE_2")):
        b += ('    <qti-response-condition><qti-response-if>\n'
              '      <qti-match><qti-variable identifier="%s"/><qti-base-value base-type="identifier">%s</qti-base-value></qti-match>\n'
              '      <qti-set-outcome-value identifier="%s"><qti-base-value base-type="float">1</qti-base-value></qti-set-outcome-value>\n'
              '    </qti-response-if></qti-response-condition>\n') % (rid, escape(part["answer"]), sc)
    b += ('    <qti-set-outcome-value identifier="SCORE"><qti-sum><qti-variable identifier="SCORE_1"/><qti-variable identifier="SCORE_2"/></qti-sum></qti-set-outcome-value>\n  </qti-response-processing>\n')
    return b + "</qti-assessment-item>\n"


BUILDERS = {"mcq": lambda i, d: mcq_xml(i, d, False), "msq": lambda i, d: mcq_xml(i, d, True),
            "sequence": order_xml, "hot-text": hottext_xml, "match": match_xml, "ebsr": ebsr_xml}


def build(jsonl_path, outdir):
    rows = [json.loads(l) for l in open(jsonl_path) if l.strip()]
    article = next((r for r in rows if itype(r) == "article"), None)
    questions = [r for r in rows if itype(r) != "article"]
    guiding, qti_dir = [], os.path.join(outdir, "qti_src")
    os.makedirs(qti_dir, exist_ok=True)
    print("=== per-item: generate QTI -> from_qti_xml -> adapt -> _item -> _validate_item ===")
    for n, q in enumerate(questions, 1):
        t = itype(q)
        iid = "g3v2-%02d-%s" % (n, t.replace("-", "_"))
        xml = BUILDERS[t](iid, q)
        open(os.path.join(qti_dir, iid + ".xml"), "w").write(xml)
        parsed = arpack.from_qti_xml(xml)
        adapted = arpack.adapt_qti_item(parsed)
        emitted = arpack._item(iid, adapted, "stim_%02d" % n)
        errs = arpack._validate_item(emitted)
        route = "XML" if emitted.get("format") == "xml" else "JSON"
        print("  %-22s %-9s -> %-4s validate=%s" % (iid, t, route, "OK" if not errs else errs))
        stim = (q.get("stimulus") or {}).get("value", "")
        guiding.append({"item": adapted, "stimulus": {
            "identifier": "stim_%02d" % n, "title": q.get("template_id", iid),
            "html": "<div><p>%s</p></div>" % escape(stim).replace("\n", "</p><p>")}})
    title = (article or {}).get("title", "Grade-3 Reading sample")
    skel = {"course": {"title": arpack.THROWAWAY_PREFIX + " " + title, "courseCode": "G3R-V2-SAMPLE",
                       "grades": ["3"], "subjects": ["reading"], "org_sourcedId": "demo-org", "contentGrade": "3"},
            "units": [{"sortOrder": 1, "title": "Grade-3 Reading (v2 sample)",
                       "lessons": [{"vendorId": "9000001", "title": title, "grade": "3",
                                    "lexileLevel": (article or {}).get("lexile", 380),
                                    "guiding": guiding, "quiz": []}]}]}
    pkg = arpack.assemble(skel)
    errs = arpack.validate(pkg)
    # NOTE: this 7-item sample is an assessment block (6 passage-bound questions), so it fills the
    # 3-6 guiding slots but has 0 standalone quiz items -> validate() flags the quiz-section count.
    # That is a contract-fit note, not an item defect; the full set, structured as lessons, fills it.
    print("\nvalidate() (full reading-course contract):", errs if errs else "NONE")
    arpack.emit(pkg, outdir)
    print("package emitted ->", outdir, "| items:", len(pkg["qti"]["items"]),
          "stimuli:", len(pkg["qti"]["stimuli"]), "| raw QTI XML ->", qti_dir)
    return pkg, errs


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/g3r_sample.jsonl"
    out = sys.argv[2] if len(sys.argv) > 2 else "out_g3v2"
    build(src, out)
