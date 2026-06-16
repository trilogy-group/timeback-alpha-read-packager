"""Shared pytest fixtures + path wiring for the Alpha Read Packager test suite.

Puts src/ on sys.path so the tests import the modules exactly as the CLI does
(every module self-inserts its own dir, so importing arpack pulls its siblings in).
Also resolves the checked-in Mayank fixture and the live production export (if present)
so the suite can round-trip against REAL data, not just synthetic samples.
"""
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)
SRC = os.path.join(REPO_ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

FIXTURE_DIR = os.path.join(REPO_ROOT, "fixtures", "qti_sample_2026-06-16")
EXAMPLES = os.path.join(REPO_ROOT, "examples")

# The live production export is OUTSIDE this repo (a sibling investigation artifact).
# Tests that touch it are SKIPPED gracefully when it is absent (e.g. on a clean checkout
# or CI box), so the suite is self-contained but uses real data when it's there.
LIVE_EXPORT = os.path.join(
    REPO_ROOT, "..", "alpha_read_contract_investigation",
    "sources", "live_course_export", "content",
)
LIVE_COURSE_RAW = os.path.join(
    REPO_ROOT, "..", "alpha_read_contract_investigation",
    "sources", "live_course_export", "course_4c49bc61_raw.json",
)


@pytest.fixture(scope="session")
def repo_root():
    return REPO_ROOT


@pytest.fixture(scope="session")
def fixture_dir():
    assert os.path.isdir(FIXTURE_DIR), f"Mayank fixture missing: {FIXTURE_DIR}"
    return FIXTURE_DIR


@pytest.fixture(scope="session")
def examples_dir():
    return EXAMPLES


@pytest.fixture(scope="session")
def live_export():
    if not os.path.isdir(LIVE_EXPORT):
        pytest.skip(f"live export not present at {LIVE_EXPORT}")
    return LIVE_EXPORT


@pytest.fixture(scope="session")
def live_course_raw():
    if not os.path.isfile(LIVE_COURSE_RAW):
        pytest.skip(f"live course raw not present at {LIVE_COURSE_RAW}")
    return LIVE_COURSE_RAW


@pytest.fixture
def sample_pkg():
    """A fresh, assembled-and-valid sample package (the arpack canonical sample)."""
    import arpack
    return arpack.assemble(arpack.SAMPLE)
