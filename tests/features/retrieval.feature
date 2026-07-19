Feature: Hybrid Retrieval
  As a RAG system
  I want to find relevant documents using multiple search methods
  So that I can provide accurate answers

  Scenario: Hybrid search with RRF
    Given documents in the knowledge base about "machine learning"
    When I search for "deep learning algorithms"
    Then I get results from both dense and sparse search
    And results are ranked by RRF score
    And the top result has the highest RRF score

  Scenario: Version filtering
    Given documents with versions "v1" and "v2"
    When I search with rag_version="v1"
    Then all results have version "v1"

  Scenario: ACL filtering
    Given a document with access_level="restricted" and allowed_groups=["engineering"]
    And a user "alice" in group "engineering"
    And a user "bob" in group "marketing"
    When "alice" searches
    Then the restricted document is in results
    When "bob" searches
    Then the restricted document is not in results

  Scenario: Graph expansion
    Given Neo4j contains entity relationships
    When I search for a query matching an entity
    Then graph-expanded context is included in results
    And related entities are surfaced

  Scenario: Reranking improves relevance
    Given initial search results with raw scores
    When results are reranked by the cross-encoder
    Then the reranked order differs from raw scores
    And more relevant results move higher

  Scenario: Empty query returns no results
    When I search with an empty query
    Then I get 0 results
    And no error is raised
