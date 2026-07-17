"""
E2E tests using Playwright.
Tests the full user journey through the Streamlit UI.
Requires:
  - Docker stack running (docker compose up -d)
  - Streamlit running (streamlit run streamlit_app.py)
"""
import pytest
from playwright.sync_api import Page, expect


BASE_URL = "http://localhost:8501"


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "viewport": {"width": 1280, "height": 720},
    }


def test_page_loads(page: Page):
    """Streamlit app loads successfully."""
    page.goto(BASE_URL)
    expect(page).to_have_title("Autocomplete Search Engine")
    expect(page.locator("h1")).to_contain_text("Autocomplete")


def test_search_returns_results(page: Page):
    """Typing a query shows suggestions."""
    page.goto(BASE_URL)

    # Find the search input and type
    search_input = page.locator("input[type='text']").first
    search_input.fill("py")
    search_input.press("Enter")

    # Wait for results to appear
    page.wait_for_timeout(2000)   # Streamlit rerender

    # Should see at least one result
    page_content = page.content()
    assert "python" in page_content.lower()


def test_fuzzy_toggle(page: Page):
    """Fuzzy toggle enables fuzzy search."""
    page.goto(BASE_URL)

    # Enable fuzzy toggle
    fuzzy_toggle = page.locator("label").filter(
        has_text="Fuzzy"
    )
    fuzzy_toggle.click()

    # Type a typo
    search_input = page.locator("input[type='text']").first
    search_input.fill("pythn")
    search_input.press("Enter")

    page.wait_for_timeout(2000)

    # Should find python despite typo
    page_content = page.content()
    assert "python" in page_content.lower()


def test_system_health_shown(page: Page):
    """Right column shows system health."""
    page.goto(BASE_URL)
    page_content = page.content()
    assert "health" in page_content.lower()