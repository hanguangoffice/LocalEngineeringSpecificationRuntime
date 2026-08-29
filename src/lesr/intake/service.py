"""Deterministic, source-preserving natural-language intake."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from lesr.intake.catalog import IntakeCatalog
from lesr.intake.models import (
    GapDisposition,
    GapItem,
    IntakeAnalysis,
    IntakeQuestion,
    IntakeRequest,
    RequirementCategory,
    RequirementItem,
    TemplateAlternative,
    TemplatePack,
)

_LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)、]|[（(]?[一二三四五六七八九十]+[）)、.])\s*(.+?)\s*$")
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\[^\r\n]+")


class IntakeService:
    """Map a raw request without inventing prose or requiring technical IDs."""

    def __init__(self, catalog: IntakeCatalog | None = None) -> None:
        self.catalog = catalog or IntakeCatalog()

    def templates(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "pack_uid": pack.pack_uid,
                "display_name": pack.display_name,
                "summary": pack.summary,
                "architecture_depth": pack.architecture_depth,
                "artifacts": tuple(
                    {
                        "display_name": artifact.display_name,
                        "purpose": artifact.purpose,
                        "role": artifact.role,
                        "source": self.catalog.source(artifact.source_uid).display_name,
                    }
                    for artifact in pack.artifacts
                ),
                "sources": tuple(
                    {
                        "display_name": self.catalog.source(uid).display_name,
                        "repository": self.catalog.source(uid).repository,
                        "commit": self.catalog.source(uid).commit,
                        "license": self.catalog.source(uid).license,
                    }
                    for uid in pack.source_uids
                ),
            }
            for pack in self.catalog.packs
        )

    def analyze(self, request: IntakeRequest) -> IntakeAnalysis:
        self.catalog.verify_vendored_sources()
        description = request.description.strip()
        scored = self._score_packs(description)
        selected = scored[0][1]
        requirements = self._extract_requirements(description)
        gaps = self._gaps(description, requirements)
        question = self._next_question(gaps)
        template_path = self._template_path(selected)
        template = self.catalog.read_vendored(template_path)
        starter = self._render_starter(template, request, selected, requirements)
        matched = tuple(
            signal
            for signal in selected.signals
            if signal.casefold() in description.casefold()
        )
        template_names = "、".join(item.display_name for item in selected.artifacts)
        reasons = (
            (f"识别到：{'、'.join(matched[:6])}" if matched else "未发现专用场景信号，采用通用软件模板"),
            f"采用的上游结构：{template_names}",
            f"共使用 {len(selected.artifacts)} 份固定版本模板；场景专用内容不会由模型自行补写",
        )
        return IntakeAnalysis(
            selected_pack=selected,
            alternatives=tuple(
                TemplateAlternative(
                    pack_uid=pack.pack_uid,
                    display_name=pack.display_name,
                    score=max(score, 0),
                )
                for score, pack in scored[1:4]
            ),
            selection_reasons=reasons,
            requirements=requirements,
            gaps=gaps,
            next_question=question,
            source_template=template_path,
            starter_document=starter,
            can_continue_with_defaults=question is None or not any(
                item.disposition is GapDisposition.BLOCKING for item in gaps
            ),
        )

    def _score_packs(self, description: str) -> list[tuple[int, TemplatePack]]:
        folded = description.casefold()
        scored: list[tuple[int, TemplatePack]] = []
        for pack in self.catalog.packs:
            matches = sum(1 for signal in pack.signals if signal.casefold() in folded)
            score = matches * 100 + pack.priority
            scored.append((score, pack))
        return sorted(scored, key=lambda item: (-item[0], -item[1].priority, item[1].pack_uid))

    def _extract_requirements(self, description: str) -> tuple[RequirementItem, ...]:
        items: list[RequirementItem] = []
        current_heading = ""
        lines = description.splitlines()
        for line_number, raw in enumerate(lines, 1):
            stripped = raw.strip()
            if not stripped:
                continue
            match = _LIST_ITEM.match(raw)
            if match:
                statement = match.group(1).strip()
            else:
                if raw.lstrip().startswith("#") or stripped.endswith(("：", ":")):
                    current_heading = stripped.lstrip("# ").rstrip("：:").strip()
                    continue
                if len(stripped) < 16:
                    continue
                statement = stripped
            if statement.endswith(("：", ":")):
                current_heading = statement.rstrip("：:")
                continue
            category = self._category(current_heading, statement)
            prefix = {
                RequirementCategory.GOAL: "GOAL",
                RequirementCategory.FUNCTION: "FR",
                RequirementCategory.QUALITY: "QR",
                RequirementCategory.CONSTRAINT: "CON",
                RequirementCategory.TEST: "TEST",
                RequirementCategory.DELIVERABLE: "DEL",
                RequirementCategory.DEPENDENCY: "DEP",
                RequirementCategory.SAFETY: "SAFE",
            }[category]
            sequence = 1 + sum(1 for item in items if item.category is category)
            items.append(
                RequirementItem(
                    human_key=f"{prefix}-{sequence:03d}",
                    statement=statement,
                    category=category,
                    source_line=line_number,
                )
            )
        if not items:
            items.append(
                RequirementItem(
                    human_key="GOAL-001",
                    statement=description,
                    category=RequirementCategory.GOAL,
                    source_line=1,
                )
            )
        return tuple(items)

    @staticmethod
    def _category(heading: str, statement: str) -> RequirementCategory:
        context = f"{heading} {statement}".casefold()
        rules = (
            (RequirementCategory.SAFETY, ("安全", "未经确认", "不得", "不允许", "密钥", "secret")),
            (RequirementCategory.TEST, ("测试", "test", "模拟", "验收", "benchmark", "基准")),
            (RequirementCategory.DELIVERABLE, ("最终提供", "交付", "deliver", "源代码", "说明")),
            (RequirementCategory.CONSTRAINT, ("约束", "windows", "显存", "兼容", "不得", "限制")),
            (RequirementCategory.QUALITY, ("性能", "实时", "可靠", "可维护", "响应", "可用")),
            (RequirementCategory.DEPENDENCY, ("依赖", "adapter", "适配器", "官方", "第三方")),
        )
        for category, terms in rules:
            if any(term in context for term in terms):
                return category
        return RequirementCategory.FUNCTION

    def _gaps(
        self, description: str, requirements: tuple[RequirementItem, ...]
    ) -> tuple[GapItem, ...]:
        folded = description.casefold()
        gaps: list[GapItem] = []
        has_tests = any(item.category is RequirementCategory.TEST for item in requirements)
        gaps.append(
            GapItem(
                topic="可验证的成功标准",
                disposition=GapDisposition.COVERED if has_tests else GapDisposition.DEFAULTED,
                reason="原始需求已给出测试或验收内容" if has_tests else "未给出测试条款；草案保留 Spec Kit 的 Success Criteria 位置",
                recommended_answer=None if has_tests else "先采用可观察、技术无关的验收结果，送审前再量化",
                source_rule="spec-kit/spec-template.md: User Scenarios & Testing + Success Criteria",
            )
        )
        has_safety = any(item.category is RequirementCategory.SAFETY for item in requirements)
        risky_action = any(term in folded for term in ("安装", "删除", "path", "下载", "环境", "系统"))
        gaps.append(
            GapItem(
                topic="高影响操作边界",
                disposition=GapDisposition.COVERED if has_safety else GapDisposition.DEFAULTED,
                reason=(
                    "原始需求已明确安全约束"
                    if has_safety
                    else "需求包含系统级动作；运行时采用本地保守执行策略"
                    if risky_action
                    else "运行时采用本地默认执行策略"
                ),
                recommended_answer=(
                    None
                    if has_safety
                    else "由运行时在实际操作边界自动限制全局安装、PATH 修改、大型下载和删除"
                ),
                source_rule="grill-me: missing failure modes and unstated assumptions",
            )
        )
        external_assets = any(term in folded for term in ("素材", "模型", "第三方", "download", "下载"))
        license_stated = any(term in folded for term in ("许可证", "许可", "license", "授权"))
        if external_assets:
            gaps.append(
                GapItem(
                    topic="外部素材与许可证",
                    disposition=GapDisposition.COVERED if license_stated else GapDisposition.DEFAULTED,
                    reason=("原始需求已提及许可证边界" if license_stated else "涉及外部模型或素材，但未指定可接受许可证"),
                    recommended_answer=(
                        None
                        if license_stated
                        else "仅纳入来源和用途边界可判定的材料；无法判定时保持未采用"
                    ),
                    source_rule="grill-me: dependency risks; reverse-prompt: constraints and blockers",
                )
            )
        repository_known = _WINDOWS_PATH.search(description) is not None or any(
            term in folded for term in ("github.com/", "仓库", "repository")
        )
        gaps.append(
            GapItem(
                topic="工程现状调查",
                disposition=GapDisposition.COVERED if repository_known else GapDisposition.DEFAULTED,
                reason="已给出工程目录或仓库" if repository_known else "未给出仓库；按新建工程处理",
                recommended_answer=None if repository_known else "采用 greenfield，不要求用户补充系统内部事实",
                source_rule="grill-me: do your homework first; explore instead of asking",
            )
        )
        return tuple(gaps)

    @staticmethod
    def _next_question(gaps: tuple[GapItem, ...]) -> IntakeQuestion | None:
        unresolved = next(
            (item for item in gaps if item.disposition is GapDisposition.NEEDS_DECISION),
            None,
        )
        if unresolved is None or unresolved.recommended_answer is None:
            return None
        return IntakeQuestion(
            topic=unresolved.topic,
            question=f"“{unresolved.topic}”会改变工程范围，需要补充哪一种？",
            recommended_answer=unresolved.recommended_answer,
            consequence="这个选择会直接改变生成的工程内容。",
            source_rule="grill-me: one branch at a time + recommended answer",
        )

    @staticmethod
    def _template_path(pack: TemplatePack) -> str:
        return next(item.path for item in pack.artifacts if item.role == "primary")

    def _render_starter(
        self,
        template: str,
        request: IntakeRequest,
        pack: TemplatePack,
        requirements: tuple[RequirementItem, ...],
    ) -> str:
        name = request.project_name or self._infer_name(request.description)
        rendered = template.replace("[FEATURE NAME]", name)
        rendered = rendered.replace("[DATE]", datetime.now(UTC).date().isoformat())
        rendered = rendered.replace("$ARGUMENTS", request.description)
        lines = [
            "",
            "---",
            "",
            "## LESR Intake Mapping",
            "",
            f"Selected source-backed pack: **{pack.display_name}**",
            "",
            "The statements below are copied from the user's input; LESR has not rewritten them.",
            "",
        ]
        lines.extend(f"- **{item.human_key}**: {item.statement}" for item in requirements)
        lines.extend(("", "### Selected source templates", ""))
        lines.extend(
            f"- **{item.display_name}** — {item.purpose}"
            for item in pack.artifacts
        )
        if "arc42-zh-2026-07-07" in pack.source_uids:
            lines.extend(("", "### arc42 Architecture Views", ""))
            lines.extend(f"- {heading}" for heading in self._arc42_headings())
        return rendered.rstrip() + "\n" + "\n".join(lines) + "\n"

    def _arc42_headings(self) -> tuple[str, ...]:
        headings: list[str] = []
        for number in range(1, 13):
            prefix = f"arc42-template/ZH/adoc/{number:02d}_"
            source = next(
                file.path
                for item in self.catalog.sources
                if item.source_uid == "arc42-zh-2026-07-07"
                for file in item.files
                if file.path.startswith(prefix)
            )
            content = self.catalog.read_vendored(source)
            title = next(line[3:].strip() for line in content.splitlines() if line.startswith("== "))
            headings.append(title)
        return tuple(headings)

    @staticmethod
    def _infer_name(description: str) -> str:
        repository = re.search(r"(?:名为|named)\s*[`\"']?([A-Za-z0-9][A-Za-z0-9._-]{1,80})", description)
        if repository:
            return repository.group(1)
        path = _WINDOWS_PATH.search(description)
        if path:
            return Path(path.group(0).rstrip("。).） ")).name
        return "New Engineering Work"
