from tests.conftest import SAMPLE_RFC


def _create_project(client):
    r = client.post("/projects", json={"name": "Orders", "rfc_text": SAMPLE_RFC})
    assert r.status_code == 201
    return r.json()["id"]


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_project_validation(client):
    assert client.post("/projects", json={"name": "x", "rfc_text": "short"}).status_code == 422
    assert client.get("/projects/999").status_code == 404


def test_project_crud(client):
    pid = _create_project(client)
    assert client.get(f"/projects/{pid}").json()["name"] == "Orders"
    assert len(client.get("/projects").json()) == 1
    assert client.delete(f"/projects/{pid}").status_code == 204
    assert client.get(f"/projects/{pid}").status_code == 404


def test_review_end_to_end(client):
    pid = _create_project(client)
    r = client.post(f"/projects/{pid}/reviews")
    assert r.status_code == 202
    rid = r.json()["id"]  # TestClient runs the background task before returning

    detail = client.get(f"/reviews/{rid}").json()
    assert detail["status"] == "completed"
    assert len(detail["findings"]) == 5
    assert len(detail["debates"]) == 5
    assert detail["report"]["decision"] == "reject"

    crit = client.get(f"/reviews/{rid}/findings", params={"severity": "critical"}).json()
    assert [f["agent_name"] for f in crit] == ["Security Agent"]

    by_agent = client.get(f"/reviews/{rid}/findings", params={"agent": "database agent"}).json()
    assert len(by_agent) == 1

    debates = client.get(f"/reviews/{rid}/debates").json()
    assert debates[0]["agent_name"] and "target_agent_name" in debates[0]

    report = client.get(f"/reviews/{rid}/report").json()
    assert report["score"] == 35
    assert len(client.get("/agents").json()) == 6
    assert len(client.get(f"/projects/{pid}/reviews").json()) == 1


def test_report_unavailable_for_failed_review(client, fake_llm):
    fake_llm.fail_all = True
    pid = _create_project(client)
    rid = client.post(f"/projects/{pid}/reviews").json()["id"]
    assert client.get(f"/reviews/{rid}").json()["status"] == "failed"
    assert client.get(f"/reviews/{rid}/report").status_code == 409


def test_project_edit_and_rereview_comparison(client):
    pid = _create_project(client)
    # First review
    r1 = client.post(f"/projects/{pid}/reviews")
    assert r1.status_code == 202
    rid1 = r1.json()["id"]

    d1 = client.get(f"/reviews/{rid1}").json()
    assert d1["status"] == "completed"
    assert d1["comparison"] is None

    # Update RFC for the project (simulate fixing security and adding something)
    updated_rfc = SAMPLE_RFC + "\n\n## Future\nWe plan to deploy multi-region."
    up = client.patch(f"/projects/{pid}", json={"rfc_text": updated_rfc})
    assert up.status_code == 200
    assert len(up.json()["rfc_versions"]) == 2

    # Second review (re-review)
    r2 = client.post(f"/projects/{pid}/reviews")
    assert r2.status_code == 202
    rid2 = r2.json()["id"]

    d2 = client.get(f"/reviews/{rid2}").json()
    assert d2["status"] == "completed"
    assert d2["previous_review_id"] == rid1
    assert d2["comparison"] is not None

    comp = d2["comparison"]
    assert comp["previous_review_id"] == rid1
    assert comp["previous_score"] == 35
    assert comp["current_score"] == 35
    assert comp["score_diff"] == 0
    # Because FakeLLM returns the same findings, all 5 match as "still_open"
    assert comp["counts"]["still_open"] == 5
    assert comp["counts"]["fixed"] == 0
    assert comp["counts"]["new"] == 0

    # Test direct comparison endpoint
    comp_endpoint = client.get(f"/reviews/{rid2}/comparison")
    assert comp_endpoint.status_code == 200
    assert comp_endpoint.json()["previous_review_id"] == rid1

    # First review has no previous comparison
    assert client.get(f"/reviews/{rid1}/comparison").status_code == 404


def test_finding_status_workflow_and_permissions(client):
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.conftest import register_user

    pid = _create_project(client)
    rid = client.post(f"/projects/{pid}/reviews").json()["id"]

    findings = client.get(f"/reviews/{rid}/findings").json()
    assert len(findings) == 5
    fid = findings[0]["id"]
    assert findings[0]["status"] == "open"

    # Initial resolution counter
    detail = client.get(f"/reviews/{rid}").json()
    assert detail["total_findings"] == 5
    assert detail["resolved_findings"] == 0

    # 1. Mark accepted
    up1 = client.patch(f"/reviews/{rid}/findings/{fid}", json={"status": "accepted"})
    assert up1.status_code == 200
    assert up1.json()["status"] == "accepted"

    # Check review summary counter
    detail = client.get(f"/reviews/{rid}").json()
    assert detail["resolved_findings"] == 1

    # 2. Mark rejected without reason -> 422
    up_bad = client.patch(f"/reviews/{rid}/findings/{fid}", json={"status": "rejected"})
    assert up_bad.status_code == 422

    # 3. Mark rejected with reason -> 200
    up_rej = client.patch(
        f"/reviews/{rid}/findings/{fid}",
        json={"status": "rejected", "reason": "Will be handled at proxy layer."},
    )
    assert up_rej.status_code == 200
    assert up_rej.json()["status"] == "rejected"
    assert up_rej.json()["status_reason"] == "Will be handled at proxy layer."

    # 4. Mark fixed
    up_fix = client.patch(f"/reviews/{rid}/findings/{fid}", json={"status": "fixed"})
    assert up_fix.status_code == 200
    assert up_fix.json()["status"] == "fixed"

    # History summary has resolved counter
    recent = client.get("/reviews?limit=5").json()
    target_row = next(r for r in recent if r["id"] == rid)
    assert target_row["total_findings"] == 5
    assert target_row["resolved_findings"] == 1

    # 5. Authorization: Another user CANNOT update this finding
    bob = TestClient(app)
    bob_headers = register_user(bob, "bob_finding@example.com", name="Bob", password="password-1234")
    unauth = bob.patch(
        f"/reviews/{rid}/findings/{fid}",
        json={"status": "open"},
        headers=bob_headers,
    )
    assert unauth.status_code == 404


def test_document_upload_and_validation(client):
    import io
    from docx import Document

    # 1. Plain text / Markdown upload
    r_txt = client.post(
        "/projects/upload",
        files={"file": ("architecture.md", b"# Service RFC\n\n## Overview\nThis is a test upload.")},
    )
    assert r_txt.status_code == 200
    assert "This is a test upload." in r_txt.json()["text"]

    # 2. Word .docx upload
    doc = Document()
    doc.add_heading("Architecture RFC", 0)
    doc.add_paragraph("This is extracted from docx successfully.")
    docx_io = io.BytesIO()
    doc.save(docx_io)
    docx_bytes = docx_io.getvalue()

    r_docx = client.post(
        "/projects/upload",
        files={"file": ("spec.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert r_docx.status_code == 200
    assert "extracted from docx successfully" in r_docx.json()["text"]

    # 3. Empty file validation
    r_empty = client.post(
        "/projects/upload",
        files={"file": ("empty.txt", b"")},
    )
    assert r_empty.status_code == 422

    # 4. Unsupported format validation
    r_bad = client.post(
        "/projects/upload",
        files={"file": ("image.png", b"\x89PNG\r\n\x1a\n")},
    )
    assert r_bad.status_code == 422


def test_review_exports_markdown_and_pdf(client):
    pid = _create_project(client)
    rid = client.post(f"/projects/{pid}/reviews").json()["id"]

    # Markdown export
    md_res = client.get(f"/reviews/{rid}/export/markdown")
    assert md_res.status_code == 200
    assert "text/markdown" in md_res.headers["content-type"]
    assert f"**Review ID:** #{rid}" in md_res.text
    assert "Executive Decision" in md_res.text
    assert "Security Agent" in md_res.text

    # PDF export
    pdf_res = client.get(f"/reviews/{rid}/export/pdf")
    assert pdf_res.status_code == 200
    assert pdf_res.headers["content-type"] == "application/pdf"
    assert pdf_res.content.startswith(b"%PDF")


def test_organization_workspaces_and_roles(client):
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.conftest import register_user

    # Alice creates a project
    pid = _create_project(client)
    alice_orgs = client.get("/organizations/me").json()
    assert len(alice_orgs) >= 1
    org_id = alice_orgs[0]["id"]

    # Register Bob and Charlie
    bob_client = TestClient(app)
    bob_headers = register_user(bob_client, "bob_workspace@example.com", name="Bob")

    charlie_client = TestClient(app)
    charlie_headers = register_user(charlie_client, "charlie_workspace@example.com", name="Charlie")

    # Before invite, Bob cannot see Alice's project
    assert len(bob_client.get("/projects", headers=bob_headers).json()) == 0
    assert bob_client.get(f"/projects/{pid}", headers=bob_headers).status_code == 404

    # Alice invites Bob as reviewer
    inv_bob = client.post(
        f"/organizations/{org_id}/invites",
        json={"email": "bob_workspace@example.com", "role": "reviewer"},
    )
    assert inv_bob.status_code == 201
    assert inv_bob.json()["role"] == "reviewer"

    # Alice invites Charlie as viewer
    inv_charlie = client.post(
        f"/organizations/{org_id}/invites",
        json={"email": "charlie_workspace@example.com", "role": "viewer"},
    )
    assert inv_charlie.status_code == 201
    assert inv_charlie.json()["role"] == "viewer"

    # Bob (reviewer) can now see Alice's project and start reviews
    assert len(bob_client.get("/projects", headers=bob_headers).json()) == 1
    bob_rev = bob_client.post(f"/projects/{pid}/reviews", headers=bob_headers)
    assert bob_rev.status_code == 202
    rid = bob_rev.json()["id"]

    # Charlie (viewer) can see the project and reviews
    assert len(charlie_client.get("/projects", headers=charlie_headers).json()) == 1
    assert charlie_client.get(f"/reviews/{rid}", headers=charlie_headers).status_code == 200

    # Charlie (viewer) CANNOT start reviews (403 forbidden)
    assert charlie_client.post(f"/projects/{pid}/reviews", headers=charlie_headers).status_code == 403

    # Charlie (viewer) CANNOT change finding status (403 forbidden)
    findings = charlie_client.get(f"/reviews/{rid}/findings", headers=charlie_headers).json()
    fid = findings[0]["id"]
    assert charlie_client.patch(
        f"/reviews/{rid}/findings/{fid}",
        json={"status": "accepted"},
        headers=charlie_headers,
    ).status_code == 403

    # Non-owner (Bob) CANNOT invite members (403 forbidden)
    assert bob_client.post(
        f"/organizations/{org_id}/invites",
        json={"email": "someone@example.com", "role": "viewer"},
        headers=bob_headers,
    ).status_code == 403


def test_finding_comments_workflow(client):
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.conftest import register_user

    pid = _create_project(client)
    org_id = client.get("/organizations/me").json()[0]["id"]
    rid = client.post(f"/projects/{pid}/reviews").json()["id"]
    findings = client.get(f"/reviews/{rid}/findings").json()
    fid = findings[0]["id"]

    # Alice comments
    c1 = client.post(
        f"/reviews/{rid}/findings/{fid}/comments",
        json={"comment": "We should consider AWS KMS for key management."},
    )
    assert c1.status_code == 200
    assert c1.json()["comment"] == "We should consider AWS KMS for key management."
    assert c1.json()["user_name"] == "Alice"

    # Bob (member) comments
    bob_client = TestClient(app)
    bob_headers = register_user(bob_client, "bob_commenter@example.com", name="Bob Commenter")
    client.post(
        f"/organizations/{org_id}/invites",
        json={"email": "bob_commenter@example.com", "role": "viewer"},
    )
    c2 = bob_client.post(
        f"/reviews/{rid}/findings/{fid}/comments",
        json={"comment": "Agreed, KMS would satisfy compliance."},
        headers=bob_headers,
    )
    assert c2.status_code == 200
    assert c2.json()["user_name"] == "Bob Commenter"

    # List comments
    comments = client.get(f"/reviews/{rid}/findings/{fid}/comments").json()
    assert len(comments) == 2
    assert comments[0]["user_name"] == "Alice"
    assert comments[1]["user_name"] == "Bob Commenter"



