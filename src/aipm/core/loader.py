"""Input bundle and prompt loader for the AIPM pipeline."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_bundle(path: str) -> dict:
    """Load a product input bundle from a directory.

    Reads manifest.json, tickets.json, and all documents from the documents/ subfolder.

    Args:
        path: Path to the bundle directory.

    Returns:
        A dict with keys: product_name, description, input_type, tickets, documents.
        Each document entry has: filename, content, doc_type (inferred from extension/name).

    Raises:
        FileNotFoundError: If the bundle directory or manifest.json is missing.
    """
    bundle_dir = Path(path)

    if not bundle_dir.is_dir():
        raise FileNotFoundError(f"Bundle directory not found: {path}")

    # Load manifest
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found in bundle: {path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    logger.info("Loaded manifest for '%s'", manifest.get("product_name", "unknown"))

    # Load tickets
    tickets: list[dict] = []
    tickets_path = bundle_dir / "tickets.json"
    if tickets_path.exists():
        tickets = json.loads(tickets_path.read_text(encoding="utf-8"))
        logger.info("Loaded %d tickets", len(tickets))
    else:
        logger.warning("No tickets.json found in bundle")

    # Load documents
    documents: list[dict] = []
    docs_dir = bundle_dir / "documents"
    if docs_dir.is_dir():
        for doc_path in sorted(docs_dir.iterdir()):
            if doc_path.is_file():
                doc_entry = _load_document(doc_path)
                documents.append(doc_entry)
        logger.info("Loaded %d documents", len(documents))
    else:
        logger.warning("No documents/ directory found in bundle")

    return {
        "product_name": manifest.get("product_name", ""),
        "description": manifest.get("description", ""),
        "input_type": manifest.get("input_type", "bundle"),
        "tickets": tickets,
        "documents": documents,
    }


def _load_document(doc_path: Path) -> dict:
    """Load a single document file and infer its type.

    Args:
        doc_path: Path to the document file.

    Returns:
        Dict with filename, content, and doc_type.
    """
    content = doc_path.read_text(encoding="utf-8")
    doc_type = _infer_doc_type(doc_path.name)

    return {
        "filename": doc_path.name,
        "content": content,
        "doc_type": doc_type,
    }


def _infer_doc_type(filename: str) -> str:
    """Infer the document type from the filename.

    Args:
        filename: The document filename.

    Returns:
        One of: note, interview, competitor_brief, metrics_snapshot, prd, spec.
    """
    name_lower = filename.lower()

    if "metric" in name_lower or "snapshot" in name_lower:
        return "metrics_snapshot"
    if "competitor" in name_lower or "competitive" in name_lower:
        return "competitor_brief"
    if "interview" in name_lower:
        return "interview"
    if "customer" in name_lower or "note" in name_lower:
        return "note"
    if "prd" in name_lower:
        return "prd"
    if "spec" in name_lower:
        return "spec"

    return "note"


def load_prompt(prompt_text: str) -> dict:
    """Create a minimal bundle from a plain text product prompt.

    Args:
        prompt_text: The user's product idea or request as text.

    Returns:
        A bundle dict with the prompt as both product_name and description,
        empty tickets and documents.
    """
    # Extract a short name from the first line or first 60 chars
    first_line = prompt_text.strip().split("\n")[0]
    product_name = first_line[:60].strip()

    logger.info("Created bundle from prompt: '%s'", product_name)

    return {
        "product_name": product_name,
        "description": prompt_text.strip(),
        "input_type": "prompt",
        "tickets": [],
        "documents": [],
    }


def validate_bundle(bundle: dict) -> list[str]:
    """Validate a loaded bundle and return a list of warnings.

    Checks for missing or empty fields that may reduce pipeline quality.

    Args:
        bundle: The loaded bundle dict.

    Returns:
        A list of warning strings. Empty list means the bundle is complete.
    """
    warnings: list[str] = []

    if not bundle.get("product_name"):
        warnings.append("Missing product_name in manifest")

    if not bundle.get("description"):
        warnings.append("Missing description in manifest")

    if not bundle.get("tickets"):
        warnings.append("No tickets provided — agents will have limited input data")

    documents = bundle.get("documents", [])
    if not documents:
        warnings.append("No documents provided — agents will have limited context")
    else:
        doc_types = {d.get("doc_type") for d in documents}

        if "note" not in doc_types and "interview" not in doc_types:
            warnings.append(
                "No customer notes or interview documents — Customer Insights Agent will have limited input"
            )

        if "metrics_snapshot" not in doc_types:
            warnings.append("No metrics snapshot — Metrics Agent will have limited input")

        if "competitor_brief" not in doc_types:
            warnings.append("No competitor brief — Competitive Agent will have limited input")

    if warnings:
        for w in warnings:
            logger.warning("Bundle validation: %s", w)
    else:
        logger.info("Bundle validation passed with no warnings")

    return warnings
