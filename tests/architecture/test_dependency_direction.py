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
        "email_triage",
        "notifications",
        "platform_status",
        "telemetry",
    }


def test_ai_domain_and_port_do_not_import_http_or_framework_packages() -> None:
    paths = [
        PACKAGE_ROOT / "domain/ai.py",
        PACKAGE_ROOT / "application/ports/ai.py",
        PACKAGE_ROOT / "domain/email_triage.py",
        PACKAGE_ROOT / "application/ports/email_triage.py",
    ]
    forbidden = ("httpx", "pydantic", "fastapi", "personal_edge_lab.infrastructure")
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            name for name in imports_in(path) if name.startswith(forbidden)
        )
        for path in paths
    }
    assert not {path: names for path, names in violations.items() if names}


def test_langfuse_and_opentelemetry_imports_are_confined_to_infrastructure() -> None:
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            name for name in imports_in(path) if name.startswith(("langfuse", "opentelemetry"))
        )
        for path in PACKAGE_ROOT.rglob("*.py")
        if "infrastructure" not in path.parts
    }
    assert not {path: names for path, names in violations.items() if names}


def test_pydantic_triage_boundary_is_confined_to_decoder() -> None:
    relevant = [
        PACKAGE_ROOT / "domain/email_triage.py",
        PACKAGE_ROOT / "application/ports/email_triage.py",
        *python_files("modules/email_triage"),
    ]
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            name for name in imports_in(path) if name.startswith("pydantic")
        )
        for path in relevant
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


def test_email_source_domain_and_port_are_standard_library_only() -> None:
    paths = [
        PACKAGE_ROOT / "domain/email.py",
        PACKAGE_ROOT / "application/ports/email.py",
    ]
    forbidden = (
        "fastapi",
        "google",
        "google_auth_oauthlib",
        "httpx",
        "langfuse",
        "opentelemetry",
        "pydantic",
        "sqlite3",
        "personal_edge_lab.apps",
        "personal_edge_lab.infrastructure",
        "personal_edge_lab.modules",
    )
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            name for name in imports_in(path) if name.startswith(forbidden)
        )
        for path in paths
    }
    assert not {path: names for path, names in violations.items() if names}


def test_google_sdk_imports_are_confined_to_gmail_infrastructure() -> None:
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            name for name in imports_in(path) if name.startswith(("google", "google_auth_oauthlib"))
        )
        for path in PACKAGE_ROOT.rglob("*.py")
        if not path.is_relative_to(PACKAGE_ROOT / "infrastructure/gmail")
    }
    assert not {path: names for path, names in violations.items() if names}


def test_gmail_wire_contract_is_confined_to_get_only_adapter() -> None:
    adapter = PACKAGE_ROOT / "infrastructure/gmail/client.py"
    marker = '"/gmail/v1/users/me/messages"'
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): marker
        for path in PACKAGE_ROOT.rglob("*.py")
        if path != adapter and marker in path.read_text(encoding="utf-8")
    }
    assert not violations
    adapter_source = adapter.read_text(encoding="utf-8")
    assert '"GET"' in adapter_source
    assert not any(
        marker in adapter_source
        for marker in ('"POST"', '"PUT"', '"PATCH"', '"DELETE"', "gmail.modify", "gmail.send")
    )


def test_gmail_infrastructure_does_not_import_model_or_langfuse() -> None:
    paths = python_files("infrastructure/gmail")
    forbidden = (
        "personal_edge_lab.infrastructure.ai",
        "personal_edge_lab.infrastructure.observability",
        "personal_edge_lab.application.ports.ai",
        "personal_edge_lab.modules.email_triage",
        "langfuse",
        "opentelemetry",
    )
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            name for name in imports_in(path) if name.startswith(forbidden)
        )
        for path in paths
    }
    assert not {path: names for path, names in violations.items() if names}


def test_wp7_batch_depends_on_ports_not_sqlite_or_gmail_adapters() -> None:
    paths = [
        PACKAGE_ROOT / "modules/email_triage/batch.py",
        PACKAGE_ROOT / "application/ports/email_triage_runs.py",
        PACKAGE_ROOT / "domain/email_triage_runs.py",
    ]
    forbidden = (
        "personal_edge_lab.infrastructure",
        "personal_edge_lab.apps",
        "httpx",
        "langfuse",
        "pydantic",
        "sqlite3",
    )
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            name for name in imports_in(path) if name.startswith(forbidden)
        )
        for path in paths
    }
    assert not {path: names for path, names in violations.items() if names}


def test_triage_sqlite_adapter_has_no_gmail_or_model_wire_dependency() -> None:
    path = PACKAGE_ROOT / "infrastructure/persistence/sqlite/email_triage.py"
    forbidden = (
        "personal_edge_lab.infrastructure.gmail",
        "personal_edge_lab.infrastructure.ai",
        "personal_edge_lab.infrastructure.observability",
        "httpx",
        "langfuse",
        "google",
    )
    assert not {name for name in imports_in(path) if name.startswith(forbidden)}
