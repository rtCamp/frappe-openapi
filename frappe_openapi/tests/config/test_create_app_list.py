"""Tests for `frappe_openapi.config.create_app_list`. Covers AC section 8 partial."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from frappe_openapi.config.create_app_list import create_openapi_app_fields

MODULE = "frappe_openapi.config.create_app_list"


class TestCreateOpenapiAppFields(IntegrationTestCase):
    def test_excludes_frappe_openapi_from_processed_apps(self):
        """create_openapi_app_fields excludes 'frappe_openapi' from the set of apps it processes (no field for itself)."""
        captured_inserts = []

        def fake_get_doc(spec):
            doc = MagicMock()
            doc.insert.side_effect = lambda: captured_inserts.append(spec)
            return doc

        with (
            patch(f"{MODULE}.frappe.get_installed_apps", return_value=["frappe", "frappe_openapi", "other_app"]),
            patch(f"{MODULE}.frappe.get_all", return_value=[]),
            patch(f"{MODULE}.get_app_title_and_version", side_effect=lambda app: (app.upper(), "1.0.0")),
            patch(f"{MODULE}.frappe.get_doc", side_effect=fake_get_doc),
        ):
            create_openapi_app_fields()
        inserted_fieldnames = [spec["fieldname"] for spec in captured_inserts]
        self.assertNotIn("frappe_openapi", inserted_fieldnames)
        self.assertIn("frappe", inserted_fieldnames)
        self.assertIn("other_app", inserted_fieldnames)

    def test_inserts_only_missing_fields(self):
        """For each installed app whose fieldname is NOT already in `Custom Field[dt='OpenAPI Settings']`, a new field is inserted."""
        captured_inserts = []

        def fake_get_doc(spec):
            doc = MagicMock()
            doc.insert.side_effect = lambda: captured_inserts.append(spec)
            return doc

        with (
            patch(f"{MODULE}.frappe.get_installed_apps", return_value=["app_a", "app_b"]),
            patch(
                f"{MODULE}.frappe.get_all",
                return_value=[frappe._dict({"name": "x", "fieldname": "app_a"})],
            ),
            patch(f"{MODULE}.get_app_title_and_version", side_effect=lambda app: (app.upper(), "1.0.0")),
            patch(f"{MODULE}.frappe.get_doc", side_effect=fake_get_doc),
        ):
            create_openapi_app_fields()
        inserted_fieldnames = [spec["fieldname"] for spec in captured_inserts]
        self.assertEqual(inserted_fieldnames, ["app_b"])

    def test_inserted_field_has_expected_shape(self):
        """Each inserted Custom Field carries fieldtype=Check, label=<title>, insert_after=<section>, default='1'."""
        captured_inserts = []

        def fake_get_doc(spec):
            doc = MagicMock()
            doc.insert.side_effect = lambda: captured_inserts.append(spec)
            return doc

        with (
            patch(f"{MODULE}.frappe.get_installed_apps", return_value=["app_a"]),
            patch(f"{MODULE}.frappe.get_all", return_value=[]),
            patch(f"{MODULE}.get_app_title_and_version", return_value=("App A Title", "1.0.0")),
            patch(f"{MODULE}.frappe.get_doc", side_effect=fake_get_doc),
        ):
            create_openapi_app_fields()
        spec = captured_inserts[0]
        self.assertEqual(spec["doctype"], "Custom Field")
        self.assertEqual(spec["dt"], "OpenAPI Settings")
        self.assertEqual(spec["fieldname"], "app_a")
        self.assertEqual(spec["fieldtype"], "Check")
        self.assertEqual(spec["label"], "App A Title")
        self.assertEqual(spec["insert_after"], "generate_openapi_specification_for_selected_apps_section")
        self.assertEqual(spec["default"], "1")

    def test_deletes_fields_for_uninstalled_apps(self):
        """Existing Custom Field rows whose fieldname is NOT in `apps_to_process` are deleted."""
        deleted_names = []

        def fake_delete(doctype, name):
            deleted_names.append(name)

        with (
            patch(f"{MODULE}.frappe.get_installed_apps", return_value=["app_a"]),
            patch(
                f"{MODULE}.frappe.get_all",
                return_value=[
                    frappe._dict({"name": "stale_field_1", "fieldname": "old_app"}),
                    frappe._dict({"name": "keep_field", "fieldname": "app_a"}),
                ],
            ),
            patch(f"{MODULE}.get_app_title_and_version", return_value=("t", "v")),
            patch(f"{MODULE}.frappe.get_doc", return_value=MagicMock()),
            patch(f"{MODULE}.frappe.delete_doc", side_effect=fake_delete),
        ):
            create_openapi_app_fields()
        self.assertEqual(deleted_names, ["stale_field_1"])

    def test_delete_failure_is_logged_with_removal_error_title(self):
        """A delete failure is swallowed and logged with title 'OpenAPI Custom Field Removal Error'."""
        with (
            patch(f"{MODULE}.frappe.get_installed_apps", return_value=[]),
            patch(
                f"{MODULE}.frappe.get_all",
                return_value=[frappe._dict({"name": "to_delete", "fieldname": "orphan"})],
            ),
            patch(f"{MODULE}.frappe.delete_doc", side_effect=Exception("can't delete")),
            patch(f"{MODULE}.frappe.log_error") as mock_log,
        ):
            create_openapi_app_fields()
        self.assertEqual(mock_log.call_args.args[1], "OpenAPI Custom Field Removal Error")

    def test_top_level_exception_is_logged_with_creation_error_title(self):
        """Any top-level exception is swallowed and logged with title 'OpenAPI Custom Field Creation Error'."""
        with (
            patch(f"{MODULE}.frappe.get_installed_apps", side_effect=Exception("boom")),
            patch(f"{MODULE}.frappe.log_error") as mock_log,
        ):
            create_openapi_app_fields()
        self.assertEqual(mock_log.call_args.args[1], "OpenAPI Custom Field Creation Error")
