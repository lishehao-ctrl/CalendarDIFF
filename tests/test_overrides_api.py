from __future__ import annotations

from tests.helpers_inputs import create_ics_input_for_user


def test_overrides_crud_for_source(client, initialized_user, db_session) -> None:
    headers = {"X-API-Key": "test-api-key"}
    source_id = create_ics_input_for_user(
        db_session,
        user_id=initialized_user["id"],
        url="https://example.com/feed.ics",
    )

    course_put = client.put(
        f"/v1/inputs/{source_id}/courses/rename",
        headers=headers,
        json={"original_course_label": "CSE 151A", "display_course_label": "ML A"},
    )
    assert course_put.status_code == 200
    assert course_put.json()["display_course_label"] == "ML A"

    task_put = client.put(
        f"/v1/inputs/{source_id}/tasks/event-1/rename",
        headers=headers,
        json={"display_title": "Homework One"},
    )
    assert task_put.status_code == 200
    assert task_put.json()["display_title"] == "Homework One"

    list_response = client.get(f"/v1/inputs/{source_id}/overrides", headers=headers)
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["input_id"] == source_id
    assert len(payload["courses"]) == 1
    assert len(payload["tasks"]) == 1
    assert payload["courses"][0]["original_course_label"] == "CSE 151A"
    assert payload["courses"][0]["display_course_label"] == "ML A"
    assert payload["tasks"][0]["event_uid"] == "event-1"
    assert payload["tasks"][0]["display_title"] == "Homework One"

    delete_course = client.delete(
        f"/v1/inputs/{source_id}/courses/rename?original_course_label=CSE%20151A",
        headers=headers,
    )
    assert delete_course.status_code == 204

    delete_task = client.delete(f"/v1/inputs/{source_id}/tasks/event-1/rename", headers=headers)
    assert delete_task.status_code == 204

    list_after_delete = client.get(f"/v1/inputs/{source_id}/overrides", headers=headers)
    assert list_after_delete.status_code == 200
    payload = list_after_delete.json()
    assert payload["courses"] == []
    assert payload["tasks"] == []
