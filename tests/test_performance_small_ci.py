from __future__ import annotations

import time
from statistics import quantiles

import pytest

from lesr.domain.evaluation import Direction, plan_context
from tests.support.performance_dataset import build_dataset


def p95(samples: list[float]) -> float:
    return quantiles(samples, n=100, method="inclusive")[94]


@pytest.fixture(scope="module")
def small_dataset():  # type: ignore[no-untyped-def]
    return build_dataset()


@pytest.mark.performance
def test_small_ci_dataset_has_exact_scale_and_full_formal_semantics(small_dataset) -> None:  # type: ignore[no-untyped-def]
    assert small_dataset.object_count == 1_000
    assert len(small_dataset.revisions) == 5_000
    assert len(small_dataset.snapshot.relations) == 10_000
    evaluator = small_dataset.evaluator()
    for relation in small_dataset.snapshot.relations[::100]:
        assert evaluator.formal_trace_credit(relation, "verification").granted


@pytest.mark.performance
def test_small_ci_hot_resolve_and_context_measurements(small_dataset) -> None:  # type: ignore[no-untyped-def]
    evaluator = small_dataset.evaluator()
    by_uid = evaluator.nodes
    target = small_dataset.snapshot.nodes[0].revision.object_uid
    for _ in range(10):
        assert target in by_uid
        evaluator.relation_count(
            target,
            predicate="verified_by",
            direction=Direction.OUTGOING,
            formal_trace_category="verification",
        )
    resolve_samples: list[float] = []
    context_samples: list[float] = []
    for _ in range(100):
        started = time.perf_counter()
        assert by_uid[target].revision.object_uid == target
        resolve_samples.append(time.perf_counter() - started)
        started = time.perf_counter()
        context = plan_context(
            evaluator,
            (target,),
            ("verified_by",),
            token_limit=500,
        )
        assert context.completeness.value == "COMPLETE"
        context_samples.append(time.perf_counter() - started)
    assert p95(resolve_samples) < 1.0
    assert p95(context_samples) < 3.0
