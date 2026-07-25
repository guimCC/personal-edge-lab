"""Build guard for packaged dashboard assets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        dashboard = (
            Path(self.root) / "src" / "personal_edge_lab" / "apps" / "api" / "static" / "dashboard"
        )
        required = (dashboard / "index.html", dashboard / ".vite" / "manifest.json")
        missing = [str(path.relative_to(self.root)) for path in required if not path.is_file()]
        if missing:
            names = ", ".join(missing)
            raise RuntimeError(
                f"dashboard build is missing ({names}); run npm ci and npm run build in frontend"
            )
