"""Verified upstream catalog used by the intake selector."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from lesr.intake.models import TemplatePack, TemplateSource


class IntakeCatalog:
    """Load the fixed catalog and reject altered vendored templates."""

    def __init__(self, root: Path | None = None) -> None:
        package_root = Path(str(files("lesr.intake")))
        self.root = root or package_root
        value = json.loads((self.root / "catalog.json").read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("intake catalog must be a JSON object")
        raw_sources = value.get("sources")
        raw_packs = value.get("packs")
        if not isinstance(raw_sources, list) or not isinstance(raw_packs, list):
            raise TypeError("intake catalog must contain sources and packs")
        self.sources = tuple(TemplateSource.model_validate(item) for item in raw_sources)
        self.packs = tuple(TemplatePack.model_validate(item) for item in raw_packs)
        self._validate_links()

    def source(self, source_uid: str) -> TemplateSource:
        try:
            return next(item for item in self.sources if item.source_uid == source_uid)
        except StopIteration as error:
            raise KeyError(source_uid) from error

    def pack(self, pack_uid: str) -> TemplatePack:
        try:
            return next(item for item in self.packs if item.pack_uid == pack_uid)
        except StopIteration as error:
            raise KeyError(pack_uid) from error

    def verify_vendored_sources(self) -> tuple[dict[str, Any], ...]:
        """Verify only redistributable files that are actually in the wheel."""

        results: list[dict[str, Any]] = []
        upstream = self.root / "upstream"
        for source in self.sources:
            if source.usage != "vendored_template":
                continue
            for expected in source.files:
                path = upstream / expected.path
                if not path.is_file():
                    raise FileNotFoundError(expected.path)
                content = path.read_bytes()
                actual = hashlib.sha256(content).hexdigest()
                if len(content) != expected.bytes or actual != expected.sha256:
                    raise ValueError(f"upstream template snapshot changed: {expected.path}")
                results.append(
                    {
                        "source_uid": source.source_uid,
                        "path": expected.path,
                        "bytes": len(content),
                        "sha256": actual,
                    }
                )
        return tuple(results)

    def read_vendored(self, relative_path: str) -> str:
        source_files = {
            item.path
            for source in self.sources
            if source.usage == "vendored_template"
            for item in source.files
        }
        if relative_path not in source_files:
            raise KeyError(relative_path)
        path = self.root / "upstream" / relative_path
        content = path.read_bytes()
        expected = next(
            file
            for source in self.sources
            for file in source.files
            if source.usage == "vendored_template" and file.path == relative_path
        )
        if len(content) != expected.bytes or hashlib.sha256(content).hexdigest() != expected.sha256:
            raise ValueError(f"upstream template snapshot changed: {relative_path}")
        return content.decode("utf-8")

    def _validate_links(self) -> None:
        source_uids = [item.source_uid for item in self.sources]
        pack_uids = [item.pack_uid for item in self.packs]
        if len(source_uids) != len(set(source_uids)):
            raise ValueError("template source UID is duplicated")
        if len(pack_uids) != len(set(pack_uids)):
            raise ValueError("template pack UID is duplicated")
        known = set(source_uids)
        for pack in self.packs:
            unknown = set(pack.source_uids) - known
            if unknown:
                raise ValueError(f"template pack has unknown sources: {sorted(unknown)}")
