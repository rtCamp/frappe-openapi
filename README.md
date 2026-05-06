<div align="center">
    <h2>Frappe OpenAPI</h2>
    A Frappe app to <strong>generate</strong> and <strong>visualize</strong> whitelisted APIs with interactive Swagger UI documentation.
</div>
<br>
<div align="center">
    <img width="192" alt="image-removebg-preview" src="https://github.com/user-attachments/assets/9c45923e-081f-461c-b3d3-44071afb34be" />
</div>

---

## Features

- Automatically generates OpenAPI (Swagger) JSON files for all installed Frappe apps.
- Responsive Swagger UI portal with sidebar app selection.
- Displays API endpoints, parameters, sample requests, and responses.

---

## Installation

Run the following commands inside your bench directory:

```bash
bench get-app https://github.com/rtCamp/frappe-openapi.git
bench install-app frappe_openapi
bench migrate
bench restart
```

> For a detailed installation guide and advanced configuration, visit the [Wiki](https://github.com/rtCamp/frappe-openapi/wiki).

---

## How to Use

1. **Install the app** using the steps above.
2. **Access the API Explorer UI** at `/docs`.
3. **Select an app** from the sidebar to view its API documentation.
4. **Try out endpoints** directly from the Swagger UI.

---

## Whitelisting Functions for API Explorer

To ensure your APIs are documented correctly:

- **Whitelist your function** using `@frappe.whitelist()`.
- **Add a Python docstring** that includes:
  - A **description** of what the endpoint does.
  - A **sample response** in JSON format.

**Example:**

```python
@frappe.whitelist()
def create_customer(name, email):
    """
    Create a new customer.

    Response:
    {
        "status": "success",
        "customer_id": "CUS12345"
    }
    """
    # Your code here
```

**Guidelines:**
- Always describe the endpoint's purpose.
- Include clear sample response blocks.
- Keep examples concise and relevant.
- These docstrings are parsed and shown in the API Explorer UI.

---

## License

[AGPL-3.0](LICENSE)
