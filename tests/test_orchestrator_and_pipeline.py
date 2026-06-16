"""End-to-end pipeline tests: gen_request -> generator_client -> course_orchestrator.

Asserts the four headline properties by construction:
  fan-out (per-lesson) · idempotent (re-run converges byte-for-byte) ·
  fail-closed (bad lesson excluded, never silently shipped) · draft-safe (forced prefix).
"""
import json
import os

import pytest

import arpack
import gen_request
import generator_client
import course_orchestrator


# ════════════════════════════ gen_request (S1) ════════════════════════════
def test_build_lesson_request_counts():
    lesson = {"vendorId": 3000001, "title": "Beavers", "genre": "informational"}
    unit = {"title": "Animals", "band": "A"}
    bundle = gen_request.build_lesson_request(lesson, unit)
    roles = [i["role"] for i in bundle["items"]]
    assert roles.count("guiding") == gen_request.DEFAULT_GUIDING_COUNT
    assert roles.count("quiz") == gen_request.QUIZ_ITEMS


def test_build_lesson_request_deterministic():
    lesson = {"vendorId": 3000001, "title": "Beavers"}
    a = gen_request.build_lesson_request(lesson, {"title": "U", "band": "B"})
    b = gen_request.build_lesson_request(lesson, {"title": "U", "band": "B"})
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_guiding_count_clamped():
    lesson = {"vendorId": 1, "title": "x"}
    big = gen_request.build_lesson_request(lesson, {}, guiding_count=99)
    assert big["counts"]["guiding"] == gen_request.GUIDING_MAX
    small = gen_request.build_lesson_request(lesson, {}, guiding_count=1)
    assert small["counts"]["guiding"] == gen_request.GUIDING_MIN


def test_band_drives_lexile():
    band_a = gen_request.build_passage_request({"vendorId": 1, "title": "x"}, {"band": "A"})
    band_c = gen_request.build_passage_request({"vendorId": 2, "title": "y"}, {"band": "C"})
    assert band_a["lexile_band"][0] < band_c["lexile_band"][0]


# ════════════════════════════ generator_client (S2) ════════════════════════════
def test_generate_stub_returns_buildresult():
    req = {"lesson_id": "L1", "topic": "T", "format": "mcq", "stimulus": {"ref": "p"}}
    r = generator_client.generate(req, backend="stub")
    assert set(r) >= {"item_id", "item_xml", "stimulus_xml", "stimulus_id", "metadata"}
    assert r["item_xml"].lstrip().startswith("<?xml")
    assert f'identifier="{r["item_id"]}"' in r["item_xml"]


def test_generate_idempotent():
    req = {"lesson_id": "L1", "topic": "Leaves", "format": "mcq", "stimulus": {"ref": "p"}}
    a = generator_client.generate(req, backend="stub")
    b = generator_client.generate(req, backend="stub")
    assert a["item_id"] == b["item_id"]
    assert a["stimulus_id"] == b["stimulus_id"]
    assert a["item_xml"] == b["item_xml"]


def test_generate_distinct_for_distinct_requests():
    a = generator_client.generate({"lesson_id": "L1", "topic": "A", "format": "mcq"}, backend="stub")
    b = generator_client.generate({"lesson_id": "L1", "topic": "B", "format": "mcq"}, backend="stub")
    assert a["item_id"] != b["item_id"]


def test_real_backend_not_wired_but_documented():
    with pytest.raises(NotImplementedError) as ei:
        generator_client.generate({"topic": "x"}, backend="real")
    assert "POST" in str(ei.value)   # the documented interface is in the message


def test_unknown_backend_raises():
    with pytest.raises(ValueError):
        generator_client.generate({"topic": "x"}, backend="banana")


# ════════════════════════════ course_orchestrator (full pipeline) ════════════════════════════
def test_orchestrator_skeleton_passes(examples_dir, tmp_path):
    skel = os.path.join(examples_dir, "sample_skeleton.json")
    report, pkg = course_orchestrator.run(skel, str(tmp_path))
    assert report["validate"]["ok"], report["validate"]["errors"]
    assert pkg is not None
    assert report["lessons_failed"] == 0
    assert report["unique_ids"]["items"] and report["unique_ids"]["stimuli"]


def test_orchestrator_csv_passes(examples_dir, tmp_path):
    csv = os.path.join(examples_dir, "expeditions.csv")
    report, pkg = course_orchestrator.run(csv, str(tmp_path))
    assert report["validate"]["ok"], report["validate"]["errors"]


def test_orchestrator_draft_safe(examples_dir, tmp_path):
    skel = os.path.join(examples_dir, "sample_skeleton.json")
    report, pkg = course_orchestrator.run(skel, str(tmp_path))
    assert pkg["course"]["title"].startswith(arpack.THROWAWAY_PREFIX)


def test_orchestrator_idempotent_byte_for_byte(examples_dir, tmp_path):
    skel = os.path.join(examples_dir, "sample_skeleton.json")
    out1, out2 = tmp_path / "a", tmp_path / "b"
    course_orchestrator.run(skel, str(out1))
    course_orchestrator.run(skel, str(out2))
    # compare the emitted course.json + every item byte-for-byte
    def read(p, *parts):
        with open(os.path.join(str(p), *parts)) as fh:
            return fh.read()
    assert read(out1, "oneroster", "course.json") == read(out2, "oneroster", "course.json")
    items1 = sorted(os.listdir(os.path.join(str(out1), "qti", "items")))
    items2 = sorted(os.listdir(os.path.join(str(out2), "qti", "items")))
    assert items1 == items2
    for name in items1:
        assert read(out1, "qti", "items", name) == read(out2, "qti", "items", name)


def test_orchestrator_emits_run_report(examples_dir, tmp_path):
    skel = os.path.join(examples_dir, "sample_skeleton.json")
    rc = course_orchestrator.main([
        "course_orchestrator.py", skel, str(tmp_path)])
    assert rc == 0
    assert os.path.isfile(os.path.join(str(tmp_path), "RUN_REPORT.md"))


def test_arpack_cli_selftest_returns_zero():
    assert arpack.main(["arpack.py", "--selftest"]) == 0


def test_arpack_cli_build_materialized_example(examples_dir, tmp_path):
    mat = os.path.join(examples_dir, "sample_materialized.json")
    rc = arpack.main(["arpack.py", "build", mat, str(tmp_path / "mat")])
    assert rc == 0
    # the materialized example must produce an emitted, valid package directly (no orchestrator)
    assert os.path.isfile(os.path.join(str(tmp_path), "mat", "oneroster", "course.json"))


def test_orchestrator_fail_closed_on_empty_skeleton(tmp_path):
    # a skeleton with zero lessons -> nothing assembles -> fatal, nothing emitted.
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({
        "course": {"title": "x"},
        "units": [{"title": "U", "sortOrder": 1, "lessons": []}],
    }))
    report, pkg = course_orchestrator.run(str(empty), str(tmp_path / "out"))
    assert pkg is None
    assert "fatal" in report
    assert not os.path.isdir(os.path.join(str(tmp_path), "out", "oneroster"))
