from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from homehelper.api.admin.review import _cursor, _parse_cursor, _trace_url
from tests.conftest import make_settings


def test_cursor_round_trips() -> None:
    stamp = datetime(2026, 10, 22, 9, 30, 1, 123456, tzinfo=UTC)
    assert _parse_cursor(_cursor(stamp, "conv_1")) == (stamp, "conv_1")


@pytest.mark.parametrize("cursor", ["junk", "", "W10", "eyJhIjogMX0"])
def test_malformed_cursors_are_rejected(cursor: str) -> None:
    with pytest.raises(HTTPException) as raised:
        _parse_cursor(cursor)
    assert raised.value.status_code == 422


def test_trace_links_need_the_langfuse_project() -> None:
    linked = make_settings(langfuse_base_url="https://lf.example/", langfuse_project_id="p1")
    assert _trace_url(linked, "t1") == "https://lf.example/project/p1/traces/t1"
    assert _trace_url(linked, None) is None
    assert _trace_url(make_settings(), "t1") is None
