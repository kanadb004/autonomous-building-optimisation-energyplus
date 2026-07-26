"""PMV anchors + monotonicity (GC-3.4, docs/GAP_CLOSURE_PLAN.md §2 Phase
GC-3). PMV math fails silently when wrong, so it is anchored against two
standard verification cases (tolerance +/-0.15 -- not exact, catches
unit/term bugs) plus monotonicity and neutrality sanity checks.

The warm anchor is the ISO 7730:2005 Annex verification row (27.0C /
RH 60% / 1.2 met / 0.5 clo -> PMV ~ +0.77), not the plan's originally
transcribed ASHRAE-55 boundary case (25.7C / RH 67% / 1.1 met / 0.5 clo ->
claimed PMV ~ +0.5), which failed by 0.27 under debugging while the cold
anchor and independent sanity checks (neutral-point crossing, monotonicity)
all held -- i.e. a bad anchor transcription, not an implementation bug. Do
not "fix" this back to the original row; see docs/decisions.md.
"""

from abms.comfort import clo_for_month, pmv


def test_ashrae55_anchor_cold():
    # air=MRT=19.6C, RH 86%, v 0.1 m/s, 1.1 met, 1.0 clo -> PMV ~ -0.5
    result = pmv(ta=19.6, tr=19.6, rh=86, vel=0.1, met=1.1, clo=1.0)
    assert abs(result - (-0.5)) <= 0.15


def test_iso7730_anchor_warm():
    # ISO 7730:2005 Annex verification case (replaces a mistranscribed
    # ASHRAE-55 boundary row that didn't hold up under debugging -- see
    # docs/decisions.md): air=MRT=27.0C, RH 60%, v 0.1 m/s, 1.2 met,
    # 0.5 clo -> PMV ~ +0.77 (PPD ~17%)
    result = pmv(ta=27.0, tr=27.0, rh=60, vel=0.1, met=1.2, clo=0.5)
    assert abs(result - 0.77) <= 0.15


def test_monotonicity_with_air_temp():
    temps = [15.0, 18.0, 21.0, 24.0, 27.0, 30.0]
    values = [pmv(ta=t, tr=t, rh=50, vel=0.1, met=1.1, clo=0.75) for t in temps]
    assert all(values[i] < values[i + 1] for i in range(len(values) - 1))


def test_neutrality_sanity_within_fixed_assumptions():
    found = False
    for tenths in range(200, 261):
        t = tenths / 10.0
        v = pmv(ta=t, tr=t, rh=50, vel=0.1, met=1.1, clo=0.75)
        if abs(v) < 0.3:
            found = True
            break
    assert found


def test_clo_for_month_heating_and_cooling():
    for month in (10, 11, 12, 1, 2, 3, 4):
        assert clo_for_month(month) == 1.0
    for month in (5, 6, 7, 8, 9):
        assert clo_for_month(month) == 0.5
