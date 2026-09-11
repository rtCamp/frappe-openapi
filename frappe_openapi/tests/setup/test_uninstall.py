"""Tests for `frappe_openapi.setup.uninstall`. Covers AC section 8 partial (before_uninstall)."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from frappe_openapi.setup.uninstall import before_uninstall

MODULE = "frappe_openapi.setup.uninstall"


class TestBeforeUninstall(IntegrationTestCase):
    def test_deletes_every_custom_field_with_dt_openapi_settings(self):
        """before_uninstall deletes every Custom Field row where dt='OpenAPI Settings'."""
        deleted = []
        with (
            patch(
                f"{MODULE}.frappe.get_all",
                return_value=[
                    frappe._dict({"name": "field_a", "fieldname": "app_a"}),
                    frappe._dict({"name": "field_b", "fieldname": "app_b"}),
                ],
            ),
            patch(f"{MODULE}.frappe.delete_doc", side_effect=lambda dt, name: deleted.append(name)),
        ):
            before_uninstall()
        self.assertEqual(sorted(deleted), ["field_a", "field_b"])

    def test_per_field_delete_failure_is_logged_with_uninstall_error_title(self):
        """A per-field delete failure is swallowed and logged with title 'OpenAPI Uninstall Error'."""
        with (
            patch(
                f"{MODULE}.frappe.get_all",
                return_value=[frappe._dict({"name": "bad", "fieldname": "x"})],
            ),
            patch(f"{MODULE}.frappe.delete_doc", side_effect=Exception("locked")),
            patch(f"{MODULE}.frappe.log_error") as mock_log,
        ):
            before_uninstall()
        mock_log.assert_called_once()
        self.assertEqual(mock_log.call_args.args[1], "OpenAPI Uninstall Error")

    def test_top_level_exception_is_logged_with_uninstall_error_title(self):
        """A top-level exception in before_uninstall is swallowed and logged with title 'OpenAPI Uninstall Error'."""
        with (
            patch(f"{MODULE}.frappe.get_all", side_effect=Exception("db down")),
            patch(f"{MODULE}.frappe.log_error") as mock_log,
        ):
            before_uninstall()
        mock_log.assert_called_once()
        self.assertEqual(mock_log.call_args.args[1], "OpenAPI Uninstall Error")
