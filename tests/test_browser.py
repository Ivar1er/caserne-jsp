"""Tests dans Chromium. Activer avec RUN_BROWSER_TESTS=1 (README)."""

import json
import os
import threading
from pathlib import Path
import pytest
from werkzeug.serving import make_server

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_TESTS") != "1",
    reason="Chromium non demandé. Voir README.",
)


@pytest.fixture
def live_url(app):
    app.config["WTF_CSRF_ENABLED"] = True
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def browser():
    from playwright.sync_api import sync_playwright

    options = {"headless": True}
    if os.environ.get("BROWSER_OPTIONS_JSON"):
        config = json.loads(Path(os.environ["BROWSER_OPTIONS_JSON"]).read_text())
        options.update(executable_path=config["executablePath"], args=config["args"])
    with sync_playwright() as pw:
        browser = pw.chromium.launch(**options)
        yield browser
        browser.close()


def sign_in(page, live_url, username):
    page.goto(live_url + "/login")
    page.locator("[name=username]").fill(username)
    page.locator("[name=password]").fill("TestPassword123")
    page.locator("[name=section_id]").select_option("1")
    page.get_by_role("button", name="Se connecter", exact=True).click()
    page.wait_for_load_state("networkidle")


def assert_page(page):
    assert page.locator("input[name=csrf_token]").count() > 0
    assert page.evaluate(
        'Array.from(document.forms).every(f => f.querySelector("input[name=csrf_token]"))'
    )
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_formateur_browser_forms_upload_and_presence(browser, live_url, tmp_path):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(page, live_url, "teacher")
    assert page.locator("h2").inner_text() == "Espace Formateur"
    form = page.locator("#seances form").first
    form.locator("[name=title]").fill("Manœuvre navigateur")
    form.locator("[name=date_time]").fill("2026-11-12T14:00")
    form.locator("[name=end_time]").fill("2026-11-12T17:00")
    form.locator("[name=target_level]").select_option("JSP 1")
    form.get_by_role("button", name="Publier").click()
    assert page.get_by_role("heading", name="Manœuvre navigateur").count() == 1
    card = page.locator("#seances .card").first
    card.locator("[name=status]").select_option("present")
    card.get_by_role("button", name="Enregistrer", exact=True).first.click()
    page.locator("#cours [name=title]").fill("Cours navigateur")
    page.locator("#cours [name=file]").set_input_files(
        {
            "name": "cours.pdf",
            "mimeType": "application/pdf",
            "buffer": b"%PDF-1.4\nTest",
        }
    )
    page.locator("#cours").get_by_role("button", name="Publier").click()
    with page.expect_download() as download:
        page.get_by_role("link", name="Cours navigateur", exact=True).click()
    assert download.value.suggested_filename == "Cours_navigateur.pdf"
    for selector in ["#fiches details", "#evaluations details", "#livret details"]:
        page.locator(selector).first.locator("summary").click()
    grade = page.locator("#evaluations details").first
    grade.locator("[name=title]").fill("Contrôle navigateur")
    grade.locator("[name=score]").fill("15")
    grade.get_by_role("button", name="Ajouter").click()
    assert page.get_by_text("Contrôle navigateur").count() == 1
    assert_page(page)
    page.screenshot(path=str(tmp_path / "formateur-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert_page(page)
    page.screenshot(path=str(tmp_path / "formateur-mobile.png"), full_page=True)
    assert not errors
    page.close()


@pytest.mark.parametrize("username", ["admin", "pupil"])
def test_admin_and_jsp_browser(browser, live_url, username, tmp_path):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(page, live_url, username)
    if username == "admin":
        page.locator('[data-bs-target="#sec1"]').click()
        page.get_by_role("button", name="Ouvrir cette section").first.click()
        assert (
            page.get_by_role("heading", name="Espace Formateur", exact=True).count()
            == 1
        )
    else:
        assert (
            page.get_by_role("heading", name="Mon espace JSP", exact=True).count() == 1
        )
    assert_page(page)
    assert not errors
    page.screenshot(path=str(tmp_path / (username + "-mobile.png")), full_page=True)
    page.get_by_role("button", name="Déconnexion").click()
    assert page.url.endswith("/login")
    page.close()
