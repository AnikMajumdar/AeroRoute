"""Airport search must not let user input alter the PostgREST filter expression."""

from __future__ import annotations

import pytest

from app.routers import routes as routes_module
from app.services.airport_search import build_search_filter, sanitize_search_term
from tests.fakes import make_airport

FILTER_SYNTAX = set(',()"\\*%_')


@pytest.fixture(autouse=True)
def _clear_search_cache():
    routes_module._AIRPORT_SEARCH_CACHE.clear()
    yield
    routes_module._AIRPORT_SEARCH_CACHE.clear()


class TestSanitize:
    @pytest.mark.parametrize(
        "raw",
        [
            "KJFK",
            'x%",id.not.is.null,name.ilike."%',
            "a),(b",
            "name.eq.\\\"; DROP TABLE airports;--",
            "wild_%card*",
        ],
    )
    def test_filter_syntax_and_wildcards_are_removed(self, raw):
        cleaned = sanitize_search_term(raw)
        assert not (set(cleaned) & FILTER_SYNTAX)

    def test_airport_name_punctuation_is_kept(self):
        assert sanitize_search_term("  St. Louis   Lambert ") == "ST. LOUIS LAMBERT"
        assert sanitize_search_term("o'hare") == "O'HARE"
        assert sanitize_search_term("Wilkes-Barre") == "WILKES-BARRE"

    def test_length_is_capped(self):
        assert len(sanitize_search_term("A" * 500)) == 50

    def test_only_syntax_characters_yield_an_empty_term(self):
        assert sanitize_search_term('%_,()"') == ""


class TestBuildFilter:
    def test_four_quoted_conditions(self):
        expression = build_search_filter("KJFK")
        assert expression == (
            'icao_code.ilike."%KJFK%",iata_code.ilike."%KJFK%",ident.ilike."%KJFK%",name.ilike."%KJFK%"'
        )

    def test_dots_in_names_stay_inside_quotes(self):
        expression = build_search_filter("ST. LOUIS")
        assert expression.count(",") == 3
        assert expression.count('"') == 8


class TestEndpoint:
    def test_injection_payload_cannot_add_conditions(self, api):
        api.db.tables["airports"] = [make_airport("KJFK")]
        response = api.client.get("/airports/search", params={"q": 'x%",id.not.is.null,name.ilike."%'})
        assert response.status_code == 200
        (expression,) = api.db.queries[-1].or_filters
        assert expression.count(",") == 3, expression
        assert expression.count('"') == 8, expression
        assert "%" not in expression.replace('"%', "").replace('%"', "")

    def test_search_returns_matching_airports(self, api):
        api.db.tables["airports"] = [make_airport("KJFK")]
        response = api.client.get("/airports/search", params={"q": "jfk"})
        assert response.status_code == 200
        assert [a["icao_code"] for a in response.json()] == ["KJFK"]

    def test_term_with_only_syntax_characters_skips_the_database(self, api):
        response = api.client.get("/airports/search", params={"q": '%_"'})
        assert response.status_code == 200
        assert response.json() == []
        assert api.db.queries == []

    def test_repeated_search_is_served_from_the_cache(self, api):
        api.db.tables["airports"] = [make_airport("KJFK")]
        api.client.get("/airports/search", params={"q": "KJFK"})
        queries_after_first = len(api.db.queries)
        api.client.get("/airports/search", params={"q": "kjfk"})
        assert len(api.db.queries) == queries_after_first
