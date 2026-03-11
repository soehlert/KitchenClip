
import os

import pytest


@pytest.fixture
def load_fixture():
    """
    Fixture to load HTML content from the fixtures directory.
    Usage: load_fixture("filename.html")
    """
    def _loader(filename):
        fixture_dir = os.path.join(os.path.dirname(__file__), "fixtures")
        fixture_path = os.path.join(fixture_dir, filename)
        with open(fixture_path, "r") as f:
            return f.read()
    return _loader
