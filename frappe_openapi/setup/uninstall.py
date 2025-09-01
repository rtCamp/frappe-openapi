import frappe


def before_uninstall():
    """
    Remove all custom fields related to OpenAPI Settings doctype before uninstalling the app
    """
    try:
        # Get all custom fields for OpenAPI Settings doctype
        custom_fields = frappe.get_all("Custom Field", filters={"dt": "OpenAPI Settings"}, fields=["name", "fieldname"])

        # Delete all custom fields
        for field in custom_fields:
            try:
                frappe.delete_doc("Custom Field", field.name)
            except Exception as e:
                frappe.log_error(f"Error removing custom field {field.fieldname}: {e!s}", "OpenAPI Uninstall Error")

    except Exception as e:
        frappe.log_error(f"Error during OpenAPI uninstall cleanup: {e!s}", "OpenAPI Uninstall Error")
