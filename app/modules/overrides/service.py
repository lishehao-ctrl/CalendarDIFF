from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CourseOverride, Input, TaskOverride


def input_exists(db: Session, input_id: int) -> bool:
    return db.get(Input, input_id) is not None


def list_input_overrides(db: Session, input_id: int) -> tuple[list[CourseOverride], list[TaskOverride]]:
    course_rows = db.scalars(
        select(CourseOverride).where(CourseOverride.input_id == input_id).order_by(CourseOverride.original_course_label)
    ).all()
    task_rows = db.scalars(
        select(TaskOverride).where(TaskOverride.input_id == input_id).order_by(TaskOverride.event_uid)
    ).all()
    return course_rows, task_rows


def upsert_course_override(
    db: Session,
    input_id: int,
    original_course_label: str,
    display_course_label: str,
) -> CourseOverride:
    stmt = select(CourseOverride).where(
        CourseOverride.input_id == input_id,
        CourseOverride.original_course_label == original_course_label,
    )
    row = db.scalar(stmt)
    if row is None:
        row = CourseOverride(
            input_id=input_id,
            original_course_label=original_course_label,
            display_course_label=display_course_label,
        )
        db.add(row)
    else:
        row.display_course_label = display_course_label

    db.commit()
    db.refresh(row)
    return row


def upsert_task_override(
    db: Session,
    input_id: int,
    event_uid: str,
    display_title: str,
) -> TaskOverride:
    stmt = select(TaskOverride).where(
        TaskOverride.input_id == input_id,
        TaskOverride.event_uid == event_uid,
    )
    row = db.scalar(stmt)
    if row is None:
        row = TaskOverride(
            input_id=input_id,
            event_uid=event_uid,
            display_title=display_title,
        )
        db.add(row)
    else:
        row.display_title = display_title

    db.commit()
    db.refresh(row)
    return row


def delete_course_override(db: Session, input_id: int, original_course_label: str) -> bool:
    stmt = select(CourseOverride).where(
        CourseOverride.input_id == input_id,
        CourseOverride.original_course_label == original_course_label,
    )
    row = db.scalar(stmt)
    if row is None:
        return False

    db.delete(row)
    db.commit()
    return True


def delete_task_override(db: Session, input_id: int, event_uid: str) -> bool:
    stmt = select(TaskOverride).where(
        TaskOverride.input_id == input_id,
        TaskOverride.event_uid == event_uid,
    )
    row = db.scalar(stmt)
    if row is None:
        return False

    db.delete(row)
    db.commit()
    return True
