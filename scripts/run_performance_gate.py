from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path
from statistics import quantiles

from lesr.domain.evaluation import plan_context

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tests.support.performance_dataset import build_dataset

SCALES = {
    "small": (1_000, 5_000, 10_000),
    "medium": (10_000, 50_000, 100_000),
    "large": (100_000, 500_000, 1_000_000),
}


def run(tier: str) -> dict[str, object]:
    objects, revisions, relations = SCALES[tier]
    started = time.perf_counter()
    dataset = build_dataset(objects, revisions, relations)
    build_seconds = time.perf_counter() - started
    evaluator = dataset.evaluator()
    target = dataset.snapshot.nodes[0].revision.object_uid
    for _ in range(10):
        plan_context(evaluator, (target,), ("verified_by",), token_limit=500)
    samples: list[float] = []
    for _ in range(100):
        started = time.perf_counter()
        plan_context(evaluator, (target,), ("verified_by",), token_limit=500)
        samples.append(time.perf_counter() - started)
    return {
        "measurement_layer": "semantic_kernel",
        "tier": tier,
        "system": platform.platform(),
        "python": platform.python_version(),
        "objects": dataset.object_count,
        "revisions": len(dataset.revisions),
        "relations": len(dataset.snapshot.relations),
        "build_seconds": round(build_seconds, 6),
        "context_manifest_p95_seconds": round(
            quantiles(samples, n=100, method="inclusive")[94], 6
        ),
        "warmups": 10,
        "samples": 100,
        "semantics_disabled": [],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("tier", choices=tuple(SCALES))
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.tier), ensure_ascii=False, sort_keys=True, indent=2))
