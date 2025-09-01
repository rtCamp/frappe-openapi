import frappe

from frappe_openapi.config.create_app_list import create_openapi_app_fields


def after_install():
    """
    Create custom fields for OpenAPI Settings doctype for all installed apps
    excluding frappe_openapi.
    """
    try:
        create_openapi_app_fields()
    except Exception as e:
        frappe.log_error(f"Error during OpenAPI after_install: {e!s}", "OpenAPI After Install Error")
