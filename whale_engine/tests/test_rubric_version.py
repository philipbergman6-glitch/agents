"""Every scorer stamps its diagnosis with the rubric version that produced it.

The README promises this for every diagnosis; the panel and the narration
header lean on it to say which rule set a verdict came from. A scorer that
forgets the field would silently break that traceability, so it is pinned
here for every registered scorer rather than inside each scorer's own
golden test.
"""

from importlib import import_module

import pytest

from whale_engine.scorers import WHALES

from conftest import load_snapshot

SCORERS = {whale: import_module(f"whale_engine.scorers.{whale}") for whale in WHALES}


@pytest.mark.parametrize("name", sorted(SCORERS))
def test_diagnosis_carries_the_module_rubric_version(name):
    module = SCORERS[name]
    assert isinstance(module.RUBRIC_VERSION, int) and module.RUBRIC_VERSION >= 1
    out = module.diagnose(load_snapshot("KO"))
    assert out["rubric_version"] == module.RUBRIC_VERSION
