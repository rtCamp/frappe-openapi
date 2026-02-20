# This script generates an OpenAPI 3.0 specification for all frappe.whitelist endpoints in a given app.
# Usage: python generate_openapi.py <app_name>
import ast
import importlib
import importlib.util
import json
import os
import re

import frappe
from frappe.utils import update_progress_bar

DEFAULT_METHODS = ["get", "post", "put", "delete"]


def find_python_files(base_path):
    return [os.path.join(root, file) for root, _, files in os.walk(base_path) for file in files if file.endswith(".py")]


def get_decorator_info(decorator_list):
    methods, allow_guest = None, False
    for deco in decorator_list:
        func = getattr(deco, "func", deco)
        name = getattr(func, "attr", getattr(func, "id", None))
        if name == "whitelist":
            # Methods
            if isinstance(deco, ast.Call):
                for kw in deco.keywords:
                    if kw.arg == "methods":
                        val = kw.value
                        if isinstance(val, ast.List):
                            methods = [elt.s.lower() for elt in val.elts if isinstance(elt, ast.Str)]
                        elif isinstance(val, ast.Str):
                            methods = [val.s.lower()]
                    elif kw.arg == "allow_guest" and isinstance(kw.value, ast.Constant):
                        allow_guest = bool(kw.value.value)
    return methods or DEFAULT_METHODS, allow_guest


def extract_returns_from_docstring(docstring):
    if not docstring:
        return None
    match = re.search(r"Returns?:\s*(.*)", docstring, re.DOTALL | re.IGNORECASE)
    if not match:
        return None
    returns_block = re.sub(r"^\s*\w+\s*:\s*", "", match.group(1))
    brace_match = re.search(r"(\{.*\}|\[.*\])", returns_block, re.DOTALL)
    if brace_match:
        block = brace_match.group(1)
        try:
            return json.loads(block.replace("'", '"'))
        except Exception:
            return block
    return returns_block.strip()


def parse_functions_from_file(file_path):
    with open(file_path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=file_path)
    return [
        {
            "name": node.name,
            "params": [arg.arg for arg in node.args.args if arg.arg not in ("self", "cls")],
            "doc": ast.get_docstring(node) or "",
            "methods": (methods := get_decorator_info(node.decorator_list))[0],
            "allow_guest": methods[1],
            "returns_example": extract_returns_from_docstring(ast.get_docstring(node) or ""),
        }
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and "whitelist"
        in {
            getattr(getattr(deco, "func", deco), "attr", getattr(getattr(deco, "func", deco), "id", None))
            for deco in node.decorator_list
        }
    ]


def generate_openapi_static(app_name):
    # Find the actual path of the app's main python package
    spec = importlib.util.find_spec(app_name)
    if not spec or not spec.submodule_search_locations:
        print(f"Could not find package for app: {app_name}")
        return {}
    app_base_path = spec.submodule_search_locations[0]
    openapi = {
        "openapi": "3.0.0",
        "info": {"title": f"{app_name} API", "version": "1.0.0"},
        "paths": {},
        "servers": [{"url": frappe.utils.get_url()}],
    }
    tags_set, needs_auth = set(), False
    for file_path in find_python_files(app_base_path):
        rel_path = os.path.relpath(file_path, app_base_path)
        module_path = rel_path.replace(os.sep, ".")[:-3]
        parent_module = ".".join(module_path.split(".")[:2]) if "." in module_path else module_path
        for func in parse_functions_from_file(file_path):
            path = f"/api/method/{app_name}.{module_path}.{func['name']}"
            tags_set.add(parent_module)
            for method in func["methods"]:
                op = {
                    "summary": func["doc"].split("\n")[0] if func["doc"] else "",
                    "parameters": [
                        {"name": p, "in": "query", "required": True, "schema": {"type": "string"}}
                        for p in func["params"]
                    ],
                    "responses": {
                        "200": {
                            "description": "Success",
                            "content": {
                                "application/json": {
                                    "example": func["returns_example"] or {"status": "success", "data": {}}
                                }
                            },
                        }
                    },
                    "tags": [parent_module],
                }
                if not func["allow_guest"]:
                    op["security"] = [{"TokenAuth": [], "bearerAuth": []}]
                    needs_auth = True
                openapi["paths"].setdefault(path, {})[method] = op
    if needs_auth:
        openapi.setdefault("components", {})["securitySchemes"] = {
            "TokenAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "Authorization",
                "description": "Enter API key and secret in `token api_key:api_secret` format.",
            },
            "bearerAuth": {
                "type": "http",
                "in": "header",
                "name": "Authorization",
                "scheme": "bearer",
                "description": "Enter access token.",
            },
        }
    openapi["tags"] = [{"name": tag} for tag in sorted(tags_set)]
    return openapi


def get_app_title_and_version(app_name):
    try:
        hooks = importlib.import_module(f"{app_name}.hooks")
        app_title = getattr(hooks, "app_title", app_name)
    except Exception:
        app_title = app_name
    try:
        version_mod = importlib.import_module(f"{app_name}")
        app_version = getattr(version_mod, "__version__", "1.0.0")
    except Exception:
        app_version = "1.0.0"
    return app_title, app_version


def generate_openapi_for_all_apps():
    # Get OpenAPI Settings to check which apps are enabled
    openapi_settings = frappe.get_single("OpenAPI Settings")

    # Get the public folder path of the current site
    public_folder = os.path.join(frappe.get_site_path(), "public", "files", "openapi")
    os.makedirs(public_folder, exist_ok=True)

    apps = frappe.get_installed_apps()

    # Filter enabled apps first to get accurate total
    enabled_apps = []
    for app_name in apps:
        app_enabled = getattr(openapi_settings, app_name, False)
        if app_enabled:
            enabled_apps.append(app_name)
        else:
            # Delete existing OpenAPI spec file if app is not enabled
            output_file = os.path.join(public_folder, f"openapi_{app_name}.json")
            if os.path.exists(output_file):
                try:
                    os.remove(output_file)
                except Exception as e:
                    frappe.log_error(f"Failed to delete OpenAPI spec for {app_name}: {e}", "OpenAPI Deletion Error")

    # Use enabled apps count for accurate progress calculation
    total = len(enabled_apps)

    for i, app_name in enumerate(enabled_apps):
        app_title, app_version = get_app_title_and_version(app_name)
        openapi = generate_openapi_static(app_name)
        openapi["info"]["title"] = app_title
        openapi["info"]["version"] = app_version
        output_file = os.path.join(public_folder, f"openapi_{app_name}.json")
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(openapi, f, indent=2)
            update_progress_bar("Generating OpenAPI spec", i, total)
        except Exception as e:
            frappe.log_error(f"Failed to write OpenAPI spec for {app_name}: {e}", "OpenAPI Generation Error")

    print()
