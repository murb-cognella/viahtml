import functools
from unittest import mock
from unittest.mock import create_autospec

import pytest


def _autopatcher(request, target, **kwargs):
    """Patch and cleanup automatically. Wraps :py:func:`mock.patch`."""
    options = {"autospec": True}
    options.update(kwargs)
    patcher = mock.patch(target, **options)
    obj = patcher.start()
    request.addfinalizer(patcher.stop)
    return obj


@pytest.fixture
def patch(request):
    return functools.partial(_autopatcher, request)


@pytest.fixture
def os():
    with mock.patch("viahtml.app.os", autospec=True) as os:
        os.environ = {
            "VIA_H_EMBED_URL": "http://localhost:3001/hypothesis",
            "VIA_IGNORE_PREFIXES": (
                # This is one string
                "http://localhost:5000/,http://localhost:3001/,"
                "https://localhost:5000/,https://localhost:3001/"
            ),
            "VIA_DEBUG": "1",
            "VIA_BLOCKLIST_FILE": "../conf/blocklist-dev.txt",
        }
        yield os


@pytest.fixture
def start_response():
    return create_autospec(lambda status, headers: None)  # pragma: no cover