from __future__ import annotations

from pwdlib import PasswordHash

from personal_edge_lab.apps.auth_cli.__main__ import main


def test_set_password_writes_only_private_argon2_hash(tmp_path, monkeypatch, capsys) -> None:
    database = tmp_path / "telemetry.db"
    password_file = tmp_path / "secrets" / "owner-password.hash"
    password = "fourteen-chars!"
    prompts = iter((password, password))
    monkeypatch.setenv("DATABASE_PATH", str(database))
    monkeypatch.setenv("AUTH_PASSWORD_HASH_FILE", str(password_file))
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(prompts))

    assert main(["set-password"]) == 0

    stored = password_file.read_text(encoding="utf-8").strip()
    assert stored.startswith("$argon2id$")
    assert PasswordHash.recommended().verify(password, stored)
    assert password_file.stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr()
    assert password not in output.out
    assert stored not in output.out
