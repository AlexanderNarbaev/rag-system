Feature: Chat Completion with RAG
  As a corporate user
  I want to ask questions and get answers from the knowledge base
  So that I can find information quickly

  Background:
    Given the RAG system is running
    And the knowledge base contains documents

  Scenario: Non-streaming chat with RAG
    When I send a chat request with model "qwen3-635b+RAG" and message "What is RAG?"
    Then I receive a response with status 200
    And the response contains "choices" with 1 item
    And the response contains "rag_feedback_id"
    And the response contains "rag_confidence" between 0 and 1
    And the response contains "rag_sources"

  Scenario: Streaming chat with RAG
    When I send a streaming chat request with model "qwen3-635b+RAG" and message "Explain RAG"
    Then I receive SSE events
    And each event starts with "data: "
    And the stream ends with "data: [DONE]"

  Scenario: Chat without knowledge base
    Given the knowledge base is empty
    When I send a chat request with model "qwen3-635b+RAG" and message "What is quantum computing?"
    Then the response contains an ungrounded notice
    And the response contains "rag_knowledge_status" as "absent"
    And the response contains "rag_clarifying_questions"

  Scenario: Direct model passthrough
    When I send a chat request with model "qwen3-635b" and message "Hello"
    Then I receive a response with status 200
    And the response does not contain "rag_sources"

  Scenario: RAG-specific parameters are accepted
    When I send a chat request with model "qwen3-635b+RAG" and message "What is CI/CD?"
      And I set rag_top_k to 3
      And I set rag_return_chunks to true
    Then I receive a response with status 200
    And the response contains "rag_sources" with at most 3 items

  Scenario: Force refresh bypasses cache
    When I send a chat request with model "qwen3-635b+RAG" and message "What is RAG?"
      And I set rag_force_refresh to true
    Then I receive a response with status 200
    And the response is freshly generated
