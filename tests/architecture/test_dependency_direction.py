from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "personal_edge_lab"


def imports_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def python_files(directory: str) -> list[Path]:
    return list((PACKAGE_ROOT / directory).rglob("*.py"))


def test_domain_does_not_know_application_modules_or_infrastructure() -> None:
    forbidden = (
        "personal_edge_lab.application",
        "personal_edge_lab.modules",
        "personal_edge_lab.infrastructure",
        "personal_edge_lab.apps",
        "httpx",
        "sqlite3",
    )
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            name for name in imports_in(path) if name.startswith(forbidden)
        )
        for path in python_files("domain")
    }
    assert not {path: names for path, names in violations.items() if names}


def test_modules_depend_on_ports_and_domain_not_adapters() -> None:
    forbidden = ("personal_edge_lab.infrastructure", "personal_edge_lab.apps", "httpx", "sqlite3")
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            name for name in imports_in(path) if name.startswith(forbidden)
        )
        for path in python_files("modules")
    }
    assert not {path: names for path, names in violations.items() if names}


def test_only_expected_real_modules_exist() -> None:
    module_names = {
        path.name
        for path in (PACKAGE_ROOT / "modules").iterdir()
        if path.is_dir() and not path.name.startswith("__")
    }
    assert module_names == {"alerting", "authentication", "home", "telemetry"}
