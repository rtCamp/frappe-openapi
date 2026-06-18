"""Tests for `frappe_openapi.setup.install`. Covers AC section 8 partial (after_install)."""

from __future__ import annotations

from unittest.mock import patch

from frappe.tests import IntegrationTestCase

from frappe_openapi.setup.install import after_install

MODULE = "frappe_openapi.setup.install"


class TestAfterInstall(IntegrationTestCase):
    def test_calls_create_openapi_app_fields(self):
        """after_install calls `create_openapi_app_fields()`."""
        with patch(f"{MODULE}.create_openapi_app_fields") as mock_create:
            after_install()
        mock_create.assert_called_once()

    def test_swallows_and_logs_exception_with_after_install_error_title(self):
        """Any exception raised by `create_openapi_app_fields` is swallowed and logged with title 'OpenAPI After Install Error'."""
        with (
            patch(f"{MODULE}.create_openapi_app_fields", side_effect=Exception("boom")),
            patch(f"{MODULE}.frappe.log_error") as mock_log,
        ):
            after_install()
        mock_log.assert_called_once()
        self.assertEqual(mock_log.call_args.args[1], "OpenAPI After Install Error")
