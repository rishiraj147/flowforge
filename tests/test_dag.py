"""DAG validator tests.

Split into two layers:

1. Pure unit tests on `validate_dag` — fast, no HTTP, no DB.
   These cover the algorithm's correctness directly.

2. One end-to-end HTTP test — proves the 422 wiring works through
   FastAPI's full request/response cycle.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from flowforge.config import Settings
from flowforge.dag import DagValidationError, validate_dag
from flowforge.main import create_app


# ===================== UNIT TESTS =====================

def test_empty_definition_is_valid():
    assert validate_dag({}) == []
    assert validate_dag({"steps": []}) == []


def test_linear_chain_returns_correct_order():
    """Welcome -> wait -> tutorial -> should come back in that exact order."""

    definition = {
        "steps": [
            {"id": "welcome", "needs": []},
            {"id": "wait", "needs": ["welcome"]},
            {"id": "tutorial", "needs": ["wait"]},
        ]
    }

    assert validate_dag(definition) == [
        "welcome",
        "wait",
        "tutorial",
    ]


def test_diamond_shape_is_valid():
    """
         A
        / \
       B   C
        \ /
         D
    """

    definition = {
        "steps": [
            {"id": "A", "needs": []},
            {"id": "B", "needs": ["A"]},
            {"id": "C", "needs": ["A"]},
            {"id": "D", "needs": ["B", "C"]},
        ]
    }

    order = validate_dag(definition)

    # A must come first, D must come last; B and C can appear in any order.
    assert order[0] == "A"
    assert order[-1] == "D"
    assert set(order[1:3]) == {"B", "C"}


def test_simple_cycle_is_rejected():
    """A -> B -> A — the simplest possible cycle."""

    definition = {
        "steps": [
            {"id": "A", "needs": ["B"]},
            {"id": "B", "needs": ["A"]},
        ]
    }

    with pytest.raises(DagValidationError) as exc_info:
        validate_dag(definition)

    assert "Cycle" in str(exc_info.value)
    assert set(exc_info.value.cycle_nodes or []) == {"A", "B"}


def test_three_node_cycle_is_rejected():
    """A -> B -> C -> A — classic 3-cycle."""

    definition = {
        "steps": [
            {"id": "A", "needs": ["C"]},
            {"id": "B", "needs": ["A"]},
            {"id": "C", "needs": ["B"]},
        ]
    }

    with pytest.raises(DagValidationError) as exc_info:
        validate_dag(definition)

    assert set(exc_info.value.cycle_nodes or []) == {
        "A",
        "B",
        "C",
    }

def test_partial_cycle_identifies_only_tangled_nodes():
    """A -> B -> C -> D -> E -> C (only C, D, E are tangled, A and B are fine)."""

    definition = {
        "steps": [
            {"id": "A", "needs": []},
            {"id": "B", "needs": ["A"]},
            {"id": "C", "needs": ["B", "E"]},
            {"id": "D", "needs": ["C"]},
            {"id": "E", "needs": ["D"]},
        ]
    }

    with pytest.raises(DagValidationError) as exc_info:
        validate_dag(definition)

    assert set(exc_info.value.cycle_nodes or []) == {"C", "D", "E"}


def test_duplicate_step_id_rejected():
    definition = {
        "steps": [
            {"id": "A", "needs": []},
            {"id": "A", "needs": []},  # dupe
        ]
    }

    with pytest.raises(DagValidationError) as exc_info:
        validate_dag(definition)

    assert "Duplicate" in str(exc_info.value)


def test_missing_step_id_rejected():
    definition = {"steps": [{"needs": []}]}

    with pytest.raises(DagValidationError) as exc_info:
        validate_dag(definition)

    assert "missing" in str(exc_info.value).lower()


def test_needs_references_unknown_step():
    definition = {
        "steps": [
            {"id": "A", "needs": []},
            {"id": "B", "needs": ["ghost"]},  # "ghost" doesn't exist
        ]
    }

    with pytest.raises(DagValidationError) as exc_info:
        validate_dag(definition)

    assert "ghost" in str(exc_info.value)
    assert exc_info.value.bad_step == "B"


# ===================== INTEGRATION TEST =====================

def _new_email() -> str:
    return f"u+{uuid.uuid4().hex[:8]}@example.com"


def test_create_workflow_with_cycle_returns_422():
    """The router must map DagValidationError → HTTP 422 with structured detail."""

    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        # Bootstrap: register + promote to developer (so workflows:write passes)
        import asyncio

        from sqlalchemy import select

        from flowforge.authz import Role
        from flowforge.config import get_settings
        from flowforge.db import create_engine, create_sessionmaker
        from flowforge.models import User

        email = _new_email()
        password = "supersecret123"

        client.post(
            "/auth/register",
            json={
                "email": email,
                "password": password,
            },
        )

        async def _promote():
            engine = create_engine(get_settings())
            Session = create_sessionmaker(engine)

            async with Session() as s:
                u = (
                    await s.execute(
                        select(User).where(User.email == email)
                    )
                ).scalar_one()

                u.role = Role.DEVELOPER.value
                await s.commit()

            await engine.dispose()

        asyncio.run(_promote())

        token = client.post(
            "/auth/login",
            json={
                "email": email,
                "password": password,
            },
        ).json()["access_token"]

        # Now try to create a workflow with a cycle
        r = client.post(
            "/workflows",
            headers={
                "Authorization": f"Bearer {token}",
            },
            json={
                "name": "bad",
                "definition": {
                    "steps": [
                        {"id": "A", "needs": ["B"]},
                        {"id": "B", "needs": ["A"]},
                    ]
                },
            },
        )

        assert r.status_code == 422

        body = r.json()

        # FastAPI wraps the detail under "detail".
        assert "Cycle" in body["detail"]["message"]
        assert set(body["detail"]["cycle_nodes"]) == {"A", "B"}