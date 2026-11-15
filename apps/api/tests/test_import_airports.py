"""Airport importer: the stored longest runway must be an open, paved runway (closed runways, water lanes and
turf/gravel strips used to inflate it).

The synthetic rows reproduce real OurAirports records (airport and runway idents are the real ones).
"""

from __future__ import annotations

import csv
import logging

import pytest

from scripts import import_airports as importer


def _row(ident: str, length, surface: str | None, closed: str = "0") -> dict[str, str]:
    return {"airport_ident": ident, "length_ft": length, "surface": surface, "closed": closed}


@pytest.mark.parametrize(
    "surface",
    [
        "ASP", "ASPH", "ASPH-G", "ASPH-F", "ASPH-P", "ASPH-E", "ASPHALT", "Asphalt", "Ashphalt",
        "CON", "CONC", "CONC-G", "Concrete", "CONCRETE", "ASPH/ CONC", "ASPHALT/CONCRETE", "CONC-ASPH",
        "PEM", "PER", "PAVED", "BIT", "BITUMINOUS", "TARMAC", "MACADAM",
    ],
)
def test_paved_surfaces(surface):
    assert importer.is_hard_surface(surface)


@pytest.mark.parametrize(
    "surface",
    [
        "TURF", "TURF-G", "TURF-F", "GRASS", "GRASS / SOD", "GRS", "GRVL", "GRAVEL", "GVL", "DIRT", "EARTH", "GRE",
        "CLAY", "SAND", "WATER", "WAT", "SNOW", "MATS",
        "", "  ", None, "UNK", "X", "N", "G", "S",
        # mixed surfaces are not positively paved
        "ASPH-TURF", "CONC-TURF", "ASPH/GRVL", "TURF-DIRT",
    ],
)
def test_unpaved_water_and_unknown_surfaces_are_not_paved(surface):
    assert not importer.is_hard_surface(surface)


class TestLongestRunways:
    def test_closed_runway_does_not_count(self):
        # 8LA1 (Chevron heliport): a closed 10,000 ft water lane next to the real 80 ft pad
        rows = [_row("8LA1", "10000", "WATER", closed="1"), _row("8LA1", "80", "CONC")]
        assert importer.longest_runways_from_rows(rows) == {"8LA1": 80}

    def test_closed_paved_runway_does_not_count(self):
        # KDUG: two closed 7,000+ ft runways, longest open one is 6,430 ft
        rows = [
            _row("KDUG", "7158", "ASP", closed="1"),
            _row("KDUG", "4966", "ASP"),
            _row("KDUG", "7503", "ASP", closed="1"),
            _row("KDUG", "6430", "ASP"),
        ]
        assert importer.longest_runways_from_rows(rows) == {"KDUG": 6430}

    def test_water_lanes_do_not_count(self):
        # KSGJ: 12,000 ft seaplane lanes and a closed runway sit next to the real 8,001 ft runway
        rows = [
            _row("KSGJ", "2609", "ASP"),
            _row("KSGJ", "5000", "WATER"),
            _row("KSGJ", "8001", "ASP"),
            _row("KSGJ", "4001", "ASP", closed="1"),
            _row("KSGJ", "12000", "WATER"),
        ]
        assert importer.longest_runways_from_rows(rows) == {"KSGJ": 8001}

    def test_airport_with_only_turf_or_gravel_has_no_runway_length(self):
        rows = [_row("00AK", "2500", "GRVL"), _row("00AL", "2200", "TURF-G"), _row("00AA", "3000", "")]
        assert importer.longest_runways_from_rows(rows) == {}

    def test_permanent_surface_spelling_is_accepted(self):
        # KCID: both runways are listed with the surface "PER"
        rows = [_row("KCID", "8600", "PER"), _row("KCID", "6200", "PER")]
        assert importer.longest_runways_from_rows(rows) == {"KCID": 8600}

    def test_longest_paved_runway_wins_over_longer_unpaved_one(self):
        rows = [_row("KXYZ", "9000", "TURF"), _row("KXYZ", "4000", "ASPH-G"), _row("KXYZ", "5200", "CONC")]
        assert importer.longest_runways_from_rows(rows) == {"KXYZ": 5200}

    @pytest.mark.parametrize("length", ["", None, "abc", "nan", "inf"])
    def test_unusable_lengths_are_skipped(self, length):
        assert importer.longest_runways_from_rows([_row("KBAD", length, "ASP")]) == {}

    def test_rows_without_an_airport_ident_are_skipped(self):
        assert importer.longest_runways_from_rows([_row("", "5000", "ASP"), _row("  ", "5000", "ASP")]) == {}

    def test_closed_flag_variants(self):
        rows = [_row("KA", "5000", "ASP", closed="1"), _row("KB", "5000", "ASP", closed="true"), _row("KC", "5000", "ASP", closed="")]
        assert importer.longest_runways_from_rows(rows) == {"KC": 5000}


class TestLoadFromCsv:
    def _write(self, path, rows):
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "airport_ident", "length_ft", "surface", "closed"])
            writer.writeheader()
            for i, row in enumerate(rows):
                writer.writerow({"id": i, **row})

    def test_reads_a_runways_file(self, tmp_path):
        path = tmp_path / "runways.csv"
        self._write(path, [_row("KSFF", "6000", "WATER"), _row("KSFF", "4500", "CON"), _row("KSFF", "2650", "ASP")])
        assert importer.load_longest_runways(path) == {"KSFF": 4500}

    def test_missing_file_gives_an_empty_mapping_and_a_warning(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger=importer.logger.name):
            assert importer.load_longest_runways(tmp_path / "nope.csv") == {}
        assert "runways.csv not found" in caplog.text


class TestParseAirportRow:
    AIRPORT = {
        "ident": "KAUW",
        "type": "medium_airport",
        "name": "Wausau Downtown Airport",
        "icao_code": "KAUW",
        "latitude_deg": "44.9283",
        "longitude_deg": "-89.6267",
        "elevation_ft": "1201",
    }

    def test_longest_runway_comes_from_the_filtered_mapping(self):
        parsed = importer.parse_airport_row(self.AIRPORT, {"KAUW": 4950})
        assert parsed["longest_runway_ft"] == 4950

    def test_airport_without_a_paved_runway_gets_null(self):
        parsed = importer.parse_airport_row(self.AIRPORT, {})
        assert parsed["longest_runway_ft"] is None
