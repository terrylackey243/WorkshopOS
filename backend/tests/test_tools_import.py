from __future__ import annotations

from httpx import AsyncClient

from .conftest import auth_headers, register_org


def _csv(headers: str, *rows: str) -> bytes:
    return ("\n".join([headers, *rows]) + "\n").encode("utf-8")


async def test_import_creates_tools_with_null_location(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])

    csv_bytes = _csv(
        "name,category,manufacturer,sku,notes,quantity",
        "Cordless Drill,Power Tools,DeWalt,DCD771,Cordless 20V,2",
        "Tape Measure,Hand Tools,Stanley,,,1",
    )
    resp = await client.post(
        f"/organizations/{org_id}/tools/import",
        headers=headers,
        files={"file": ("tools.csv", csv_bytes, "text/csv")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["imported"] == 2
    names = {t["name"] for t in body["tools"]}
    assert names == {"Cordless Drill", "Tape Measure"}
    for tool in body["tools"]:
        assert tool["location"] is None
        assert tool["drawer_id"] is None

    drill = next(t for t in body["tools"] if t["name"] == "Cordless Drill")
    assert drill["category"] == "Power Tools"
    assert drill["manufacturer"] == "DeWalt"
    assert drill["sku"] == "DCD771"
    assert drill["quantity"] == 2

    tape = next(t for t in body["tools"] if t["name"] == "Tape Measure")
    assert tape["quantity"] == 1  # defaulted, blank in CSV

    list_resp = await client.get(f"/organizations/{org_id}/tools", headers=headers)
    assert len(list_resp.json()) == 2


async def test_import_rejects_whole_file_on_one_bad_row(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])

    csv_bytes = _csv(
        "name,category,manufacturer,sku,notes,quantity",
        "Good Tool,,,,,1",
        ",Missing Name,,,,1",  # row 2: empty name
    )
    resp = await client.post(
        f"/organizations/{org_id}/tools/import",
        headers=headers,
        files={"file": ("tools.csv", csv_bytes, "text/csv")},
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert len(body["errors"]) == 1
    assert body["errors"][0]["row"] == 2
    assert "name is required" in body["errors"][0]["message"]

    # Nothing was created -- all-or-nothing, not partial success.
    list_resp = await client.get(f"/organizations/{org_id}/tools", headers=headers)
    assert list_resp.json() == []


async def test_import_reports_non_numeric_quantity(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])

    csv_bytes = _csv(
        "name,category,manufacturer,sku,notes,quantity",
        "Hammer,,,,,abc",
    )
    resp = await client.post(
        f"/organizations/{org_id}/tools/import",
        headers=headers,
        files={"file": ("tools.csv", csv_bytes, "text/csv")},
    )
    assert resp.status_code == 422, resp.text
    assert "not a whole number" in resp.json()["errors"][0]["message"]


async def test_import_rejected_when_it_would_exceed_free_plan_tool_limit(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])

    for i in range(98):
        create_resp = await client.post(
            f"/organizations/{org_id}/tools", json={"name": f"Existing Tool {i}", "quantity": 1}, headers=headers
        )
        assert create_resp.status_code == 201, create_resp.text

    # Free plan allows 100 tools total; org has 98, importing 3 would exceed it.
    csv_bytes = _csv(
        "name,category,manufacturer,sku,notes,quantity",
        "New Tool 1,,,,,1",
        "New Tool 2,,,,,1",
        "New Tool 3,,,,,1",
    )
    resp = await client.post(
        f"/organizations/{org_id}/tools/import",
        headers=headers,
        files={"file": ("tools.csv", csv_bytes, "text/csv")},
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["errors"][0]["row"] is None
    assert "exceed" in body["errors"][0]["message"]

    list_resp = await client.get(f"/organizations/{org_id}/tools", headers=headers)
    assert len(list_resp.json()) == 98  # nothing new created


async def test_import_ignores_unknown_columns_and_skips_blank_rows(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])

    csv_bytes = _csv(
        "name,category,manufacturer,sku,notes,quantity,unknown_column",
        "Wrench,,,,,1,ignored-value",
        ",,,,,,",  # fully blank row -- skipped, not an error
        "Screwdriver,,,,,1,also-ignored",
    )
    resp = await client.post(
        f"/organizations/{org_id}/tools/import",
        headers=headers,
        files={"file": ("tools.csv", csv_bytes, "text/csv")},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["imported"] == 2


async def test_import_rejects_non_csv_extension(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])

    resp = await client.post(
        f"/organizations/{org_id}/tools/import",
        headers=headers,
        files={"file": ("tools.txt", b"name\nHammer\n", "text/plain")},
    )
    assert resp.status_code == 422
    assert "csv" in resp.json()["detail"].lower()


async def test_import_rejects_oversized_file(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])

    # 2MB cap -- build a file just over it.
    huge_row = "x" * 200
    rows = [f"Tool {i},{huge_row},,,,1" for i in range(11000)]
    csv_bytes = _csv("name,category,manufacturer,sku,notes,quantity", *rows)
    assert len(csv_bytes) > 2 * 1024 * 1024

    resp = await client.post(
        f"/organizations/{org_id}/tools/import",
        headers=headers,
        files={"file": ("tools.csv", csv_bytes, "text/csv")},
    )
    assert resp.status_code == 413


async def test_import_rejects_too_many_rows(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])

    rows = [f"Tool {i},,,,,1" for i in range(5001)]
    csv_bytes = _csv("name,category,manufacturer,sku,notes,quantity", *rows)
    resp = await client.post(
        f"/organizations/{org_id}/tools/import",
        headers=headers,
        files={"file": ("tools.csv", csv_bytes, "text/csv")},
    )
    assert resp.status_code == 422, resp.text
    assert any("row" in e["message"].lower() for e in resp.json()["errors"])
