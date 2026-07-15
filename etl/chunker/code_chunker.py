# etl/chunker/code_chunker.py
"""AST-aware and regex-based code chunking for Python, JavaScript, and Java."""

import ast
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger (__name__)

CODE_CHUNKING_ENABLED = True
AST_LANGUAGES = ["python", "javascript", "java"]


@dataclass
class CodeChunk:
  name: str
  code: str
  language: str
  docstring: str = ""
  line_start: int = 0
  line_end: int = 0


def _extract_python_docstring (node: ast.AST) -> str:
  if isinstance (node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
    doc = ast.get_docstring (node)
    return doc or ""
  return ""


def chunk_python (source: str) -> list [CodeChunk]:
  """Split Python source by top-level functions and classes using AST."""
  if not source.strip ():
    return []

  try:
    tree = ast.parse (source)
  except SyntaxError:
    logger.warning ("Python AST parse failed, falling back to regex")
    return _chunk_python_regex (source)

  lines = source.splitlines ()
  chunks = []

  for node in ast.iter_child_nodes (tree):
    if isinstance (node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
      start = node.lineno - 1
      if node.decorator_list:
        start = min (d.lineno for d in node.decorator_list) - 1
      end = node.end_lineno if hasattr (node, "end_lineno") and node.end_lineno else start + 1
      code = "\n".join (lines [start:end])
      docstring = _extract_python_docstring (node)
      chunks.append (
          CodeChunk (name = node.name, code = code, language = "python", docstring = docstring, line_start = start + 1,
              line_end = end if isinstance (end, int) else start + 1, ))

  return chunks


def _chunk_python_regex (source: str) -> list [CodeChunk]:
  """Fallback regex-based Python chunking."""
  chunks = []
  patterns = [
      (r"(?:@\w+\n\s*)*(?:async\s+)?def\s+(\w+)\s*\([^)]*\)\s*:(?:\n(?:[ \t].*\n?)*)*", "function"),
      (r"class\s+(\w+)\s*(?:\([^)]*\))?\s*:(?:\n(?:[ \t].*\n?)*)*", "class"),
  ]
  for pattern, _kind in patterns:
    for match in re.finditer (pattern, source, re.MULTILINE):
      name = match.group (1)
      code = match.group (0)
      chunks.append (CodeChunk (name = name, code = code, language = "python"))
  return chunks


def chunk_javascript (source: str) -> list [CodeChunk]:
  """Split JavaScript source by functions and classes using regex."""
  if not source.strip ():
    return []

  chunks = []
  seen_names = set ()

  patterns = [
      (
          r"/\*\*(.*?)\*/\s*\n\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\([^)]*\)\s*\{(?:[^{}]|\{[^{}]*\})*\}",
          True,
      ),  # noqa: E501
      (r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\([^)]*\)\s*\{(?:[^{}]|\{[^{}]*\})*\}", False),
      (r"(?:export\s+)?class\s+(\w+)\s*(?:extends\s+\w+\s*)?\{(?:[^{}]|\{[^{}]*\})*\}", False),
      (r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{(?:[^{}]|\{[^{}]*\})*\}", False),
      (r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>\s*[^;]+;", False),
  ]

  for pattern, has_jsdoc in patterns:
    for match in re.finditer (pattern, source, re.MULTILINE | re.DOTALL):
      if has_jsdoc:
        docstring = match.group (1).strip ()
        doc_lines = [re.sub (r"^\s*\*\s?", "", line).strip () for line in docstring.splitlines () if
            line.strip () and not line.strip ().startswith ("* @")]
        docstring = " ".join (doc_lines).strip ()
        name = match.group (2)
      else:
        name = match.group (1)
        docstring = ""

      if name in seen_names:
        continue
      seen_names.add (name)

      code = match.group (0)
      chunks.append (CodeChunk (name = name, code = code, language = "javascript", docstring = docstring, ))

  return chunks


def chunk_java (source: str) -> list [CodeChunk]:
  """Split Java source by classes, interfaces, and methods using regex."""
  if not source.strip ():
    return []

  chunks = []

  class_pattern = (r"(?:/\*\*(.*?)\*/\s*\n\s*)?(?:public\s+)?(?:abstract\s+)?(?:class|interface|enum)\s+(\w+)\s*("
                   r"?:extends\s+\w+\s*)?(?:implements\s+[^{]+\s*)?\{(?:[^{}]|\{[^{}]*\})*\}")  # noqa: E501
  for match in re.finditer (class_pattern, source, re.MULTILINE | re.DOTALL):
    groups = match.groups ()
    docstring = ""
    _name_idx = 1
    if groups [0] is not None:
      docstring = groups [0].strip ()
      doc_lines = [re.sub (r"^\s*\*\s?", "", line).strip () for line in docstring.splitlines () if
          line.strip () and not line.strip ().startswith ("* @")]
      docstring = " ".join (doc_lines).strip ()
      name = groups [2] if len (groups) > 2 else groups [1]
    else:
      name = groups [1]
    code = match.group (0)
    chunks.append (CodeChunk (name = name, code = code, language = "java", docstring = docstring))

  method_pattern = (r"(?:/\*\*(.*?)\*/\s*\n\s*)?(?:public|private|protected|static|\s)*\s+(\w+(?:<[^>]+>)?)\s+("
                    r"\w+)\s*\([^)]*\)\s*(?:\{|throws[^{]*\{)(?:[^{}]|\{[^{}]*\})*\}")  # noqa: E501
  for match in re.finditer (method_pattern, source, re.MULTILINE | re.DOTALL):
    javadoc_group = match.group (1)
    _return_type = match.group (2)
    name = match.group (3)
    if javadoc_group:
      doc_lines = [re.sub (r"^\s*\*\s?", "", line).strip () for line in javadoc_group.splitlines () if
          line.strip () and not line.strip ().startswith ("* @")]
      docstring = " ".join (doc_lines).strip ()
    else:
      docstring = ""
    code = match.group (0)
    chunks.append (CodeChunk (name = name, code = code, language = "java", docstring = docstring))

  return chunks


def chunk_code (source: str, language: str) -> list [CodeChunk]:
  """Dispatch to the appropriate language chunker.

  :param source: source code string
  :param language: one of 'python', 'javascript', 'java'
  :return: list of CodeChunk objects
  """
  if not CODE_CHUNKING_ENABLED:
    return []

  lang = language.lower ()
  if lang == "python":
    return chunk_python (source)
  elif lang in ("javascript", "js"):
    return chunk_javascript (source)
  elif lang == "java":
    return chunk_java (source)
  else:
    logger.debug ("No chunker for language: %s", lang)
    return []
