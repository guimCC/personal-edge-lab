import type { ReactNode } from "react";

interface LabShellProps {
  actorId?: string | null;
  authEnabled: boolean;
  emailTriageEnabled: boolean;
  activeSection: NavigationSection;
  workspaceLabel: string;
  systemLabel: string;
  version?: string;
  timezone: string;
  lastUpdated: string;
  onRefresh: () => void;
  onLogout: () => Promise<void>;
  children: ReactNode;
}

export type NavigationSection = "climate" | "activity" | "system" | "email-triage";

interface NavigationItem {
  href: `#${NavigationSection}`;
  index: string;
  label: string;
  section: NavigationSection;
}

const NAVIGATION: NavigationItem[] = [
  { href: "#climate", index: "01", label: "Climate", section: "climate" },
  { href: "#activity", index: "02", label: "Activity", section: "activity" },
  { href: "#system", index: "03", label: "System", section: "system" },
];

export function LabShell({
  actorId,
  authEnabled,
  emailTriageEnabled,
  activeSection,
  workspaceLabel,
  systemLabel,
  version,
  timezone,
  lastUpdated,
  onRefresh,
  onLogout,
  children,
}: LabShellProps) {
  const navigation = emailTriageEnabled
    ? [
        ...NAVIGATION,
        {
          href: "#email-triage" as const,
          index: "04",
          label: "Email triage",
          section: "email-triage" as const,
        },
      ]
    : NAVIGATION;

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
          <NavigationLinks items={navigation} activeSection={activeSection} />
        </nav>

        <div className="rail-status">
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
        </header>

        <nav className="mobile-navigation" aria-label="Mobile workspace sections">
          <NavigationLinks items={navigation} activeSection={activeSection} />
        </nav>

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

function NavigationLinks({
  items,
  activeSection,
}: {
  items: NavigationItem[];
  activeSection: NavigationSection;
}) {
  return items.map((item) => {
    const active = item.section === activeSection;
    return (
      <a
        aria-current={active ? "page" : undefined}
        className={active ? "is-active" : undefined}
        href={item.href}
        key={item.href}
      >
        <span>{item.index}</span>
        {item.label}
      </a>
    );
  });
}
