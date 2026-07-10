"""Tests for proxy/app/sanitizer.py — input sanitization for SQL injection, XSS, length limits."""

from proxy.app.shared.sanitizer import sanitize_feedback, sanitize_query, validate_length


class TestSanitizeQuery:
    def test_plain_text_passes_through(self):
        assert sanitize_query("What is RAG?") == "What is RAG?"

    def test_strips_sql_select_injection(self):
        result = sanitize_query("SELECT * FROM users; DROP TABLE users;")
        assert "DROP" not in result.upper()
        assert "SELECT" not in result.upper()

    def test_strips_sql_union_injection(self):
        result = sanitize_query("1' UNION SELECT password FROM users--")
        assert "UNION" not in result.upper()

    def test_strips_sql_comment_injection(self):
        result = sanitize_query("admin'--")
        assert "--" not in result

    def test_strips_sql_or_injection(self):
        result = sanitize_query("' OR '1'='1")
        assert "OR 1" not in result

    def test_strips_sql_drop(self):
        result = sanitize_query("hello; DROP TABLE documents;")
        assert "DROP" not in result.upper()

    def test_strips_sql_insert(self):
        result = sanitize_query("INSERT INTO logs VALUES ('hack')")
        assert "INSERT" not in result.upper()

    def test_strips_sql_delete(self):
        result = sanitize_query("DELETE FROM knowledge_base WHERE 1=1")
        assert "DELETE" not in result.upper()

    def test_strips_sql_update(self):
        result = sanitize_query("UPDATE users SET role='admin' WHERE id=1")
        assert "UPDATE" not in result.upper()

    def test_strips_sql_exec(self):
        result = sanitize_query("EXEC sp_configure 'xp_cmdshell', 1")
        assert "EXEC" not in result.upper()

    def test_strips_semicolons(self):
        result = sanitize_query("hello; world")
        assert ";" not in result

    def test_html_tags_stripped(self):
        result = sanitize_query("<script>alert('xss')</script>search query")
        assert "<script>" not in result
        assert "search query" in result

    def test_empty_string(self):
        assert sanitize_query("") == ""

    def test_none_input(self):
        assert sanitize_query(None) == ""

    def test_only_sql_keywords(self):
        result = sanitize_query("SELECT DROP UNION DELETE")
        assert result == ""

    def test_mixed_safe_and_unsafe(self):
        result = sanitize_query("How to SELECT data from DROP TABLE?")
        assert "How to" in result
        assert "SELECT" not in result.upper()

    def test_strips_dql_injection(self):
        result = sanitize_query("{ $where: function() { return true; } }")
        assert "function()" not in result

    def test_strips_sql_truncate(self):
        result = sanitize_query("TRUNCATE TABLE users")
        assert "TRUNCATE" not in result.upper()

    def test_strips_sql_alter(self):
        result = sanitize_query("ALTER TABLE users ADD COLUMN password TEXT")
        assert "ALTER" not in result.upper()

    def test_collapses_whitespace(self):
        result = sanitize_query("hello    world\n\ttest")
        assert result == "hello world test"


class TestSanitizeFeedback:
    def test_plain_text_passes(self):
        assert sanitize_feedback("Great answer!") == "Great answer!"

    def test_strips_html_tags(self):
        result = sanitize_feedback("<p>Good <b>answer</b></p>")
        assert "<p>" not in result
        assert "<b>" not in result
        assert "Good" in result
        assert "answer" in result

    def test_strips_script_tags(self):
        result = sanitize_feedback("<script>alert('xss')</script>feedback")
        assert "<script>" not in result

    def test_strips_event_handlers(self):
        result = sanitize_feedback('<img src=x onerror="alert(1)">')
        assert "onerror" not in result.lower()

    def test_strips_javascript_protocol(self):
        result = sanitize_feedback('<a href="javascript:alert(1)">click</a>')
        assert "javascript:" not in result.lower()
        assert "click" in result

    def test_empty_string(self):
        assert sanitize_feedback("") == ""

    def test_none_input(self):
        assert sanitize_feedback(None) == ""

    def test_preserves_urls(self):
        result = sanitize_feedback("See https://docs.example.com for more info")
        assert "https://docs.example.com" in result

    def test_strips_iframe(self):
        result = sanitize_feedback('<iframe src="http://evil.com"></iframe>')
        assert "iframe" not in result.lower()

    def test_strips_css_expression(self):
        result = sanitize_feedback('<div style="expression(alert(1))">text</div>')
        assert "expression" not in result.lower()
        assert "text" in result

    def test_strips_onload_attribute(self):
        result = sanitize_feedback('<body onload="evil()">content</body>')
        assert "onload" not in result.lower()

    def test_unicode_normal_text_preserved(self):
        result = sanitize_feedback("Привет, как дела?")
        assert result == "Привет, как дела?"


class TestValidateLength:
    def test_within_limit(self):
        result = validate_length("hello", max_len=10)
        assert result == "hello"

    def test_exceeds_limit_truncates(self):
        result = validate_length("hello world", max_len=5)
        assert len(result) <= 5
        assert result == "hello"

    def test_exact_limit(self):
        result = validate_length("hello", max_len=5)
        assert result == "hello"

    def test_zero_max_len(self):
        result = validate_length("hello", max_len=0)
        assert result == ""

    def test_negative_max_len(self):
        result = validate_length("hello", max_len=-1)
        assert result == ""

    def test_empty_string(self):
        result = validate_length("", max_len=10)
        assert result == ""

    def test_none_input(self):
        result = validate_length(None, max_len=10)
        assert result == ""

    def test_default_max_len(self):
        result = validate_length("A" * 10000, max_len=8000)
        assert len(result) <= 8000

    def test_non_string_input(self):
        result = validate_length(12345, max_len=10)
        assert result == ""
