"""Business and object authorization regression tests using real JWT login."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from app.core.db import engine
from app.models import InventoryTransaction, Item

P = "/api/v1"


@pytest.fixture
def farmer(client):
    phone = "+231" + str(uuid.uuid4().int)[:9]
    body = {
        "full_name": "Test Farmer",
        "phone_number": phone,
        "password": "testing-password",
        "farm": {"name": "Test Farm", "county": "Bong", "farm_type": "Crops"},
    }
    response = client.post(P + "/farmers/signup", json=body)
    assert response.status_code == 201, response.text
    assert "hashed_password" not in response.text
    account = response.json()
    token = client.post(
        P + "/login/access-token",
        data={"username": phone, "password": body["password"]},
    )
    assert token.status_code == 200
    return {
        "farm": account["farm"]["id"],
        "headers": {"Authorization": "Bearer " + token.json()["access_token"]},
    }


def post(client, farmer, path, body):
    response = client.post(P + path, headers=farmer["headers"], json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


def item(client, farmer):
    return post(
        client,
        farmer,
        "/items/",
        {"title": "Seeds", "farm_id": farmer["farm"], "unit": "kg"},
    )


def harvest(client, farmer):
    return post(
        client,
        farmer,
        "/harvests",
        {
            "farm_id": farmer["farm"],
            "crop_name": "Rice",
            "quantity": "50",
            "unit": "kg",
            "harvest_date": "2026-11-01",
        },
    )


def movement(client, farmer, resource, kind, quantity, key=None):
    return client.post(
        P + "/inventory-transactions",
        headers=farmer["headers"],
        json={
            "item_id": resource["id"],
            "transaction_type": kind,
            "quantity": str(quantity),
            "idempotency_key": key or str(uuid.uuid4()),
        },
    )


def test_farms_profiles_and_permissions(client, farmer):
    assert client.get(P + "/farms/").status_code == 401
    assert (
        client.get(
            P + "/farms/" + farmer["farm"], headers=farmer["headers"]
        ).status_code
        == 200
    )
    other = post(
        client,
        farmer,
        "/farms/",
        {"name": "Second", "county": "Lofa", "farm_type": "Crops"},
    )
    assert (
        client.patch(
            P + "/farms/" + other["id"],
            headers=farmer["headers"],
            json={"name": "Updated"},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            P + "/farms/" + other["id"], headers=farmer["headers"], json={"name": None}
        ).status_code
        == 422
    )
    assert (
        client.delete(
            P + "/farms/" + other["id"], headers=farmer["headers"]
        ).status_code
        == 200
    )
    response = client.patch(
        P + "/users/me", headers=farmer["headers"], json={"is_superuser": True}
    )
    assert response.json()["is_superuser"] is False


def test_cross_user_access(client, farmer):
    response = client.post(
        P + "/farmers/signup",
        json={
            "full_name": "Other",
            "phone_number": "+231" + str(uuid.uuid4().int)[:9],
            "password": "testing-password",
            "farm": {"name": "Private", "county": "Bong", "farm_type": "Crops"},
        },
    )
    private_farm = response.json()["farm"]["id"]
    assert (
        client.get(P + "/farms/" + private_farm, headers=farmer["headers"]).status_code
        == 404
    )
    assert (
        client.post(
            P + "/items/",
            headers=farmer["headers"],
            json={"title": "Bad", "farm_id": private_farm},
        ).status_code
        == 404
    )
    for path, fields in [
        (
            "/farm-expenses",
            {"category": "Seeds", "amount": "5", "expense_date": "2026-11-01"},
        ),
        (
            "/harvests",
            {
                "crop_name": "Rice",
                "quantity": "5",
                "unit": "kg",
                "harvest_date": "2026-11-01",
            },
        ),
        ("/loss-records", {"loss_type": "Pest", "quantity": "1", "unit": "kg"}),
    ]:
        assert (
            client.post(
                P + path,
                headers=farmer["headers"],
                json={"farm_id": private_farm, **fields},
            ).status_code
            == 404
        )
    assert (
        client.get(
            P + "/harvests", headers=farmer["headers"], params={"farm_id": private_farm}
        ).json()["count"]
        == 0
    )
    assert (
        client.get(
            P + "/farms/" + private_farm + "/overview", headers=farmer["headers"]
        ).status_code
        == 404
    )


def test_stock_balance_retry_adjustment_and_history(client, farmer):
    resource = item(client, farmer)
    key = str(uuid.uuid4())
    first = movement(client, farmer, resource, "IN", "10.25", key)
    assert first.status_code == 201
    assert (
        movement(client, farmer, resource, "IN", "10.25", key).json()["id"]
        == first.json()["id"]
    )
    assert movement(client, farmer, resource, "IN", "11", key).status_code == 409
    assert movement(client, farmer, resource, "OUT", "20").status_code == 409
    assert movement(client, farmer, resource, "OUT", "0").status_code == 422
    assert movement(client, farmer, resource, "IN", "-1").status_code == 422
    assert movement(client, farmer, resource, "OUT", "0.25").status_code == 201
    adjustment = movement(client, farmer, resource, "ADJUSTMENT", "0")
    assert adjustment.status_code == 201
    assert Decimal(adjustment.json()["balance_after"]) == 0
    assert (
        client.patch(
            P + "/items/" + resource["id"],
            headers=farmer["headers"],
            json={"quantity": 999},
        ).status_code
        == 422
    )
    assert (
        client.delete(
            P + "/items/" + resource["id"], headers=farmer["headers"]
        ).status_code
        == 409
    )
    assert (
        client.delete(
            P + "/farms/" + farmer["farm"], headers=farmer["headers"]
        ).status_code
        == 409
    )
    result = client.get(
        P + "/inventory-transactions",
        headers=farmer["headers"],
        params={"item_id": resource["id"]},
    ).json()
    assert result["count"] == 3


def test_concurrent_stock_withdrawals(client, farmer):
    resource = item(client, farmer)
    assert movement(client, farmer, resource, "IN", "10").status_code == 201
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: movement(client, farmer, resource, "OUT", "7").status_code,
                range(2),
            )
        )
    assert sorted(results) == [201, 409]
    with Session(engine) as session:
        stock = session.get(Item, uuid.UUID(resource["id"]))
        assert stock.quantity == Decimal("3")
        assert (
            len(
                session.exec(
                    select(InventoryTransaction).where(
                        InventoryTransaction.item_id == stock.id
                    )
                ).all()
            )
            == 2
        )


@pytest.mark.parametrize("amount,currency", [("0", "LRD"), ("-1", "USD"), ("1", "EUR")])
def test_expense_validation(client, farmer, amount, currency):
    response = client.post(
        P + "/farm-expenses",
        headers=farmer["headers"],
        json={
            "farm_id": farmer["farm"],
            "category": "Seeds",
            "amount": amount,
            "currency": currency,
            "expense_date": "2026-11-01",
        },
    )
    assert response.status_code == 422


def test_crud_filters_and_loss_links(client, farmer):
    crop = harvest(client, farmer)
    assert (
        client.get(
            P + "/harvests",
            headers=farmer["headers"],
            params={"farm_id": farmer["farm"], "start_date": "2026-11-02"},
        ).json()["count"]
        == 0
    )
    assert (
        client.post(
            P + "/harvests",
            headers=farmer["headers"],
            json={
                "farm_id": farmer["farm"],
                "crop_name": "Rice",
                "quantity": 0,
                "unit": "kg",
                "harvest_date": "2026-11-01",
            },
        ).status_code
        == 422
    )
    loss = post(
        client,
        farmer,
        "/loss-records",
        {
            "farm_id": farmer["farm"],
            "harvest_id": crop["id"],
            "loss_type": "Pest",
            "quantity": "2",
            "unit": "kg",
        },
    )
    assert (
        client.delete(
            P + "/harvests/" + crop["id"], headers=farmer["headers"]
        ).status_code
        == 409
    )
    assert (
        client.patch(
            P + "/harvests/" + crop["id"],
            headers=farmer["headers"],
            json={"unit": "bags"},
        ).status_code
        == 409
    )
    assert (
        client.patch(
            P + "/loss-records/" + loss["id"],
            headers=farmer["headers"],
            json={"quantity": "3"},
        ).status_code
        == 200
    )
    assert (
        client.delete(
            P + "/loss-records/" + loss["id"], headers=farmer["headers"]
        ).status_code
        == 200
    )
    assert (
        client.delete(
            P + "/harvests/" + crop["id"], headers=farmer["headers"]
        ).status_code
        == 200
    )
    post(
        client,
        farmer,
        "/loss-records",
        {
            "farm_id": farmer["farm"],
            "loss_type": "Weather",
            "quantity": "1",
            "unit": "kg",
        },
    )
    other_farm = post(
        client,
        farmer,
        "/farms/",
        {"name": "Other", "county": "Lofa", "farm_type": "Crops"},
    )
    other_crop = post(
        client,
        farmer,
        "/harvests",
        {
            "farm_id": other_farm["id"],
            "crop_name": "Rice",
            "quantity": "5",
            "unit": "kg",
            "harvest_date": "2026-11-01",
        },
    )
    assert (
        client.post(
            P + "/loss-records",
            headers=farmer["headers"],
            json={
                "farm_id": farmer["farm"],
                "harvest_id": other_crop["id"],
                "loss_type": "Pest",
                "quantity": "1",
                "unit": "kg",
            },
        ).status_code
        == 422
    )


def test_traceability_batches(client, farmer):
    crop = harvest(client, farmer)
    key = str(uuid.uuid4())
    body = {
        "harvest_id": crop["id"],
        "origin": "Bong",
        "status": "HARVESTED",
        "recorded_at": "2026-11-01T00:00:00Z",
        "event_key": key,
    }
    first = post(client, farmer, "/traceability", body)
    assert post(client, farmer, "/traceability", body)["id"] == first["id"]
    second = post(
        client,
        farmer,
        "/traceability",
        {
            **body,
            "batch_code": first["batch_code"],
            "event_key": str(uuid.uuid4()),
            "status": "STORED",
            "recorded_at": "2026-11-02T00:00:00Z",
        },
    )
    history = client.get(
        P + "/traceability/batches/" + first["batch_code"], headers=farmer["headers"]
    ).json()
    assert [event["id"] for event in history["data"]] == [first["id"], second["id"]]
    public_url = P + "/public/batches/" + first["batch_code"]
    public_response = client.get(public_url)
    assert public_response.status_code == 200
    public_history = public_response.json()
    assert set(public_history) == {"batch_code", "crop", "county", "stages"}
    assert public_history["crop"] == crop["crop_name"]
    assert [stage["status"] for stage in public_history["stages"]] == [
        "HARVESTED",
        "STORED",
    ]
    assert all(
        set(stage) == {"status", "recorded_at"} for stage in public_history["stages"]
    )
    assert client.get(P + "/public/batches/unknown").status_code == 404
    different = harvest(client, farmer)
    assert (
        client.post(
            P + "/traceability",
            headers=farmer["headers"],
            json={
                **body,
                "harvest_id": different["id"],
                "batch_code": first["batch_code"],
                "event_key": str(uuid.uuid4()),
            },
        ).status_code
        == 422
    )


def test_reports_and_overview(client, farmer):
    expense = None
    for currency in ("LRD", "USD"):
        expense = post(
            client,
            farmer,
            "/farm-expenses",
            {
                "farm_id": farmer["farm"],
                "category": "Seeds",
                "amount": "5.25",
                "currency": currency,
                "expense_date": "2026-11-01",
            },
        )
    harvest(client, farmer)
    post(
        client,
        farmer,
        "/harvests",
        {
            "farm_id": farmer["farm"],
            "crop_name": "Rice",
            "quantity": "2",
            "unit": "bags",
            "harvest_date": "2026-11-01",
        },
    )
    body = {
        "farm_id": farmer["farm"],
        "report_type": "FARM_SUMMARY",
        "period_start": "2026-11-01",
        "period_end": "2026-11-30",
    }
    report = post(client, farmer, "/farm-reports/generate", body)
    assert len(report["report_data"]["expenses"]) == 2
    assert len(report["report_data"]["harvests"]) == 2
    assert (
        client.patch(
            P + "/farm-expenses/" + expense["id"],
            headers=farmer["headers"],
            json={"amount": "10"},
        ).status_code
        == 200
    )
    original = client.get(
        P + "/farm-reports/" + report["id"], headers=farmer["headers"]
    ).json()
    assert original["report_data"] == report["report_data"]
    newer = post(client, farmer, "/farm-reports/generate", body)
    assert newer["id"] != report["id"]
    assert newer["report_data"] != original["report_data"]
    assert (
        client.post(
            P + "/farm-reports/generate",
            headers=farmer["headers"],
            json={**body, "period_end": "2026-10-01"},
        ).status_code
        == 422
    )
    overview = client.get(
        P + "/farms/" + farmer["farm"] + "/overview", headers=farmer["headers"]
    )
    assert overview.status_code == 200, overview.text
    assert len(overview.json()["expenses"]) == 2


@pytest.mark.parametrize(
    "path",
    [
        "/items/",
        "/inventory-transactions",
        "/farm-expenses",
        "/harvests",
        "/traceability",
        "/loss-records",
        "/farm-reports",
    ],
)
def test_private_lists_require_authentication(client, path):
    assert client.get(P + path).status_code == 401


def test_decimal_withdrawals_are_consistent(client, farmer):
    resource = item(client, farmer)
    assert movement(client, farmer, resource, "IN", "0.3").status_code == 201
    assert movement(client, farmer, resource, "OUT", "0.1").status_code == 201
    last = movement(client, farmer, resource, "OUT", "0.2")
    assert last.status_code == 201, last.text
    assert Decimal(last.json()["balance_after"]) == 0


def test_same_retry_concurrently_applies_once(client, farmer):
    resource = item(client, farmer)
    key = str(uuid.uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: movement(client, farmer, resource, "IN", "5", key), range(2)
            )
        )
    assert [result.status_code for result in results] == [201, 201]
    assert results[0].json()["id"] == results[1].json()["id"]
    assert (
        Decimal(
            client.get(
                P + "/items/" + resource["id"], headers=farmer["headers"]
            ).json()["quantity"]
        )
        == 5
    )


def test_all_report_types_and_foreign_objects(client, farmer):
    crop = harvest(client, farmer)
    resource = item(client, farmer)
    movement(client, farmer, resource, "IN", "2")
    event = post(
        client,
        farmer,
        "/traceability",
        {
            "harvest_id": crop["id"],
            "origin": "Bong",
            "status": "HARVESTED",
            "event_key": str(uuid.uuid4()),
        },
    )
    reports = []
    for kind in (
        "FARM_SUMMARY",
        "INVENTORY",
        "EXPENSE",
        "HARVEST",
        "LOSS",
        "TRACEABILITY",
    ):
        reports.append(
            post(
                client,
                farmer,
                "/farm-reports/generate",
                {
                    "farm_id": farmer["farm"],
                    "report_type": kind,
                    "period_start": "2026-01-01",
                    "period_end": "2026-12-31",
                },
            )
        )
    phone = "+231" + str(uuid.uuid4().int)[:9]
    client.post(
        P + "/farmers/signup",
        json={
            "full_name": "Other",
            "phone_number": phone,
            "password": "testing-password",
            "farm": {"name": "Other", "county": "Lofa", "farm_type": "Crops"},
        },
    )
    token = client.post(
        P + "/login/access-token",
        data={"username": phone, "password": "testing-password"},
    ).json()["access_token"]
    headers = {"Authorization": "Bearer " + token}
    for path in (
        "/harvests/" + crop["id"],
        "/farm-reports/" + reports[0]["id"],
        "/traceability/" + event["id"],
        "/traceability/batches/" + event["batch_code"],
    ):
        assert client.get(P + path, headers=headers).status_code == 404
    assert (
        client.post(
            P + "/farm-reports/generate",
            headers=headers,
            json={
                "farm_id": farmer["farm"],
                "report_type": "EXPENSE",
                "period_start": "2026-01-01",
                "period_end": "2026-12-31",
            },
        ).status_code
        == 404
    )
    assert (
        client.patch(
            P + "/harvests/" + crop["id"], headers=headers, json={"quantity": "1"}
        ).status_code
        == 404
    )
    assert (
        client.delete(P + "/harvests/" + crop["id"], headers=headers).status_code == 404
    )
