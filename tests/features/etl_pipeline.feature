Feature: ETL Pipeline
  As a data engineer
  I want to extract, transform, and load documents from various sources
  So that the knowledge base stays up to date

  Scenario: Confluence extraction
    Given a Confluence space "ENG" with 10 pages
    When I run the Confluence extractor
    Then 10 documents are extracted
    And each document has title, content, source_type="confluence"
    And each document has ACL metadata from space permissions

  Scenario: Incremental extraction with WAL
    Given a previous ETL run completed 50% before failure
    When I restart the ETL pipeline
    Then extraction resumes from the checkpoint
    And only remaining documents are processed

  Scenario: Semantic chunking
    Given a document with 5 headings and 20 paragraphs
    When I chunk the document
    Then chunks preserve heading context
    And chunks have 50-100 token overlap
    And no chunk breaks mid-sentence

  Scenario: SHA-256 content deduplication
    Given a document that was already indexed
    When I re-index the same document without changes
    Then no duplicate chunks are created
    And the existing chunks are preserved

  Scenario: Multi-source indexing
    Given documents from Confluence, Jira, and GitLab
    When I run the full ETL pipeline
    Then all documents are indexed in Qdrant
    And each document has correct source_type metadata
    And the graph is updated with extracted entities

  Scenario: Embedding generation
    Given a chunk of text
    When I generate embeddings
    Then the dense vector has 1024 dimensions
    And the sparse vector has lexical features
