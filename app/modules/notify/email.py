from __future__ import annotations

import html
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.oauth_config import resolve_frontend_app_base_url
from app.modules.notify.interface import ChangeDigestItem, Notifier, SendResult


class SMTPEmailNotifier(Notifier):
    def send_changes_digest(
        self,
        to_email: str,
        review_label: str,
        user_id: int,
        items: list[ChangeDigestItem],
        timezone_name: str | None = None,
    ) -> SendResult:
        settings = get_settings()
        review_count = len(items)
        review_label = "new review" if review_count == 1 else "new reviews"

        subject = f"[CalendarDIFF] {review_count} {review_label}"
        plain_body, html_body = _build_email_bodies(
            user_id=user_id,
            review_label=review_label,
            items=items,
            timezone_name=timezone_name,
        )

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = _format_from_header(
            from_email=settings.smtp_from_email,
            from_name=settings.smtp_from_name,
        )
        message["To"] = to_email
        message.set_content(plain_body)
        message.add_alternative(html_body, subtype="html")

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


def _format_from_header(*, from_email: str, from_name: str | None) -> str:
    normalized_name = (from_name or "").strip()
    if not normalized_name:
        return from_email
    return formataddr((normalized_name, from_email))


def _build_email_bodies(
    user_id: int,
    review_label: str,
    items: list[ChangeDigestItem],
    timezone_name: str | None,
) -> tuple[str, str]:
    settings = get_settings()
    del user_id, review_label
    try:
        base_url = resolve_frontend_app_base_url(settings=settings)
    except Exception:
        base_url = settings.app_base_url.rstrip("/") if settings.app_base_url else ""
    link_path = "/changes?review_status=pending"
    link = f"{base_url}{link_path}" if base_url else link_path

    review_count = len(items)
    review_label = "new review" if review_count == 1 else "new reviews"
    plain_lines: list[str] = [
        f"You have {review_count} {review_label} in your review box.",
        "",
    ]
    html_parts: list[str] = [
        "<html><body>",
        f"<p>You have {review_count} {review_label} in your review box.</p>",
    ]

    for section_title, section_items in _group_items(items=items):
        plain_lines.append(section_title)
        html_parts.append(f"<p><strong>{html.escape(section_title)}</strong></p>")
        html_parts.append("<ul>")
        for item in section_items:
            before = _format_due_for_timezone(
                item.before_due_at,
                time_precision=item.before_time_precision,
                timezone_name=timezone_name,
            )
            after = _format_due_for_timezone(
                item.after_due_at,
                time_precision=item.after_time_precision,
                timezone_name=timezone_name,
            )
            line = _build_change_line(
                item=item,
                before=before,
                after=after,
            )
            plain_lines.append(line)
            html_parts.append(f"<li>{html.escape(line)}</li>")
        plain_lines.append("")
        html_parts.append("</ul>")

    plain_lines.append(f"Open review box: {link}")
    html_parts.append(f'<p><a href="{html.escape(link, quote=True)}">Open review box</a></p>')
    html_parts.append("</body></html>")
    return "\n".join(plain_lines), "".join(html_parts)


def _format_due_for_timezone(value: str | None, *, time_precision: str, timezone_name: str | None) -> str:
    if not value:
        return "N/A"
    if time_precision == "date_only":
        return value[:10]

    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    if timezone_name:
        try:
            parsed = parsed.astimezone(ZoneInfo(timezone_name))
        except Exception:
            parsed = parsed.astimezone(timezone.utc)

    date_part = parsed.strftime("%Y-%m-%d")
    hour = parsed.strftime("%I").lstrip("0") or "12"
    minute = parsed.strftime("%M")
    meridiem = parsed.strftime("%p")
    return f"{date_part} {hour}:{minute} {meridiem}"


def _build_change_line(
    *,
    item: ChangeDigestItem,
    before: str,
    after: str,
) -> str:
    before_label = item.before_display.display_label if item.before_display is not None else item.entity_uid
    after_label = item.after_display.display_label if item.after_display is not None else before_label
    if item.change_type == "created":
        return f"Added {after_label}: {after}"
    if item.change_type == "removed":
        return f"Removed {before_label}: {before}"
    return f"{before_label}: {before} -> {after}"


def _group_items(items: list[ChangeDigestItem]) -> list[tuple[str, list[ChangeDigestItem]]]:
    ordered_sections = [
        ("Changed", "due_changed"),
        ("Added", "created"),
        ("Removed", "removed"),
    ]
    out: list[tuple[str, list[ChangeDigestItem]]] = []
    for section_title, change_type in ordered_sections:
        section_items = [item for item in items if item.change_type == change_type]
        if not section_items:
            continue
        section_items.sort(
            key=lambda item: (
                (item.after_display or item.before_display).course_display.casefold() if (item.after_display or item.before_display) is not None else "",
                (item.after_display or item.before_display).display_label.casefold() if (item.after_display or item.before_display) is not None else item.entity_uid.casefold(),
                item.after_due_at or item.before_due_at or "",
            )
        )
        out.append((section_title, section_items))
    return out
