"""Template engine for rendering artifact templates with context data."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Directory containing the template files
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def load_template(template_name: str) -> str:
    """Load a template file by name.

    Args:
        template_name: Filename of the template, e.g. "prd_template.md".

    Returns:
        The raw template content as a string.

    Raises:
        FileNotFoundError: If the template file does not exist.
    """
    template_path = TEMPLATES_DIR / template_name
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    content = template_path.read_text(encoding="utf-8")
    logger.debug("Loaded template: %s (%d chars)", template_name, len(content))
    return content


def render_template(template: str, context: dict) -> str:
    """Render a template by replacing {variable} placeholders with context values.

    Handles missing keys gracefully by leaving the placeholder as-is
    and logging a warning.

    Supports section injection: if a context value is a list of strings,
    it will be joined with newlines.

    Args:
        template: The raw template string with {variable} placeholders.
        context: A dict mapping variable names to their values.

    Returns:
        The rendered template string.
    """
    rendered = template

    for key, value in context.items():
        placeholder = "{" + key + "}"
        if placeholder not in rendered:
            continue

        # Convert lists to newline-joined strings
        if isinstance(value, list):
            value = "\n".join(str(item) for item in value)
        else:
            value = str(value)

        rendered = rendered.replace(placeholder, value)

    # Warn about any remaining un-replaced placeholders
    import re

    remaining = re.findall(r"\{(\w+)\}", rendered)
    if remaining:
        unique = sorted(set(remaining))
        logger.warning("Unresolved template placeholders: %s", ", ".join(unique))

    return rendered
