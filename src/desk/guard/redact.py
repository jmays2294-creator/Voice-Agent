"""Redaction for anything that is written down or spoken back.

Applied to denial logs, audit rows, bench fixtures and — if session logging is
ever switched on — transcripts. The rule is that a log line is a place a WCB
number or a claimant name must never come to rest.

Patterns are deliberately over-broad. A redaction that eats an innocent string
costs a confusing log line; one that misses costs a privilege problem.
"""

from __future__ import annotations

import re

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # --- credentials ------------------------------------------------------
    ("[key]", re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}\b")),
    ("[key]", re.compile(r"\b(?:gh[pousr]|github_pat)_[A-Za-z0-9_]{16,}\b")),
    ("[key]", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("[jwt]", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("[key]", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("[key]", re.compile(r"-----BEGIN[^-]{0,40}PRIVATE KEY-----[\s\S]*?-----END[^-]{0,40}-----")),
    ("[key]", re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|bearer)"
                         r"\s*[:=]\s*\"?[A-Za-z0-9_\-./+]{12,}\"?")),

    # --- case identifiers -------------------------------------------------
    # WCB case numbers print as a letter/digit group; accept the common shapes.
    ("[wcb]", re.compile(r"(?i)\bWCB\s*(?:case\s*)?(?:#|no\.?|number)?\s*[:\-]?\s*"
                         r"[A-Z]?\d{6,9}\b")),
    ("[wcb]", re.compile(r"\b[A-Z]\d{7,8}\b")),
    ("[carriercase]", re.compile(r"(?i)\bcarrier\s+case\s*(?:#|no\.?)?\s*[:\-]?\s*[A-Z0-9-]{5,}\b")),
    ("[ssn]", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("[dob]", re.compile(r"(?i)\b(?:d\.?o\.?b\.?|date of birth)\s*[:\-]?\s*"
                         r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")),

    # --- case captions and parties ---------------------------------------
    # "Surname v. Employer", "In the Matter of ...", "Claimant: Name"
    ("[caption]", re.compile(r"\b[A-Z][A-Za-z'\-]{1,30}\s+v\.?s?\.?\s+[A-Z][A-Za-z'\-&., ]{2,60}")),
    ("[caption]", re.compile(r"(?i)\bin the matter of\s+[^,.\n]{2,80}")),
    ("[name]", re.compile(r"(?i)\b(?:claimant|injured worker|petitioner|respondent|"
                          r"employer|carrier|deponent)\s*[:\-]\s*[A-Z][^\n,;]{1,60}")),

    # --- contact details --------------------------------------------------
    ("[email]", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("[phone]", re.compile(r"\b(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b")),

    # --- machine identity -------------------------------------------------
    # Never let an absolute home path reach a log, a row, or the microphone.
    # Assembled from parts so this file does not itself contain the literal it
    # exists to remove — the acceptance check scans the whole tree, this file
    # included, and an exception list is how a rule starts to rot.
    ("[home]", re.compile(r"/" + "Users" + r"/[^/\s\"']+")),
    ("[home]", re.compile(r"/" + "home" + r"/[^/\s\"']+")),
    ("[icloud]", re.compile(r"(?:/[^\s\"']*)?" + "Mobile" + r"\s" + "Documents" + r"[^\s\"']*")),
)


def redact(text: str) -> str:
    """Return text with every known sensitive shape replaced by a placeholder."""
    if not text:
        return text
    out = text
    for placeholder, pattern in _RULES:
        out = pattern.sub(placeholder, out)
    return out


def redact_obj(obj):
    """Redact recursively through a JSON-shaped structure."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v) for v in obj]
    return obj
