import type { RefObject } from "react";

import type { BrowserCommand } from "../../api/contracts";
import { humanize } from "../../shared/format";

interface CommandReviewDialogProps {
  command: BrowserCommand;
  submitting: boolean;
  cancelRef: RefObject<HTMLButtonElement | null>;
  confirmRef: RefObject<HTMLButtonElement | null>;
  onCancel: () => void;
  onConfirm: () => void;
}

export function CommandReviewDialog({
  command,
  submitting,
  cancelRef,
  confirmRef,
  onCancel,
  onConfirm,
}: CommandReviewDialogProps) {
  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !submitting) onCancel();
      }}
    >
      <section
        className="review-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-title"
        onKeyDown={(event) => {
          if (event.key === "Escape" && !submitting) onCancel();
          if (
            event.key === "Tab" &&
            event.shiftKey &&
            document.activeElement === cancelRef.current
          ) {
            event.preventDefault();
            confirmRef.current?.focus();
          } else if (
            event.key === "Tab" &&
            !event.shiftKey &&
            document.activeElement === confirmRef.current
          ) {
            event.preventDefault();
            cancelRef.current?.focus();
          }
        }}
      >
        <p className="overline">ONE PHYSICAL REQUEST</p>
        <h2 id="review-title">
          {command.command_type === "power_off" ? "Power off AC?" : "Send these settings?"}
        </h2>
        <p>
          RUBIK will transmit this once. If the response is interrupted, the physical outcome may
          remain unknown and the dashboard will not retry automatically.
        </p>
        <dl className="review-command">
          <div>
            <dt>Action</dt>
            <dd>{command.command_type === "power_off" ? "Power off" : "Set state"}</dd>
          </div>
          {command.command_type === "set_state" && (
            <>
              <div>
                <dt>Temperature</dt>
                <dd>{command.state.temperature_c} °C</dd>
              </div>
              <div>
                <dt>Mode</dt>
                <dd>Cool</dd>
              </div>
              <div>
                <dt>Fan / vane</dt>
                <dd>
                  {humanize(command.state.fan)} / {humanize(command.state.vertical_vane)}
                </dd>
              </div>
            </>
          )}
        </dl>
        <div className="modal-actions">
          <button
            ref={cancelRef}
            className="button"
            type="button"
            disabled={submitting}
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            ref={confirmRef}
            className={`button ${
              command.command_type === "power_off" ? "button-danger" : "button-primary"
            }`}
            type="button"
            disabled={submitting}
            onClick={onConfirm}
          >
            {submitting ? "Sending once…" : "Confirm once"}
          </button>
        </div>
      </section>
    </div>
  );
}
