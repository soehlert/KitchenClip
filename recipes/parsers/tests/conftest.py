import os
from unittest.mock import MagicMock, patch

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

@pytest.fixture(autouse=True)
def mock_recipe_responses(load_fixture, request):
    """
    Global interceptor for network calls.
    Automatically serves a fixture if the test is marked with @pytest.mark.recipe_fixture("filename.html")
    """
    # Look for the 'recipe_fixture' marker on the current test
    marker = request.node.get_closest_marker("recipe_fixture")
    fixture_file = marker.args[0] if marker else None

    def _mock_get(url, *args, **kwargs):
        if not fixture_file:
            # If no marker is present, we prevent accidental network calls during tests
            raise ValueError(
                f"No fixture assigned to this test, but a network call was attempted for {url}. "
                "Use @pytest.mark.recipe_fixture('filename.html') to mock this call."
            )
        
        content = load_fixture(fixture_file)
        
        # Mock HTTXP response
        mock_resp = MagicMock()
        mock_resp.text = content
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None
        return mock_resp

    # Intercept httpx (BaseParser)
    with patch("httpx.Client.get", side_effect=_mock_get):
        with patch("httpx.get", side_effect=_mock_get):
            # Intercept recipe_scrapers
            from recipe_scrapers import scrape_me
            
            def mocked_scrape_me(url, html=None, **kwargs):
                # If html is NOT provided but we have a fixture, inject it
                if html is None and fixture_file:
                    html = load_fixture(fixture_file)
                
                with patch("recipe_scrapers.scrape_me", wraps=scrape_me):
                    return scrape_me(url, html=html, **kwargs)

            with patch("recipe_scrapers.scrape_me", side_effect=mocked_scrape_me):
                yield
