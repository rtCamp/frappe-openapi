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
                            methods = [
                                elt.value.lower()
                                for elt in val.elts
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                            ]
                        elif isinstance(val, ast.Constant) and isinstance(val.value, str):
                            methods = [val.value.lower()]
                    elif kw.arg == "allow_guest" and isinstance(kw.value, ast.Constant):
                        allow_guest = bool(kw.value.value)
    return methods or DEFAULT_METHODS, allow_guest


_PLACEHOLDER_TYPE_MAP = {
    "float": {"type": "number"},
    "number": {"type": "number"},
    "int": {"type": "integer"},
    "integer": {"type": "integer"},
    "str": {"type": "string"},
    "string": {"type": "string"},
    "bool": {"type": "boolean"},
    "boolean": {"type": "boolean"},
    "list": {"type": "array", "items": {}},
    "array": {"type": "array", "items": {}},
    "dict": {"type": "object"},
    "object": {"type": "object"},
}


def _parse_typed_block(block):
    """Parse a dict block containing <type> placeholders like ``{"key": <float>}``.

    Returns a dict of ``{key: openapi_schema}`` tagged with ``__placeholder_schema__``
    so that ``build_response_schema`` can recognise it, or ``None`` if no
    ``<type>`` patterns are found.
    """
    pairs = re.findall(r'"(\w+)"\s*:\s*<(\w+)>', block)
    if not pairs:
        return None
    schemas = {key: dict(_PLACEHOLDER_TYPE_MAP.get(typ.lower(), {"type": "string"})) for key, typ in pairs}
    return {"__placeholder_schema__": schemas}


def extract_returns_from_docstring(docstring):
    if not docstring:
        return None
    # Stop at the next top-level section header (e.g. "Raises:", "Example:")
    match = re.search(
        r"Returns?:\s*\n(.*?)(?:\n[ \t]*\n|\n[ \t]*[A-Z]\w*:|\Z)",
        docstring,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        # Fallback: grab everything after "Returns:"
        match = re.search(r"Returns?:\s*(.*)", docstring, re.DOTALL | re.IGNORECASE)
        if not match:
            return None
    returns_block = match.group(1).strip()

    def _extract_balanced(text, open_ch, close_ch):
        """Return the first balanced open_ch...close_ch substring, or None."""
        start = text.find(open_ch)
        if start == -1:
            return None
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    raw_block = _extract_balanced(returns_block, "{", "}") or _extract_balanced(returns_block, "[", "]")
    brace_match = raw_block is not None
    if brace_match:
        block = raw_block
        # Handle <type> placeholder blocks first
        if re.search(r"<\w+>", block):
            return _parse_typed_block(block)
        try:
            return json.loads(block.replace("'", '"'))
        except Exception:
            return block
    return returns_block.strip() or None


_PYTHON_TO_OPENAPI = {
    "str": "string",
    "string": "string",
    "int": "integer",
    "integer": "integer",
    "float": "number",
    "number": "number",
    "bool": "boolean",
    "boolean": "boolean",
    "bytes": "string",
    "list": "array",
    "dict": "object",
}


def get_openapi_type(annotation):
    """Convert an AST annotation node to an OpenAPI schema dict."""
    if annotation is None:
        return {"type": "string"}

    if isinstance(annotation, ast.Name):
        name = annotation.id
        if name in _PYTHON_TO_OPENAPI:
            openapi_type = _PYTHON_TO_OPENAPI[name]
            if openapi_type == "array":
                return {"type": "array", "items": {}}
            return {"type": openapi_type}
        return {"type": "string"}

    if isinstance(annotation, ast.Constant):
        if annotation.value is None:
            return {"nullable": True}
        return {"type": "string"}

    if isinstance(annotation, ast.Subscript):
        outer = annotation.value
        outer_name = None
        if isinstance(outer, ast.Name):
            outer_name = outer.id
        elif isinstance(outer, ast.Attribute):
            outer_name = outer.attr

        slice_node = annotation.slice
        # Python < 3.9 wraps slice in ast.Index
        if hasattr(ast, "Index") and isinstance(slice_node, ast.Index):
            slice_node = slice_node.value  # type: ignore[attr-defined]

        if outer_name == "Optional":
            inner = get_openapi_type(slice_node)
            inner["nullable"] = True
            return inner

        if outer_name in ("List", "list", "Sequence", "Iterable", "FrozenSet", "Set"):
            items = get_openapi_type(slice_node) if not isinstance(slice_node, ast.Tuple) else {}
            return {"type": "array", "items": items}

        if outer_name in ("Dict", "dict", "Mapping", "DefaultDict"):
            return {"type": "object"}

        if outer_name in ("Tuple", "tuple"):
            return {"type": "array", "items": {}}

        if outer_name == "Union":
            if isinstance(slice_node, ast.Tuple):
                non_none = [
                    n
                    for n in slice_node.elts
                    if not (isinstance(n, ast.Constant) and n.value is None)
                    and not (isinstance(n, ast.Name) and n.id == "None")
                ]
                has_none = len(non_none) < len(slice_node.elts)
                if len(non_none) == 1:
                    # Simple Union[X, None] -> X with nullable
                    schema = get_openapi_type(non_none[0])
                    if has_none:
                        schema["nullable"] = True
                    return schema
                elif len(non_none) > 1:
                    # Complex union -> oneOf with multiple schemas
                    one_of = [get_openapi_type(n) for n in non_none]
                    schema = {"oneOf": one_of}
                    if has_none:
                        schema["nullable"] = True
                    return schema
            return {"type": "string"}

        return {"type": "string"}

    # Python 3.10+ union syntax: X | Y | None
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        # Collect all union members by walking the BitOr chain
        union_members = []

        def collect_union_members(node):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
                collect_union_members(node.left)
                collect_union_members(node.right)
            else:
                union_members.append(node)

        collect_union_members(annotation)

        # Separate None from other types
        non_none = [
            n
            for n in union_members
            if not (isinstance(n, ast.Constant) and n.value is None)
            and not (isinstance(n, ast.Name) and n.id == "None")
        ]
        has_none = len(non_none) < len(union_members)

        if len(non_none) == 1:
            # Simple X | None -> X with nullable
            schema = get_openapi_type(non_none[0])
            if has_none:
                schema["nullable"] = True
            return schema
        elif len(non_none) > 1:
            # Complex union -> oneOf
            one_of = [get_openapi_type(n) for n in non_none]
            schema = {"oneOf": one_of}
            if has_none:
                schema["nullable"] = True
            return schema

        return {"type": "string"}

    if isinstance(annotation, ast.Attribute):
        return get_openapi_type(ast.Name(id=annotation.attr, ctx=ast.Load()))

    return {"type": "string"}


def parse_docstring_args(docstring):
    """Parse a Google-style Args section from a docstring.

    Returns a dict of {param_name: {"type_schema": {...}, "required": bool, "description": str}}.
    Handles multi-line parameter descriptions (continuation lines).
    """
    if not docstring:
        return {}
    args_match = re.search(
        r"Args?:\s*\n(.*?)(?:\n[ \t]*\n|\n[ \t]*[A-Z]\w*:|\Z)",
        docstring,
        re.DOTALL | re.IGNORECASE,
    )
    if not args_match:
        return {}
    block = args_match.group(1)
    result = {}
    param_re = re.compile(r"^(\s{2,})(\w+)\s*(?:\(([^)]+)\))?\s*:\s*(.*)", re.MULTILINE)

    lines = block.split("\n")
    current_param = None
    current_type_info = ""
    current_desc_lines: list[str] = []
    current_indent = ""

    def _flush():
        if not current_param:
            return
        description = " ".join(line.strip() for line in current_desc_lines if line.strip())
        parts = [p.strip().lower() for p in current_type_info.split(",")]
        required = "optional" not in parts
        type_name = parts[0] if parts and parts[0] else "string"
        openapi_type = _PYTHON_TO_OPENAPI.get(type_name, "string")
        schema: dict = {"type": openapi_type}
        if openapi_type == "array":
            schema["items"] = {}
        result[current_param] = {"type_schema": schema, "required": required, "description": description}

    for line in lines:
        m = param_re.match(line)
        if m:
            _flush()
            current_indent = m.group(1)
            current_param = m.group(2)
            current_type_info = m.group(3) or ""
            current_desc_lines = [m.group(4).strip()]
        elif current_param and line.strip():
            # Continuation line — must be indented deeper than the param name
            stripped = line.lstrip()
            line_indent = line[: len(line) - len(stripped)]
            if len(line_indent) > len(current_indent):
                current_desc_lines.append(stripped)

    _flush()
    return result


def build_response_schema(return_annotation, example):
    """Build an OpenAPI response schema from a return type annotation and/or docstring example.

    Frappe always wraps the return value under a ``message`` key, so the outer schema
    is ``{message: <inner>}``.  When a JSON example is available its keys are used to
    populate ``properties`` for a richer object schema.

    When the docstring Returns block used ``<type>`` placeholders (e.g. ``{"total": <float>}``)
    ``example`` will be a ``{"__placeholder_schema__": {key: schema, ...}}`` dict produced
    by :func:`_parse_typed_block`; this is converted directly to an object schema.
    """
    # ── Placeholder schema from <type> annotations in docstring ──────────
    if isinstance(example, dict) and "__placeholder_schema__" in example:
        properties = example["__placeholder_schema__"]
        inner: dict = {"type": "object", "properties": properties}
        return {"type": "object", "properties": {"message": inner}}

    # ── Normal path ───────────────────────────────────────────────────────
    if return_annotation is not None:
        inner = get_openapi_type(return_annotation)
    elif isinstance(example, list):
        inner = {"type": "array", "items": {}}
    elif isinstance(example, dict):
        inner = {"type": "object"}
    else:
        inner = {"type": "string"}

    # When we have a real dict example, derive properties from its keys/value types
    if isinstance(example, dict) and inner.get("type") == "object":
        _type_map = {
            bool: "boolean",
            int: "integer",
            float: "number",
            str: "string",
            list: "array",
            dict: "object",
        }
        properties = {}
        for key, value in example.items():
            prop_type = _type_map.get(type(value), "string")
            prop: dict = {"type": prop_type}
            if prop_type == "array":
                prop["items"] = {}
            properties[key] = prop
        if properties:
            inner = {"type": "object", "properties": properties}

    return {"type": "object", "properties": {"message": inner}}


def parse_functions_from_file(file_path):
    # nosemgrep: frappe-semgrep.rules.security.frappe-security-file-traversal
    with open(file_path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=file_path)

    result = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        deco_names = {
            getattr(getattr(deco, "func", deco), "attr", getattr(getattr(deco, "func", deco), "id", None))
            for deco in node.decorator_list
        }
        if "whitelist" not in deco_names:
            continue

        methods, allow_guest = get_decorator_info(node.decorator_list)
        docstring = ast.get_docstring(node) or ""
        docstring_args = parse_docstring_args(docstring)

        filtered_args = [arg for arg in node.args.args if arg.arg not in ("self", "cls")]
        n_required = len(filtered_args) - len(node.args.defaults)

        params = []
        for i, arg in enumerate(filtered_args):
            is_required = i < n_required
            doc_info = docstring_args.get(arg.arg, {})

            if arg.annotation is not None:
                type_schema = get_openapi_type(arg.annotation)
            elif doc_info.get("type_schema"):
                type_schema = doc_info["type_schema"]
            else:
                type_schema = {"type": "string"}

            params.append(
                {
                    "name": arg.arg,
                    "required": is_required,
                    "type_schema": type_schema,
                    "description": doc_info.get("description", ""),
                }
            )

        result.append(
            {
                "name": node.name,
                "params": params,
                "doc": docstring,
                "methods": methods,
                "allow_guest": allow_guest,
                "return_annotation": node.returns,
                "returns_example": extract_returns_from_docstring(docstring),
            }
        )

    return result


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
                response_schema = build_response_schema(func["return_annotation"], func["returns_example"])
                response_content: dict = {"schema": response_schema}
                example_val = func["returns_example"]
                if isinstance(example_val, dict) and "__placeholder_schema__" in example_val:
                    # Build a human-readable example from the placeholder types
                    _example_defaults = {
                        "number": 0.0,
                        "integer": 0,
                        "string": "",
                        "boolean": False,
                        "array": [],
                        "object": {},
                    }
                    inner_example = {
                        k: _example_defaults.get(v.get("type", "string"), "")
                        for k, v in example_val["__placeholder_schema__"].items()
                    }
                    response_content["example"] = {"message": inner_example}
                elif example_val is not None:
                    response_content["example"] = {"message": example_val}

                # For non-GET methods, send params as form-encoded request body
                if method in ("post", "put", "patch", "delete"):
                    param_objects = []
                    rb_properties: dict = {}
                    rb_required: list[str] = []
                    for p in func["params"]:
                        prop: dict = {**p["type_schema"]}
                        if p["description"]:
                            prop["description"] = p["description"]
                        rb_properties[p["name"]] = prop
                        if p["required"]:
                            rb_required.append(p["name"])
                    rb_schema: dict = {"type": "object", "properties": rb_properties}
                    if rb_required:
                        rb_schema["required"] = rb_required

                    # Only mark requestBody as required if there are required fields
                    has_required_params = bool(rb_required)
                    if rb_properties:  # Only add requestBody if there are parameters
                        request_body: dict | None = {
                            "required": has_required_params,
                            "content": {"application/x-www-form-urlencoded": {"schema": rb_schema}},
                        }
                    else:
                        request_body = None
                else:
                    # GET — use query parameters
                    param_objects = []
                    for p in func["params"]:
                        param = {
                            "name": p["name"],
                            "in": "query",
                            "required": p["required"],
                            "schema": p["type_schema"],
                        }
                        if p["description"]:
                            param["description"] = p["description"]
                        param_objects.append(param)
                    request_body = None

                doc_lines = func["doc"].splitlines() if func["doc"] else []
                summary = doc_lines[0].strip() if doc_lines else ""
                description = "\n".join(doc_lines[1:]).strip() if len(doc_lines) > 1 else ""

                op: dict = {
                    "summary": summary,
                    "parameters": param_objects,
                    "responses": {
                        "200": {
                            "description": "Success",
                            "content": {"application/json": response_content},
                        }
                    },
                    "tags": [parent_module],
                }
                if description:
                    op["description"] = description
                if request_body is not None:
                    op["requestBody"] = request_body
                if not func["allow_guest"]:
                    op["security"] = [{"TokenAuth": []}, {"bearerAuth": []}]
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
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "Enter OAuth2 bearer access token.",
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
            # Writes the generated OpenAPI spec JSON to the app's public folder;
            # the path is built from installed app names, not from user input.
            # nosemgrep: frappe-semgrep.rules.security.frappe-security-file-traversal
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(openapi, f, indent=2)
            update_progress_bar("Generating OpenAPI spec", i, total)
        except Exception as e:
            frappe.log_error(f"Failed to write OpenAPI spec for {app_name}: {e}", "OpenAPI Generation Error")

    print()
