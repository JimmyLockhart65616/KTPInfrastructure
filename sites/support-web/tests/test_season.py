"""Season calendar tests.

Anchor dates are asserted against real-world 2026/2027 calendars rather than
against the code's own arithmetic -- the whole value of deriving seasons is that
the derivation is right, so a test that just re-runs the formula proves nothing.
"""

from datetime import date

import pytest

from app import season as S


def test_holiday_anchors_match_the_real_calendar():
    assert S.super_bowl_sunday(2026) == date(2026, 2, 8)
    assert S.super_bowl_sunday(2027) == date(2027, 2, 14)
    assert S.labor_day(2026) == date(2026, 9, 7)
    assert S.labor_day(2027) == date(2027, 9, 6)
    assert S.thanksgiving(2026) == date(2026, 11, 26)
    assert S.easter(2026) == date(2026, 4, 5)
    assert S.easter(2027) == date(2027, 3, 28)
    assert S.easter(2024) == date(2024, 3, 31)
    assert S.easter(2030) == date(2030, 4, 21)


def test_every_derived_date_lands_on_a_sunday():
    for year in range(2024, 2036):
        for term in (S.SPRING, S.FALL):
            assert S.season_start(year, term).weekday() == 6
            assert S.bye_sunday(year, term).weekday() == 6


def test_s10_is_fall_2026_opening_september_13():
    s = S._build(2026, S.FALL)
    assert (s.number, s.label) == (10, "S10")
    assert s.start == date(2026, 9, 13)
    assert s.bye == date(2026, 11, 22)
    assert s.window_end == date(2026, 12, 6)


def test_season_numbering_runs_spring_then_fall():
    assert S.season_number(2026, S.SPRING) == 9
    assert S.season_number(2026, S.FALL) == 10
    assert S.season_number(2027, S.SPRING) == 11
    assert S.season_number(2027, S.FALL) == 12


def test_bye_is_excluded_and_count_is_capped():
    s = S._build(2026, S.FALL)
    days = s.match_sundays()
    assert len(days) == S.MATCH_SUNDAYS
    assert s.bye not in days
    assert days[0] == s.start and days[-1] == s.window_end


def test_super_bowl_override_moves_spring_and_nothing_else():
    fall_before = S.season_start(2028, S.FALL)
    S.SUPER_BOWL_OVERRIDES[2028] = date(2028, 2, 20)
    try:
        assert S.season_start(2028, S.SPRING) == date(2028, 2, 27)
        assert S.season_start(2028, S.FALL) == fall_before
    finally:
        S.SUPER_BOWL_OVERRIDES.pop(2028)


def test_current_season_holds_through_the_gap_between_windows():
    # Deep in the S10 off-window: S10 has ended, S11 has not begun.
    gap = date(2027, 1, 15)
    assert S.current_season(gap).number == 10
    assert S.next_season(gap).number == 11


@pytest.mark.parametrize(
    "today,expected",
    [
        (date(2026, 9, 13), 10),   # S10 opening day
        (date(2026, 12, 6), 10),   # last playable Sunday
        (date(2027, 2, 21), 11),   # S11 opening day
    ],
)
def test_current_season_boundaries(today, expected):
    assert S.current_season(today).number == expected


def test_nag_fires_only_inside_the_lead_window():
    assert S._build(2027, S.SPRING).start == date(2027, 2, 21)
    assert S.days_until_next_season(date(2027, 2, 7)) == 14
    assert S.should_nag(date(2027, 2, 7)) is True   # exactly 14 days out
    assert S.should_nag(date(2027, 2, 6)) is False  # 15 days out -- still quiet
    assert S.should_nag(date(2027, 2, 20)) is True


def test_nag_is_quiet_mid_season():
    assert S.should_nag(date(2026, 10, 4)) is False
