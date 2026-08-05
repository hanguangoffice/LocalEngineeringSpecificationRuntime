# 附录 A：ASPICE-like 与 MISRA-like 映射示例

**说明性示例，不复制正式标准内容**

## ASPICE-like

- Requirement：Governed Object + Normative/Traceability；
- Test Case：Governed Object + Verification Plan；
- Test Execution：Immutable Record + Evidence；
- Process Definition：Profile/Governed Object；
- Activity Record：Immutable Record；
- Approval：Immutable Attestation。

## MISRA-like

- Coding Rule：Governed Object + Normative/Applicability/Executable；
- Analyzer Result：Immutable Observation；
- Tracking Issue：Governed Object + Issue；
- Deviation：Governed Object + Authorization；
- Suppression：外部工具状态，不自动等同批准 Deviation。

两类 Profile 共享身份、关系、Revision、Applicability、Evidence 和 Provenance，但不需要同一 Kind。
