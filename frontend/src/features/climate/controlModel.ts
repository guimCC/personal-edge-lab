import type {
  CommandHistory,
  CommandResponse,
  Fan,
  Vane,
} from "../../api/contracts";
import { humanize } from "../../shared/format";

export const FANS: Fan[] = ["auto", "low", "medium", "high", "max"];
export const VANES: Vane[] = [
  "auto",
  "highest",
  "high",
  "middle",
  "low",
  "lowest",
  "swing",
];

export type ControlResult =
  | { kind: "completed"; response: CommandResponse }
  | { kind: "unknown"; message: string }
  | { kind: "error"; message: string };

interface ControlDefaults {
  temperature: number;
  fan: Fan;
  vane: Vane;
}

export function lastRequestedDefaults(
  commands: CommandHistory | undefined,
): ControlDefaults {
  for (const command of commands?.items ?? []) {
    const payload = command.command_payload;
    if (
      command.command_type === "set_state" &&
      payload.power === true &&
      payload.mode === "cool" &&
      typeof payload.temperature_c === "number" &&
      payload.temperature_c >= 16 &&
      payload.temperature_c <= 31 &&
      typeof payload.fan === "string" &&
      FANS.includes(payload.fan as Fan) &&
      typeof payload.vertical_vane === "string" &&
      VANES.includes(payload.vertical_vane as Vane)
    ) {
      return {
        temperature: payload.temperature_c,
        fan: payload.fan as Fan,
        vane: payload.vertical_vane as Vane,
      };
    }
  }
  return { temperature: 24, fan: "auto", vane: "middle" };
}

export function outcomeMessage(response: CommandResponse): string {
  const { audit, replayed } = response;
  const prefix = replayed ? "Recovered recorded result. " : "";
  switch (audit.outcome) {
    case "confirmed_success":
      return `${prefix}The ESP32 confirmed the command.`;
    case "rejected_locally":
      return `${prefix}RUBIK rejected the request before contacting the ESP32.`;
    case "node_unreachable":
      return `${prefix}The ESP32 could not be reached; the command was not confirmed.`;
    case "node_reported_failure":
      return `${prefix}The ESP32 reported that the command failed.`;
    case "timeout_unknown":
    case "response_unknown":
      return `${prefix}The command may have been transmitted, but its physical outcome is unknown. Do not automatically retry it.`;
    default:
      return `${prefix}The command is recorded as ${humanize(audit.outcome)}.`;
  }
}
