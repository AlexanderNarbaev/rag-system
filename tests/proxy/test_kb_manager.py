# tests/proxy/test_kb_manager.py
"""Tests for KnowledgeBaseManager — SQLite-backed KB management."""

import os
import tempfile

import pytest

from proxy.app.core.kb_manager import ETLTask, KnowledgeBase, KnowledgeBaseManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kb_manager (tmp_path):
  """Create a KBManager with a temporary database."""
  db_path = str (tmp_path / "test_kb.db")
  return KnowledgeBaseManager (db_path = db_path, qdrant_client = None)


@pytest.fixture
def sample_kb (kb_manager):
  """Create a sample knowledge base."""
  return kb_manager.create_kb (
      name = "Test KB", description = "A test knowledge base",
      embedding_model = "BAAI/bge-m3", dense_vector_size = 1024,
  )


# ---------------------------------------------------------------------------
# Knowledge Base CRUD tests
# ---------------------------------------------------------------------------


class TestKnowledgeBaseCRUD:
  """Test KB create, read, update, delete operations."""
  
  def test_create_kb (self, kb_manager):
    kb = kb_manager.create_kb (name = "Production Docs", description = "Production documentation")
    assert kb.name == "Production Docs"
    assert kb.description == "Production documentation"
    assert kb.status == "active"
    assert kb.id  # UUID generated
    assert kb.collection_name  # collection name generated
  
  def test_create_kb_duplicate_name (self, kb_manager):
    kb_manager.create_kb (name = "Unique KB")
    with pytest.raises (ValueError, match = "already exists"):
      kb_manager.create_kb (name = "Unique KB")
  
  def test_get_kb (self, kb_manager, sample_kb):
    retrieved = kb_manager.get_kb (sample_kb.id)
    assert retrieved is not None
    assert retrieved.name == sample_kb.name
    assert retrieved.id == sample_kb.id
  
  def test_get_kb_not_found (self, kb_manager):
    assert kb_manager.get_kb ("nonexistent-id") is None
  
  def test_get_kb_by_name (self, kb_manager, sample_kb):
    retrieved = kb_manager.get_kb_by_name (sample_kb.name)
    assert retrieved is not None
    assert retrieved.id == sample_kb.id
  
  def test_list_kbs (self, kb_manager):
    kb_manager.create_kb (name = "KB One")
    kb_manager.create_kb (name = "KB Two")
    kb_manager.create_kb (name = "KB Three")
    kbs = kb_manager.list_kbs ()
    assert len (kbs) == 3
  
  def test_list_kbs_excludes_deleted (self, kb_manager):
    kb1 = kb_manager.create_kb (name = "Active KB")
    kb2 = kb_manager.create_kb (name = "To Delete")
    kb_manager.delete_kb (kb2.id)
    kbs = kb_manager.list_kbs ()
    assert len (kbs) == 1
    assert kbs [0].id == kb1.id
  
  def test_list_kbs_includes_deleted (self, kb_manager):
    kb_manager.create_kb (name = "Active KB")
    kb2 = kb_manager.create_kb (name = "To Delete")
    kb_manager.delete_kb (kb2.id)
    kbs = kb_manager.list_kbs (include_deleted = True)
    assert len (kbs) == 2
  
  def test_update_kb (self, kb_manager, sample_kb):
    updated = kb_manager.update_kb (sample_kb.id, name = "Updated Name", description = "New description")
    assert updated.name == "Updated Name"
    assert updated.description == "New description"
  
  def test_update_kb_invalid_field (self, kb_manager, sample_kb):
    # Should silently ignore invalid fields
    updated = kb_manager.update_kb (sample_kb.id, name = "Valid Update")
    assert updated.name == "Valid Update"
  
  def test_soft_delete (self, kb_manager, sample_kb):
    assert kb_manager.delete_kb (sample_kb.id) is True
    # Should not be found by default
    assert kb_manager.get_kb (sample_kb.id) is None
    # But should be found with include_deleted
    kbs = kb_manager.list_kbs (include_deleted = True)
    assert len (kbs) == 1
    assert kbs [0].status == "deleted"


# ---------------------------------------------------------------------------
# ETL Task tests
# ---------------------------------------------------------------------------


class TestETLTaskManagement:
  """Test ETL task creation and tracking."""
  
  def test_create_task (self, kb_manager, sample_kb):
    task = kb_manager.create_task (kb_id = sample_kb.id, source_type = "confluence", source_id = "page-123")
    assert task.kb_id == sample_kb.id
    assert task.source_type == "confluence"
    assert task.source_id == "page-123"
    assert task.status == "pending"
    assert task.progress == 0.0
  
  def test_update_task (self, kb_manager, sample_kb):
    task = kb_manager.create_task (kb_id = sample_kb.id, source_type = "jira", source_id = "ISSUE-42")
    kb_manager.update_task (task.id, status = "running", progress = 0.5)
    updated = kb_manager.get_task (task.id)
    assert updated.status == "running"
    assert updated.progress == 0.5
  
  def test_update_task_with_error (self, kb_manager, sample_kb):
    task = kb_manager.create_task (kb_id = sample_kb.id, source_type = "gitlab", source_id = "proj-1")
    kb_manager.update_task (task.id, status = "failed", error_message = "Connection timeout")
    updated = kb_manager.get_task (task.id)
    assert updated.status == "failed"
    assert updated.error_message == "Connection timeout"
  
  def test_list_tasks_by_kb (self, kb_manager, sample_kb):
    kb_manager.create_task (kb_id = sample_kb.id, source_type = "confluence", source_id = "p1")
    kb_manager.create_task (kb_id = sample_kb.id, source_type = "jira", source_id = "i1")
    tasks = kb_manager.list_tasks (kb_id = sample_kb.id)
    assert len (tasks) == 2
  
  def test_list_tasks_by_status (self, kb_manager, sample_kb):
    t1 = kb_manager.create_task (kb_id = sample_kb.id, source_type = "confluence", source_id = "p1")
    kb_manager.create_task (kb_id = sample_kb.id, source_type = "jira", source_id = "i1")
    kb_manager.update_task (t1.id, status = "completed")
    completed = kb_manager.list_tasks (kb_id = sample_kb.id, status = "completed")
    assert len (completed) == 1
    assert completed [0].id == t1.id
  
  def test_get_task_not_found (self, kb_manager):
    assert kb_manager.get_task ("nonexistent") is None


# ---------------------------------------------------------------------------
# Statistics tests
# ---------------------------------------------------------------------------


class TestKBStatistics:
  """Test KB statistics tracking."""
  
  def test_update_kb_stats (self, kb_manager, sample_kb):
    # Create some tasks
    t1 = kb_manager.create_task (kb_id = sample_kb.id, source_type = "confluence", source_id = "p1")
    t2 = kb_manager.create_task (kb_id = sample_kb.id, source_type = "jira", source_id = "i1")
    kb_manager.update_task (t1.id, status = "completed")
    kb_manager.update_task (t2.id, status = "completed")
    
    kb_manager.update_kb_stats (sample_kb.id)
    kb = kb_manager.get_kb (sample_kb.id)
    assert kb.doc_count == 2


# ---------------------------------------------------------------------------
# Data model tests
# ---------------------------------------------------------------------------


class TestDataModels:
  """Test data model classes."""
  
  def test_knowledge_base_defaults (self):
    kb = KnowledgeBase (id = "test", name = "Test", collection_name = "test_collection")
    assert kb.status == "active"
    assert kb.doc_count == 0
    assert kb.embedding_model == "BAAI/bge-m3"
  
  def test_etl_task_defaults (self):
    task = ETLTask (id = "test", kb_id = "kb-1", source_type = "confluence", source_id = "page-1")
    assert task.status == "pending"
    assert task.progress == 0.0
    assert task.error_message == ""
