"""Tests for `frappe_openapi.frappe_openapi.doctype.openapi_settings.openapi_settings`. Covers AC section 8 partial (controller on_update)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from frappe.tests import IntegrationTestCase

from frappe_openapi.frappe_openapi.doctype.openapi_settings.openapi_settings import OpenAPISettings
from frappe_openapi.frappe_openapi.generate_api_docs import generate_openapi_for_all_apps

MODULE = "frappe_openapi.frappe_openapi.doctype.openapi_settings.openapi_settings"


class TestOpenAPISettingsOnUpdate(IntegrationTestCase):
    def test_on_update_enqueues_generate_openapi_for_all_apps_on_long_queue(self):
        """OpenAPISettings.on_update calls `enqueue(generate_openapi_for_all_apps, queue='long', enqueue_after_commit=True)` and nothing else."""
        doc = MagicMock(spec=OpenAPISettings)
        with patch(f"{MODULE}.enqueue") as mock_enqueue:
            OpenAPISettings.on_update(doc)
        mock_enqueue.assert_called_once_with(
            generate_openapi_for_all_apps,
            queue="long",
            enqueue_after_commit=True,
        )
