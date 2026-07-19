Feature: Authentication and Authorization
  As a system administrator
  I want to control who can access the system
  So that sensitive data is protected

  Scenario: JWT login
    Given a user "alice" with password "secret123"
    When I POST to "/v1/auth/login" with credentials
    Then I receive an access token and refresh token
    And the access token expires in 15 minutes

  Scenario: API key authentication
    Given an API key "sk-test-key-123"
    When I send a request with Authorization header "Bearer sk-test-key-123"
    Then the request is authenticated
    And the user context has the API key's user

  Scenario: RBAC enforcement
    Given a user "bob" with role "user"
    When I try to access "/v1/admin/models"
    Then I receive status 403

  Scenario: Rate limiting
    Given rate limiting is enabled with 60 requests per minute
    When I send 61 requests in 1 minute
    Then the 61st request returns status 429

  Scenario: Token refresh
    Given a valid refresh token
    When I POST to "/v1/auth/refresh" with the refresh token
    Then I receive a new access token and refresh token
    And the old refresh token is invalidated

  Scenario: Logout revokes tokens
    Given a logged-in user with access token
    When I POST to "/v1/auth/logout"
    Then the access token is blacklisted
    And all refresh tokens for the user are revoked
