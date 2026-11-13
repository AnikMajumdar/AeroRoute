"""In-memory stand-in for the supabase-py client, faithful to the postgrest behaviours the API relies on.

Notably ``maybe_single().execute()`` returns ``None`` (not a response) when no row matches, exactly like the
installed postgrest library, and ``single()`` raises ``APIError`` unless exactly one row matches.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Callable

from postgrest.exceptions import APIError


class FakeSupabase:
    def __init__(self, tables: dict[str, list[dict[str, Any]]] | None = None, rpc: dict[str, Any] | None = None):
        self.tables: dict[str, list[dict[str, Any]]] = {name: copy.deepcopy(rows) for name, rows in (tables or {}).items()}
        self.rpc_results: dict[str, Any] = rpc or {}
        self.ops: list[tuple[str, str]] = []  # (table, operation) in execution order
        self.queries: list[FakeQuery] = []

    def table(self, name: str) -> FakeQuery:
        self.tables.setdefault(name, [])
        query = FakeQuery(self, name)
        self.queries.append(query)
        return query

    def rpc(self, name: str, params: dict[str, Any] | None = None) -> FakeRpc:
        self.ops.append((f"rpc:{name}", "rpc"))
        return FakeRpc(self.rpc_results.get(name, []), params or {})

    def writes(self) -> list[tuple[str, str]]:
        return [op for op in self.ops if op[1] in {"insert", "update", "upsert", "delete"}]

    def rows(self, table: str) -> list[dict[str, Any]]:
        return self.tables.get(table, [])


class FakeRpc:
    def __init__(self, result: Any, params: dict[str, Any]):
        self._result = result
        self._params = params

    def execute(self) -> SimpleNamespace:
        data = self._result(self._params) if callable(self._result) else self._result
        return SimpleNamespace(data=copy.deepcopy(data), count=None)


class _Not:
    def __init__(self, query: FakeQuery):
        self._query = query

    def is_(self, column: str, value: str) -> FakeQuery:
        wants_null = value == "null"
        self._query._filters.append(lambda row: (row.get(column) is None) != wants_null)
        return self._query


class FakeQuery:
    def __init__(self, db: FakeSupabase, table: str):
        self._db = db
        self._table = table
        self._op = "select"
        self._payload: Any = None
        self._filters: list[Callable[[dict[str, Any]], bool]] = []
        self._order: tuple[str, bool] | None = None
        self._limit: int | None = None
        self._mode = "list"
        self._columns = "*"
        self._count: str | None = None
        self.or_filters: list[str] = []

    # ----- builder API -------------------------------------------------------------------------------
    def select(self, columns: str = "*", count: str | None = None) -> FakeQuery:
        self._op, self._columns, self._count = "select", columns, count
        return self

    def insert(self, payload: Any, **_: Any) -> FakeQuery:
        self._op, self._payload = "insert", payload
        return self

    def update(self, payload: dict[str, Any], **_: Any) -> FakeQuery:
        self._op, self._payload = "update", payload
        return self

    def upsert(self, payload: Any, **_: Any) -> FakeQuery:
        self._op, self._payload = "upsert", payload
        return self

    def delete(self) -> FakeQuery:
        self._op = "delete"
        return self

    def eq(self, column: str, value: Any) -> FakeQuery:
        self._filters.append(lambda row: row.get(column) == value)
        return self

    def neq(self, column: str, value: Any) -> FakeQuery:
        self._filters.append(lambda row: row.get(column) != value)
        return self

    def in_(self, column: str, values: Any) -> FakeQuery:
        allowed = list(values)
        self._filters.append(lambda row: row.get(column) in allowed)
        return self

    def gte(self, column: str, value: Any) -> FakeQuery:
        self._filters.append(lambda row: row.get(column) is not None and row[column] >= value)
        return self

    def lte(self, column: str, value: Any) -> FakeQuery:
        self._filters.append(lambda row: row.get(column) is not None and row[column] <= value)
        return self

    def like(self, column: str, pattern: str) -> FakeQuery:
        prefix = pattern.rstrip("%")
        self._filters.append(lambda row: str(row.get(column) or "").startswith(prefix))
        return self

    def or_(self, expression: str) -> FakeQuery:
        self.or_filters.append(expression)  # recorded for assertions, not evaluated
        return self

    @property
    def not_(self) -> _Not:
        return _Not(self)

    def order(self, column: str, desc: bool = False) -> FakeQuery:
        self._order = (column, desc)
        return self

    def limit(self, count: int) -> FakeQuery:
        self._limit = count
        return self

    def maybe_single(self) -> FakeQuery:
        self._mode = "maybe_single"
        return self

    def single(self) -> FakeQuery:
        self._mode = "single"
        return self

    # ----- execution ---------------------------------------------------------------------------------
    def execute(self) -> SimpleNamespace | None:
        self._db.ops.append((self._table, self._op))
        rows = self._db.tables[self._table]

        if self._op in {"insert", "upsert"}:
            items = self._payload if isinstance(self._payload, list) else [self._payload]
            stored = []
            for item in items:
                row = {
                    "id": str(uuid.uuid4()),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    **copy.deepcopy(item),
                }
                rows.append(row)
                stored.append(copy.deepcopy(row))
            return SimpleNamespace(data=stored, count=None)

        matching = [row for row in rows if all(flt(row) for flt in self._filters)]

        if self._op == "update":
            for row in matching:
                row.update(copy.deepcopy(self._payload))
            return SimpleNamespace(data=copy.deepcopy(matching), count=None)

        if self._op == "delete":
            rows[:] = [row for row in rows if row not in matching]
            return SimpleNamespace(data=copy.deepcopy(matching), count=None)

        if self._order:
            column, desc = self._order
            matching.sort(key=lambda row: (row.get(column) is None, row.get(column)), reverse=desc)
        total = len(matching)
        if self._limit is not None:
            matching = matching[: self._limit]
        data = [self._project(copy.deepcopy(row)) for row in matching]

        if self._mode == "single":
            if len(data) != 1:
                raise APIError(
                    {
                        "message": "JSON object requested, multiple (or no) rows returned",
                        "code": "PGRST116",
                        "hint": None,
                        "details": f"The result contains {len(data)} rows",
                    }
                )
            return SimpleNamespace(data=data[0], count=None)
        if self._mode == "maybe_single":
            return SimpleNamespace(data=data[0], count=None) if data else None
        return SimpleNamespace(data=data, count=total if self._count else None)

    def _project(self, row: dict[str, Any]) -> dict[str, Any]:
        if "airports(*)" in self._columns and "airport_id" in row:
            airport = next((a for a in self._db.tables.get("airports", []) if a["id"] == row["airport_id"]), None)
            row["airports"] = copy.deepcopy(airport)
        return row


# ----- row factories -----------------------------------------------------------------------------------
def make_id() -> str:
    return str(uuid.uuid4())


def make_airport(icao: str = "KJFK", **overrides: Any) -> dict[str, Any]:
    row = {
        "id": make_id(),
        "ident": icao,
        "icao_code": icao,
        "iata_code": None,
        "name": f"{icao} Test Airport",
        "municipality": "Testville",
        "latitude": 40.6398,
        "longitude": -73.7789,
        "airport_type": "large_airport",
        "longest_runway_ft": 12000,
        "elevation_ft": 13,
    }
    row.update(overrides)
    return row


def make_aircraft(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": make_id(),
        "user_id": None,
        "name": "Cessna 172",
        "cruise_speed_kt": 122,
        "fuel_burn_gph": 8.5,
        "cruise_altitude_ft": 8500,
        "climb_fuel_gal": 1.5,
        "climb_time_min": 12,
        "descent_time_min": 8,
        "reserve_fuel_min": 45,
        "min_runway_ft": 2500,
        "is_preset": True,
    }
    row.update(overrides)
    return row


def seed_route(db: FakeSupabase, user_id: str = "user_A") -> dict[str, str]:
    """Insert a complete stored route (airports, aircraft, request, result, segments, diversion) for ``user_id``."""
    dep = make_airport("KJFK")
    dest = make_airport("KLAX", latitude=33.9425, longitude=-118.4081)
    aircraft = make_aircraft()
    db.tables.setdefault("airports", []).extend([dep, dest])
    db.tables.setdefault("aircraft_profiles", []).append(aircraft)
    request_id, result_id = make_id(), make_id()
    db.tables.setdefault("route_requests", []).append(
        {
            "id": request_id,
            "user_id": user_id,
            "departure_airport_id": dep["id"],
            "destination_airport_id": dest["id"],
            "aircraft_profile_id": aircraft["id"],
            "status": "completed",
            "route_preference": "balanced",
            "fuel_price_usd_per_gal": 6.5,
            "departure_time": "2026-11-14T12:00:00+00:00",
            "created_at": "2026-11-13T12:00:00+00:00",
        }
    )
    db.tables.setdefault("route_results", []).append(
        {
            "id": result_id,
            "route_request_id": request_id,
            "primary_distance_nm": 2145.0,
            "primary_ete_minutes": 702.0,
            "primary_fuel_burn_gal": 198.5,
            "primary_fuel_cost_usd": 1290.0,
            "primary_score": 82.0,
            "primary_path": [{"lat": 40.6398, "lon": -73.7789}, {"lat": 33.9425, "lon": -118.4081}],
            "warnings": [],
            "created_at": "2026-11-13T12:00:01+00:00",
        }
    )
    return {"result_id": result_id, "request_id": request_id, "dep_id": dep["id"], "dest_id": dest["id"], "aircraft_id": aircraft["id"]}
