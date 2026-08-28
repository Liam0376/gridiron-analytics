from unittest.mock import Mock


class _FakePolarsFrame:
    def __init__(self, rows):
        self._rows = rows
    def to_dicts(self):
        return self._rows


def test_get_trending_adds():
    from ffanalytics.adapters import news
    session = Mock()
    response = Mock()
    response.json.return_value = [
        {"player_id": "4046", "count": 12500},
        {"player_id": "5849", "count": 8300},
    ]
    response.raise_for_status.return_value = None
    session.get.return_value = response

    result = news.get_trending_adds(limit=10, session=session)
    assert len(result) == 2
    assert result[0]["player_id"] == "4046"
    assert result[0]["count"] == 12500


def test_get_injury_with_practice():
    from ffanalytics.adapters import news
    fake_nfl = Mock()
    fake_nfl.load_injuries.return_value = _FakePolarsFrame([
        {
            "gsis_id": "4046",
            "full_name": "Tyreek Hill",
            "team": "MIA",
            "report_status": "Questionable",
            "practice_status": "Limited",
            "date_modified": "2026-09-10",
        },
        {
            "gsis_id": "5849",
            "full_name": "Justin Jefferson",
            "team": "MIN",
            "report_status": None,
            "practice_status": "Full",
            "date_modified": "2026-09-10",
        },
    ])

    result = news.get_injury_with_practice(2026, nfl_module=fake_nfl)
    assert len(result) == 2
    assert result[0]["practice_status"] == "Limited"
    assert result[1]["practice_status"] == "Full"
    assert result[0]["injury_status"] == "Questionable"
