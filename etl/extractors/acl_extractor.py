# etl/extractors/acl_extractor.py
"""Extract access control metadata from Confluence, Jira, and GitLab sources.

Each source system encodes document visibility differently:

- **Confluence**: page-level read restrictions (groups/users) and space-level
  permissions.  The REST API returns ``restrictions.read`` on expanded pages.
- **Jira**: issue security levels within security schemes, plus project-level
  role/group mappings.
- **GitLab**: project visibility (private / internal / public) and membership.

This module normalises those heterogeneous representations into a single
``DocumentACL`` dataclass that downstream consumers (chunker, Qdrant indexer)
can rely on.
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DocumentACL:
    """Access control list for a single document."""

    access_level: str = "public"  # public | internal | confidential | restricted
    allowed_groups: list[str] = field(default_factory=list)
    allowed_users: list[str] = field(default_factory=list)
    source_permissions: dict[str, object] = field(default_factory=dict)


# ── Confluence ──────────────────────────────────────────────────────────────


def extract_confluence_acl(page_data: dict) -> DocumentACL:
    """Extract ACL from Confluence page restrictions and space metadata.

    Confluence REST API (v2) returns restrictions in page metadata when
    expanded with ``metadata.properties`` or ``metadata.restrictions``::

        restrictions.read.restrictions[].subjects[].identifier
        restrictions.read.restrictions[].subjects[].type  ("group" | "user")

    Space key is mapped to a department group via :func:`map_department_from_space`.
    """
    acl = DocumentACL()

    # 1. Page-level read restrictions
    restrictions = page_data.get("restrictions", {}).get("read", {}).get("restrictions", [])
    if restrictions:
        acl.access_level = "restricted"
        for restriction in restrictions:
            for subject in restriction.get("subjects", []):
                identifier = subject.get("identifier", "")
                subject_type = subject.get("type", "")
                if subject_type == "group":
                    acl.allowed_groups.append(identifier)
                elif subject_type == "user":
                    acl.allowed_users.append(identifier)

    # 2. Space-level metadata
    space_key = page_data.get("space_key", "") or page_data.get("space", {}).get("key", "")
    if space_key:
        acl.source_permissions["space_key"] = space_key
        department = map_department_from_space(space_key)
        if department and department != "general" and department not in acl.allowed_groups:
            acl.allowed_groups.append(department)

    # 3. Labels that imply restricted access
    labels = page_data.get("labels", [])
    if (
        any(label.lower() in ("confidential", "restricted", "internal") for label in labels)
        and acl.access_level == "public"
    ):
        acl.access_level = "internal"

    # Deduplicate
    acl.allowed_groups = list(dict.fromkeys(acl.allowed_groups))
    acl.allowed_users = list(dict.fromkeys(acl.allowed_users))

    return acl


# ── Jira ───────────────────────────────────────────────────────────────────


def extract_jira_acl(issue_data: dict) -> DocumentACL:
    """Extract ACL from Jira issue security level.

    Jira REST API returns::

        fields.security.name   (security scheme name)
        fields.security.id     (security level ID)

    If no security scheme is set the issue is considered public.
    """
    acl = DocumentACL()

    # 1. Issue-level security
    fields_data = issue_data.get("fields", {})
    security = fields_data.get("security") or issue_data.get("security", {})
    if security:
        acl.access_level = "restricted"
        acl.source_permissions["security_scheme"] = security.get("name", "")
        acl.source_permissions["security_level"] = security.get("id", "")

    # 2. Project key for department mapping
    project_key = fields_data.get("project", {}).get("key", "") or issue_data.get("project_key", "")
    if project_key:
        acl.source_permissions["project_key"] = project_key
        department = map_department_from_project(project_key)
        if department:
            acl.allowed_groups.append(department)

    # Deduplicate
    acl.allowed_groups = list(dict.fromkeys(acl.allowed_groups))
    acl.allowed_users = list(dict.fromkeys(acl.allowed_users))

    return acl


# ── GitLab ─────────────────────────────────────────────────────────────────


def extract_gitlab_acl(
    project_data: dict,
    members: list[dict] | None = None,
) -> DocumentACL:
    """Extract ACL from GitLab project visibility.

    GitLab visibility levels:

    - ``private``  — only explicit project members
    - ``internal`` — any authenticated user on the GitLab instance
    - ``public``   — everyone

    ``members`` is an optional list of dicts with ``type`` (``"Group"`` or
    ``"User"``) and ``name`` / ``username``.  When not provided the ACL still
    captures the visibility level.
    """
    acl = DocumentACL()

    visibility = project_data.get("visibility", "internal")

    if visibility == "private":
        acl.access_level = "restricted"
        member_list = members or project_data.get("members", [])
        for member in member_list:
            member_type = member.get("type", "")
            if member_type.lower() == "group":
                acl.allowed_groups.append(member.get("name", member.get("path", "")))
            else:
                acl.allowed_users.append(member.get("username", member.get("name", "")))
    elif visibility == "internal":
        acl.access_level = "internal"
    else:
        acl.access_level = "public"

    acl.source_permissions["visibility"] = visibility

    # Deduplicate
    acl.allowed_groups = list(dict.fromkeys(acl.allowed_groups))
    acl.allowed_users = list(dict.fromkeys(acl.allowed_users))

    return acl


# ── Department mapping helpers ─────────────────────────────────────────────

# Mapping of common prefixes to department groups.  Override via
# ``config["department_map"]`` in the extractor config if needed.
_DEFAULT_DEPARTMENT_MAP: dict[str, str] = {
    "ENG": "engineering",
    "DEV": "engineering",
    "FE": "engineering",
    "BE": "engineering",
    "HR": "hr",
    "FIN": "finance",
    "MKT": "marketing",
    "OPS": "operations",
    "SEC": "security",
    "QA": "quality",
    "PM": "product",
    "DES": "design",
    "INFRA": "infrastructure",
    "DATA": "data",
    "SRE": "sre",
    "LEGAL": "legal",
    "SUP": "support",
}


def map_department_from_space(space_key: str) -> str:
    """Map a Confluence space key to a department group name.

    Common patterns: ``ENG-*`` → ``engineering``, ``HR-*`` → ``hr``, etc.
    """
    if not space_key:
        return "general"
    prefix = space_key.split("-")[0].upper() if "-" in space_key else space_key.upper()
    return _DEFAULT_DEPARTMENT_MAP.get(prefix, "general")


def map_department_from_project(project_key: str) -> str:
    """Map a Jira project key to a department group name.

    Uses the same prefix-based mapping as :func:`map_department_from_space`.
    """
    if not project_key:
        return ""
    prefix = project_key.split("-")[0].upper() if "-" in project_key else project_key.upper()
    return _DEFAULT_DEPARTMENT_MAP.get(prefix, "")
