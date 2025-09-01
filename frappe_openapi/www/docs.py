import frappe

from frappe_openapi.frappe_openapi.generate_api_docs import get_app_title_and_version


def get_context(context):
    # Get Open API Settings to check which apps are enabled
    openapi_settings = frappe.get_single("Open API Settings")

    # Filter apps based on Open API Settings
    enabled_apps = []
    context.app_titles = {}

    for app in frappe.get_installed_apps():
        # Check if the app is enabled in Open API Settings
        app_enabled = getattr(openapi_settings, app, False) if openapi_settings else True

        if app_enabled:
            enabled_apps.append(app)
            app_title, _ = get_app_title_and_version(app)
            context.app_titles[app] = app_title

    context.apps = enabled_apps
    context.default_app = enabled_apps[0] if enabled_apps else ""
