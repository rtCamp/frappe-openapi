import frappe
from frappe_open_api.frappe_open_api.generate_api_docs import get_app_title_and_version

def create_openapi_app_fields():
    """
    Create custom fields for Open API Setting doctype for all installed apps
    excluding frappe_open_api. Also remove fields for uninstalled apps.
    """
    try:
        # Get all installed apps
        installed_apps = frappe.get_installed_apps()
        
        # Exclude frappe_open_api from the list
        apps_to_process = [app for app in installed_apps if app != "frappe_open_api"]
        
        # Get existing custom fields for Open API Setting
        existing_fields = frappe.get_all(
            "Custom Field",
            filters={
                "dt": "Open API Setting"
            },
            fields=["name", "fieldname"]
        )
        
        existing_fieldnames = [field.fieldname for field in existing_fields]
        
        # Create custom fields for apps that don't have them
        for app in apps_to_process:
            fieldname = app
            app_title, _ = get_app_title_and_version(app)
            
            if fieldname not in existing_fieldnames:
                # Create custom field
                custom_field = frappe.get_doc({
                    "doctype": "Custom Field",
                    "dt": "Open API Setting",
                    "fieldname": fieldname,
                    "fieldtype": "Check",
                    "label": app_title,
                    "insert_after": "generate_openapi_specification_for_selected_apps_section",
                    "default": "1"
                })
                
                custom_field.insert()
        
        # Remove custom fields for uninstalled apps
        for field in existing_fields:
            if field.fieldname not in apps_to_process:
                try:
                    frappe.delete_doc("Custom Field", field.name)
                except Exception as e:
                    frappe.log_error(f"Error removing custom field {field.fieldname}: {str(e)}", "OpenAPI Custom Field Removal Error")
        
    except Exception as e:
        frappe.log_error(f"Error creating OpenAPI custom fields: {str(e)}", "OpenAPI Custom Field Creation Error")