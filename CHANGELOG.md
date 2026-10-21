# Changelog

Changes to the `celesto` Python package. The TypeScript SDK (`@celestoai/sdk`)
is versioned separately.

## 0.0.15

### New: custom templates

Build your own computer image from a built-in template and a setup script, then
create computers that start with your packages already installed. Custom
templates are turned on per account; until they are, these calls raise
`CelestoNotFoundError` saying so.

```python
from celesto import Template

template = Template(name="data-env", build_script="pip install pandas")
template.wait(on_log=print)
computer = template.create_computer()
```

- `Template(...)` creates a template and starts its build. `Template.get()`,
  `Template.list()` and `Template.lint()` load, list and check templates.
- `template.wait()` follows the build until it is ready, streaming the build
  log to `on_log`. It retries rate limits, server errors and network errors
  until its timeout (40 minutes by default).
- `template.edit()`, `rebuild()`, `logs()`, `delete()` and `create_computer()`
  manage the template and use it.
- `CelestoTemplateBuildError` reports a failed build with the failing line,
  exit code and a hint.
- Guide: https://docs.celesto.ai/cloud/features/custom-templates

### Changed

- A 409 response now raises `CelestoConflictError`. It subclasses
  `CelestoServerError`, which 409s raised before, so existing
  `except CelestoServerError` handlers still catch it, and the message still
  contains "409".
- A 202 response is now treated as success instead of raising
  `CelestoServerError("Unexpected response (202)")`.
- Validation errors (422) now name each invalid field and its rule, for example
  `Validation error: name: String should match pattern ...`, instead of
  `Validation error: Validation error`.
- `Computer.list_templates()` docs now say it lists built-in templates only.
