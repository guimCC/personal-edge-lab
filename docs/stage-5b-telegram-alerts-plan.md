# Stage 5B — Proactive operational alerts through Casadaqui

## Scope

Release `0.8.0` makes the existing owner bot an outbound interface for confirmed operational alert
and recovery transitions. No new service is introduced. Alert evaluation stays read-only with
respect to external systems and Casadaqui remains the only Telegram network process.

## Durable contract

- Only transitions to `alerting` and `recovered` are notifiable.
- The transition and its outbox row commit in the same SQLite transaction.
- One dedupe key exists per transition, channel, and owner.
- Casadaqui leases oldest due rows in bounded batches before sending.
- Delivery retries use 30 seconds, 2 minutes, 10 minutes, 30 minutes, then hourly.
- Telegram `429 Retry-After` is honored when longer.
- Undelivered events expire after 24 hours.
- Telegram delivery is at-least-once; a crash after Telegram accepts a message but before SQLite
  records completion can create a rare duplicate.
- Physical AC commands retain exactly one ESP32 request and no automatic retry.

Migration `005_notification_outbox` adds the outbox, due/flapping indexes, delivery runtime, and
one owner policy for the `operational_alerts` topic.

## Owner policy

`/notifications` and the home menu expose:

- pause for one hour;
- pause for eight hours;
- pause until 08:00 the following day in `OWNER_TIMEZONE`;
- pause indefinitely;
- reactivate.

Pausing suppresses pending and future operational notifications. Alert evaluation, dashboard state,
and incident history continue. Suppressed messages are retained for traceability and never delivered
after reactivation. A third transition for the same alert type inside 15 minutes is delayed and
coalesced with newer transitions into one instability message.

## Deployment configuration

```dotenv
TELEGRAM_NOTIFICATION_DELIVERY_ENABLED=false
TELEGRAM_NOTIFICATION_BATCH_SIZE=20
TELEGRAM_NOTIFICATION_LEASE_SECONDS=60
TELEGRAM_NOTIFICATION_MAX_AGE_SECONDS=86400
TELEGRAM_NOTIFICATION_RUNTIME_STALE_AFTER_SECONDS=90
OWNER_TIMEZONE=Europe/Madrid
```

Deploy once with delivery disabled, inspect migration `005`, then set
`TELEGRAM_NOTIFICATION_DELIVERY_ENABLED=true` and restart Casadaqui. `/status` must show notification
delivery as operational. Rollback reinstalls `0.7.2` and restarts the bot and evaluator as needed;
the additive migration may remain.

## Acceptance

- Suspect and healthy transitions create no delivery.
- One confirmed incident creates one alert message.
- One genuine recovery creates one recovery message.
- Pausing suppresses pending and new events; reactivation sends no backlog.
- A Telegram outage leaves durable retries and does not block inbound commands.
- Reboot preserves pending delivery and policy.
- `/status`, `/ac`, `/off`, dashboard, API, collector cadence, and alert evaluation remain
  compatible.
