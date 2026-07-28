import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { getSession, logout } from "./api/client";
import type { Session } from "./api/contracts";
import Dashboard from "./Dashboard";
import { LoginScreen } from "./features/auth/LoginScreen";

export default function App() {
  const queryClient = useQueryClient();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: getSession,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  });

  useEffect(() => {
    const loseAuthentication = () => {
      queryClient.removeQueries({
        predicate: (query) => query.queryKey[0] !== "session",
      });
      queryClient.setQueryData<Session>(["session"], (current) => ({
        authenticated: false,
        auth_enabled: current?.auth_enabled ?? true,
        controls_enabled: current?.controls_enabled ?? false,
        email_triage_review_enabled: false,
      }));
      queryClient.invalidateQueries({ queryKey: ["session"] });
    };
    window.addEventListener("pel:unauthorized", loseAuthentication);
    return () => window.removeEventListener("pel:unauthorized", loseAuthentication);
  }, [queryClient]);

  const handleLogout = async () => {
    if (session.data?.csrf_token) {
      await logout(session.data.csrf_token);
    }
    queryClient.clear();
    await queryClient.invalidateQueries({ queryKey: ["session"] });
  };

  if (session.isPending) {
    return (
      <main className="session-state">
        <div className="session-pulse" aria-hidden="true" />
        <p>Establishing a secure RUBIK session…</p>
      </main>
    );
  }
  if (session.isError || !session.data) {
    return (
      <main className="session-state" role="alert">
        <strong>RUBIK authentication is unavailable.</strong>
        <p>Check the local node and try again.</p>
      </main>
    );
  }
  if (session.data.auth_enabled && !session.data.authenticated) {
    return (
      <LoginScreen
        session={session.data}
        onAuthenticated={(value) => queryClient.setQueryData(["session"], value)}
      />
    );
  }
  return <Dashboard session={session.data} onLogout={handleLogout} />;
}
