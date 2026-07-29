"""Owner-only manual email-triage feedback queue."""

from __future__ import annotations

import base64
import html
from collections.abc import Callable

from personal_edge_lab.apps.telegram_bot.contracts import (
    AuthorizedCallback,
    AuthorizedMessage,
    BotCommand,
    HomeAction,
    TelegramGateway,
)
from personal_edge_lab.domain.email_triage import TriageLabel
from personal_edge_lab.domain.email_triage_feedback import (
    TriageFeedbackAction,
    TriageFeedbackCandidate,
    TriageFeedbackError,
    TriageFeedbackRecord,
)

CandidateProvider = Callable[[], TriageFeedbackCandidate | None]
CandidateLookup = Callable[[str], TriageFeedbackCandidate | None]
FeedbackRecorder = Callable[
    [str, int, int, TriageFeedbackAction, TriageLabel | None],
    TriageFeedbackRecord,
]

LABEL_CODES = {
    "m": TriageLabel.MCKINSEY,
    "e": TriageLabel.EDUCATION,
    "j": TriageLabel.JOB,
    "p": TriageLabel.PERSONAL,
    "a": TriageLabel.ADMIN,
    "n": TriageLabel.NOTIFICATION,
    "w": TriageLabel.NEWSLETTER,
    "s": TriageLabel.SLOP,
    "o": TriageLabel.OTHER,
}


class EmailTriageCapability:
    namespace = "triage"
    commands = (BotCommand("triage_review", "Revisar recomendaciones de correo"),)
    home_action = HomeAction("📨 Revisar correos")
    legacy_callback_actions = frozenset()

    def __init__(
        self,
        *,
        gateway: TelegramGateway,
        next_candidate: CandidateProvider,
        candidate: CandidateLookup,
        record_feedback: FeedbackRecorder,
    ) -> None:
        self._gateway = gateway
        self._next_candidate = next_candidate
        self._candidate = candidate
        self._record_feedback = record_feedback

    def handle_command(self, command: str, message: AuthorizedMessage) -> None:
        if command != "triage_review":
            raise ValueError("unsupported email-triage command")
        self._show_next(chat_id=message.chat_id)

    def open_from_home(self, callback: AuthorizedCallback) -> None:
        self._gateway.answer_callback(callback_query_id=callback.query_id)
        self._show_next(chat_id=callback.chat_id, message_id=callback.message_id)

    def handle_callback(self, action: str, callback: AuthorizedCallback) -> None:
        if action == "next":
            self._gateway.answer_callback(callback_query_id=callback.query_id)
            self._show_next(chat_id=callback.chat_id, message_id=callback.message_id)
            return
        parts = action.split(":")
        if len(parts) == 4 and parts[0] in {"confirm", "correct", "dismiss"}:
            selected, record_id, attempt_id, version = _decode_action(parts)
            if selected == "correct":
                self._gateway.answer_callback(callback_query_id=callback.query_id)
                candidate = self._candidate(record_id)
                if candidate is None or candidate.record_id != record_id:
                    self._expired(callback)
                    return
                self._gateway.edit_message(
                    chat_id=callback.chat_id,
                    message_id=callback.message_id,
                    text=_candidate_text(candidate),
                    reply_markup=_correction_keyboard(candidate),
                )
                return
            self._save(
                callback,
                record_id=record_id,
                attempt_id=attempt_id,
                version=version,
                action=TriageFeedbackAction(selected),
                corrected_label=None,
            )
            return
        if len(parts) == 5 and parts[0] == "label":
            label = LABEL_CODES.get(parts[1])
            if label is None:
                raise ValueError("invalid correction label")
            _, record_id, attempt_id, version = _decode_action(
                (parts[0], parts[2], parts[3], parts[4])
            )
            self._save(
                callback,
                record_id=record_id,
                attempt_id=attempt_id,
                version=version,
                action=TriageFeedbackAction.CORRECT,
                corrected_label=label,
            )
            return
        raise ValueError("unknown email-triage callback")

    def _save(
        self,
        callback: AuthorizedCallback,
        *,
        record_id: str,
        attempt_id: int,
        version: int,
        action: TriageFeedbackAction,
        corrected_label: TriageLabel | None,
    ) -> None:
        try:
            result = self._record_feedback(
                record_id,
                attempt_id,
                version,
                action,
                corrected_label,
            )
        except TriageFeedbackError:
            self._expired(callback)
            return
        self._gateway.answer_callback(
            callback_query_id=callback.query_id,
            text="Feedback guardado",
        )
        expected = (
            "descartado"
            if result.expected_label is None
            else f"etiqueta esperada: {html.escape(result.expected_label.value)}"
        )
        sync = (
            "vinculado con Langfuse"
            if result.sync_status.value == "synced"
            else "guardado localmente; sincronización pendiente"
        )
        self._gateway.edit_message(
            chat_id=callback.chat_id,
            message_id=callback.message_id,
            text=(
                f"✅ <b>FEEDBACK GUARDADO</b>\n\n{expected}\n{sync}\n\nGmail no se ha modificado."
            ),
            reply_markup={
                "inline_keyboard": [[{"text": "Siguiente correo", "callback_data": "triage:next"}]]
            },
        )

    def _expired(self, callback: AuthorizedCallback) -> None:
        self._gateway.answer_callback(
            callback_query_id=callback.query_id,
            text="La recomendación cambió. Cargando la versión actual.",
            show_alert=True,
        )
        self._show_next(chat_id=callback.chat_id, message_id=callback.message_id)

    def _show_next(self, *, chat_id: int, message_id: int | None = None) -> None:
        candidate = self._next_candidate()
        if candidate is None:
            text = (
                "📨 <b>REVISIÓN DE CORREOS</b>\n\n"
                "No hay recomendaciones pendientes de feedback.\n\n"
                "Gmail labels applied: none."
            )
            keyboard = {
                "inline_keyboard": [[{"text": "↻ Actualizar", "callback_data": "triage:next"}]]
            }
        else:
            text = _candidate_text(candidate)
            keyboard = _feedback_keyboard(candidate)
        if message_id is None:
            self._gateway.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
        else:
            self._gateway.edit_message(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=keyboard,
            )


def _candidate_text(candidate: TriageFeedbackCandidate) -> str:
    reason = (
        f"\n\n<b>Razón</b>\n{html.escape(candidate.reason)}" if candidate.reason is not None else ""
    )
    content = html.escape(candidate.model_input)
    return (
        "📨 <b>REVISAR RECOMENDACIÓN</b>\n\n"
        f"<b>De</b> {html.escape(candidate.sender)}\n"
        f"<b>Asunto</b> {html.escape(candidate.subject or '(sin asunto)')}\n"
        f"<b>Propuesta</b> {html.escape(candidate.recommendation_label.value)}"
        f"{reason}\n\n"
        f"<blockquote expandable>{content}</blockquote>\n"
        "Gmail labels applied: none."
    )


def _feedback_keyboard(candidate: TriageFeedbackCandidate) -> dict[str, object]:
    token = _candidate_token(candidate)
    first_row: list[dict[str, str]] = []
    if not candidate.recommendation_label.is_legacy:
        first_row.append(
            {
                "text": "✓ Confirmar",
                "callback_data": f"triage:confirm:{token}",
                "style": "success",
            }
        )
    first_row.extend(
        [
            {
                "text": "Corregir",
                "callback_data": f"triage:correct:{token}",
                "style": "primary",
            },
            {
                "text": "Descartar",
                "callback_data": f"triage:dismiss:{token}",
                "style": "danger",
            },
        ]
    )
    return {"inline_keyboard": [first_row]}


def _correction_keyboard(candidate: TriageFeedbackCandidate) -> dict[str, object]:
    token = _candidate_token(candidate)
    buttons = [
        {
            "text": label.value,
            "callback_data": f"triage:label:{code}:{token}",
        }
        for code, label in LABEL_CODES.items()
        if label is not candidate.recommendation_label
    ]
    rows = [buttons[index : index + 3] for index in range(0, len(buttons), 3)]
    rows.append([{"text": "Cancelar", "callback_data": "triage:next"}])
    return {"inline_keyboard": rows}


def _candidate_token(candidate: TriageFeedbackCandidate) -> str:
    record = base64.urlsafe_b64encode(bytes.fromhex(candidate.record_id)).decode().rstrip("=")
    token = (
        f"{record}:{_base36(candidate.recommendation_attempt_id)}:"
        f"{_base36(candidate.feedback_version)}"
    )
    if len(f"triage:label:m:{token}".encode()) > 64:
        raise ValueError("Telegram callback data exceeds 64 bytes")
    return token


def _decode_action(parts: tuple[str, ...] | list[str]) -> tuple[str, str, int, int]:
    selected, encoded_record, encoded_attempt, encoded_version = parts
    try:
        padded = encoded_record + "=" * (-len(encoded_record) % 4)
        record_id = base64.urlsafe_b64decode(padded).hex()
        attempt_id = int(encoded_attempt, 36)
        version = int(encoded_version, 36)
    except (ValueError, TypeError) as error:
        raise ValueError("invalid feedback callback") from error
    if len(record_id) != 32 or attempt_id < 1 or version < 0:
        raise ValueError("invalid feedback callback")
    return selected, record_id, attempt_id, version


def _base36(value: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value == 0:
        return "0"
    encoded = ""
    while value:
        value, remainder = divmod(value, 36)
        encoded = digits[remainder] + encoded
    return encoded
