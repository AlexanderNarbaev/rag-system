Feature: Answer Quality Assurance
  As a quality engineer
  I want to ensure answers are grounded and accurate
  So that users can trust the system

  Scenario: Grounding verification
    Given a response generated from context
    When I verify grounding
    Then the grounding score is >= 0.70
    And the response is marked as well-grounded

  Scenario: Hallucination detection
    Given a response with claims not in the context
    When I check for hallucinations
    Then unsupported claims are flagged
    And hallucination_score > 0

  Scenario: Corrective re-generation
    Given a response with confidence < 0.5
    When the system triggers re-generation
    Then the context is expanded
    And the prompt is modified
    And a new response is generated

  Scenario: Confidence scoring
    Given a response with high-quality retrieval results
    When confidence is calculated
    Then the confidence score is >= 0.8
    And the confidence factors are returned

  Scenario: Expert feedback collection
    Given a response with rag_feedback_id
    When an expert submits positive feedback
    Then the feedback is stored
    And the response quality metrics are updated

  Scenario: Retrieval quality metrics
    Given a set of test queries with known answers
    When retrieval is evaluated
    Then MRR >= 0.7
    And Recall@5 >= 0.8
    And nDCG >= 0.75
