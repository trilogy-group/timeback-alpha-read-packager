#!/usr/bin/env python3
"""Automated push: a QTI package -> a draft course on TimeBack (live or any env).

Implements Ilma's documented push pipeline (incept-timeback-plugin) end-to-end so the live
upload is reproducible, not hand-typed. Ilma's `/timeback` skill remains the canonical,
maintained surface; this is the automation we ran on 2026-06-17 to push the real ELA package
and confirm it renders in AlphaBuild (all 6 formats, QTI "Valid").

INPUT: a QTI package dir with `items/*.xml` (raw QTI assessment-items, posted VERBATIM per Ilma
RULE 1 — correct for every interaction type) and `stimuli/*.xml` (qti-assessment-stimulus).

USAGE:
  export TIMEBACK_CLIENT_ID=...        # or TIMEBACK_SSO_CLIENT_ID (from a gitignored .env; NEVER commit)
  export TIMEBACK_CLIENT_SECRET=...    # or TIMEBACK_SSO_CLIENT_SECRET
  python3 examples/push_to_timeback.py --package /path/to/qti_package --org <ORG_SOURCEDID> \
      [--title "..."] [--prefix STAN-PROBE-DELETEME-<ts>] [--checkpoint /tmp/push_state.json] [--verify]

SAFETY (by design):
  * Creates ONLY new entities; 409 = already exists = treated as success. Never PUT/PATCH/DELETE.
  * Course sourcedId must start with STAN-PROBE-DELETEME unless --allow-non-draft (avoids clobbering real courses).
  * --org GOTCHA: the draft must be created in an org the VIEWER belongs to, or AlphaBuild shows "Access denied".
  * Checkpointed (resume-safe) + retry on 429/5xx.
Creds come from env only — never echoed, never written to the repo.
"""
import argparse, base64, glob, json, os, re, sys, time, urllib.parse, urllib.request, urllib.error
from xml.sax.saxutils import escape as _xml_escape

# Reuse the packager's QTI parser so the EBSR split sees the SAME parsed parts (choices/keys/prompts)
# the assembler does — single source of truth for the decomposition.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    import arpack
except Exception:                                          # arpack absent → EBSR split degrades to
    arpack = None                                          # posting the composite verbatim (old behavior)


def _ebsr_split(raw):
    """If `raw` is a COMPOSITE EBSR item (one assessment-item with TWO qti-choice-interactions),
    return [(partA_id, partA_xml), (partB_id, partB_xml), …] — one standalone single-interaction
    QTI 3.0 choice item per part, id-linked as <iid>-partA / <iid>-partB. Otherwise return None.

    Alpha Read's reading renderer flattens a composite (two-interaction) item into one ~8-option
    question (confirmed live); two linked single-select choice items render correctly. Each emitted
    item carries: one qti-response-declaration (single/identifier) with the part's correct id, one
    qti-choice-interaction with the part's own <qti-prompt> + simple-choices, a SCORE outcome decl,
    a match_correct-style response-processing, and the SAME qti-assessment-stimulus-ref as the source."""
    if arpack is None:
        return None
    try:
        parsed = arpack.from_qti_xml(raw)
    except Exception:
        return None
    if parsed.get("format") != "ebsr":
        return None
    parts = parsed.get("ebsr_parts") or []
    if len(parts) < 2:
        return None
    src_iid = parsed.get("identifier") or "ebsr"
    src_title = parsed.get("title") or src_iid
    sref = re.search(r'<qti-assessment-stimulus-ref[^>]*/?>', raw)        # copy verbatim if present
    sref_xml = ("\n  " + sref.group(0)) if sref else ""
    out = []
    for k, part in enumerate(parts):
        pid = f"{src_iid}-part{chr(65 + k)}"
        ptitle = f"{src_title} — Part {chr(65 + k)}"
        ids = part.get("choice_ids") or [f"{pid}_c{n}" for n in range(len(part.get("choices", [])))]
        corr = [ids[i] for i in part.get("correct_indices", []) if 0 <= i < len(ids)]
        corr_xml = "".join(f"<qti-value>{_xml_escape(c)}</qti-value>" for c in corr)
        choices_xml = "".join(
            f'\n      <qti-simple-choice identifier="{_xml_escape(ids[n])}"><p>{_xml_escape(txt)}</p>'
            f'</qti-simple-choice>'
            for n, txt in enumerate(part.get("choices", [])))
        prompt = part.get("prompt") or ""
        prompt_xml = f"<qti-prompt><p>{_xml_escape(prompt)}</p></qti-prompt>" if prompt else ""
        xml = (
            "<?xml version='1.0' encoding='UTF-8'?>\n"
            '<qti-assessment-item xmlns="http://www.imsglobal.org/xsd/imsqtiasi_v3p0" '
            f'identifier="{_xml_escape(pid)}" title="{_xml_escape(ptitle)}" '
            'adaptive="false" time-dependent="false">\n'
            '  <qti-response-declaration identifier="RESPONSE" cardinality="single" '
            f'base-type="identifier"><qti-correct-response>{corr_xml}</qti-correct-response>'
            '</qti-response-declaration>\n'
            '  <qti-outcome-declaration identifier="SCORE" cardinality="single" base-type="float"/>'
            f"{sref_xml}\n"
            '  <qti-item-body>\n'
            '    <qti-choice-interaction response-identifier="RESPONSE" max-choices="1">'
            f"{prompt_xml}{choices_xml}\n"
            '    </qti-choice-interaction>\n'
            '  </qti-item-body>\n'
            '  <qti-response-processing '
            'template="https://www.imsglobal.org/question/qti_v3p0/rptemplates/match_correct"/>\n'
            '</qti-assessment-item>\n'
        )
        out.append((pid, ptitle, xml))
    return out

TOKEN_URL = os.environ.get("TIMEBACK_TOKEN_URL",
    "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token")
QTI = os.environ.get("TIMEBACK_QTI_BASE", "https://qti.alpha-1edtech.ai/api")
OR = os.environ.get("TIMEBACK_OR_BASE", "https://api.alpha-1edtech.ai/ims/oneroster")


def _env(*names):
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    sys.exit("Missing credential env var (one of: %s)" % ", ".join(names))


def mint_token():
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": _env("TIMEBACK_CLIENT_ID", "TIMEBACK_SSO_CLIENT_ID"),
        "client_secret": _env("TIMEBACK_CLIENT_SECRET", "TIMEBACK_SSO_CLIENT_SECRET"),
    }).encode()
    r = urllib.request.urlopen(urllib.request.Request(
        TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=30)
    tok = json.load(r)["access_token"]
    scopes = json.loads(base64.urlsafe_b64decode(tok.split(".")[1] + "==")).get("scope", "")
    return tok, scopes


def post(url, body, label, tok, state, ckpt):
    if label in state:
        print("  skip (ckpt) %-28s -> %s" % (label, state[label].get("status")))
        return True
    data = json.dumps(body).encode()
    for attempt in range(3):
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                url, data=data, method="POST",
                headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"}), timeout=40)
            state[label] = {"status": r.status}
            json.dump(state, open(ckpt, "w"), indent=1)
            print("  OK  %-28s HTTP %s" % (label, r.status))
            return True
        except urllib.error.HTTPError as e:
            if e.code == 409:
                state[label] = {"status": 409, "note": "exists"}
                json.dump(state, open(ckpt, "w"), indent=1)
                print("  OK  %-28s HTTP 409 (exists)" % label)
                return True
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep([5, 15, 30][attempt]); continue
            print("  ERR %-28s HTTP %s %s" % (label, e.code, e.read()[:200])); return False
        except Exception as e:
            if attempt < 2:
                time.sleep([5, 15, 30][attempt]); continue
            print("  ERR %-28s %s" % (label, str(e)[:200])); return False


def get_json(url, tok):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": "Bearer " + tok}), timeout=30)
        return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True, help="QTI package dir (items/*.xml + stimuli/*.xml)")
    ap.add_argument("--org", required=True, help="OneRoster org sourcedId the VIEWER belongs to")
    ap.add_argument("--title", default="STAN-PROBE-DELETEME draft course")
    ap.add_argument("--prefix", default="STAN-PROBE-DELETEME-" +
                    __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M"))
    ap.add_argument("--checkpoint", default="/tmp/timeback_push_state.json")
    ap.add_argument("--allow-non-draft", action="store_true")
    ap.add_argument("--enroll-student", default=None,
                    help="OneRoster user sourcedId to enroll as a student (creates term+class+enrollment "
                         "so the course surfaces in the student app). Use a TEST student you own — never a real child.")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    if not a.prefix.startswith("STAN-PROBE-DELETEME") and not a.allow_non_draft:
        sys.exit("Refusing: --prefix must start with STAN-PROBE-DELETEME (or pass --allow-non-draft).")

    P = a.prefix
    # Render rules (verified 2026-06-17): Alpha Read fetches assessment-tests/article_<vendorResourceId>
    # (vendorResourceId = BARE NUMBER) and the DASHBOARD derives each article's link from the OneRoster
    # resource/component-resource sourcedIds — so per article: test = resource = component-resource = article_<N>.
    # AND one article must be ONE passage + its questions (items sharing a stimulus-ref); unrelated passages in
    # one article render as an incoherent jumble. So we GROUP items by stimulus-ref → one article per passage.
    base = (re.sub(r"\D", "", P) or "90000001")[-10:]
    COURSE, UNIT = P, P + "-unit-1"
    state = json.load(open(a.checkpoint)) if os.path.exists(a.checkpoint) else {}
    tok, scopes = mint_token()
    print("token OK | scopes:", scopes or "(none)")
    print("course:", COURSE, "| org:", a.org)

    print("--- stimuli ---")
    for f in sorted(glob.glob(os.path.join(a.package, "stimuli", "*.xml"))):
        raw = open(f, encoding="utf-8-sig").read()
        sid = re.search(r'identifier="([^"]+)"', raw).group(1)
        title = (re.search(r'title="([^"]+)"', raw) or [None, sid])[1]
        m = re.search(r"<qti-stimulus-body[^>]*>(.*)</qti-stimulus-body>", raw, re.S)
        post(QTI + "/stimuli", {"identifier": sid, "title": title,
             "content": (m.group(1).strip() if m else "<p></p>")}, "stim:" + sid, tok, state, a.checkpoint)

    print("--- items (verbatim XML) + group by passage (stimulus-ref) ---")
    from collections import OrderedDict
    groups, item_ids = OrderedDict(), []
    for f in sorted(glob.glob(os.path.join(a.package, "items", "*.xml"))):
        raw = open(f, encoding="utf-8-sig").read()
        iid = re.search(r'identifier="([^"]+)"', raw).group(1)
        ititle = (re.search(r'title="([^"]+)"', raw) or [None, iid])[1]
        sref = re.search(r'qti-assessment-stimulus-ref[^>]*identifier="([^"]+)"', raw)
        key = sref.group(1) if sref else iid
        # COMPOSITE EBSR (one item, two qti-choice-interactions) renders as one ~8-option blob in
        # Alpha Read (confirmed live). Split it into two single-interaction choice items (-partA/-partB)
        # and POST + reference BOTH, so each renders as its own single-select question. Every other
        # item type is POSTed verbatim, unchanged.
        ebsr = _ebsr_split(raw)
        if ebsr:
            for pid, ptitle, pxml in ebsr:
                groups.setdefault(key, []).append((pid, ptitle))
                item_ids.append(pid)
                post(QTI + "/assessment-items", {"format": "xml", "xml": pxml},
                     "item:" + pid, tok, state, a.checkpoint)
        else:
            groups.setdefault(key, []).append((iid, ititle))
            item_ids.append(iid)
            post(QTI + "/assessment-items", {"format": "xml", "xml": raw},
                 "item:" + iid, tok, state, a.checkpoint)
    if not item_ids:
        sys.exit("No items/*.xml found in package.")
    print("  -> %d item(s) in %d passage-group(s) = %d article(s)" % (len(item_ids), len(groups), len(groups)))

    print("--- oneroster course + unit ---")
    post(OR + "/rostering/v1p2/courses", {"course": {
        "sourcedId": COURSE, "status": "active", "title": a.title, "courseCode": COURSE,
        "grades": ["3"], "subjects": ["Reading"], "org": {"sourcedId": a.org}, "primaryApp": "alpha_read",
        "metadata": {"primaryApp": "alpha_read", "isAlphaRead": True, "publishStatus": "testing", "timebackVisible": True}}},
        "course:" + COURSE, tok, state, a.checkpoint)
    post(OR + "/rostering/v1p2/courses/components", {"courseComponent": {
        "sourcedId": UNIT, "status": "active", "title": "Unit 1", "sortOrder": 1,
        "course": {"sourcedId": COURSE}, "parent": None, "courseComponent": None, "metadata": {}}},
        "unit:" + UNIT, tok, state, a.checkpoint)

    print("--- articles (one per passage: test + lesson + resource + component-resource = article_<N>) ---")
    articles = []
    for i, (key, members) in enumerate(groups.items(), 1):
        N = base + "%02d" % i
        ART, LES = "article_" + N, P + "-lesson-%02d" % i
        iids = [m[0] for m in members]
        title = members[0][1] or a.title
        post(QTI + "/assessment-tests", {"identifier": ART, "title": title,
            "qti-test-part": [{"identifier": "tp1", "navigationMode": "nonlinear", "submissionMode": "individual",
                "qti-assessment-section": [{"identifier": "sec1", "title": title, "visible": True, "required": True,
                    "fixed": False, "sequence": 1,
                    "qti-assessment-item-ref": [{"identifier": x, "href": x + ".xml"} for x in iids]}]}],
            "qti-outcome-declaration": [{"identifier": "SCORE", "cardinality": "single", "baseType": "float"}]},
            "test:" + ART, tok, state, a.checkpoint)
        post(OR + "/rostering/v1p2/courses/components", {"courseComponent": {
            "sourcedId": LES, "status": "active", "title": title, "sortOrder": i,
            "course": {"sourcedId": COURSE}, "parent": {"sourcedId": UNIT}, "courseComponent": {"sourcedId": UNIT},
            "metadata": {}}}, "lesson:" + LES, tok, state, a.checkpoint)
        post(OR + "/resources/v1p2/resources/", {"resource": {
            "sourcedId": ART, "status": "active", "title": title, "importance": "primary", "vendorResourceId": N,
            "metadata": {"type": "qti", "subType": "qti-test", "lessonType": "alpha-read-article", "xp": 12,
                         "questionType": "custom", "url": QTI + "/assessment-tests/" + ART}}},
            "res:" + ART, tok, state, a.checkpoint)
        post(OR + "/rostering/v1p2/courses/component-resources", {"componentResource": {
            "sourcedId": ART, "status": "active", "title": title, "sortOrder": 1,
            "resource": {"sourcedId": ART}, "courseComponent": {"sourcedId": LES},
            "metadata": {"lessonType": "alpha-read-article"}}}, "cr:" + ART, tok, state, a.checkpoint)
        articles.append((N, ART, title, len(iids)))

    if a.enroll_student:
        # Make the course surface in the student app: term (in --org) -> class (course+org+term) -> enrollment.
        # OneRoster: class requires `org`; terms must be in the same org (hence a draft term in --org).
        TERM, CLASS, ENR = P + "-term", P + "-class", P + "-enr"
        print("--- enroll student", a.enroll_student, "---")
        post(OR + "/rostering/v1p2/academicSessions", {"academicSession": {
            "sourcedId": TERM, "status": "active", "title": a.title + " Term", "type": "term",
            "startDate": "2025-08-01", "endDate": "2026-06-30", "schoolYear": "2026",
            "org": {"sourcedId": a.org}}}, "term:" + TERM, tok, state, a.checkpoint)
        post(OR + "/rostering/v1p2/classes", {"class": {
            "sourcedId": CLASS, "status": "active", "title": a.title, "classCode": CLASS, "classType": "scheduled",
            "grades": ["3"], "subjects": ["Reading"], "course": {"sourcedId": COURSE},
            "org": {"sourcedId": a.org}, "school": {"sourcedId": a.org}, "terms": [{"sourcedId": TERM}]}},
            "class:" + CLASS, tok, state, a.checkpoint)
        post(OR + "/rostering/v1p2/enrollments", {"enrollment": {
            "sourcedId": ENR, "status": "active", "role": "student", "primary": True,
            "user": {"sourcedId": a.enroll_student}, "class": {"sourcedId": CLASS},
            "org": {"sourcedId": a.org}, "school": {"sourcedId": a.org}}}, "enroll:" + ENR, tok, state, a.checkpoint)

    if a.verify:
        print("--- verify (read-back) ---")
        sc, _ = get_json(OR + "/rostering/v1p2/courses/" + COURSE, tok); print("  course GET:", sc)
        for N, ART, title, n in articles:
            sc, _ = get_json(QTI + "/assessment-tests/" + ART, tok); print("  test %s GET: %s" % (ART, sc))

    print("\n=== DONE === %d article(s), one per passage" % len(articles))
    print("AlphaBuild course   :", "https://app.alpha-build.org/content/" + COURSE)
    # The Alpha Read STUDENT app needs BOTH articleId=<N> and crsid=article_<N> (verified 2026-06-17).
    for N, ART, title, n in articles:
        print("  %-32s (%dq) -> https://alpharead.alpha-1edtech.ai/articles?articleId=%s&crsid=%s" % (title[:32], n, N, ART))


if __name__ == "__main__":
    main()
