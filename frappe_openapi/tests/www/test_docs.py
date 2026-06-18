"""Tests for `frappe_openapi.www.docs`. Covers AC section 9 (get_context)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from frappe.tests import IntegrationTestCase

from frappe_openapi.www.docs import get_context

MODULE = "frappe_openapi.www.docs"


class TestGetContext(IntegrationTestCase):
    def test_populates_only_enabled_apps_from_settings(self):
        """get_context populates context.apps and context.app_titles only with apps whose settings flag is truthy."""
        settings = SimpleNamespace(app_a=True, app_b=False, app_c=True)
        context = MagicMock()
        with (
            patch(f"{MODULE}.frappe.get_single", return_value=settings),
            patch(f"{MODULE}.frappe.get_installed_apps", return_value=["app_a", "app_b", "app_c"]),
            patch(f"{MODULE}.get_app_title_and_version", side_effect=lambda app: (app.upper(), "v")),
        ):
            get_context(context)
        self.assertEqual(context.apps, ["app_a", "app_c"])
        self.assertEqual(context.app_titles, {"app_a": "APP_A", "app_c": "APP_C"})

    def test_falsy_settings_doc_falls_open_and_includes_every_app(self):
        """When the settings doc is falsy, the gate falls open and every installed app is enabled."""
        context = MagicMock()
        with (
            patch(f"{MODULE}.frappe.get_single", return_value=None),
            patch(f"{MODULE}.frappe.get_installed_apps", return_value=["app_a", "app_b"]),
            patch(f"{MODULE}.get_app_title_and_version", side_effect=lambda app: (app, "v")),
        ):
            get_context(context)
        self.assertEqual(context.apps, ["app_a", "app_b"])

    def test_default_app_is_first_enabled_app(self):
        """context.default_app is the first element of enabled_apps."""
        settings = SimpleNamespace(app_a=False, app_b=True, app_c=True)
        context = MagicMock()
        with (
            patch(f"{MODULE}.frappe.get_single", return_value=settings),
            patch(f"{MODULE}.frappe.get_installed_apps", return_value=["app_a", "app_b", "app_c"]),
            patch(f"{MODULE}.get_app_title_and_version", side_effect=lambda app: (app, "v")),
        ):
            get_context(context)
        self.assertEqual(context.default_app, "app_b")

    def test_default_app_is_empty_string_when_no_apps_enabled(self):
        """context.default_app is '' when enabled_apps is empty."""
        settings = SimpleNamespace(app_a=False, app_b=False)
        context = MagicMock()
        with (
            patch(f"{MODULE}.frappe.get_single", return_value=settings),
            patch(f"{MODULE}.frappe.get_installed_apps", return_value=["app_a", "app_b"]),
            patch(f"{MODULE}.get_app_title_and_version", side_effect=lambda app: (app, "v")),
        ):
            get_context(context)
        self.assertEqual(context.default_app, "")
        self.assertEqual(context.apps, [])
