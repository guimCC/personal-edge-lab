from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]
SERVICE = (PROJECT_ROOT / "deploy/systemd/personal-edge-lab-telegram-bot.service").read_text(
    encoding="utf-8"
)


def test_telegram_bot_is_an_independent_hardened_network_service() -> None:
    assert "Type=simple" in SERVICE
    assert (
        "ExecStart=/home/ubuntu/personal-edge-lab/.venv/bin/python "
        "-m personal_edge_lab.apps.telegram_bot"
    ) in SERVICE
    assert "EnvironmentFile=/home/ubuntu/personal-edge-lab/.env" in SERVICE
    assert "ReadWritePaths=/home/ubuntu/personal-edge-lab/data" in SERVICE
    assert "ProtectSystem=strict" in SERVICE
    assert "ProtectHome=read-only" in SERVICE
    assert "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" in SERVICE
    assert "personal-edge-lab-api.service" not in SERVICE
    assert "telemetry-collector.service" not in SERVICE
