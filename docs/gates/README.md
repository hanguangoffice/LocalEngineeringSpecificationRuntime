# LESR 1.0 Gate evidence

这里保存 Canonical Format 1.0 与 Runtime 1.0 发布周期的历史证据。报告中的 `PASS`
只适用于报告注明的契约、提交和测试范围，不表示当前 2.0 工作版本已经完成发布验证。
当前产品交互契约见 `../AGENTIC-PRODUCT-CONTRACT.md`，版本关系见 `../versioning.md`。

Gate reports use the fixed state vocabulary `PLANNED/IN_PROGRESS/PASS/FAIL/DEFERRED`
and separately identify contract version, tests and measurements, injected failure
modes, retained limitations, and commit scope. A design decision is not reported as
an implemented feature; implementation is not reported as integrated; integration
is not reported as a passed release gate.
