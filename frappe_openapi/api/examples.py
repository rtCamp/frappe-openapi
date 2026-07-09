# Copyright (c) 2025, rtCamp and contributors
# For license information, please see license.txt
#
# ---------------------------------------------------------------------------
# SAMPLE API ENDPOINTS
# ---------------------------------------------------------------------------
# These functions exist purely to demonstrate every feature of the OpenAPI
# spec generator.  Each one is decorated with @frappe.whitelist so the
# parser picks it up, and each docstring exercises a different aspect of the
# comment format:
#
#   1. demo_health_check   - minimal GET, guest-accessible, no parameters
#   2. demo_list_items     - GET with multiple typed query params, pagination
#   3. demo_create_item    - POST with required + optional body params, rich
#                            Returns example that drives the response schema
#   4. demo_update_item    - PUT showing path-style name in params, optional fields
#   5. demo_delete_item    - DELETE showing boolean response
#   6. demo_upload_file    - POST with binary / mixed types
#   7. demo_authenticated  - endpoint that requires auth (no allow_guest)
# ---------------------------------------------------------------------------

from __future__ import annotations

from typing import Any

import frappe


def _check_demo_enabled():
    """Check if demo endpoints should be enabled.

    Demo endpoints are only enabled in:
    1. Developer mode
    2. When frappe_openapi_enable_demos site config is True
    """
    if frappe.conf.developer_mode:
        return True

    if frappe.conf.get("frappe_openapi_enable_demos"):
        return True

    frappe.throw(
        frappe._(
            "Demo endpoints are disabled in production. Enable developer mode or set frappe_openapi_enable_demos=1 in site_config.json"
        ),
        frappe.PermissionError,
    )


# ---------------------------------------------------------------------------
# 1. Health check - minimal, guest, GET
# ---------------------------------------------------------------------------
# nosemgrep: frappe-semgrep.rules.security.guest-whitelisted-method
@frappe.whitelist(allow_guest=True, methods=["GET"])
def demo_health_check() -> dict[str, Any]:
    """Return a simple liveness probe for the API.

    No parameters required.  Always returns HTTP 200 with status information.

    Returns:
        dict: {
            "status": "ok",
            "timestamp": "2026-01-01T00:00:00Z",
            "version": "1.0.0"
        }
    """
    _check_demo_enabled()
    return {
        "status": "ok",
        "timestamp": frappe.utils.now(),
        "version": frappe.get_attr("frappe_openapi.__version__") or "1.0.0",
    }


# ---------------------------------------------------------------------------
# 2. List items - GET with typed query params and pagination
# ---------------------------------------------------------------------------
# Demo endpoint: gated by developer mode or the frappe_openapi_enable_demos site config.
# nosemgrep: frappe-semgrep.rules.security.guest-whitelisted-method
@frappe.whitelist(allow_guest=True, methods=["GET"])
def demo_list_items(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    category: str | None = None,
    is_active: bool = True,
    min_price: float | None = None,
    max_price: float | None = None,
) -> dict[str, Any]:
    """List catalogue items with optional filtering and pagination.

    Supports full-text search, category filtering, active/inactive toggle and
    price-range constraints.  Results are paginated; use ``page`` and
    ``page_size`` to navigate.

    Args:
        page (int, optional): Page number, 1-based (default: 1).
        page_size (int, optional): Number of results per page, max 100 (default: 20).
        search (str, optional): Free-text search term applied to name and description.
        category (str, optional): Filter by category slug, e.g. ``"electronics"``.
        is_active (bool, optional): When True only active items are returned (default: True).
        min_price (float, optional): Lower bound for item price (inclusive).
        max_price (float, optional): Upper bound for item price (inclusive).

    Returns:
        dict: {
            "total": 42,
            "page": 1,
            "page_size": 20,
            "items": [
                {
                    "name": "ITEM-00001",
                    "title": "Demo Widget",
                    "category": "electronics",
                    "price": 9.99,
                    "is_active": true
                }
            ]
        }
    """
    _check_demo_enabled()
    # Demo implementation — not executed in production
    return {"total": 0, "page": page, "page_size": page_size, "items": []}


# ---------------------------------------------------------------------------
# 3. Create item - POST with required + optional params, rich response example
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"])
def demo_create_item(
    title: str,
    category: str,
    price: float,
    description: str | None = None,
    is_active: bool = True,
    tags: list | None = None,
    metadata: dict | None = None,
) -> dict[str, Any]:
    """Create a new catalogue item.

    Creates a new item in the catalogue and returns its generated identifier.
    The ``title``, ``category`` and ``price`` fields are mandatory; all other
    fields are optional.

    Args:
        title (str): Human-readable item title (max 140 characters).
        category (str): Category slug the item belongs to, e.g. ``"electronics"``.
        price (float): Retail price in the site's default currency (must be >= 0).
        description (str, optional): Long-form description supporting Markdown.
        is_active (bool, optional): Whether the item should be immediately visible
                  (default: True).
        tags (list, optional): List of tag strings for search and filtering,
              e.g. ``["new", "sale"]``.
        metadata (dict, optional): Arbitrary key-value pairs for custom attributes,
                 e.g. ``{"weight_kg": 0.5, "sku": "WDG-001"}``.

    Returns:
        dict: {
            "success": true,
            "name": "ITEM-00042",
            "title": "Demo Widget",
            "category": "electronics",
            "price": 9.99,
            "is_active": true,
            "created_at": "2026-01-01T00:00:00Z"
        }
    """
    _check_demo_enabled()
    frappe.only_for("System Manager")
    return {"success": True, "name": "ITEM-NEW"}


# ---------------------------------------------------------------------------
# 4. Update item - PUT showing optional partial update
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["PUT"])
def demo_update_item(
    item_name: str,
    title: str | None = None,
    price: float | None = None,
    description: str | None = None,
    is_active: bool | None = None,
    tags: list | None = None,
) -> dict[str, Any]:
    """Update one or more fields on an existing catalogue item.

    Only the fields that are explicitly provided will be updated; omitted fields
    are left unchanged (PATCH semantics over HTTP PUT).

    Args:
        item_name (str): The document name of the item to update, e.g. ``"ITEM-00042"``.
        title (str, optional): New item title.
        price (float, optional): New retail price (must be >= 0 if provided).
        description (str, optional): Replacement description text.
        is_active (bool, optional): Toggle visibility.
        tags (list, optional): Replacement tag list; pass an empty list to clear all tags.

    Returns:
        dict: {
            "success": true,
            "name": "ITEM-00042",
            "updated_fields": ["title", "price"]
        }
    """
    _check_demo_enabled()
    frappe.only_for("System Manager")
    return {"success": True, "name": item_name, "updated_fields": []}


# ---------------------------------------------------------------------------
# 5. Delete item - DELETE showing boolean response
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["DELETE"])
def demo_delete_item(
    item_name: str,
    permanent: bool = False,
) -> dict[str, Any]:
    """Delete or archive a catalogue item.

    By default the item is soft-deleted (archived) so it can be restored later.
    Pass ``permanent=True`` to hard-delete the record; this action is irreversible.

    Args:
        item_name (str): The document name of the item to remove, e.g. ``"ITEM-00042"``.
        permanent (bool, optional): When True the record is permanently deleted
                  instead of archived (default: False).

    Returns:
        dict: {
            "success": true,
            "deleted": true,
            "permanent": false
        }
    """
    _check_demo_enabled()
    frappe.only_for("System Manager")
    return {"success": True, "deleted": True, "permanent": permanent}


# ---------------------------------------------------------------------------
# 6. Upload file - POST with binary / mixed types
# ---------------------------------------------------------------------------
# nosemgrep: frappe-semgrep.rules.security.guest-whitelisted-method
@frappe.whitelist(allow_guest=True, methods=["POST"])
def demo_upload_file(
    file_url: str,
    file_name: str | None = None,
    folder: str = "Home",
    is_private: bool = False,
    optimize: bool = True,
    max_width: int | None = None,
    quality: int = 85,
) -> dict[str, Any]:
    """Download a remote file and attach it to the file manager.

    Fetches the file from ``file_url``, optionally re-encodes images for size
    optimisation, and stores the result in the Frappe File doctype.

    Args:
        file_url (str): Publicly accessible URL of the file to download.
        file_name (str, optional): Override the stored file name. Defaults to the
                  last segment of ``file_url``.
        folder (str, optional): Destination folder in the file manager (default: ``"Home"``).
        is_private (bool, optional): Store as a private file visible only to the
                   uploader (default: False).
        optimize (bool, optional): Re-encode JPEG/WebP images for smaller file size
                 (default: True).
        max_width (int, optional): Resize image so its width does not exceed this value
                  in pixels (aspect ratio preserved).  No resizing when omitted.
        quality (int, optional): JPEG/WebP encoding quality 1-100 (default: 85).
                Only applies when ``optimize`` is True.

    Returns:
        dict: {
            "success": true,
            "file_url": "/files/my-image.webp",
            "file_name": "my-image.webp",
            "file_size": 204800,
            "is_private": false,
            "content_type": "image/webp"
        }
    """
    _check_demo_enabled()
    return {"success": True, "file_url": file_url}


# ---------------------------------------------------------------------------
# 7. Authenticated endpoint - requires Bearer token / API key
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["GET"])
def demo_authenticated(
    resource_id: str,
    include_metadata: bool = False,
) -> dict[str, Any]:
    """Fetch a private resource that requires authentication.

    This endpoint does **not** set ``allow_guest=True``, so the OpenAPI spec
    will include a ``security`` requirement showing both ``TokenAuth`` (API
    key/secret) and ``bearerAuth`` (OAuth2 token) schemes.

    Args:
        resource_id (str): Unique identifier of the private resource.
        include_metadata (bool, optional): When True extra metadata is included
                         in the response (default: False).

    Returns:
        dict: {
            "success": true,
            "resource_id": "RES-00001",
            "owner": "user@example.com",
            "data": {
                "value": "secret content",
                "created_at": "2026-01-01T00:00:00Z"
            },
            "metadata": {}
        }
    """
    _check_demo_enabled()
    return {
        "success": True,
        "resource_id": resource_id,
        "owner": frappe.session.user,
        "data": {},
        "metadata": {},
    }
