# UNO Q inference-node deployment capture

This directory records the reviewed configuration for `unoq-ai-01`.

- `uno-ai.service` is the user-level service owned by `arduino`. It was captured from
  `/home/arduino/.config/systemd/user/uno-ai.service` on 2026-07-26, then changed only to make the
  one-slot concurrency requirement explicit with `--parallel 1`. That reviewed unit is installed,
  enabled, active, and accepted after a service restart.
- `uno-ai-firewall` owns one additive legacy-iptables chain. It accepts TCP 8080 from RUBIK at
  `192.168.1.81` and drops that port from every other IPv4 source without flushing or replacing
  unrelated rules.
- `uno-ai-firewall.service` reapplies that chain during boot before normal networking.
- `install-firewall.sh` is the root-only, fail-closed installer. It retains the complete prior
  legacy-iptables rules and any previous helper/unit under `/var/backups/personal-edge-lab/`,
  installs and starts the dedicated service, and restores the prior state if installation fails.

The first nftables-based attempt on 2026-07-26 rolled back safely. The UNO Q kernel has
`CONFIG_NF_TABLES` disabled but provides `ip_tables`, `iptable_filter`, `x_tables`, and `xt_tcpudp`
as working modules, so the reviewed deployment deliberately uses `/usr/sbin/iptables-legacy`.

The replacement firewall was installed on 2026-07-26 with its pre-change state retained under
`/var/backups/personal-edge-lab/unoq-ai-wp0-20260726T165938Z`. The service is enabled and active.
RUBIK retained authenticated access, a non-RUBIK source timed out on TCP 8080, and SSH remained
available. After a full UNO Q reboot, the firewall and inference services started automatically,
RUBIK retained access, and the non-RUBIK source remained blocked.

The API key, model files, and host-specific logs must never be copied into this repository.

Installation and acceptance steps are recorded in
[`docs/contracts/unoq-ai-01.md`](../../docs/contracts/unoq-ai-01.md).
