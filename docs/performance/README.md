# LESR 1.0 fixed performance protocol

The reference condition is 8 x86-64 cores, 32 GiB RAM, NVMe SSD, Python 3.12,
Windows 11 with Defender enabled, and the current Ubuntu LTS. Interactive measurements
use a complete hot Projection, ten warm-ups, and at least 100 samples. Cold Projection
Build is measured separately. Formal Trace, Rule evaluation, Configuration Resolution,
and transaction integrity remain enabled in every tier.

| Tier | Objects | Revisions | Relations | Use |
|---|---:|---:|---:|---|
| small | 1,000 | 5,000 | 10,000 | every CI |
| medium | 10,000 | 50,000 | 100,000 | RC/release gate |
| large | 100,000 | 500,000 | 1,000,000 | explicit pre-release stress/trend, at most 24 GiB |

Medium data includes ten Normative Profiles, 500 Rules, mean graph degree ten, bounded
path depth three, and a Candidate Overlay of at most 100 Objects/500 Relations.
Targets are Resolve/Inspect/paged Query P95 below 1 s; Context Manifest (at most 20
targets and 500 Mandatory resources) and Focused Read (at most 100 resources/2 MiB)
P95 below 3 s; Working Copy Edit/Checkpoint below 1 s; incremental review of at most
100 Objects below 30 s; cancellation response below 2 s; cold Projection Build below
5 min. Deep Trace and full large validation are persistent Tasks, not 3-second
interactions.

`tests/test_performance_small_ci.py` is the mandatory small gate.
`scripts/run_performance_gate.py medium` and `large` execute the corresponding explicit
dataset. A release report records hardware, OS, cache state, Defender state, samples,
profiles, rules, graph degree/depth, overlay/body size, and whether first Projection
Build is included. A non-reference machine result is supporting evidence, not a silent
substitution for the reference condition.
