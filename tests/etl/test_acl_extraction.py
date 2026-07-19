# tests/etl/test_acl_extraction.py
"""Tests for ACL extraction from Confluence, Jira, and GitLab sources.

Covers:
- DocumentACL defaults
- extract_confluence_acl (page restrictions, space mapping, labels)
- extract_jira_acl (security levels, project mapping)
- extract_gitlab_acl (visibility levels, member types)
- Department mapping helpers
- ACL propagation from document metadata to chunks
"""

from dataclasses import asdict

from etl.chunker.semantic_chunker import Chunk, MDKeyChunker, MetadataEnricher, SemanticChunker
from etl.extractors.acl_extractor import (
    DocumentACL,
    extract_confluence_acl,
    extract_gitlab_acl,
    extract_jira_acl,
    map_department_from_project,
    map_department_from_space,
)
from etl.extractors.base_extractor import ExtractedDocument

# ── DocumentACL defaults ───────────────────────────────────────────────────


class TestDocumentACLDefaults:
    def test_default_values(self):
        acl = DocumentACL()
        assert acl.access_level == "public"
        assert acl.allowed_groups == []
        assert acl.allowed_users == []
        assert acl.source_permissions == {}

    def test_custom_values(self):
        acl = DocumentACL(
            access_level="restricted",
            allowed_groups=["engineering"],
            allowed_users=["alice"],
            source_permissions={"space_key": "ENG"},
        )
        assert acl.access_level == "restricted"
        assert acl.allowed_groups == ["engineering"]
        assert acl.allowed_users == ["alice"]
        assert acl.source_permissions["space_key"] == "ENG"


# ── Confluence ACL ─────────────────────────────────────────────────────────


class TestExtractConfluenceACL:
    def test_public_page_no_restrictions(self):
        """A page with no restrictions defaults to public."""
        page_data = {
            "id": "12345",
            "title": "Public Page",
            "space": {"key": "GENERAL"},
        }
        acl = extract_confluence_acl(page_data)
        assert acl.access_level == "public"
        assert acl.allowed_groups == []
        assert acl.allowed_users == []

    def test_restricted_page_with_group(self):
        """Page with group-level read restriction."""
        page_data = {
            "id": "12345",
            "title": "Restricted Page",
            "space": {"key": "ENG"},
            "restrictions": {
                "read": {
                    "restrictions": [
                        {
                            "subjects": [
                                {"identifier": "engineering", "type": "group"},
                            ],
                        },
                    ],
                },
            },
        }
        acl = extract_confluence_acl(page_data)
        assert acl.access_level == "restricted"
        assert "engineering" in acl.allowed_groups

    def test_restricted_page_with_user_and_group(self):
        """Page with both user and group restrictions."""
        page_data = {
            "id": "12345",
            "title": "Restricted Page",
            "space": {"key": "SEC"},
            "restrictions": {
                "read": {
                    "restrictions": [
                        {
                            "subjects": [
                                {"identifier": "security-team", "type": "group"},
                                {"identifier": "alice", "type": "user"},
                                {"identifier": "bob", "type": "user"},
                            ],
                        },
                    ],
                },
            },
        }
        acl = extract_confluence_acl(page_data)
        assert acl.access_level == "restricted"
        assert "security-team" in acl.allowed_groups
        assert "alice" in acl.allowed_users
        assert "bob" in acl.allowed_users

    def test_space_key_mapped_to_department(self):
        """Space key is used to derive department group."""
        page_data = {
            "id": "12345",
            "title": "Page",
            "space": {"key": "ENG-DOCS"},
        }
        acl = extract_confluence_acl(page_data)
        assert acl.source_permissions.get("space_key") == "ENG-DOCS"
        assert "engineering" in acl.allowed_groups

    def test_space_key_fallback_format(self):
        """Space key without hyphen is uppercased for prefix lookup."""
        page_data = {
            "id": "12345",
            "title": "Page",
            "space_key": "HR",
        }
        acl = extract_confluence_acl(page_data)
        assert acl.source_permissions.get("space_key") == "HR"
        assert "hr" in acl.allowed_groups

    def test_unknown_space_defaults_to_general(self):
        page_data = {
            "id": "12345",
            "title": "Page",
            "space": {"key": "XYZ"},
        }
        acl = extract_confluence_acl(page_data)
        # "general" department is not added to allowed_groups (filtered out)
        assert "XYZ" not in acl.allowed_groups

    def test_confidential_label(self):
        """Labels like 'confidential' upgrade access_level to internal."""
        page_data = {
            "id": "12345",
            "title": "Confidential Page",
            "space": {"key": "GENERAL"},
            "labels": ["confidential", "roadmap"],
        }
        acl = extract_confluence_acl(page_data)
        assert acl.access_level == "internal"

    def test_no_duplicate_groups(self):
        """Groups are deduplicated."""
        page_data = {
            "id": "12345",
            "title": "Page",
            "space": {"key": "ENG-API"},
            "restrictions": {
                "read": {
                    "restrictions": [
                        {
                            "subjects": [
                                {"identifier": "engineering", "type": "group"},
                            ],
                        },
                    ],
                },
            },
        }
        acl = extract_confluence_acl(page_data)
        assert acl.allowed_groups.count("engineering") == 1


# ── Jira ACL ───────────────────────────────────────────────────────────────


class TestExtractJiraACL:
    def test_public_issue_no_security(self):
        """An issue without security scheme is public."""
        issue_data = {
            "key": "PROJ-1",
            "fields": {
                "project": {"key": "PROJ"},
                "summary": "Test issue",
            },
        }
        acl = extract_jira_acl(issue_data)
        assert acl.access_level == "public"

    def test_restricted_issue_with_security(self):
        """Issue with security scheme is restricted."""
        issue_data = {
            "key": "SEC-1",
            "fields": {
                "project": {"key": "SEC"},
                "security": {
                    "name": "Internal Only",
                    "id": "10000",
                },
            },
        }
        acl = extract_jira_acl(issue_data)
        assert acl.access_level == "restricted"
        assert acl.source_permissions["security_scheme"] == "Internal Only"
        assert acl.source_permissions["security_level"] == "10000"

    def test_project_key_department_mapping(self):
        """Project key prefix maps to department group."""
        issue_data = {
            "key": "ENG-42",
            "fields": {
                "project": {"key": "ENG"},
            },
        }
        acl = extract_jira_acl(issue_data)
        assert "engineering" in acl.allowed_groups

    def test_unknown_project_key(self):
        """Unknown project prefix yields empty department."""
        issue_data = {
            "key": "ABC-1",
            "fields": {
                "project": {"key": "ABC"},
            },
        }
        acl = extract_jira_acl(issue_data)
        # No department mapping for ABC
        assert all(g != "" for g in acl.allowed_groups) or acl.allowed_groups == []

    def test_project_key_from_top_level(self):
        """Falls back to top-level project_key field."""
        issue_data = {
            "key": "HR-10",
            "fields": {},
            "project_key": "HR",
        }
        acl = extract_jira_acl(issue_data)
        assert "hr" in acl.allowed_groups


# ── GitLab ACL ─────────────────────────────────────────────────────────────


class TestExtractGitLabACL:
    def test_public_project(self):
        project_data = {"id": 1, "visibility": "public"}
        acl = extract_gitlab_acl(project_data)
        assert acl.access_level == "public"
        assert acl.source_permissions["visibility"] == "public"

    def test_internal_project(self):
        project_data = {"id": 2, "visibility": "internal"}
        acl = extract_gitlab_acl(project_data)
        assert acl.access_level == "internal"

    def test_private_project_with_members(self):
        project_data = {
            "id": 3,
            "visibility": "private",
            "members": [
                {"type": "User", "username": "alice", "name": "Alice"},
                {"type": "Group", "name": "backend-team", "path": "backend-team"},
                {"type": "User", "username": "bob", "name": "Bob"},
            ],
        }
        acl = extract_gitlab_acl(project_data)
        assert acl.access_level == "restricted"
        assert "backend-team" in acl.allowed_groups
        assert "alice" in acl.allowed_users
        assert "bob" in acl.allowed_users

    def test_private_project_with_members_param(self):
        """Members can be passed as a separate parameter."""
        project_data = {"id": 4, "visibility": "private"}
        members = [
            {"type": "User", "username": "charlie"},
        ]
        acl = extract_gitlab_acl(project_data, members=members)
        assert acl.access_level == "restricted"
        assert "charlie" in acl.allowed_users

    def test_private_project_no_members(self):
        """Private project with no member data still sets restricted."""
        project_data = {"id": 5, "visibility": "private"}
        acl = extract_gitlab_acl(project_data)
        assert acl.access_level == "restricted"
        assert acl.allowed_groups == []
        assert acl.allowed_users == []

    def test_defaults_to_internal(self):
        """Missing visibility defaults to internal."""
        project_data = {"id": 6}
        acl = extract_gitlab_acl(project_data)
        assert acl.access_level == "internal"


# ── Department mapping helpers ─────────────────────────────────────────────


class TestDepartmentMapping:
    def test_space_eng_prefix(self):
        assert map_department_from_space("ENG-DOCS") == "engineering"

    def test_space_hr_prefix(self):
        assert map_department_from_space("HR-ONBOARDING") == "hr"

    def test_space_unknown_prefix(self):
        assert map_department_from_space("XYZ") == "general"

    def test_space_no_hyphen(self):
        assert map_department_from_space("OPS") == "operations"

    def test_space_empty(self):
        assert map_department_from_space("") == "general"

    def test_project_eng_prefix(self):
        assert map_department_from_project("ENG") == "engineering"

    def test_project_fin_prefix(self):
        assert map_department_from_project("FIN-2024") == "finance"

    def test_project_unknown(self):
        assert map_department_from_project("ABC") == ""

    def test_project_empty(self):
        assert map_department_from_project("") == ""


# ── ExtractedDocument ACL fields ───────────────────────────────────────────


class TestExtractedDocumentACL:
    def test_default_acl_fields(self):
        doc = ExtractedDocument(
            source_id="1",
            source_type="confluence",
            title="Test",
            content="Hello",
            content_type="text",
        )
        assert doc.access_level == "internal"
        assert doc.allowed_groups == []
        assert doc.allowed_users == []

    def test_custom_acl_fields(self):
        doc = ExtractedDocument(
            source_id="1",
            source_type="jira",
            title="Issue",
            content="Body",
            content_type="text",
            access_level="restricted",
            allowed_groups=["engineering", "security"],
            allowed_users=["alice"],
        )
        assert doc.access_level == "restricted"
        assert doc.allowed_groups == ["engineering", "security"]
        assert doc.allowed_users == ["alice"]


# ── ACL propagation to chunks ──────────────────────────────────────────────


class TestACLPropagationToChunks:
    def test_chunk_from_source_metadata_with_acl(self):
        """SemanticChunker._create_chunk propagates ACL from source_metadata."""
        chunker = SemanticChunker()
        source_metadata = {
            "source_type": "confluence",
            "source_id": "12345",
            "doc_title": "Test Page",
            "access_level": "restricted",
            "allowed_groups": ["engineering", "security"],
            "allowed_users": ["alice"],
        }
        chunk = chunker._create_chunk("Hello world", 0, source_metadata, "Section 1")

        assert chunk.access_level == "restricted"
        assert chunk.allowed_groups == ["engineering", "security"]
        assert chunk.allowed_users == ["alice"]

    def test_chunk_defaults_to_public_without_acl(self):
        """Chunks default to public when source_metadata has no ACL."""
        chunker = SemanticChunker()
        source_metadata = {
            "source_type": "confluence",
            "source_id": "12345",
            "doc_title": "Test Page",
        }
        chunk = chunker._create_chunk("Hello world", 0, source_metadata, "Section 1")

        assert chunk.access_level == "public"
        assert chunk.allowed_groups == []
        assert chunk.allowed_users == []

    def test_md_key_chunker_propagates_acl(self):
        """MDKeyChunker propagates ACL from source_metadata to all chunks."""
        base_chunker = SemanticChunker(max_tokens=5000, contextual_enrichment=False)
        enricher = MetadataEnricher()
        md_chunker = MDKeyChunker(base_chunker, enricher)

        source_metadata = {
            "source_type": "confluence",
            "source_id": "12345",
            "doc_title": "Test Page",
            "access_level": "internal",
            "allowed_groups": ["engineering"],
            "allowed_users": [],
        }
        markdown = "# Title\n\nSome content here.\n\n## Section\n\nMore content."
        chunks = md_chunker.process_document(markdown, "markdown", source_metadata)

        assert len(chunks) > 0
        for chunk in chunks:
            assert chunk.access_level == "internal"
            assert "engineering" in chunk.allowed_groups

    def test_acl_mutation_isolation(self):
        """Mutating source_metadata lists after chunking doesn't affect chunks."""
        chunker = SemanticChunker()
        groups = ["engineering"]
        source_metadata = {
            "source_type": "confluence",
            "source_id": "1",
            "doc_title": "T",
            "access_level": "restricted",
            "allowed_groups": groups,
            "allowed_users": [],
        }
        chunk = chunker._create_chunk("text", 0, source_metadata, "H")
        # Mutate the original list
        groups.append("security")
        assert "security" not in chunk.allowed_groups

    def test_chunk_acl_round_trip_to_dict(self):
        """ACL fields survive Chunk → dict conversion (for Qdrant payload)."""
        chunk = Chunk(
            text="test",
            hash="abc",
            access_level="restricted",
            allowed_groups=["engineering"],
            allowed_users=["alice"],
        )
        d = asdict(chunk)
        assert d["access_level"] == "restricted"
        assert d["allowed_groups"] == ["engineering"]
        assert d["allowed_users"] == ["alice"]
