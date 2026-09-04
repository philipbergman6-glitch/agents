"""Every scorer stamps its diagnosis with the rubric version that produced it.

The README promises this for every diagnosis; the panel and the narration
header lean on it to say which rule set a verdict came from. A scorer that
forgets the field would silently break that traceability, so it is pinned
here for all three rather than inside each scorer's own golden test.
"""

import pytest

from whale_engine.scorers import buffett, graham, lynch

from conftest import load_snapshot

SCORERS = {"buffett": buffett, "graham": graham, "lynch": lynch}


@pytest.mark.parametrize("name", sorted(SCORERS))
def test_diagnosis_carries_the_module_rubric_version(name):
    module = SCORERS[name]
    assert isinstance(module.RUBRIC_VERSION, int) and module.RUBRIC_VERSION >= 1
    out = module.diagnose(load_snapshot("KO"))
    assert out["rubric_version"] == module.RUBRIC_VERSION
