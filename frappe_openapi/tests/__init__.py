"""Helpers for the frappe_openapi test suite."""

from __future__ import annotations

import ast
import os
import tempfile
import textwrap
from collections.abc import Iterator
from contextlib import contextmanager


def parse_first_function(source: str) -> ast.FunctionDef:
    """Parse source and return the first FunctionDef AST node."""
    tree = ast.parse(textwrap.dedent(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            return node
    raise ValueError("No function found")


def parse_first_annotation(source: str) -> ast.AST | None:
    """Parse source like `x: int = 0` and return the annotation AST node."""
    tree = ast.parse(textwrap.dedent(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            return node.annotation
    raise ValueError("No annotation found")


@contextmanager
def temp_app_package(name: str, files: dict[str, str]) -> Iterator[str]:
    """Create a temporary Python package on disk, return its top-level directory.

    `files` maps each relative `.py` path (under the package) to its source content.
    An empty `__init__.py` is created at the package root if not supplied.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        package_dir = os.path.join(tmpdir, name)
        os.makedirs(package_dir, exist_ok=True)
        if "__init__.py" not in files:
            with open(os.path.join(package_dir, "__init__.py"), "w") as f:
                f.write("")
        for rel_path, content in files.items():
            full_path = os.path.join(package_dir, rel_path)
            os.makedirs(os.path.dirname(full_path) or package_dir, exist_ok=True)
            with open(full_path, "w") as f:
                f.write(textwrap.dedent(content))
        yield package_dir
