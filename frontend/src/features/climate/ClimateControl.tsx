import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError, sendCommand } from "../../api/client";
import type { BrowserCommand, CommandHistory, Fan, Vane } from "../../api/contracts";
import { humanize } from "../../shared/format";
import { CommandReviewDialog } from "./CommandReviewDialog";
import {
  FANS,
  lastRequestedDefaults,
  outcomeMessage,
  type ControlResult,
  VANES,
} from "./controlModel";

interface ClimateControlProps {
  csrfToken: string;
  commands?: CommandHistory;
  degraded: boolean;
  onCompleted: () => void;
}

export function ClimateControl({
  csrfToken,
  commands,
  degraded,
  onCompleted,
}: ClimateControlProps) {
  const defaults = useMemo(() => lastRequestedDefaults(commands), [commands]);
  const [temperature, setTemperature] = useState(defaults.temperature);
  const [fan, setFan] = useState<Fan>(defaults.fan);
  const [vane, setVane] = useState<Vane>(defaults.vane);
  const [review, setReview] = useState<BrowserCommand | null>(null);
  const [lastCommand, setLastCommand] = useState<BrowserCommand | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<ControlResult | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const reviewTriggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (review) confirmRef.current?.focus();
  }, [review]);

  const openReview = (command: BrowserCommand, trigger: HTMLButtonElement) => {
    reviewTriggerRef.current = trigger;
    setReview(command);
    setLastCommand(command);
    setIdempotencyKey(crypto.randomUUID());
    setResult(null);
  };

  const closeReview = () => {
    setReview(null);
    requestAnimationFrame(() => reviewTriggerRef.current?.focus());
  };

  const submit = async () => {
    const command = review ?? lastCommand;
    if (!command || !idempotencyKey) return;
    setSubmitting(true);
    setResult(null);
    try {
      const response = await sendCommand(command, idempotencyKey, csrfToken);
      setResult({ kind: "completed", response });
      closeReview();
      onCompleted();
    } catch (caught) {
      if (!(caught instanceof ApiError) || caught.status === 503) {
        setResult({
          kind: "unknown",
          message:
            "RUBIK could not return a reliable result. The command may have been transmitted. Do not create a new command; check this same request safely.",
        });
      } else if (caught.status === 409) {
        setResult({
          kind: "error",
          message:
            "This request is already in progress, conflicts with its request key, or another command currently holds the device.",
        });
      } else if (caught.status === 429) {
        setResult({
          kind: "error",
          message: `Command limit reached. Wait about ${caught.retryAfter ?? 60} seconds.`,
        });
      } else {
        setResult({ kind: "error", message: `Command was not accepted (${caught.status}).` });
      }
      closeReview();
    } finally {
      setSubmitting(false);
    }
  };

  const adjustTemperature = (difference: number) => {
    setTemperature((current) => Math.min(31, Math.max(16, current + difference)));
  };

  return (
    <section className="climate-control" aria-labelledby="control-title">
      <div className="control-heading">
        <div>
          <p className="overline">DEVICE CONTROL</p>
          <h2 id="control-title">Air conditioner</h2>
        </div>
        <span className="mode-label">COOL ONLY</span>
      </div>

      <p className="control-disclaimer">
        Last requested settings. The physical AC state is not inferred.
      </p>

      {degraded && (
        <div className="control-warning">
          Current node health is degraded. Controls remain available, but delivery may be
          uncertain.
        </div>
      )}

      <div className="temperature-control">
        <span>Requested temperature</span>
        <div>
          <button
            type="button"
            aria-label="Decrease requested temperature"
            disabled={temperature === 16 || submitting}
            onClick={() => adjustTemperature(-1)}
          >
            −
          </button>
          <output aria-live="polite">
            {temperature}
            <small>°C</small>
          </output>
          <button
            type="button"
            aria-label="Increase requested temperature"
            disabled={temperature === 31 || submitting}
            onClick={() => adjustTemperature(1)}
          >
            +
          </button>
        </div>
      </div>

      <div className="control-options">
        <label>
          Fan
          <select value={fan} onChange={(event) => setFan(event.target.value as Fan)}>
            {FANS.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          Vertical vane
          <select value={vane} onChange={(event) => setVane(event.target.value as Vane)}>
            {VANES.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="control-actions">
        <button
          className="button control-primary"
          type="button"
          disabled={submitting}
          onClick={(event) =>
            openReview(
              {
                command_type: "set_state",
                state: {
                  power: true,
                  temperature_c: temperature,
                  mode: "cool",
                  fan,
                  vertical_vane: vane,
                },
              },
              event.currentTarget,
            )
          }
        >
          Review settings
        </button>
        <button
          className="button control-off"
          type="button"
          disabled={submitting}
          onClick={(event) =>
            openReview({ command_type: "power_off" }, event.currentTarget)
          }
        >
          Power off
        </button>
      </div>

      {result && (
        <div
          className={`command-result result-${result.kind}`}
          role={result.kind === "completed" ? "status" : "alert"}
        >
          <strong>
            {result.kind === "completed"
              ? humanize(result.response.audit.outcome)
              : result.kind === "unknown"
                ? "Physical outcome unknown"
                : "Command not submitted"}
          </strong>
          <p>
            {result.kind === "completed" ? outcomeMessage(result.response) : result.message}
          </p>
          {result.kind === "unknown" && (
            <button className="text-action" type="button" disabled={submitting} onClick={submit}>
              {submitting ? "Checking…" : "Check recorded result"}
            </button>
          )}
        </div>
      )}

      {review && (
        <CommandReviewDialog
          command={review}
          submitting={submitting}
          cancelRef={cancelRef}
          confirmRef={confirmRef}
          onCancel={closeReview}
          onConfirm={submit}
        />
      )}
    </section>
  );
}
