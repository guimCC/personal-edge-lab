"""Google OAuth authorization and refresh with private token-file handling."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from personal_edge_lab.application.ports.email import (
    EmailSourceError,
    EmailSourceFailureCategory,
)

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_READONLY_SCOPES = (GMAIL_READONLY_SCOPE,)


class GoogleOAuthCredentialStore:
    """Load and, when required, refresh one owner-controlled Gmail credential."""

    def __init__(
        self,
        *,
        token_file: Path,
        timeout_seconds: float,
        request_factory: Callable[[], Any] = Request,
    ) -> None:
        self._token_file = token_file
        self._timeout_seconds = timeout_seconds
        self._request_factory = request_factory

    def access_token(self) -> str:
        try:
            credentials = Credentials.from_authorized_user_file(
                str(self._token_file),
                scopes=list(GMAIL_READONLY_SCOPES),
            )
        except (OSError, ValueError) as error:
            raise _authentication_error() from error
        if not credentials.has_scopes(GMAIL_READONLY_SCOPES):
            raise _authentication_error()
        if credentials.expired:
            if not credentials.refresh_token:
                raise _authentication_error()
            request = self._request_factory()

            def bounded_request(**kwargs: Any) -> Any:
                kwargs["timeout"] = self._timeout_seconds
                return request(**kwargs)

            try:
                credentials.refresh(bounded_request)
            except (RefreshError, OSError, ValueError) as error:
                raise _authentication_error() from error
            _write_credentials(self._token_file, credentials)
        if not credentials.valid or not isinstance(credentials.token, str) or not credentials.token:
            raise _authentication_error()
        return credentials.token


def authorize_google_oauth(
    *,
    client_secret_file: Path,
    token_file: Path,
    callback_port: int,
    replace_token: bool,
) -> None:
    """Run one explicit installed-app authorization and atomically store its token."""

    if token_file.exists() and not replace_token:
        raise EmailSourceError(
            "Gmail token already exists; use --replace-token to replace it",
            category=EmailSourceFailureCategory.AUTHENTICATION,
            retry_eligible=False,
        )
    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_secret_file),
            scopes=list(GMAIL_READONLY_SCOPES),
        )
        credentials = flow.run_local_server(
            host="127.0.0.1",
            port=callback_port,
            open_browser=False,
            authorization_prompt_message=(
                "Open this URL in the browser on the SSH-tunnel workstation:\n{url}"
            ),
            success_message="Gmail read-only authorization completed. You may close this window.",
            access_type="offline",
            prompt="consent",
        )
    except Exception as error:
        raise _authentication_error("Gmail read-only authorization failed") from error
    if not credentials.has_scopes(GMAIL_READONLY_SCOPES):
        raise _authentication_error("Gmail did not grant the required read-only scope")
    _write_credentials(token_file, credentials)


def _write_credentials(path: Path, credentials: Any) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=path.parent,
            text=True,
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(credentials.to_json())
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
        temporary_path = None
    except OSError as error:
        raise _authentication_error("Gmail token could not be stored") from error
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink()


def _authentication_error(
    message: str = "Gmail authentication failed; authorize the integration again",
) -> EmailSourceError:
    return EmailSourceError(
        message,
        category=EmailSourceFailureCategory.AUTHENTICATION,
        retry_eligible=False,
    )
