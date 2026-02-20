# Copyright (c) 2025, rtCamp and contributors
# For license information, please see license.txt

# import frappe
from frappe import enqueue
from frappe.model.document import Document

from frappe_openapi.frappe_openapi.generate_api_docs import generate_openapi_for_all_apps


class OpenAPISettings(Document):
    def on_update(self):
        enqueue(generate_openapi_for_all_apps, queue="long", enqueue_after_commit=True)
