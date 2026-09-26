"""The configuration file may replace one entity's setup, never another's."""
import io
import json


def _workspace(client, email):
    result = client.post("/api/auth/signup", json={
        "email": email, "password": "Passw0rd!x", "company_name": "Bundle test",
    })
    assert result.status_code == 200, result.text
    headers = {"Authorization": f"Bearer {result.json()['data']['access_token']}"}
    entity = client.post("/api/org/entities", headers=headers, json={"name": email}).json()["data"]
    headers["X-Entity-Id"] = entity["id"]
    return headers


def _send(client, headers, bundle, dry_run=True):
    return client.post(
        f"/api/config/bundle/import?dry_run={str(dry_run).lower()}", headers=headers,
        files={"file": ("configuration.json", io.BytesIO(json.dumps(bundle).encode()), "application/json")},
    )


def test_configuration_upload_preview_apply_and_entity_isolation(client):
    first = _workspace(client, "config-bundle-first@example.com")
    second = _workspace(client, "config-bundle-second@example.com")
    bundle = client.get("/api/config/bundle/export", headers=first).json()["data"]
    assert bundle["format"] == "peopleopslab-config"
    # A downloaded file is a template. Only sections present will be replaced.
    bundle["sections"] = {"components": [{
        "component_name": "Basic", "pf_applicable": True,
        "esic_applicable": True, "pt_applicable": True, "lwf_applicable": True,
        "bonus_applicable": False, "included_in_wages": True,
        "taxable": True, "tax_exemption_type": "none",
    }]}
    preview = _send(client, first, bundle)
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["replace_sections"] == {"components": 1}
    assert client.get("/api/components", headers=first).json()["data"] == []
    applied = _send(client, first, bundle, dry_run=False)
    assert applied.status_code == 200, applied.text
    assert client.get("/api/components", headers=first).json()["data"][0]["component_name"] == "Basic"
    assert client.get("/api/components", headers=second).json()["data"] == []

    # A file cannot supply an ID to overwrite another entity's record.
    bundle["sections"]["components"][0]["entity_id"] = second["X-Entity-Id"]
    rejected = _send(client, first, bundle, dry_run=False)
    assert rejected.status_code == 422
    assert len(client.get("/api/components", headers=first).json()["data"]) == 1


def test_downloaded_configuration_round_trips_with_statutory_and_wage_settings(client):
    headers = _workspace(client, "config-bundle-roundtrip@example.com")
    decision = client.post("/api/minimum-wage/applicability", headers=headers, json={
        "effective_from": "2026-04-01", "applicable": False,
        "reason": "Reviewed for test", "source_reference": "Review record",
    })
    assert decision.status_code == 200, decision.text
    rate = client.post("/api/minimum-wage/rates", headers=headers, json={
        "state": "Karnataka", "skill_category": "skilled", "basic_per_month": "16000",
        "vda_per_month": "1000", "effective_from": "2026-04-01",
        "source_reference": "Test notification",
    })
    assert rate.status_code == 200, rate.text
    bundle = client.get("/api/config/bundle/export", headers=headers).json()["data"]
    assert bundle["sections"]["minimum_wage_rates"]
    assert bundle["sections"]["minimum_wage_applicability"]
    result = _send(client, headers, bundle, dry_run=False)
    assert result.status_code == 200, result.text
    after = client.get("/api/config/bundle/export", headers=headers).json()["data"]
    assert after["sections"] == bundle["sections"]
