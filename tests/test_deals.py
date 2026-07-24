from uuid import uuid4


async def register(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "buyer@example.com",
            "display_name": "Buyer Demo",
            "password": "correct-horse-battery-staple",
        },
    )
    assert response.status_code == 201, response.text


async def test_create_deal_validates_allocations_and_lists_it(client):
    await register(client)
    payload = {
        "title": "Commerce redesign",
        "description": "Design and deliver a conversion-focused commerce workspace.",
        "total_amount": 1_000_000_000,
        "milestones": [
            {
                "title": "Research and prototype",
                "description": "Validated journeys and interactive prototype",
                "amount": 400_000_000,
                "acceptance_criteria": [{"type": "file", "label": "Prototype supplied"}],
            },
            {
                "title": "Production handoff",
                "description": "Responsive final system and implementation notes",
                "amount": 600_000_000,
                "acceptance_criteria": [{"type": "checklist", "label": "Handoff complete"}],
            },
        ],
    }
    created = await client.post(
        "/api/v1/deals", json=payload, headers={"Idempotency-Key": str(uuid4())}
    )
    assert created.status_code == 201, created.text
    assert created.json()["funding_threshold_bps"] == 5000
    listed = await client.get("/api/v1/deals")
    assert listed.status_code == 200
    assert listed.json()[0]["title"] == "Commerce redesign"


async def test_rejects_inconsistent_financial_allocation(client):
    await register(client)
    response = await client.post(
        "/api/v1/deals",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "title": "Broken allocation",
            "description": "Amounts do not equal the signed total and must fail.",
            "total_amount": 100,
            "milestones": [
                {
                    "title": "Only step",
                    "description": "Invalid amount",
                    "amount": 90,
                    "acceptance_criteria": [{"type": "manual", "label": "Review"}],
                }
            ],
        },
    )
    assert response.status_code == 422
