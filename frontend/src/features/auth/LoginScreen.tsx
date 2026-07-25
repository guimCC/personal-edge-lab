import { useState, type FormEvent } from "react";

import { ApiError, login } from "../../api/client";
import type { Session } from "../../api/contracts";

interface LoginScreenProps {
  session: Session;
  onAuthenticated: (session: Session) => void;
}

export function LoginScreen({ session, onAuthenticated }: LoginScreenProps) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      onAuthenticated(await login(password));
      setPassword("");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 429) {
        setError(
          `Too many attempts. Try again in about ${caught.retryAfter ?? 900} seconds.`,
        );
      } else {
        setError("The password was not accepted.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-shell">
      <section className="login-layout" aria-labelledby="login-title">
        <div className="login-identity">
          <div className="brand-mark" aria-hidden="true">
            <span>01</span>
          </div>
          <p className="brand-name">Personal Edge Lab</p>
          <p className="login-manifesto">
            A private workspace for local telemetry, devices, and deliberate automation.
          </p>
          <span className="node-label">RUBIK · LOCAL NODE</span>
        </div>

        <div className="login-form">
          <p className="overline">OWNER ACCESS</p>
          <h1 id="login-title">Enter your lab</h1>
          <p>Authenticate locally to inspect data and operate connected devices.</p>
          <form onSubmit={submit}>
            <label htmlFor="owner-password">Password</label>
            <input
              id="owner-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoFocus
              required
            />
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            <button className="button button-primary" type="submit" disabled={submitting}>
              {submitting ? "Opening session…" : "Continue"}
            </button>
          </form>
          <small>
            Private HTTPS session · Controls are{" "}
            {session.controls_enabled ? "available after sign-in" : "currently disabled"}
          </small>
        </div>
      </section>
    </main>
  );
}
