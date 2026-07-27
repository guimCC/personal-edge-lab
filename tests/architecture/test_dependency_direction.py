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


def test_application_ports_depend_only_on_domain_and_standard_library() -> None:
    forbidden = (
        "personal_edge_lab.apps",
        "personal_edge_lab.infrastructure",
        "personal_edge_lab.modules",
        "fastapi",
        "httpx",
        "pydantic",
        "sqlite3",
    )
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            name for name in imports_in(path) if name.startswith(forbidden)
        )
        for path in python_files("application/ports")
    }
    assert not {path: names for path, names in violations.items() if names}


def test_infrastructure_does_not_depend_on_apps_or_feature_modules() -> None:
    forbidden = ("personal_edge_lab.apps", "personal_edge_lab.modules")
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            name for name in imports_in(path) if name.startswith(forbidden)
        )
        for path in python_files("infrastructure")
    }
    assert not {path: names for path, names in violations.items() if names}


def test_only_expected_real_modules_exist() -> None:
    module_names = {
        path.name
        for path in (PACKAGE_ROOT / "modules").iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    }
    assert module_names == {
        "ac_control",
        "alerting",
        "authentication",
        "notifications",
        "platform_status",
        "telemetry",
    }


def test_ai_domain_and_port_do_not_import_http_or_framework_packages() -> None:
    paths = [
        PACKAGE_ROOT / "domain/ai.py",
        PACKAGE_ROOT / "application/ports/ai.py",
    ]
    forbidden = ("httpx", "pydantic", "fastapi", "personal_edge_lab.infrastructure")
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            name for name in imports_in(path) if name.startswith(forbidden)
        )
        for path in paths
    }
    assert not {path: names for path, names in violations.items() if names}


def test_ai_httpx_import_is_confined_to_infrastructure() -> None:
    paths = [
        PACKAGE_ROOT / "domain/ai.py",
        PACKAGE_ROOT / "application/ports/ai.py",
        PACKAGE_ROOT / "apps/ai_cli/__main__.py",
        PACKAGE_ROOT / "apps/ai_cli/config.py",
        PACKAGE_ROOT / "infrastructure/ai/concurrency.py",
    ]
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            name for name in imports_in(path) if name == "httpx"
        )
        for path in paths
    }
    assert not {path: names for path, names in violations.items() if names}


def test_llama_cpp_completion_wire_shape_is_confined_to_adapter() -> None:
    markers = ('"/v1/chat/completions"', '"choices"')
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            marker for marker in markers if marker in path.read_text(encoding="utf-8")
        )
        for path in PACKAGE_ROOT.rglob("*.py")
        if path != PACKAGE_ROOT / "infrastructure/ai/llama_cpp.py"
    }
    assert not {path: names for path, names in violations.items() if names}
