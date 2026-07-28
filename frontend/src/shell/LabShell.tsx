import type { ReactNode } from "react";

import type { StatusTone } from "../shared/status";

interface LabShellProps {
  actorId?: string | null;
  authEnabled: boolean;
  emailTriageEnabled: boolean;
  activeWorkspace: "climate" | "email-triage";
  workspaceLabel: string;
  systemLabel: string;
  systemTone: StatusTone;
  version?: string;
  timezone: string;
  lastUpdated: string;
  onRefresh: () => void;
  onLogout: () => Promise<void>;
  children: ReactNode;
}

const NAVIGATION = [
  { href: "#climate", index: "01", label: "Climate" },
  { href: "#activity", index: "02", label: "Activity" },
  { href: "#system", index: "03", label: "System" },
];

export function LabShell({
  actorId,
  authEnabled,
  emailTriageEnabled,
  activeWorkspace,
  workspaceLabel,
  systemLabel,
  systemTone,
  version,
  timezone,
  lastUpdated,
  onRefresh,
  onLogout,
  children,
}: LabShellProps) {
  return (
    <div className="lab-shell">
      <aside className="lab-rail">
        <a className="lab-brand" href="#climate" aria-label="Personal Edge Lab home">
          <span className="brand-mark" aria-hidden="true">
            <span>01</span>
          </span>
          <span>
            <strong>Personal Edge Lab</strong>
            <small>RUBIK · LOCAL NODE</small>
          </span>
        </a>

        <nav className="lab-navigation" aria-label="Workspace sections">
          {NAVIGATION.map((item) => (
            <a
              className={
                activeWorkspace === "climate" && item.href === "#climate"
                  ? "is-active"
                  : undefined
              }
              href={item.href}
              key={item.href}
            >
              <span>{item.index}</span>
              {item.label}
            </a>
          ))}
          {emailTriageEnabled && (
            <a
              className={activeWorkspace === "email-triage" ? "is-active" : undefined}
              href="#email-triage"
            >
              <span>04</span>
              Email triage
            </a>
          )}
        </nav>

        <div className="rail-status">
          <span className={`signal signal-${systemTone}`} aria-hidden="true" />
          <div>
            <strong>{systemLabel}</strong>
            <small>{authEnabled ? `Owner · ${actorId ?? "owner"}` : "Trusted local access"}</small>
          </div>
        </div>
      </aside>

      <div className="lab-stage">
        <header className="mobile-header">
          <a className="mobile-brand" href="#climate">
            <span className="brand-mark" aria-hidden="true">
              <span>01</span>
            </span>
            <span>
              <strong>Personal Edge Lab</strong>
              <small>RUBIK</small>
            </span>
          </a>
          <span className={`signal signal-${systemTone}`} aria-label={systemLabel} />
        </header>

        <div className="workspace-bar">
          <div>
            <span>WORKSPACE</span>
            <strong>{workspaceLabel}</strong>
          </div>
          <div className="workspace-actions">
            <button className="text-action" type="button" onClick={onRefresh}>
              Refresh
            </button>
            {authEnabled && (
              <button className="text-action" type="button" onClick={onLogout}>
                Log out
              </button>
            )}
          </div>
        </div>

        <main className="workspace">{children}</main>

        <footer className="lab-footer">
          <span>PEL API {version ?? "—"}</span>
          <span>
            {timezone} · Refreshed {lastUpdated}
          </span>
        </footer>
      </div>
    </div>
  );
}
