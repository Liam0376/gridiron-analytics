"""B8: interval factor parity between projection.py and decision.py."""

from ffanalytics.projection import (
    POS_WIDTH_FACTORS as P_FACTORS,
    INTERVAL_FACTORS_VERSION as P_VER,
)
from ffanalytics.decision import (
    POS_WIDTH_FACTORS as D_FACTORS,
    INTERVAL_FACTORS_VERSION as D_VER,
)


def test_interval_factors_match():
    assert P_FACTORS == D_FACTORS, f"projection.py {P_FACTORS} != decision.py {D_FACTORS}"


def test_interval_version_match():
    assert P_VER == D_VER, f"projection.py v{P_VER} != decision.py v{D_VER}"
