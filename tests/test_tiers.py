"""The tour-tier classifier, which reads a tier out of a free-text tournament name.

There is no tier field in the corpus — 637 distinct names across 1960-2026, with drift — so
this is derived, and it is derived in two places that must not disagree: `ingest.build`
labels every historical match with it, and `live.espn` falls back to it when the Wikipedia
calendar does not cover an event.

The ordering inside `classify_tier` is what these pin. Almost every rule below is reachable
only because an earlier one did not fire, and the checks are not disjoint: "Miami Masters"
matches both the Masters substring and the WTA-1000 city list, "Tokyo" is a 1000 for the
women and a tour stop for the men, and the team markers have to be tested before the
alphabetic floor sweeps them into the tour bucket. Get the order wrong and every answer is
still a valid tier.
"""

import pytest

from match_charting_project.analysis import tiers
from match_charting_project.analysis.tiers import (
    GRAND_SLAM,
    MASTERS_1000,
    OTHER,
    TEAM_EVENT,
    TOUR_500_250,
    TOUR_FINALS,
    classify_tier,
)

CASES = [
    # The slams, under both names the corpus uses for the French.
    ("Australian Open", "M", GRAND_SLAM),
    ("Roland Garros", "W", GRAND_SLAM),
    ("French Open", "M", GRAND_SLAM),
    ("Wimbledon", "W", GRAND_SLAM),
    ("US Open", "M", GRAND_SLAM),
    # An ATP 1000 carries the suffix; the suffix is stripped before the slam check, so a
    # name that is a slam plus "Masters" would still read as a slam — which is why the
    # 1000 test comes after it rather than before.
    ("Miami Masters", "M", MASTERS_1000),
    ("Canada Masters", "M", MASTERS_1000),
    # Older naming drops the suffix on a few, which is what the extra list is for.
    ("Monte Carlo", "M", MASTERS_1000),
    ("Shanghai", "M", MASTERS_1000),
    # Year-end finals, under each tour's several names for them.
    ("Tour Finals", "M", TOUR_FINALS),
    ("WTA Championships", "W", TOUR_FINALS),
    ("Masters Cup", "M", TOUR_FINALS),
    # Team and non-tour events, matched as substrings so a sponsor prefix cannot hide them.
    ("Davis Cup", "M", TEAM_EVENT),
    ("Billie Jean King Cup", "W", TEAM_EVENT),
    ("Olympics", "W", TEAM_EVENT),
    ("2024 Olympic Games", "M", TEAM_EVENT),
    # The floor: an ordinary tour stop.
    ("Halle", "M", TOUR_500_250),
    ("Eastbourne", "W", TOUR_500_250),
    # Nothing to read.
    ("", "M", OTHER),
    ("   ", "W", OTHER),
    ("1997", "M", OTHER),
]


@pytest.mark.parametrize("name,gender,tier", CASES)
def test_classify_tier(name, gender, tier):
    assert classify_tier(name, gender) == tier


def test_a_1000_city_is_read_per_tour():
    """The WTA's 1000s carry no suffix, so they need a name list — and that list is only
    consulted for the women. Tokyo and Charleston are 1000s on one tour and ordinary stops
    on the other, in the same years."""
    for city in ("Tokyo", "Charleston", "Wuhan"):
        assert classify_tier(city, "W") == MASTERS_1000
        assert classify_tier(city, "M") == TOUR_500_250


def test_the_gender_is_optional_and_defaults_to_the_stricter_reading():
    """`ingest.build` always has a gender; `live.espn` sometimes does not. Without one, a
    WTA-1000 city falls through to the tour bucket rather than being promoted on a guess."""
    assert classify_tier("Wuhan") == TOUR_500_250
    assert classify_tier("Monte Carlo") == MASTERS_1000     # not gender-dependent


def test_matching_ignores_case_padding_and_the_ampersand():
    assert classify_tier("  wImBlEdOn  ", "W") == GRAND_SLAM
    assert classify_tier("DAVIS CUP", "M") == TEAM_EVENT
    assert classify_tier("miami   masters", "M") == MASTERS_1000


def test_the_shared_1000_city_list_is_one_list():
    """`live.espn` uses `CITIES_1000` as its last resort when the calendar doesn't cover an
    event. It is the union of both tours' lists rather than a second copy, so a city added
    for one tour cannot go missing for the other."""
    assert tiers.CITIES_1000 >= tiers._WTA_1000
    assert tiers.CITIES_1000 >= tiers._ATP_1000_EXTRA


def test_every_tier_the_classifier_returns_has_a_place_in_the_display_order():
    """`TIER_ORDER` drives the chart categories, so a tier that can be returned and is not
    in it would be a bar with nowhere to go."""
    returned = {tier for _name, _g, tier in CASES}
    returned |= {classify_tier("Wuhan", "W"), classify_tier("Wuhan", "M")}
    assert returned <= set(tiers.TIER_ORDER)
