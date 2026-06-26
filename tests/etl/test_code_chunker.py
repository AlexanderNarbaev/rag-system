"""Tests for etl/chunker/code_chunker.py."""
import pytest

from etl.chunker.code_chunker import (
    CodeChunk,
    CODE_CHUNKING_ENABLED,
    AST_LANGUAGES,
    chunk_python,
    chunk_javascript,
    chunk_java,
    chunk_code,
)


class TestCodeChunk:
    def test_creation_defaults(self):
        cc = CodeChunk(name="my_func", code="def my_func(): pass", language="python")
        assert cc.name == "my_func"
        assert cc.code == "def my_func(): pass"
        assert cc.language == "python"
        assert cc.docstring == ""
        assert cc.line_start == 0
        assert cc.line_end == 0

    def test_creation_with_docstring(self):
        cc = CodeChunk(
            name="my_func",
            code='def my_func():\n    """Docs."""\n    pass',
            language="python",
            docstring="Docs.",
            line_start=1,
            line_end=3,
        )
        assert cc.docstring == "Docs."
        assert cc.line_start == 1
        assert cc.line_end == 3

    def test_repr(self):
        cc = CodeChunk(name="foo", code="def foo(): pass", language="python")
        r = repr(cc)
        assert "foo" in r
        assert "python" in r


class TestChunkPython:
    def test_simple_function(self):
        source = "def hello():\n    return 'world'\n"
        chunks = chunk_python(source)
        assert len(chunks) == 1
        assert chunks[0].name == "hello"
        assert "hello" in chunks[0].code

    def test_function_with_docstring(self):
        source = 'def add(a, b):\n    """Add two numbers."""\n    return a + b\n'
        chunks = chunk_python(source)
        assert len(chunks) == 1
        assert chunks[0].name == "add"
        assert "Add two numbers" in chunks[0].docstring

    def test_class_with_method(self):
        source = "class Calculator:\n    def add(self, a, b):\n        return a + b\n"
        chunks = chunk_python(source)
        assert len(chunks) == 1
        assert chunks[0].name == "Calculator"

    def test_multiple_functions(self):
        source = "def foo():\n    pass\n\ndef bar():\n    pass\n"
        chunks = chunk_python(source)
        assert len(chunks) == 2

    def test_empty_source(self):
        assert chunk_python("") == []

    def test_no_functions(self):
        source = "x = 1\ny = 2\nprint(x + y)\n"
        chunks = chunk_python(source)
        assert len(chunks) == 0

    def test_async_function(self):
        source = "async def fetch(url):\n    return await get(url)\n"
        chunks = chunk_python(source)
        assert len(chunks) == 1
        assert "async" in chunks[0].code
        assert chunks[0].name == "fetch"

    def test_nested_function_ignored(self):
        source = "def outer():\n    def inner():\n        pass\n    return inner\n"
        chunks = chunk_python(source)
        assert len(chunks) == 1
        assert chunks[0].name == "outer"

    def test_decorator_preserved(self):
        source = "@staticmethod\ndef static_method():\n    return 42\n"
        chunks = chunk_python(source)
        assert len(chunks) == 1
        assert "@staticmethod" in chunks[0].code


class TestChunkJavascript:
    def test_simple_function(self):
        source = "function hello() {\n  return 'world';\n}\n"
        chunks = chunk_javascript(source)
        assert len(chunks) == 1
        assert chunks[0].name == "hello"

    def test_arrow_function(self):
        source = "const add = (a, b) => a + b;\n"
        chunks = chunk_javascript(source)
        assert len(chunks) == 1
        assert "add" in chunks[0].name.lower()

    def test_class_with_method(self):
        source = "class Calculator {\n  add(a, b) {\n    return a + b;\n  }\n}\n"
        chunks = chunk_javascript(source)
        assert len(chunks) == 1
        assert chunks[0].name == "Calculator"

    def test_empty_source(self):
        assert chunk_javascript("") == []

    def test_async_function(self):
        source = "async function fetchData(url) {\n  return await fetch(url);\n}\n"
        chunks = chunk_javascript(source)
        assert len(chunks) == 1
        assert chunks[0].name == "fetchData"

    def test_export_function(self):
        source = "export function greet(name) {\n  return `Hello ${name}`;\n}\n"
        chunks = chunk_javascript(source)
        assert len(chunks) == 1
        assert chunks[0].name == "greet"

    def test_jsdoc_comment(self):
        source = "/**\n * Add two numbers.\n */\nfunction add(a, b) {\n  return a + b;\n}\n"
        chunks = chunk_javascript(source)
        assert len(chunks) == 1
        assert "Add two numbers" in chunks[0].docstring


class TestChunkJava:
    def test_simple_method(self):
        source = "public class Hello {\n  public void greet() {\n    System.out.println(\"Hi\");\n  }\n}\n"
        chunks = chunk_java(source)
        assert len(chunks) >= 2  # class + method

    def test_static_method(self):
        source = """
        public class MathUtils {
            public static int add(int a, int b) {
                return a + b;
            }
        }
        """
        chunks = chunk_java(source)
        assert any("add" in c.name for c in chunks)

    def test_empty_source(self):
        assert chunk_java("") == []

    def test_interface(self):
        source = "public interface Repository {\n  List<Item> findAll();\n}\n"
        chunks = chunk_java(source)
        assert len(chunks) >= 1
        assert any("Repository" in c.name for c in chunks)

    def test_javadoc_comment(self):
        source = """
        /**
         * Calculate the sum.
         * @param a first number
         * @param b second number
         */
        public int sum(int a, int b) {
            return a + b;
        }
        """
        chunks = chunk_java(source)
        assert any("Calculate the sum" in c.docstring for c in chunks)


class TestChunkCode:
    def test_dispatches_python(self):
        source = "def foo():\n    pass\n"
        chunks = chunk_code(source, "python")
        assert len(chunks) == 1
        assert chunks[0].name == "foo"

    def test_dispatches_javascript(self):
        source = "function bar() {\n  return 1;\n}\n"
        chunks = chunk_code(source, "javascript")
        assert len(chunks) == 1

    def test_dispatches_java(self):
        source = "public class Foo {\n  public void m() {}\n}\n"
        chunks = chunk_code(source, "java")
        assert len(chunks) >= 1

    def test_unknown_language_returns_empty(self):
        chunks = chunk_code("some code", "ruby")
        assert chunks == []

    def test_disabled_chunking(self):
        import etl.chunker.code_chunker as mod

        original = mod.CODE_CHUNKING_ENABLED
        mod.CODE_CHUNKING_ENABLED = False
        try:
            chunks = chunk_code("def f(): pass", "python")
            assert chunks == []
        finally:
            mod.CODE_CHUNKING_ENABLED = original


class TestConfigFlags:
    def test_ast_languages(self):
        assert "python" in AST_LANGUAGES
        assert "javascript" in AST_LANGUAGES
        assert "java" in AST_LANGUAGES

    def test_code_chunking_enabled(self):
        assert CODE_CHUNKING_ENABLED in (True, False)
