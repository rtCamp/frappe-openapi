"""Tests for `frappe_openapi.frappe_openapi.generate_api_docs`.

Covers AC sections 1-7 of SPEC_FRAPPE_OPENAPI: AST helpers, docstring parsing,
type annotation conversion, response schema building, function metadata
extraction, per-app OpenAPI generation, app metadata and bulk generation.
"""

from __future__ import annotations

import ast
import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests import IntegrationTestCase

from frappe_openapi.frappe_openapi.generate_api_docs import (
    _PLACEHOLDER_TYPE_MAP,
    _PYTHON_TO_OPENAPI,
    DEFAULT_METHODS,
    _parse_typed_block,
    build_response_schema,
    extract_returns_from_docstring,
    find_python_files,
    generate_openapi_for_all_apps,
    generate_openapi_static,
    get_app_title_and_version,
    get_decorator_info,
    get_openapi_type,
    parse_docstring_args,
    parse_functions_from_file,
)
from frappe_openapi.tests import parse_first_annotation, parse_first_function, temp_app_package

MODULE = "frappe_openapi.frappe_openapi.generate_api_docs"


# ---------------------------------------------------------------------------
# Section 1: AST helpers and type-map constants
# ---------------------------------------------------------------------------


class TestConstants(IntegrationTestCase):
    def test_default_methods_value(self):
        """DEFAULT_METHODS is the lowercased HTTP method list `["get", "post", "put", "delete"]`."""
        self.assertEqual(DEFAULT_METHODS, ["get", "post", "put", "delete"])

    def test_placeholder_type_map(self):
        """_PLACEHOLDER_TYPE_MAP maps placeholder type names to their OpenAPI schema fragments."""
        self.assertEqual(_PLACEHOLDER_TYPE_MAP["float"], {"type": "number"})
        self.assertEqual(_PLACEHOLDER_TYPE_MAP["number"], {"type": "number"})
        self.assertEqual(_PLACEHOLDER_TYPE_MAP["int"], {"type": "integer"})
        self.assertEqual(_PLACEHOLDER_TYPE_MAP["integer"], {"type": "integer"})
        self.assertEqual(_PLACEHOLDER_TYPE_MAP["str"], {"type": "string"})
        self.assertEqual(_PLACEHOLDER_TYPE_MAP["string"], {"type": "string"})
        self.assertEqual(_PLACEHOLDER_TYPE_MAP["bool"], {"type": "boolean"})
        self.assertEqual(_PLACEHOLDER_TYPE_MAP["boolean"], {"type": "boolean"})
        self.assertEqual(_PLACEHOLDER_TYPE_MAP["list"], {"type": "array", "items": {}})
        self.assertEqual(_PLACEHOLDER_TYPE_MAP["array"], {"type": "array", "items": {}})
        self.assertEqual(_PLACEHOLDER_TYPE_MAP["dict"], {"type": "object"})
        self.assertEqual(_PLACEHOLDER_TYPE_MAP["object"], {"type": "object"})

    def test_python_to_openapi_map(self):
        """_PYTHON_TO_OPENAPI maps Python annotation names to OpenAPI type strings."""
        self.assertEqual(
            _PYTHON_TO_OPENAPI,
            {
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
            },
        )


class TestFindPythonFiles(IntegrationTestCase):
    def test_returns_only_python_files_recursively(self):
        """find_python_files returns every `.py` file under base_path (recursive) and excludes non-`.py` files."""
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "a.py"), "w") as f:
                f.write("")
            with open(os.path.join(tmp, "b.txt"), "w") as f:
                f.write("")
            subdir = os.path.join(tmp, "sub")
            os.makedirs(subdir)
            with open(os.path.join(subdir, "c.py"), "w") as f:
                f.write("")
            result = sorted(find_python_files(tmp))
            self.assertEqual(
                result,
                sorted([os.path.join(tmp, "a.py"), os.path.join(subdir, "c.py")]),
            )


class TestGetDecoratorInfo(IntegrationTestCase):
    def test_empty_list_returns_default_methods_and_false(self):
        """get_decorator_info([]) returns (DEFAULT_METHODS, False)."""
        methods, allow_guest = get_decorator_info([])
        self.assertEqual(methods, ["get", "post", "put", "delete"])
        self.assertFalse(allow_guest)

    def test_methods_list_with_two_strings(self):
        """get_decorator_info parses `methods=["GET", "POST"]` to `["get", "post"]`."""
        fn = parse_first_function('@frappe.whitelist(methods=["GET", "POST"])\ndef f():\n    pass\n')
        methods, allow_guest = get_decorator_info(fn.decorator_list)
        self.assertEqual(methods, ["get", "post"])
        self.assertFalse(allow_guest)

    def test_methods_single_string(self):
        """get_decorator_info parses `methods="POST"` (single string) to `["post"]`."""
        fn = parse_first_function('@frappe.whitelist(methods="POST")\ndef f():\n    pass\n')
        methods, _allow_guest = get_decorator_info(fn.decorator_list)
        self.assertEqual(methods, ["post"])

    def test_allow_guest_true(self):
        """get_decorator_info parses `allow_guest=True` to True."""
        fn = parse_first_function("@frappe.whitelist(allow_guest=True)\ndef f():\n    pass\n")
        methods, allow_guest = get_decorator_info(fn.decorator_list)
        self.assertEqual(methods, ["get", "post", "put", "delete"])
        self.assertTrue(allow_guest)

    def test_allow_guest_with_methods(self):
        """get_decorator_info combines `allow_guest=True` with `methods=["POST"]`."""
        fn = parse_first_function('@frappe.whitelist(allow_guest=True, methods=["POST"])\ndef f():\n    pass\n')
        methods, allow_guest = get_decorator_info(fn.decorator_list)
        self.assertEqual(methods, ["post"])
        self.assertTrue(allow_guest)


# ---------------------------------------------------------------------------
# Section 2: Docstring parsing
# ---------------------------------------------------------------------------


class TestParseTypedBlock(IntegrationTestCase):
    def test_returns_none_when_no_placeholders(self):
        """_parse_typed_block returns None when no `"key": <type>` pairs are present."""
        self.assertIsNone(_parse_typed_block('{"a": 1, "b": "x"}'))

    def test_parses_typed_placeholders(self):
        """_parse_typed_block parses a `{"key": <type>}` block into placeholder schemas."""
        result = _parse_typed_block('{"total": <float>, "items": <list>}')
        self.assertEqual(
            result,
            {
                "__placeholder_schema__": {
                    "total": {"type": "number"},
                    "items": {"type": "array", "items": {}},
                }
            },
        )

    def test_unknown_placeholder_type_falls_back_to_string(self):
        """_parse_typed_block uses `{"type": "string"}` for unknown placeholder types."""
        result = _parse_typed_block('{"data": <weirdtype>}')
        self.assertEqual(result, {"__placeholder_schema__": {"data": {"type": "string"}}})


class TestExtractReturnsFromDocstring(IntegrationTestCase):
    def test_returns_none_for_empty_and_none(self):
        """extract_returns_from_docstring returns None for None/empty input."""
        self.assertIsNone(extract_returns_from_docstring(None))
        self.assertIsNone(extract_returns_from_docstring(""))

    def test_matches_returns_and_return_case_insensitive(self):
        """extract_returns_from_docstring matches both `Returns:` and `Return:` (case-insensitive)."""
        self.assertEqual(
            extract_returns_from_docstring('Returns:\n    {"status": "ok"}\n'),
            {"status": "ok"},
        )
        self.assertEqual(
            extract_returns_from_docstring('return:\n    {"status": "ok"}\n'),
            {"status": "ok"},
        )

    def test_parses_balanced_dict_as_json(self):
        """extract_returns_from_docstring parses balanced `{...}` content as JSON (single-quotes normalised)."""
        self.assertEqual(
            extract_returns_from_docstring("Returns:\n    {'status': 'ok'}\n"),
            {"status": "ok"},
        )

    def test_dispatches_to_typed_block_for_placeholder_dicts(self):
        """extract_returns_from_docstring recognises `<type>` placeholder blocks."""
        result = extract_returns_from_docstring('Returns:\n    {"total": <float>}\n')
        self.assertEqual(result, {"__placeholder_schema__": {"total": {"type": "number"}}})

    def test_returns_raw_block_when_json_parse_fails(self):
        """extract_returns_from_docstring returns the raw block string when JSON parsing fails."""
        result = extract_returns_from_docstring("Returns:\n    {invalid json content}\n")
        self.assertEqual(result, "{invalid json content}")

    def test_stops_at_next_section_header(self):
        """extract_returns_from_docstring stops at the next top-level header (e.g. `Raises:`) rather than consuming the rest of the docstring."""
        docstring = 'Some summary.\n\nReturns:\n    {"ok": true}\n\nRaises:\n    ValueError: if bad input\n'
        result = extract_returns_from_docstring(docstring)
        self.assertEqual(result, {"ok": True})


class TestParseDocstringArgs(IntegrationTestCase):
    def test_returns_empty_dict_for_empty_input(self):
        """parse_docstring_args returns {} for None/empty input."""
        self.assertEqual(parse_docstring_args(None), {})
        self.assertEqual(parse_docstring_args(""), {})

    def test_returns_empty_dict_when_no_args_section(self):
        """parse_docstring_args returns {} when there is no `Args:` section."""
        self.assertEqual(parse_docstring_args("Some summary without args section."), {})

    def test_parses_single_param_with_optional_int(self):
        """parse_docstring_args parses `name (int, optional): desc` into a schema with `required=False`."""
        docstring = "Args:\n    age (int, optional): The user's age.\n"
        result = parse_docstring_args(docstring)
        self.assertEqual(
            result,
            {
                "age": {
                    "type_schema": {"type": "integer"},
                    "required": False,
                    "description": "The user's age.",
                }
            },
        )

    def test_marks_param_required_without_optional_keyword(self):
        """parse_docstring_args marks a parameter without `optional` in the type info as required."""
        docstring = "Args:\n    title (str): The title.\n"
        result = parse_docstring_args(docstring)
        self.assertTrue(result["title"]["required"])

    def test_joins_multiline_continuation_descriptions(self):
        """parse_docstring_args joins multi-line continuation descriptions with a single space."""
        docstring = "Args:\n    title (str): First line.\n        Second line of description.\n"
        result = parse_docstring_args(docstring)
        self.assertEqual(result["title"]["description"], "First line. Second line of description.")

    def test_list_type_info_maps_to_array_with_items(self):
        """parse_docstring_args maps `list` type info to `{"type": "array", "items": {}}`."""
        docstring = "Args:\n    tags (list, optional): List of tags.\n"
        result = parse_docstring_args(docstring)
        self.assertEqual(result["tags"]["type_schema"], {"type": "array", "items": {}})


# ---------------------------------------------------------------------------
# Section 3: Type annotation -> OpenAPI schema
# ---------------------------------------------------------------------------


class TestGetOpenApiType(IntegrationTestCase):
    def test_none_input_returns_string_schema(self):
        """get_openapi_type(None) returns `{"type": "string"}`."""
        self.assertEqual(get_openapi_type(None), {"type": "string"})

    def test_ast_name_known_types(self):
        """get_openapi_type on `ast.Name("int")` returns `{"type": "integer"}` and unknown names fall back to string."""
        self.assertEqual(get_openapi_type(parse_first_annotation("x: int = 0")), {"type": "integer"})
        self.assertEqual(get_openapi_type(parse_first_annotation("x: str = 0")), {"type": "string"})
        self.assertEqual(get_openapi_type(parse_first_annotation("x: list = 0")), {"type": "array", "items": {}})
        self.assertEqual(get_openapi_type(parse_first_annotation("x: SomeWeirdType = 0")), {"type": "string"})

    def test_ast_constant_none_returns_nullable_only(self):
        """get_openapi_type on `ast.Constant(None)` returns `{"nullable": True}` (no `type` key)."""
        node = ast.Constant(value=None)
        self.assertEqual(get_openapi_type(node), {"nullable": True})

    def test_optional_int(self):
        """get_openapi_type on `Optional[int]` returns `{"type": "integer", "nullable": True}`."""
        node = parse_first_annotation("x: Optional[int] = 0")
        self.assertEqual(get_openapi_type(node), {"type": "integer", "nullable": True})

    def test_list_of_int(self):
        """get_openapi_type on `List[int]` returns `{"type": "array", "items": {"type": "integer"}}`."""
        node = parse_first_annotation("x: List[int] = 0")
        self.assertEqual(get_openapi_type(node), {"type": "array", "items": {"type": "integer"}})

    def test_dict_of_str_int(self):
        """get_openapi_type on `Dict[str, int]` returns `{"type": "object"}`."""
        node = parse_first_annotation("x: Dict[str, int] = 0")
        self.assertEqual(get_openapi_type(node), {"type": "object"})

    def test_tuple_int_str(self):
        """get_openapi_type on `Tuple[int, str]` returns `{"type": "array", "items": {}}`."""
        node = parse_first_annotation("x: Tuple[int, str] = 0")
        self.assertEqual(get_openapi_type(node), {"type": "array", "items": {}})

    def test_union_int_none(self):
        """get_openapi_type on `Union[int, None]` returns `{"type": "integer", "nullable": True}`."""
        node = parse_first_annotation("x: Union[int, None] = 0")
        self.assertEqual(get_openapi_type(node), {"type": "integer", "nullable": True})

    def test_union_int_str(self):
        """get_openapi_type on `Union[int, str]` returns `{"oneOf": [{"type": "integer"}, {"type": "string"}]}`."""
        node = parse_first_annotation("x: Union[int, str] = 0")
        self.assertEqual(get_openapi_type(node), {"oneOf": [{"type": "integer"}, {"type": "string"}]})

    def test_union_int_str_none(self):
        """get_openapi_type on `Union[int, str, None]` returns oneOf + nullable."""
        node = parse_first_annotation("x: Union[int, str, None] = 0")
        self.assertEqual(
            get_openapi_type(node),
            {"oneOf": [{"type": "integer"}, {"type": "string"}], "nullable": True},
        )

    def test_pep604_int_or_none(self):
        """get_openapi_type on Python 3.10+ `int | None` returns `{"type": "integer", "nullable": True}`."""
        node = parse_first_annotation("x: int | None = 0")
        self.assertEqual(get_openapi_type(node), {"type": "integer", "nullable": True})

    def test_pep604_int_or_str_or_none(self):
        """get_openapi_type on Python 3.10+ chained `int | str | None` returns oneOf + nullable."""
        node = parse_first_annotation("x: int | str | None = 0")
        self.assertEqual(
            get_openapi_type(node),
            {"oneOf": [{"type": "integer"}, {"type": "string"}], "nullable": True},
        )

    def test_ast_attribute_recurses_via_synthetic_name(self):
        """get_openapi_type on `typing.Optional`-style `ast.Attribute` recurses via a synthetic `ast.Name`."""
        node = parse_first_annotation("x: typing.int = 0")
        # `typing.int` is an Attribute; the helper recurses with `ast.Name("int")` -> integer
        self.assertEqual(get_openapi_type(node), {"type": "integer"})


# ---------------------------------------------------------------------------
# Section 4: Response schema builder
# ---------------------------------------------------------------------------


class TestBuildResponseSchema(IntegrationTestCase):
    def test_default_string_message_for_none_inputs(self):
        """build_response_schema(None, None) returns `{"message": {"type": "string"}}` under an object wrapper."""
        self.assertEqual(
            build_response_schema(None, None),
            {"type": "object", "properties": {"message": {"type": "string"}}},
        )

    def test_list_example_produces_array_message(self):
        """build_response_schema(None, []) returns `{"message": {"type": "array", "items": {}}}` under an object wrapper."""
        self.assertEqual(
            build_response_schema(None, []),
            {"type": "object", "properties": {"message": {"type": "array", "items": {}}}},
        )

    def test_empty_dict_example_produces_object_message(self):
        """build_response_schema(None, {}) returns `{"message": {"type": "object"}}` under an object wrapper."""
        self.assertEqual(
            build_response_schema(None, {}),
            {"type": "object", "properties": {"message": {"type": "object"}}},
        )

    def test_dict_example_derives_properties_from_keys(self):
        """build_response_schema derives `properties` from a non-empty example dict, mapping each value's Python type to an OpenAPI type."""
        example = {"flag": True, "count": 5, "ratio": 1.5, "name": "x", "list": [], "obj": {}}
        result = build_response_schema(None, example)
        inner = result["properties"]["message"]
        self.assertEqual(inner["type"], "object")
        self.assertEqual(inner["properties"]["flag"], {"type": "boolean"})
        self.assertEqual(inner["properties"]["count"], {"type": "integer"})
        self.assertEqual(inner["properties"]["ratio"], {"type": "number"})
        self.assertEqual(inner["properties"]["name"], {"type": "string"})
        self.assertEqual(inner["properties"]["list"], {"type": "array", "items": {}})
        self.assertEqual(inner["properties"]["obj"], {"type": "object"})

    def test_int_annotation_no_example_yields_integer_message(self):
        """build_response_schema with `int` annotation and no example yields `{"message": {"type": "integer"}}`."""
        node = parse_first_annotation("x: int = 0")
        self.assertEqual(
            build_response_schema(node, None),
            {"type": "object", "properties": {"message": {"type": "integer"}}},
        )

    def test_placeholder_schema_example(self):
        """build_response_schema honours a `__placeholder_schema__` example and wraps it under `message`."""
        example = {"__placeholder_schema__": {"total": {"type": "number"}}}
        self.assertEqual(
            build_response_schema(None, example),
            {
                "type": "object",
                "properties": {"message": {"type": "object", "properties": {"total": {"type": "number"}}}},
            },
        )


# ---------------------------------------------------------------------------
# Section 5: Function metadata extraction
# ---------------------------------------------------------------------------


class TestParseFunctionsFromFile(IntegrationTestCase):
    def test_skips_non_whitelisted_functions(self):
        """parse_functions_from_file skips functions not decorated with `whitelist`."""
        with tempfile.TemporaryDirectory() as tmp:
            file_path = os.path.join(tmp, "m.py")
            with open(file_path, "w") as f:
                f.write(
                    "import frappe\n"
                    "@frappe.whitelist()\n"
                    "def whitelisted():\n    pass\n"
                    "def not_whitelisted():\n    pass\n"
                )
            funcs = parse_functions_from_file(file_path)
            self.assertEqual([f["name"] for f in funcs], ["whitelisted"])

    def test_returns_expected_fields_per_function(self):
        """parse_functions_from_file returns a dict per whitelisted function with name/params/doc/methods/allow_guest/return_annotation/returns_example."""
        with tempfile.TemporaryDirectory() as tmp:
            file_path = os.path.join(tmp, "m.py")
            with open(file_path, "w") as f:
                f.write(
                    "import frappe\n"
                    '@frappe.whitelist(methods=["POST"], allow_guest=True)\n'
                    "def f(name: str) -> dict:\n"
                    '    """summary line.\n\nReturns:\n    {"ok": true}\n"""\n'
                    "    pass\n"
                )
            (func,) = parse_functions_from_file(file_path)
            self.assertEqual(func["name"], "f")
            self.assertEqual(func["methods"], ["post"])
            self.assertTrue(func["allow_guest"])
            self.assertEqual(func["returns_example"], {"ok": True})
            self.assertEqual(len(func["params"]), 1)
            self.assertIn("summary line", func["doc"])
            self.assertIsNotNone(func["return_annotation"])

    def test_excludes_self_and_cls_from_params(self):
        """parse_functions_from_file excludes `self` and `cls` from `params`."""
        with tempfile.TemporaryDirectory() as tmp:
            file_path = os.path.join(tmp, "m.py")
            with open(file_path, "w") as f:
                f.write(
                    "import frappe\n"
                    "class C:\n"
                    "    @frappe.whitelist()\n"
                    "    def method(self, x: int):\n        pass\n"
                    "    @frappe.whitelist()\n"
                    "    @classmethod\n"
                    "    def cmethod(cls, y: int):\n        pass\n"
                )
            funcs = parse_functions_from_file(file_path)
            for func in funcs:
                names = [p["name"] for p in func["params"]]
                self.assertNotIn("self", names)
                self.assertNotIn("cls", names)

    def test_required_flag_based_on_defaults(self):
        """parse_functions_from_file computes `required = i < n_required` based on `len(args) - len(defaults)`."""
        with tempfile.TemporaryDirectory() as tmp:
            file_path = os.path.join(tmp, "m.py")
            with open(file_path, "w") as f:
                f.write(
                    "import frappe\n@frappe.whitelist()\ndef f(a: int, b: int, c: int = 1, d: int = 2):\n    pass\n"
                )
            (func,) = parse_functions_from_file(file_path)
            required_flags = {p["name"]: p["required"] for p in func["params"]}
            self.assertTrue(required_flags["a"])
            self.assertTrue(required_flags["b"])
            self.assertFalse(required_flags["c"])
            self.assertFalse(required_flags["d"])

    def test_type_schema_priority_annotation_then_doc_then_default(self):
        """parse_functions_from_file resolves type_schema: annotation if present, else `Args:` block, else `{"type": "string"}`."""
        with tempfile.TemporaryDirectory() as tmp:
            file_path = os.path.join(tmp, "m.py")
            with open(file_path, "w") as f:
                f.write(
                    "import frappe\n"
                    "@frappe.whitelist()\n"
                    "def f(annotated: int, from_doc, no_info):\n"
                    '    """Args:\n        from_doc (str): from docstring.\n    """\n'
                    "    pass\n"
                )
            (func,) = parse_functions_from_file(file_path)
            params = {p["name"]: p["type_schema"] for p in func["params"]}
            self.assertEqual(params["annotated"], {"type": "integer"})
            self.assertEqual(params["from_doc"], {"type": "string"})
            self.assertEqual(params["no_info"], {"type": "string"})


# ---------------------------------------------------------------------------
# Section 6: Per-app OpenAPI generation
# ---------------------------------------------------------------------------


class TestGenerateOpenapiStatic(IntegrationTestCase):
    def test_returns_empty_dict_when_package_not_found(self):
        """generate_openapi_static returns {} when `importlib.util.find_spec` returns None."""
        with patch(f"{MODULE}.importlib.util.find_spec", return_value=None):
            self.assertEqual(generate_openapi_static("does_not_exist_app"), {})

    def test_seed_dict_shape(self):
        """The seed dict has openapi='3.0.0', info, paths={}, servers."""
        with temp_app_package("myapp", {"__init__.py": ""}) as package_dir:
            spec = SimpleNamespace(submodule_search_locations=[package_dir])
            with (
                patch(f"{MODULE}.importlib.util.find_spec", return_value=spec),
                patch(f"{MODULE}.frappe.utils.get_url", return_value="https://site.example"),
            ):
                result = generate_openapi_static("myapp")
        self.assertEqual(result["openapi"], "3.0.0")
        self.assertEqual(result["info"], {"title": "myapp API", "version": "1.0.0"})
        self.assertEqual(result["paths"], {})
        self.assertEqual(result["servers"], [{"url": "https://site.example"}])

    def test_path_and_tags_for_whitelisted_function(self):
        """Each whitelisted function becomes one entry per HTTP method at `/api/method/{app}.{module_path}.{func_name}` with tags=[parent_module]."""
        with temp_app_package(
            "myapp",
            {
                "__init__.py": "",
                "api/__init__.py": "",
                "api/endpoints.py": ("import frappe\n@frappe.whitelist()\ndef hello():\n    pass\n"),
            },
        ) as package_dir:
            spec = SimpleNamespace(submodule_search_locations=[package_dir])
            with (
                patch(f"{MODULE}.importlib.util.find_spec", return_value=spec),
                patch(f"{MODULE}.frappe.utils.get_url", return_value="x"),
            ):
                result = generate_openapi_static("myapp")
        self.assertIn("/api/method/myapp.api.endpoints.hello", result["paths"])
        operation = result["paths"]["/api/method/myapp.api.endpoints.hello"]["get"]
        self.assertEqual(operation["tags"], ["api.endpoints"])

    def test_summary_and_description_split(self):
        """summary is the first docstring line; description is the rest (only set when non-empty)."""
        with temp_app_package(
            "myapp",
            {
                "__init__.py": "",
                "m.py": (
                    "import frappe\n"
                    "@frappe.whitelist()\n"
                    "def f():\n"
                    '    """First summary line.\n\nLonger description here.\n"""\n'
                    "    pass\n"
                ),
            },
        ) as package_dir:
            spec = SimpleNamespace(submodule_search_locations=[package_dir])
            with (
                patch(f"{MODULE}.importlib.util.find_spec", return_value=spec),
                patch(f"{MODULE}.frappe.utils.get_url", return_value="x"),
            ):
                result = generate_openapi_static("myapp")
        operation = result["paths"]["/api/method/myapp.m.f"]["get"]
        self.assertEqual(operation["summary"], "First summary line.")
        self.assertIn("Longer description here.", operation["description"])

    def test_get_method_emits_query_parameters(self):
        """GET operations carry query parameters built from the function's `params`."""
        with temp_app_package(
            "myapp",
            {
                "__init__.py": "",
                "m.py": ("import frappe\n@frappe.whitelist()\ndef f(name: str, count: int = 10):\n    pass\n"),
            },
        ) as package_dir:
            spec = SimpleNamespace(submodule_search_locations=[package_dir])
            with (
                patch(f"{MODULE}.importlib.util.find_spec", return_value=spec),
                patch(f"{MODULE}.frappe.utils.get_url", return_value="x"),
            ):
                result = generate_openapi_static("myapp")
        operation = result["paths"]["/api/method/myapp.m.f"]["get"]
        params_by_name = {p["name"]: p for p in operation["parameters"]}
        self.assertEqual(params_by_name["name"]["in"], "query")
        self.assertEqual(params_by_name["name"]["required"], True)
        self.assertEqual(params_by_name["name"]["schema"], {"type": "string"})
        self.assertEqual(params_by_name["count"]["required"], False)
        self.assertEqual(params_by_name["count"]["schema"], {"type": "integer"})

    def test_post_method_emits_form_encoded_request_body(self):
        """POST operations carry an `application/x-www-form-urlencoded` request body whose schema lists all params as properties."""
        with temp_app_package(
            "myapp",
            {
                "__init__.py": "",
                "m.py": (
                    'import frappe\n@frappe.whitelist(methods=["POST"])\ndef f(title: str, count: int = 0):\n    pass\n'
                ),
            },
        ) as package_dir:
            spec = SimpleNamespace(submodule_search_locations=[package_dir])
            with (
                patch(f"{MODULE}.importlib.util.find_spec", return_value=spec),
                patch(f"{MODULE}.frappe.utils.get_url", return_value="x"),
            ):
                result = generate_openapi_static("myapp")
        operation = result["paths"]["/api/method/myapp.m.f"]["post"]
        body = operation["requestBody"]
        self.assertIn("application/x-www-form-urlencoded", body["content"])
        schema = body["content"]["application/x-www-form-urlencoded"]["schema"]
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["properties"]["title"], {"type": "string"})
        self.assertEqual(schema["properties"]["count"], {"type": "integer"})
        self.assertEqual(schema["required"], ["title"])

    def test_post_zero_params_omits_request_body(self):
        """A POST operation with zero parameters has no `requestBody` key."""
        with temp_app_package(
            "myapp",
            {
                "__init__.py": "",
                "m.py": ('import frappe\n@frappe.whitelist(methods=["POST"])\ndef f():\n    pass\n'),
            },
        ) as package_dir:
            spec = SimpleNamespace(submodule_search_locations=[package_dir])
            with (
                patch(f"{MODULE}.importlib.util.find_spec", return_value=spec),
                patch(f"{MODULE}.frappe.utils.get_url", return_value="x"),
            ):
                result = generate_openapi_static("myapp")
        operation = result["paths"]["/api/method/myapp.m.f"]["post"]
        self.assertNotIn("requestBody", operation)

    def test_post_all_optional_request_body_required_false(self):
        """A POST operation whose params are all optional has `requestBody.required=False`."""
        with temp_app_package(
            "myapp",
            {
                "__init__.py": "",
                "m.py": (
                    'import frappe\n@frappe.whitelist(methods=["POST"])\ndef f(a: int = 1, b: int = 2):\n    pass\n'
                ),
            },
        ) as package_dir:
            spec = SimpleNamespace(submodule_search_locations=[package_dir])
            with (
                patch(f"{MODULE}.importlib.util.find_spec", return_value=spec),
                patch(f"{MODULE}.frappe.utils.get_url", return_value="x"),
            ):
                result = generate_openapi_static("myapp")
        body = result["paths"]["/api/method/myapp.m.f"]["post"]["requestBody"]
        self.assertFalse(body["required"])

    def test_post_with_required_request_body_required_true(self):
        """A POST operation with at least one required param has `requestBody.required=True`."""
        with temp_app_package(
            "myapp",
            {
                "__init__.py": "",
                "m.py": (
                    'import frappe\n@frappe.whitelist(methods=["POST"])\ndef f(must: str, maybe: int = 0):\n    pass\n'
                ),
            },
        ) as package_dir:
            spec = SimpleNamespace(submodule_search_locations=[package_dir])
            with (
                patch(f"{MODULE}.importlib.util.find_spec", return_value=spec),
                patch(f"{MODULE}.frappe.utils.get_url", return_value="x"),
            ):
                result = generate_openapi_static("myapp")
        body = result["paths"]["/api/method/myapp.m.f"]["post"]["requestBody"]
        self.assertTrue(body["required"])

    def test_security_is_two_separate_scheme_requirements_when_not_allow_guest(self):
        """A non-guest operation's `security` is `[{"TokenAuth": []}, {"bearerAuth": []}]` (two separate dicts)."""
        with temp_app_package(
            "myapp",
            {
                "__init__.py": "",
                "m.py": ("import frappe\n@frappe.whitelist()\ndef secret():\n    pass\n"),
            },
        ) as package_dir:
            spec = SimpleNamespace(submodule_search_locations=[package_dir])
            with (
                patch(f"{MODULE}.importlib.util.find_spec", return_value=spec),
                patch(f"{MODULE}.frappe.utils.get_url", return_value="x"),
            ):
                result = generate_openapi_static("myapp")
        operation = result["paths"]["/api/method/myapp.m.secret"]["get"]
        self.assertEqual(operation["security"], [{"TokenAuth": []}, {"bearerAuth": []}])

    def test_response_example_for_placeholder_schema(self):
        """When the returns example is a placeholder dict, response content's `example` carries placeholder defaults under `message`."""
        with temp_app_package(
            "myapp",
            {
                "__init__.py": "",
                "m.py": (
                    "import frappe\n"
                    "@frappe.whitelist(allow_guest=True)\n"
                    "def f():\n"
                    '    """Returns:\n    {"count": <integer>, "ratio": <float>}\n"""\n'
                    "    pass\n"
                ),
            },
        ) as package_dir:
            spec = SimpleNamespace(submodule_search_locations=[package_dir])
            with (
                patch(f"{MODULE}.importlib.util.find_spec", return_value=spec),
                patch(f"{MODULE}.frappe.utils.get_url", return_value="x"),
            ):
                result = generate_openapi_static("myapp")
        operation = result["paths"]["/api/method/myapp.m.f"]["get"]
        content = operation["responses"]["200"]["content"]["application/json"]
        self.assertEqual(content["example"], {"message": {"count": 0, "ratio": 0.0}})

    def test_response_example_for_plain_returns_dict(self):
        """When the returns example is a plain dict, response content's `example` is `{"message": <returns_example>}`."""
        with temp_app_package(
            "myapp",
            {
                "__init__.py": "",
                "m.py": (
                    "import frappe\n"
                    "@frappe.whitelist(allow_guest=True)\n"
                    "def f():\n"
                    '    """Returns:\n    {"status": "ok"}\n"""\n'
                    "    pass\n"
                ),
            },
        ) as package_dir:
            spec = SimpleNamespace(submodule_search_locations=[package_dir])
            with (
                patch(f"{MODULE}.importlib.util.find_spec", return_value=spec),
                patch(f"{MODULE}.frappe.utils.get_url", return_value="x"),
            ):
                result = generate_openapi_static("myapp")
        operation = result["paths"]["/api/method/myapp.m.f"]["get"]
        content = operation["responses"]["200"]["content"]["application/json"]
        self.assertEqual(content["example"], {"message": {"status": "ok"}})

    def test_components_security_schemes_added_when_needs_auth(self):
        """components.securitySchemes is added only when at least one operation had allow_guest=False; includes TokenAuth + bearerAuth with bearerFormat='JWT'."""
        with temp_app_package(
            "myapp",
            {
                "__init__.py": "",
                "m.py": ("import frappe\n@frappe.whitelist()\ndef secret():\n    pass\n"),
            },
        ) as package_dir:
            spec = SimpleNamespace(submodule_search_locations=[package_dir])
            with (
                patch(f"{MODULE}.importlib.util.find_spec", return_value=spec),
                patch(f"{MODULE}.frappe.utils.get_url", return_value="x"),
            ):
                result = generate_openapi_static("myapp")
        schemes = result["components"]["securitySchemes"]
        self.assertEqual(schemes["TokenAuth"]["type"], "apiKey")
        self.assertEqual(schemes["TokenAuth"]["in"], "header")
        self.assertEqual(schemes["TokenAuth"]["name"], "Authorization")
        self.assertEqual(schemes["bearerAuth"]["type"], "http")
        self.assertEqual(schemes["bearerAuth"]["scheme"], "bearer")
        self.assertEqual(schemes["bearerAuth"]["bearerFormat"], "JWT")

    def test_components_omitted_when_all_guest(self):
        """components is NOT added when every operation has allow_guest=True."""
        with temp_app_package(
            "myapp",
            {
                "__init__.py": "",
                "m.py": ("import frappe\n@frappe.whitelist(allow_guest=True)\ndef public():\n    pass\n"),
            },
        ) as package_dir:
            spec = SimpleNamespace(submodule_search_locations=[package_dir])
            with (
                patch(f"{MODULE}.importlib.util.find_spec", return_value=spec),
                patch(f"{MODULE}.frappe.utils.get_url", return_value="x"),
            ):
                result = generate_openapi_static("myapp")
        self.assertNotIn("components", result)

    def test_tags_sorted(self):
        """openapi['tags'] is a sorted list of `{name: <module>}` dicts."""
        with temp_app_package(
            "myapp",
            {
                "__init__.py": "",
                "z_mod.py": ("import frappe\n@frappe.whitelist(allow_guest=True)\ndef z():\n    pass\n"),
                "a_mod.py": ("import frappe\n@frappe.whitelist(allow_guest=True)\ndef a():\n    pass\n"),
            },
        ) as package_dir:
            spec = SimpleNamespace(submodule_search_locations=[package_dir])
            with (
                patch(f"{MODULE}.importlib.util.find_spec", return_value=spec),
                patch(f"{MODULE}.frappe.utils.get_url", return_value="x"),
            ):
                result = generate_openapi_static("myapp")
        tag_names = [t["name"] for t in result["tags"]]
        self.assertEqual(tag_names, sorted(tag_names))


# ---------------------------------------------------------------------------
# Section 7: App metadata and bulk generation
# ---------------------------------------------------------------------------


class TestGetAppTitleAndVersion(IntegrationTestCase):
    def test_returns_hooks_title_and_module_version_on_success(self):
        """get_app_title_and_version returns (hooks.app_title, module.__version__) when both are importable."""
        hooks_mod = SimpleNamespace(app_title="My App Title")
        version_mod = SimpleNamespace(__version__="2.5.0")

        def fake_import(name):
            if name.endswith(".hooks"):
                return hooks_mod
            return version_mod

        with patch(f"{MODULE}.importlib.import_module", side_effect=fake_import):
            title, version = get_app_title_and_version("myapp")
        self.assertEqual(title, "My App Title")
        self.assertEqual(version, "2.5.0")

    def test_falls_back_to_app_name_when_hooks_missing(self):
        """get_app_title_and_version falls back to `app_name` when `hooks.app_title` is missing or hooks import fails."""

        def fake_import(name):
            if name.endswith(".hooks"):
                raise ImportError("no hooks")
            return SimpleNamespace(__version__="2.0.0")

        with patch(f"{MODULE}.importlib.import_module", side_effect=fake_import):
            title, version = get_app_title_and_version("missing_app")
        self.assertEqual(title, "missing_app")
        self.assertEqual(version, "2.0.0")

    def test_falls_back_to_default_version_when_missing(self):
        """get_app_title_and_version falls back to `"1.0.0"` when `__version__` is missing or import fails."""

        def fake_import(name):
            if name.endswith(".hooks"):
                return SimpleNamespace(app_title="t")
            raise ImportError("no module")

        with patch(f"{MODULE}.importlib.import_module", side_effect=fake_import):
            _, version = get_app_title_and_version("any_app")
        self.assertEqual(version, "1.0.0")


class TestGenerateOpenapiForAllApps(IntegrationTestCase):
    def test_writes_one_json_per_enabled_app(self):
        """generate_openapi_for_all_apps writes `openapi_<app>.json` per enabled app under <site>/public/files/openapi."""
        with tempfile.TemporaryDirectory() as site_path:
            settings = SimpleNamespace(app1=True, app2=False)
            with (
                patch(f"{MODULE}.frappe.get_single", return_value=settings),
                patch(f"{MODULE}.frappe.get_installed_apps", return_value=["app1", "app2"]),
                patch(f"{MODULE}.frappe.get_site_path", return_value=site_path),
                patch(f"{MODULE}.update_progress_bar"),
                patch(
                    f"{MODULE}.get_app_title_and_version",
                    side_effect=lambda app: (app.upper(), "9.9.9"),
                ),
                patch(
                    f"{MODULE}.generate_openapi_static",
                    side_effect=lambda app: {"openapi": "3.0.0", "info": {"title": "x", "version": "0"}, "paths": {}},
                ),
            ):
                generate_openapi_for_all_apps()
            self.assertTrue(os.path.exists(os.path.join(site_path, "public", "files", "openapi", "openapi_app1.json")))
            self.assertFalse(os.path.exists(os.path.join(site_path, "public", "files", "openapi", "openapi_app2.json")))

    def test_overwrites_info_title_and_version_from_get_app_title_and_version(self):
        """The bulk loop overwrites info.title and info.version on the returned dict from `get_app_title_and_version`."""
        with tempfile.TemporaryDirectory() as site_path:
            settings = SimpleNamespace(app1=True)
            with (
                patch(f"{MODULE}.frappe.get_single", return_value=settings),
                patch(f"{MODULE}.frappe.get_installed_apps", return_value=["app1"]),
                patch(f"{MODULE}.frappe.get_site_path", return_value=site_path),
                patch(f"{MODULE}.update_progress_bar"),
                patch(f"{MODULE}.get_app_title_and_version", return_value=("Pretty Title", "7.7.7")),
                patch(
                    f"{MODULE}.generate_openapi_static",
                    side_effect=lambda app: {"openapi": "3.0.0", "info": {"title": "raw", "version": "0"}, "paths": {}},
                ),
            ):
                generate_openapi_for_all_apps()
            with open(os.path.join(site_path, "public", "files", "openapi", "openapi_app1.json")) as f:
                doc = json.load(f)
            self.assertEqual(doc["info"]["title"], "Pretty Title")
            self.assertEqual(doc["info"]["version"], "7.7.7")

    def test_deletes_stale_spec_for_disabled_app(self):
        """For each disabled app, a pre-existing `openapi_<app>.json` is deleted."""
        with tempfile.TemporaryDirectory() as site_path:
            output_dir = os.path.join(site_path, "public", "files", "openapi")
            os.makedirs(output_dir, exist_ok=True)
            stale = os.path.join(output_dir, "openapi_disabled_app.json")
            with open(stale, "w") as f:
                f.write("{}")
            settings = SimpleNamespace(disabled_app=False)
            with (
                patch(f"{MODULE}.frappe.get_single", return_value=settings),
                patch(f"{MODULE}.frappe.get_installed_apps", return_value=["disabled_app"]),
                patch(f"{MODULE}.frappe.get_site_path", return_value=site_path),
                patch(f"{MODULE}.update_progress_bar"),
            ):
                generate_openapi_for_all_apps()
            self.assertFalse(os.path.exists(stale))

    def test_delete_failure_is_logged_via_log_error(self):
        """A delete failure is swallowed and logged via `frappe.log_error` with title 'OpenAPI Deletion Error'."""
        with tempfile.TemporaryDirectory() as site_path:
            output_dir = os.path.join(site_path, "public", "files", "openapi")
            os.makedirs(output_dir, exist_ok=True)
            stale = os.path.join(output_dir, "openapi_disabled_app.json")
            with open(stale, "w") as f:
                f.write("{}")
            settings = SimpleNamespace(disabled_app=False)
            with (
                patch(f"{MODULE}.frappe.get_single", return_value=settings),
                patch(f"{MODULE}.frappe.get_installed_apps", return_value=["disabled_app"]),
                patch(f"{MODULE}.frappe.get_site_path", return_value=site_path),
                patch(f"{MODULE}.update_progress_bar"),
                patch(f"{MODULE}.os.remove", side_effect=OSError("boom")),
                patch(f"{MODULE}.frappe.log_error") as mock_log,
            ):
                generate_openapi_for_all_apps()
            mock_log.assert_called_once()
            self.assertEqual(mock_log.call_args.args[1], "OpenAPI Deletion Error")

    def test_write_failure_is_logged_via_log_error(self):
        """A write failure is swallowed and logged via `frappe.log_error` with title 'OpenAPI Generation Error'."""
        with tempfile.TemporaryDirectory() as site_path:
            settings = SimpleNamespace(app1=True)
            with (
                patch(f"{MODULE}.frappe.get_single", return_value=settings),
                patch(f"{MODULE}.frappe.get_installed_apps", return_value=["app1"]),
                patch(f"{MODULE}.frappe.get_site_path", return_value=site_path),
                patch(f"{MODULE}.update_progress_bar"),
                patch(f"{MODULE}.get_app_title_and_version", return_value=("t", "v")),
                patch(f"{MODULE}.generate_openapi_static", return_value={"info": {"title": "", "version": ""}}),
                patch(f"{MODULE}.open", side_effect=OSError("boom")),
                patch(f"{MODULE}.frappe.log_error") as mock_log,
            ):
                generate_openapi_for_all_apps()
            mock_log.assert_called_once()
            self.assertEqual(mock_log.call_args.args[1], "OpenAPI Generation Error")

    def test_progress_bar_is_called_with_total_enabled(self):
        """progress is reported via `update_progress_bar("Generating OpenAPI spec", i, total)` where total = len(enabled_apps)."""
        with tempfile.TemporaryDirectory() as site_path:
            settings = SimpleNamespace(a=True, b=True, c=False)
            with (
                patch(f"{MODULE}.frappe.get_single", return_value=settings),
                patch(f"{MODULE}.frappe.get_installed_apps", return_value=["a", "b", "c"]),
                patch(f"{MODULE}.frappe.get_site_path", return_value=site_path),
                patch(f"{MODULE}.update_progress_bar") as mock_progress,
                patch(f"{MODULE}.get_app_title_and_version", return_value=("t", "v")),
                patch(f"{MODULE}.generate_openapi_static", return_value={"info": {"title": "", "version": ""}}),
            ):
                generate_openapi_for_all_apps()
            calls = mock_progress.call_args_list
            self.assertEqual(len(calls), 2)
            for call in calls:
                self.assertEqual(call.args[0], "Generating OpenAPI spec")
                self.assertEqual(call.args[2], 2)
