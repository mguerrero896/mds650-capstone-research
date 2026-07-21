from __future__ import annotations

import pytest

from mds650.errors import QualityGateError
from mds650.providers.base import Page, paginate


def test_paginate_collects_pages_until_cursor_is_absent() -> None:
    pages = {
        None: Page(records=[{"id": 1}], next_cursor="c1"),
        "c1": Page(records=[{"id": 2}], next_cursor=None),
    }

    assert paginate(lambda cursor: pages[cursor]) == [{"id": 1}, {"id": 2}]


def test_paginate_fails_on_repeated_cursor() -> None:
    with pytest.raises(QualityGateError, match="PAGINATION_CURSOR_REPEATED"):
        paginate(lambda _cursor: Page(records=[], next_cursor="same"))


def test_paginate_fails_at_configured_page_limit() -> None:
    with pytest.raises(QualityGateError, match="PAGINATION_PAGE_LIMIT_EXCEEDED"):
        paginate(
            lambda cursor: Page(
                records=[],
                next_cursor=str(int(cursor or "0") + 1),
            ),
            max_pages=2,
        )
