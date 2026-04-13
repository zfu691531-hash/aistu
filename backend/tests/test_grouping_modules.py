# -*- coding: utf-8 -*-
"""教师分组与校务分班专项模块回归测试。"""

import pytest

from tests.conftest import auth_headers, create_client, login_as


def test_grouping_scheme_create_and_list():
    client = create_client()
    token = login_as(client)
    headers = auth_headers(token)

    class_response = client.get(
        "/api/classes",
        headers=headers,
        params={"page": 1, "page_size": 50, "status": 1},
    )
    assert class_response.status_code == 200

    classes = class_response.json()["data"]["list"]
    if not classes:
        pytest.skip("No active classes available for grouping scheme test.")

    class_id = classes[0]["id"]
    student_response = client.get(
        "/api/students",
        headers=headers,
        params={"page": 1, "page_size": 100, "class_id": class_id},
    )
    assert student_response.status_code == 200

    students = student_response.json()["data"]["list"]
    if not students:
        pytest.skip("No students available in selected class for grouping scheme test.")

    midpoint = max(1, len(students) // 2)
    assignments = [
        {"group_no": 1, "student_ids": [item["id"] for item in students[:midpoint]]},
        {"group_no": 2, "student_ids": [item["id"] for item in students[midpoint:]]},
    ]
    assignments = [item for item in assignments if item["student_ids"]]

    create_response = client.post(
        "/api/grouping/schemes",
        headers=headers,
        json={
            "class_id": class_id,
            "scheme_name": "测试分组方案",
            "group_count": len(assignments),
            "balance_factors": ["score", "gender"],
            "source_type": "manual",
            "remark": "自动化测试创建",
            "assignments": assignments,
        },
    )

    assert create_response.status_code == 200
    assert create_response.json()["code"] == 200

    list_response = client.get(
        "/api/grouping/schemes",
        headers=headers,
        params={"page": 1, "page_size": 20, "class_id": class_id},
    )

    assert list_response.status_code == 200
    body = list_response.json()
    assert body["code"] == 200
    assert any(item["scheme_name"] == "测试分组方案" for item in body["data"]["list"])


def test_grouping_generate_with_profile_loadable():
    client = create_client()
    token = login_as(client)
    headers = auth_headers(token)

    class_response = client.get(
        "/api/classes",
        headers=headers,
        params={"page": 1, "page_size": 50, "status": 1},
    )
    assert class_response.status_code == 200

    classes = class_response.json()["data"]["list"]
    if not classes:
        pytest.skip("No active classes available for grouping profile generation test.")

    selected_class = None
    students = []
    for item in classes:
        student_response = client.get(
            "/api/students",
            headers=headers,
            params={"page": 1, "page_size": 100, "class_id": item["id"]},
        )
        assert student_response.status_code == 200
        students = student_response.json()["data"]["list"]
        if len(students) >= 2:
            selected_class = item
            break

    if not selected_class:
        pytest.skip("No class with enough students available for grouping profile generation test.")

    response = client.post(
        "/api/grouping/generate-with-profile",
        headers=headers,
        json={"class_id": selected_class["id"], "group_count": 2, "constraints": {"balance_risk": True}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["data"]["class_id"] == selected_class["id"]
    assert len(body["data"]["assignments"]) == 2


def test_placement_overview_loadable():
    client = create_client()
    token = login_as(client)
    headers = auth_headers(token)

    class_response = client.get(
        "/api/classes",
        headers=headers,
        params={"page": 1, "page_size": 50, "status": 1},
    )
    assert class_response.status_code == 200

    classes = class_response.json()["data"]["list"]
    if not classes:
        pytest.skip("No active classes available for placement overview test.")

    grade = classes[0]["grade"]
    response = client.get(
        "/api/placement/overview",
        headers=headers,
        params={"grade": grade},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["data"]["grade"] == grade


def test_placement_generate_with_profile_loadable():
    client = create_client()
    token = login_as(client)
    headers = auth_headers(token)

    class_response = client.get(
        "/api/classes",
        headers=headers,
        params={"page": 1, "page_size": 50, "status": 1},
    )
    assert class_response.status_code == 200

    classes = class_response.json()["data"]["list"]
    if not classes:
        pytest.skip("No active classes available for placement profile generation test.")

    grade = classes[0]["grade"]
    response = client.post(
        "/api/placement/generate-with-profile",
        headers=headers,
        json={"grade": grade, "constraints": {"balance_risk": True, "disperse_high_risk": True}},
    )

    assert response.status_code == 200
    body = response.json()
    if body["code"] != 200 and body["msg"] == "当前没有可用于正式分班的学生":
        pytest.skip("No eligible students available for placement profile generation test.")
    assert body["code"] == 200
    assert body["data"]["grade"] == grade
    assert "assignments" in body["data"]
