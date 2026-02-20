from __future__ import annotations

import smtplib
from collections import defaultdict
from datetime import timedelta
from email.message import EmailMessage

from app.core.config import get_settings
from app.modules.notify.interface import ChangeDigestItem, Notifier, SendResult


class SMTPEmailNotifier(Notifier):
    def send_changes_digest(
        self,
        to_email: str,
        source_name: str,
        source_id: int,
        items: list[ChangeDigestItem],
    ) -> SendResult:
        settings = get_settings()

        subject = f"[Deadline Diff] {source_name} - {len(items)} changes"
        body = _build_email_body(source_id=source_id, source_name=source_name, items=items)

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.smtp_from_email
        message["To"] = to_email
        message.set_content(body)

        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password or "")
                smtp.send_message(message)
        except Exception as exc:
            return SendResult(success=False, error=str(exc))

        return SendResult(success=True)


def _build_email_body(source_id: int, source_name: str, items: list[ChangeDigestItem]) -> str:
    settings = get_settings()
    grouped: dict[str, list[ChangeDigestItem]] = defaultdict(list)
    for item in items:
        grouped[item.course_label].append(item)

    if settings.app_base_url:
        link = f"{settings.app_base_url.rstrip('/')}/v1/changes?source_id={source_id}"
    else:
        link = f"/v1/changes?source_id={source_id}"

    lines: list[str] = [f"Source: {source_name}", f"Changes: {len(items)}", ""]

    for course_label in sorted(grouped):
        lines.append(f"## {course_label}")
        for item in grouped[course_label]:
            before = item.before_start_at_utc or "N/A"
            after = item.after_start_at_utc or "N/A"
            delta_text = _humanize_delta(item.delta_seconds)
            lines.append(f"- title: {item.title}")
            lines.append(f"  before -> after: {before} -> {after}")
            lines.append(f"  delta: {delta_text}")
            lines.append(f"  detected_at: {item.detected_at.isoformat()}")
            lines.append(f"  change_type: {item.change_type}")
            lines.append(f"  evidence: {item.evidence_path or 'n/a'}")
        lines.append("")

    lines.append(f"View changes: {link}")
    return "\n".join(lines)


def _humanize_delta(delta_seconds: int | None) -> str:
    if delta_seconds is None:
        return "n/a"
    if delta_seconds == 0:
        return "no time shift"

    direction = "later" if delta_seconds > 0 else "earlier"
    total_seconds = abs(delta_seconds)
    delta = timedelta(seconds=total_seconds)

    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes = remainder // 60

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{total_seconds}s")

    return f"moved {direction} by {' '.join(parts)}"
