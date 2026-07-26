# Stage 5A — Casadaqui Telegram AC control

## Outcome

Release `0.7.0` added an owner-only Telegram control surface for the air conditioner. Release
`0.7.1` refines its native interaction without changing the command or security architecture. It
is a delivery adapter over the existing AC command use case, not another controller implementation
and not another monitoring dashboard.

The first conversation supports:

- `/ac`: open a Cool-mode temperature panel with fan and vertical-vane submenus;
- `/off`: open a Power Off review directly;
- `/help`: explain the bounded command surface;
- one explicit **Enviar ajuste** action from the normalized Set State panel;
- a separate confirmation before Power Off.

It excludes monitoring queries, alert notifications, multiple users, groups, webhooks, natural
language, automation, and physical-state inference.

Unlike the dashboard, this channel is reachable while the owner is away from the home LAN because
RUBIK maintains an outbound connection to Telegram. Bot conversations are Telegram cloud chats,
not Secret Chats with end-to-end encryption. No password, bot token, response body, or raw device
error is sent through the conversation. The owner Telegram account should use Telegram 2-Step
Verification and a local app passcode before remote physical control is enabled.

## Security and delivery contract

- Only the configured numeric `TELEGRAM_OWNER_USER_ID` is authorized.
- The chat must be a private chat whose ID matches that owner user ID.
- Unauthorized messages and groups are ignored; unauthorized callbacks receive a generic denial.
- The token is validated through `getMe`, stored outside `.env` in a mode-`0600` file, excluded
  from Git, and never included in application error text or HTTP logs.
- Telegram callbacks are treated as untrusted input and fully parsed and validated.
- Callback data remains within Telegram's 64-byte limit.
- Opening a panel creates a deterministic 20-character token that becomes a channel-scoped idempotency
  key. Selection callbacks preserve it, and update redelivery or repeated send taps retrieve the
  original audit result.
- The bot composes `ExecuteCoolOnlyCommand` and `CommandService`; it cannot bypass local policy,
  audit reservation, the rolling rate limit, or the per-device lease.
- Every new accepted attempt performs exactly one ESP32 request.
- Timeouts, invalid success responses, or an audit completion failure remain physically unknown
  and are never retried automatically.

The implementation uses Telegram's documented long polling, inline keyboard, callback answer, and
message-editing APIs: <https://core.telegram.org/bots/api>.

## Runtime

`personal-edge-lab-telegram-bot.service` is independent from the collector, API, evaluator, Nginx,
and Avahi. It requires outbound HTTPS to Telegram plus local HTTP access to the ESP32 and SQLite
write access for AC audit reservation/completion.

The service processes updates sequentially. It advances the polling offset only after an update is
handled successfully. If delivery of the result message fails after an AC request, Telegram may
redeliver the update, but the same stable panel key safely replays the durable result.

## RUBIK provisioning

After installing `0.7.1` with the bot disabled:

```bash
set -a
source .env
set +a
python -m personal_edge_lab.apps.telegram_cli set-token
```

Send `/start` to `Casadaqui_bot`, then discover the private numeric identity:

```bash
python -m personal_edge_lab.apps.telegram_cli discover-owner
```

Add the emitted positive ID and the following values to `.env`:

```dotenv
TELEGRAM_BOT_ENABLED=true
TELEGRAM_BOT_TOKEN_FILE=/home/ubuntu/personal-edge-lab/secrets/telegram-bot.token
TELEGRAM_OWNER_USER_ID=<numeric ID>
TELEGRAM_AC_COMMAND_RATE_LIMIT_PER_MINUTE=6
TELEGRAM_POLL_TIMEOUT_SECONDS=25
```

Run the normal deployment again. It backs up the token, validates its permissions, installs the
unit, and starts the service.

## Acceptance

1. Confirm the service remains active and logs identify `@Casadaqui_bot` without printing its
   token.
2. Confirm `/start`, `/help`, `/ac`, temperature adjustments, fan/vane submenus, and `/off` review
   work.
3. Confirm another Telegram account and a group cannot open or operate the controls.
4. Exercise every Set State selector without pressing **Enviar ajuste**, then cancel one Power Off
   review; neither may create an audit row.
5. Under operator control, send one Cool set-state request and observe one new audit row with
   `request_source=telegram_bot` and `actor_id=telegram:<owner ID>`.
6. Double-tap or replay the same send callback and verify one audit row and at most one ESP32
   request.
7. Confirm one Power Off request under operator control with the same evidence.
8. Exercise an unavailable ESP32 and an unknown response without automatic retransmission.
9. Verify dashboard controls, CLI output, telemetry cadence, alert evaluation, and HTTPS remain
   unchanged.
10. Reboot RUBIK and verify the bot, collector, API, alert timer, Nginx, and Avahi start
    independently.

Rollback disables and stops `personal-edge-lab-telegram-bot.service`, restores the prior wheel and
`.env`, and leaves the new Telegram-attributed audit rows intact. No migration or database restore
is required because Stage 5A adds no schema.
