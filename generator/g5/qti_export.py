#!/usr/bin/env python3
"""
QTI 2.1 Export Pipeline for G5 Course (Gate 5 preparation).

Reads COURSE_SKELETON_V2.json for item slot assignments and
/tmp/abdul_verified_gate2.jsonl for item content, then generates
one QTI 2.1 XML assessmentItem file per item plus an imsmanifest.xml.

Item types handled:
  hot-text   -> customInteraction with hottextInteraction
  sequence   -> orderInteraction
  match      -> matchInteraction
  ebsr       -> two choiceInteractions (RESPONSE_A + RESPONSE_B)
  vocab-mcq  -> choiceInteraction (single-select MCQ)

Output:
  /tmp/qti_output/{item_id}.xml  (one per item)
  /tmp/qti_output/imsmanifest.xml
"""

import json
import os
import sys
import re
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.dom import minidom

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SKELETON_PATH = Path(
    "/Users/stanhus/Documents/grade3-reading/artifacts/"
    "g5-course-candidate-v0/COURSE_SKELETON_V2.json"
)
JSONL_PATH = Path("/tmp/abdul_verified_gate2.jsonl")
VOCAB_SEEDS_V1 = Path(
    "/Users/stanhus/Documents/grade3-reading/artifacts/"
    "alpha-read-packager/generator/g5/l5_vocab_seeds.json"
)
VOCAB_SEEDS_V2 = Path(
    "/Users/stanhus/Documents/grade3-reading/artifacts/"
    "alpha-read-packager/generator/g5/l5_vocab_seeds_v2.json"
)
OUTPUT_DIR = Path("/tmp/qti_output")

# QTI 2.1 namespace
QTI_NS = "http://www.imsglobal.org/xsd/imsqti_v2p1"
QTI_NS_MAP = {
    "xmlns": QTI_NS,
    "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "xsi:schemaLocation": (
        "http://www.imsglobal.org/xsd/imsqti_v2p1 "
        "http://www.imsglobal.org/xsd/imsqti_v2p1.xsd"
    ),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _escape(text: str) -> str:
    """Light XML-safe text; ET handles escaping but this normalises whitespace."""
    if not isinstance(text, str):
        text = str(text)
    return text.strip()


def _safe_id(raw: str) -> str:
    """Make an XML-safe identifier from an arbitrary string."""
    s = re.sub(r"[^a-zA-Z0-9_\-.]", "_", raw)
    if s and s[0].isdigit():
        s = "I_" + s
    return s or "ITEM"


def _pretty_xml(root: ET.Element) -> str:
    """Return pretty-printed XML string with declaration."""
    raw = ET.tostring(root, encoding="unicode")
    reparsed = minidom.parseString(raw)
    return reparsed.toprettyxml(indent="  ", encoding=None)


def _make_assessment_item(item_id: str, title: str) -> ET.Element:
    """Create the root assessmentItem element with QTI 2.1 attributes."""
    attrib = {
        "identifier": _safe_id(item_id),
        "title": title,
        "adaptive": "false",
        "timeDependent": "false",
    }
    attrib.update(QTI_NS_MAP)
    root = ET.Element("assessmentItem", attrib)
    return root


# ---------------------------------------------------------------------------
# Type handlers
# Each returns a fully populated assessmentItem ET.Element.
# ---------------------------------------------------------------------------

def _build_hot_text(item: dict) -> ET.Element:
    """
    hot-text -> customInteraction containing hottext span elements.

    Abdul's schema: options = [{id, text}], key = [id, ...]
    We map this to QTI hottextInteraction (a standard QTI 2.1 interaction
    in the PCI / custom-interaction namespace).  TimeBack accepts this as
    customInteraction wrapping individual hottext spans.
    """
    item_id = item["id"]
    root = _make_assessment_item(item_id, item.get("stem", "")[:80])

    # --- responseDeclaration ---
    correct_ids = item.get("key", [])
    resp_decl = ET.SubElement(root, "responseDeclaration", {
        "identifier": "RESPONSE",
        "cardinality": "multiple",
        "baseType": "identifier",
    })
    correct_response = ET.SubElement(resp_decl, "correctResponse")
    for cid in correct_ids:
        val = ET.SubElement(correct_response, "value")
        val.text = _safe_id(cid)

    # --- outcomeDeclaration ---
    out_decl = ET.SubElement(root, "outcomeDeclaration", {
        "identifier": "SCORE",
        "cardinality": "single",
        "baseType": "float",
    })
    default_val = ET.SubElement(out_decl, "defaultValue")
    dv = ET.SubElement(default_val, "value")
    dv.text = "0"

    # --- itemBody ---
    body = ET.SubElement(root, "itemBody")
    prompt_p = ET.SubElement(body, "p")
    prompt_p.text = _escape(item.get("stem", ""))

    interaction = ET.SubElement(body, "hottextInteraction", {
        "responseIdentifier": "RESPONSE",
        "maxChoices": str(len(correct_ids)),
    })
    prompt_block = ET.SubElement(interaction, "prompt")
    prompt_block.text = "Select the correct words or phrases."

    # Wrap all tokens in a <p>; selectable ones become <hottext>
    token_p = ET.SubElement(interaction, "p")
    options = item.get("options", [])
    for opt in options:
        ht = ET.SubElement(token_p, "hottext", {
            "identifier": _safe_id(opt["id"]),
        })
        ht.text = _escape(opt.get("text", ""))
        # Add a space between tokens for readability
        ht.tail = " "

    # --- responseProcessing ---
    rp = ET.SubElement(root, "responseProcessing", {
        "template": "http://www.imsglobal.org/question/qti_v2p1/rptemplates/match_correct",
    })

    return root


def _build_sequence(item: dict) -> ET.Element:
    """sequence -> orderInteraction."""
    item_id = item["id"]
    root = _make_assessment_item(item_id, item.get("stem", "")[:80])

    correct_order = item.get("key", [])

    # --- responseDeclaration ---
    resp_decl = ET.SubElement(root, "responseDeclaration", {
        "identifier": "RESPONSE",
        "cardinality": "ordered",
        "baseType": "identifier",
    })
    correct_response = ET.SubElement(resp_decl, "correctResponse")
    for cid in correct_order:
        val = ET.SubElement(correct_response, "value")
        val.text = _safe_id(cid)

    # --- outcomeDeclaration ---
    out_decl = ET.SubElement(root, "outcomeDeclaration", {
        "identifier": "SCORE",
        "cardinality": "single",
        "baseType": "float",
    })
    default_val = ET.SubElement(out_decl, "defaultValue")
    dv = ET.SubElement(default_val, "value")
    dv.text = "0"

    # --- itemBody ---
    body = ET.SubElement(root, "itemBody")
    prompt_p = ET.SubElement(body, "p")
    prompt_p.text = _escape(item.get("stem", ""))

    interaction = ET.SubElement(body, "orderInteraction", {
        "responseIdentifier": "RESPONSE",
        "shuffle": "true",
    })
    prompt_block = ET.SubElement(interaction, "prompt")
    prompt_block.text = "Drag and drop to arrange in the correct order."

    options = item.get("options", [])
    for opt in options:
        choice = ET.SubElement(interaction, "simpleChoice", {
            "identifier": _safe_id(opt["id"]),
        })
        choice.text = _escape(opt.get("text", ""))

    # --- responseProcessing ---
    ET.SubElement(root, "responseProcessing", {
        "template": "http://www.imsglobal.org/question/qti_v2p1/rptemplates/match_correct",
    })

    return root


def _build_match(item: dict) -> ET.Element:
    """match -> matchInteraction."""
    item_id = item["id"]
    root = _make_assessment_item(item_id, item.get("stem", "")[:80])

    left_items = item.get("left", [])
    right_items = item.get("right", [])
    key_map = item.get("key", {})  # {left_id: right_id}

    # Build correct response as directed pairs "left_id right_id"
    correct_pairs = [f"{_safe_id(l)} {_safe_id(r)}" for l, r in key_map.items()]
    max_assoc = len(left_items)

    # --- responseDeclaration ---
    resp_decl = ET.SubElement(root, "responseDeclaration", {
        "identifier": "RESPONSE",
        "cardinality": "multiple",
        "baseType": "directedPair",
    })
    correct_response = ET.SubElement(resp_decl, "correctResponse")
    for pair in correct_pairs:
        val = ET.SubElement(correct_response, "value")
        val.text = pair

    # --- outcomeDeclaration ---
    out_decl = ET.SubElement(root, "outcomeDeclaration", {
        "identifier": "SCORE",
        "cardinality": "single",
        "baseType": "float",
    })
    default_val = ET.SubElement(out_decl, "defaultValue")
    dv = ET.SubElement(default_val, "value")
    dv.text = "0"

    # --- itemBody ---
    body = ET.SubElement(root, "itemBody")
    prompt_p = ET.SubElement(body, "p")
    prompt_p.text = _escape(item.get("stem", ""))

    interaction = ET.SubElement(body, "matchInteraction", {
        "responseIdentifier": "RESPONSE",
        "maxAssociations": str(max_assoc),
    })
    prompt_block = ET.SubElement(interaction, "prompt")
    prompt_block.text = "Match each item on the left to its category on the right."

    # simpleMatchSet 1: left items
    sms1 = ET.SubElement(interaction, "simpleMatchSet")
    for opt in left_items:
        sac = ET.SubElement(sms1, "simpleAssociableChoice", {
            "identifier": _safe_id(opt["id"]),
            "matchMax": str(len(right_items)),
        })
        sac.text = _escape(opt.get("text", ""))

    # simpleMatchSet 2: right items (categories)
    sms2 = ET.SubElement(interaction, "simpleMatchSet")
    for opt in right_items:
        sac = ET.SubElement(sms2, "simpleAssociableChoice", {
            "identifier": _safe_id(opt["id"]),
            "matchMax": str(max_assoc),
        })
        sac.text = _escape(opt.get("text", ""))

    # --- responseProcessing ---
    ET.SubElement(root, "responseProcessing", {
        "template": "http://www.imsglobal.org/question/qti_v2p1/rptemplates/match_correct",
    })

    return root


def _build_ebsr(item: dict) -> ET.Element:
    """ebsr -> two choiceInteractions: RESPONSE_A and RESPONSE_B."""
    item_id = item["id"]
    root = _make_assessment_item(item_id, item.get("stem", "")[:80])

    options = item.get("options", [])
    part_a_opts = [o for o in options if o.get("part") == "A"]
    part_b_opts = [o for o in options if o.get("part") == "B"]

    key = item.get("key", [])
    # key is a list of option IDs like ["A_B", "B_C"]
    correct_a = [_safe_id(k) for k in key if k.startswith("A_")]
    correct_b = [_safe_id(k) for k in key if k.startswith("B_")]

    # --- responseDeclaration A ---
    resp_a = ET.SubElement(root, "responseDeclaration", {
        "identifier": "RESPONSE_A",
        "cardinality": "single",
        "baseType": "identifier",
    })
    corr_a = ET.SubElement(resp_a, "correctResponse")
    for cid in correct_a:
        val = ET.SubElement(corr_a, "value")
        val.text = cid

    # --- responseDeclaration B ---
    resp_b = ET.SubElement(root, "responseDeclaration", {
        "identifier": "RESPONSE_B",
        "cardinality": "single",
        "baseType": "identifier",
    })
    corr_b = ET.SubElement(resp_b, "correctResponse")
    for cid in correct_b:
        val = ET.SubElement(corr_b, "value")
        val.text = cid

    # --- outcomeDeclarations ---
    for resp_id in ("SCORE_A", "SCORE_B", "SCORE"):
        out_decl = ET.SubElement(root, "outcomeDeclaration", {
            "identifier": resp_id,
            "cardinality": "single",
            "baseType": "float",
        })
        default_val = ET.SubElement(out_decl, "defaultValue")
        dv = ET.SubElement(default_val, "value")
        dv.text = "0"

    # --- itemBody ---
    body = ET.SubElement(root, "itemBody")
    stem_p = ET.SubElement(body, "p")
    stem_p.text = _escape(item.get("stem", ""))

    # Part A
    part_a_label = ET.SubElement(body, "p")
    part_a_label.text = "Part A"
    interaction_a = ET.SubElement(body, "choiceInteraction", {
        "responseIdentifier": "RESPONSE_A",
        "shuffle": "false",
        "maxChoices": "1",
    })
    prompt_a = ET.SubElement(interaction_a, "prompt")
    prompt_a.text = "Choose the best answer."
    for opt in part_a_opts:
        choice = ET.SubElement(interaction_a, "simpleChoice", {
            "identifier": _safe_id(opt["id"]),
        })
        choice.text = _escape(opt.get("text", ""))

    # Part B
    part_b_label = ET.SubElement(body, "p")
    part_b_label.text = "Part B"
    interaction_b = ET.SubElement(body, "choiceInteraction", {
        "responseIdentifier": "RESPONSE_B",
        "shuffle": "false",
        "maxChoices": "1",
    })
    prompt_b = ET.SubElement(interaction_b, "prompt")
    prompt_b.text = "Which evidence from the text best supports your answer to Part A?"
    for opt in part_b_opts:
        choice = ET.SubElement(interaction_b, "simpleChoice", {
            "identifier": _safe_id(opt["id"]),
        })
        choice.text = _escape(opt.get("text", ""))

    # --- responseProcessing: custom (both parts must be correct for SCORE=1) ---
    rp = ET.SubElement(root, "responseProcessing")
    # SCORE_A
    rr_a = ET.SubElement(rp, "responseCondition")
    if_a = ET.SubElement(rr_a, "responseIf")
    match_a = ET.SubElement(if_a, "match")
    var_a = ET.SubElement(match_a, "variable", {"identifier": "RESPONSE_A"})
    correct_a_el = ET.SubElement(match_a, "correct", {"identifier": "RESPONSE_A"})
    set_score_a = ET.SubElement(if_a, "setOutcomeValue", {"identifier": "SCORE_A"})
    base_val_a = ET.SubElement(set_score_a, "baseValue", {"baseType": "float"})
    base_val_a.text = "1"
    else_a = ET.SubElement(rr_a, "responseElse")
    set_score_a0 = ET.SubElement(else_a, "setOutcomeValue", {"identifier": "SCORE_A"})
    base_val_a0 = ET.SubElement(set_score_a0, "baseValue", {"baseType": "float"})
    base_val_a0.text = "0"

    # SCORE_B
    rr_b = ET.SubElement(rp, "responseCondition")
    if_b = ET.SubElement(rr_b, "responseIf")
    match_b = ET.SubElement(if_b, "match")
    var_b = ET.SubElement(match_b, "variable", {"identifier": "RESPONSE_B"})
    correct_b_el = ET.SubElement(match_b, "correct", {"identifier": "RESPONSE_B"})
    set_score_b = ET.SubElement(if_b, "setOutcomeValue", {"identifier": "SCORE_B"})
    base_val_b = ET.SubElement(set_score_b, "baseValue", {"baseType": "float"})
    base_val_b.text = "1"
    else_b = ET.SubElement(rr_b, "responseElse")
    set_score_b0 = ET.SubElement(else_b, "setOutcomeValue", {"identifier": "SCORE_B"})
    base_val_b0 = ET.SubElement(set_score_b0, "baseValue", {"baseType": "float"})
    base_val_b0.text = "0"

    # SCORE = SCORE_A * SCORE_B (both must be 1)
    rr_final = ET.SubElement(rp, "setOutcomeValue", {"identifier": "SCORE"})
    product = ET.SubElement(rr_final, "product")
    sa_var = ET.SubElement(product, "variable", {"identifier": "SCORE_A"})
    sb_var = ET.SubElement(product, "variable", {"identifier": "SCORE_B"})

    return root


def _build_vocab_mcq(item: dict) -> ET.Element:
    """vocab-mcq -> choiceInteraction (single-select MCQ)."""
    item_id = item["id"]
    root = _make_assessment_item(item_id, item.get("stem", "")[:80])

    correct_key = item.get("key", "")
    if isinstance(correct_key, list):
        correct_key = correct_key[0] if correct_key else ""

    # --- responseDeclaration ---
    resp_decl = ET.SubElement(root, "responseDeclaration", {
        "identifier": "RESPONSE",
        "cardinality": "single",
        "baseType": "identifier",
    })
    correct_response = ET.SubElement(resp_decl, "correctResponse")
    val = ET.SubElement(correct_response, "value")
    val.text = _safe_id(correct_key)

    # --- outcomeDeclaration ---
    out_decl = ET.SubElement(root, "outcomeDeclaration", {
        "identifier": "SCORE",
        "cardinality": "single",
        "baseType": "float",
    })
    default_val = ET.SubElement(out_decl, "defaultValue")
    dv = ET.SubElement(default_val, "value")
    dv.text = "0"

    # --- itemBody ---
    body = ET.SubElement(root, "itemBody")

    # Include passage text if present (vocab items carry their own passage)
    passage = item.get("passage_text", "")
    if passage:
        passage_div = ET.SubElement(body, "div", {"class": "passage"})
        passage_p = ET.SubElement(passage_div, "p")
        passage_p.text = _escape(passage)

    stem_p = ET.SubElement(body, "p")
    stem_p.text = _escape(item.get("stem", ""))

    interaction = ET.SubElement(body, "choiceInteraction", {
        "responseIdentifier": "RESPONSE",
        "shuffle": "false",
        "maxChoices": "1",
    })
    prompt_block = ET.SubElement(interaction, "prompt")
    prompt_block.text = "Choose the best answer."

    options = item.get("options", [])
    for opt in options:
        choice = ET.SubElement(interaction, "simpleChoice", {
            "identifier": _safe_id(opt["id"]),
        })
        choice.text = _escape(opt.get("text", ""))

    # --- responseProcessing ---
    ET.SubElement(root, "responseProcessing", {
        "template": "http://www.imsglobal.org/question/qti_v2p1/rptemplates/match_correct",
    })

    return root


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
BUILDERS = {
    "hot-text": _build_hot_text,
    "sequence": _build_sequence,
    "match": _build_match,
    "ebsr": _build_ebsr,
    "vocab-mcq": _build_vocab_mcq,
    # mcq and msq from the JSONL pool can also be exported as vocab-mcq if needed
    "mcq": _build_vocab_mcq,
}


def build_item(item: dict) -> ET.Element:
    itype = item.get("type", "").lower()
    builder = BUILDERS.get(itype)
    if builder is None:
        raise ValueError(f"No builder for type '{itype}'")
    return builder(item)


# ---------------------------------------------------------------------------
# Manifest builder
# ---------------------------------------------------------------------------

def build_manifest(exported: list[dict]) -> str:
    """
    Build imsmanifest.xml listing all exported items.
    exported: list of {item_id, filename, type, ccss}
    """
    manifest = ET.Element("manifest", {
        "xmlns": "http://www.imsglobal.org/xsd/imscp_v1p1",
        "xmlns:imsqti": "http://www.imsglobal.org/xsd/imsqti_v2p1",
        "identifier": "G5-QTI-PACKAGE",
    })
    metadata = ET.SubElement(manifest, "metadata")
    schema = ET.SubElement(metadata, "schema")
    schema.text = "IMS Content"
    schema_version = ET.SubElement(metadata, "schemaversion")
    schema_version.text = "1.2"

    organizations = ET.SubElement(manifest, "organizations")

    resources = ET.SubElement(manifest, "resources")
    for entry in exported:
        res = ET.SubElement(resources, "resource", {
            "identifier": _safe_id(entry["item_id"]),
            "type": "imsqti_item_xmlv2p1",
            "href": entry["filename"],
        })
        res_meta = ET.SubElement(res, "metadata")
        qti_meta = ET.SubElement(res_meta, "imsqti:qtiMetadata")
        it = ET.SubElement(qti_meta, "imsqti:itemType")
        it.text = entry["type"]
        ccss_el = ET.SubElement(qti_meta, "imsqti:learningObjectives")
        ccss_el.text = entry.get("ccss", "")
        file_el = ET.SubElement(res, "file", {"href": entry["filename"]})

    raw = ET.tostring(manifest, encoding="unicode")
    reparsed = minidom.parseString(raw)
    return reparsed.toprettyxml(indent="  ", encoding=None)


# ---------------------------------------------------------------------------
# Skeleton walker
# ---------------------------------------------------------------------------

def collect_skeleton_items(skeleton: dict) -> list[dict]:
    """
    Recursively collect all {slot_id, item_id, type, ccss, ...} dicts
    from the nested skeleton structure.
    """
    results = []

    def walk(obj):
        if isinstance(obj, dict):
            if "item_id" in obj and "type" in obj:
                results.append(obj)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(skeleton)
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- Load skeleton ---
    print(f"Loading skeleton: {SKELETON_PATH}")
    with open(SKELETON_PATH) as f:
        skeleton = json.load(f)
    all_slots = collect_skeleton_items(skeleton)
    print(f"  {len(all_slots)} item slots found in skeleton")

    # --- Load JSONL item pool ---
    print(f"Loading item pool: {JSONL_PATH}")
    item_pool: dict[str, dict] = {}
    with open(JSONL_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            item_pool[item["id"]] = item
    print(f"  {len(item_pool)} items in JSONL pool")

    # --- Load vocab seeds (supplemental pool for vocab item IDs) ---
    # The skeleton uses two ID conventions for vocab-mcq items:
    #   1. L5_vocab_NN  (positional 1-indexed from v1 seeds)
    #   2. L5_4a_NN, L5_5c_NN, etc. (native IDs from v2 seeds, used in MAP slots)
    # We index both: positional L5_vocab_NN mapping AND native-ID passthrough.
    vocab_items: list[dict] = []
    for vocab_path in (VOCAB_SEEDS_V1, VOCAB_SEEDS_V2):
        if vocab_path.exists():
            with open(vocab_path) as f:
                vocab_items.extend(json.load(f))

    vocab_map: dict[str, dict] = {}
    for idx, item in enumerate(vocab_items, start=1):
        # Positional alias: L5_vocab_01, L5_vocab_02, ...
        positional_key = f"L5_vocab_{idx:02d}"
        cloned_pos = dict(item)
        cloned_pos["id"] = positional_key
        cloned_pos["type"] = "vocab-mcq"
        vocab_map[positional_key] = cloned_pos

        # Native-ID passthrough (e.g. L5_4a_03 -> direct lookup)
        native_key = item["id"]
        cloned_native = dict(item)
        cloned_native["type"] = "vocab-mcq"
        vocab_map[native_key] = cloned_native

    print(
        f"  {len(vocab_items)} vocab-mcq items loaded; "
        f"{len(vocab_map)} map entries (positional + native-ID)"
    )

    # --- Process each slot ---
    exported = []
    errors = []
    skipped_pending = 0

    for slot in all_slots:
        item_id = slot.get("item_id", "")
        slot_type = slot.get("type", "").lower()

        # Skip PENDING placeholders
        if item_id == "PENDING" or not item_id:
            skipped_pending += 1
            continue

        # Resolve item content
        item = item_pool.get(item_id)
        if item is None:
            item = vocab_map.get(item_id)
        if item is None:
            errors.append({
                "item_id": item_id,
                "slot_id": slot.get("slot_id", ""),
                "type": slot_type,
                "error": "Item not found in JSONL pool or vocab seeds",
            })
            continue

        # Normalise type: the pool item's type may differ from skeleton type label
        # (e.g. pool uses 'mcq' but skeleton says 'vocab-mcq'). Skeleton wins.
        working_item = dict(item)
        if slot_type and slot_type != working_item.get("type", "").lower():
            working_item["type"] = slot_type

        # Generate QTI XML
        try:
            qti_root = build_item(working_item)
            xml_str = _pretty_xml(qti_root)

            # Validate: re-parse the generated XML
            ET.fromstring(xml_str)

            filename = f"{item_id}.xml"
            out_path = OUTPUT_DIR / filename
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(xml_str)

            exported.append({
                "item_id": item_id,
                "filename": filename,
                "type": slot_type,
                "ccss": slot.get("ccss", item.get("ccss", "")),
            })

        except Exception as exc:
            errors.append({
                "item_id": item_id,
                "slot_id": slot.get("slot_id", ""),
                "type": slot_type,
                "error": str(exc),
            })

    # --- Write manifest ---
    manifest_str = build_manifest(exported)
    manifest_path = OUTPUT_DIR / "imsmanifest.xml"
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(manifest_str)

    # Validate manifest
    try:
        ET.fromstring(manifest_str)
        manifest_valid = True
    except ET.ParseError as e:
        manifest_valid = False
        errors.append({"item_id": "imsmanifest.xml", "error": str(e)})

    # --- Write error log ---
    error_log_path = OUTPUT_DIR / "export_errors.json"
    with open(error_log_path, "w", encoding="utf-8") as f:
        json.dump(errors, f, indent=2)

    # --- Report ---
    print()
    print("=" * 60)
    print("QTI EXPORT REPORT")
    print("=" * 60)
    print(f"Total skeleton slots:    {len(all_slots)}")
    print(f"Skipped (PENDING):       {skipped_pending}")
    print(f"Items exported:          {len(exported)}")
    print(f"Errors:                  {len(errors)}")
    print(f"Manifest valid:          {manifest_valid}")
    print(f"Output directory:        {OUTPUT_DIR}")
    print()

    if errors:
        print("ERROR DETAILS:")
        # Group errors by reason
        by_reason: dict[str, list] = {}
        for e in errors:
            r = e.get("error", "unknown")
            by_reason.setdefault(r, []).append(e["item_id"])
        for reason, ids in sorted(by_reason.items(), key=lambda x: -len(x[1])):
            print(f"  [{len(ids)}] {reason}")
            if len(ids) <= 5:
                print(f"        IDs: {ids}")
            else:
                print(f"        IDs (first 5): {ids[:5]} ...")
        print()
        print(f"Full error log: {error_log_path}")

    # Type breakdown of exported items
    print("EXPORTED BREAKDOWN BY TYPE:")
    type_counts: dict[str, int] = {}
    for e in exported:
        t = e["type"]
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, c in sorted(type_counts.items()):
        print(f"  {t:<20} {c:>4}")

    print()
    print(f"Manifest: {manifest_path}")

    return len(errors) == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
