from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]
SERVICE = (PROJECT_ROOT / "deploy/systemd/personal-edge-lab-alert-evaluator.service").read_text(
    encoding="utf-8"
)
TIMER = (PROJECT_ROOT / "deploy/systemd/personal-edge-lab-alert-evaluator.timer").read_text(
    encoding="utf-8"
)


def test_alert_evaluator_is_a_network_isolated_one_shot() -> None:
    assert "Type=oneshot" in SERVICE
    assert (
        "ExecStart=/home/ubuntu/personal-edge-lab/.venv/bin/python "
        "-m personal_edge_lab.apps.alert_evaluator"
    ) in SERVICE
    assert "EnvironmentFile=/home/ubuntu/personal-edge-lab/.env" in SERVICE
    assert "ReadWritePaths=/home/ubuntu/personal-edge-lab/data" in SERVICE
    assert "RestrictAddressFamilies=AF_UNIX" in SERVICE
    assert "AF_INET" not in SERVICE
    assert "AF_INET6" not in SERVICE


def test_alert_timer_matches_the_locked_evaluation_interval() -> None:
    assert "OnBootSec=30s" in TIMER
    assert "OnUnitActiveSec=30s" in TIMER
    assert "AccuracySec=1s" in TIMER
    assert "RandomizedDelaySec=0" in TIMER
    assert "Unit=personal-edge-lab-alert-evaluator.service" in TIMER
    assert "WantedBy=timers.target" in TIMER
