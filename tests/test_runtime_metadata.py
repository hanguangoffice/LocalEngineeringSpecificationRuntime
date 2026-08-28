from __future__ import annotations

import lesr


def test_runtime_maturity_is_separate_from_design_baseline() -> None:
    assert lesr.__version__ == "1.1.0"
    assert lesr.__design_baseline__ == "1.0"
