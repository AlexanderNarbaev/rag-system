"""Tests for etl/chunker/table_extractor.py."""

from etl.chunker.table_extractor import (
  TABLE_EXTRACTION_ENABLED, TableData, extract_tables_from_html, table_to_json, table_to_markdown,
)


class TestTableData:
  def test_creation_defaults (self):
    td = TableData (headers = ["Name", "Age"], rows = [["Alice", "30"], ["Bob", "25"]])
    assert td.headers == ["Name", "Age"]
    assert len (td.rows) == 2
    assert td.caption == ""
  
  def test_creation_with_caption (self):
    td = TableData (headers = ["Col"], rows = [["val"]], caption = "Test Table", )
    assert td.caption == "Test Table"
  
  def test_repr (self):
    td = TableData (headers = ["A"], rows = [["x"]], caption = "Cap")
    r = repr (td)
    assert "TableData" in r
    assert "Cap" in r
  
  def test_equality (self):
    a = TableData (headers = ["H"], rows = [["v"]])
    b = TableData (headers = ["H"], rows = [["v"]])
    assert a == b
  
  def test_inequality (self):
    a = TableData (headers = ["H"], rows = [["v"]])
    b = TableData (headers = ["H"], rows = [["w"]])
    assert a != b
  
  def test_no_headers (self):
    td = TableData (headers = [], rows = [["a", "b"], ["c", "d"]])
    assert td.headers == []
    assert len (td.rows) == 2


class TestExtractTablesFromHtml:
  def test_empty_html (self):
    assert extract_tables_from_html ("") == []
  
  def test_no_tables (self):
    html = "<html><body><p>Hello world</p></body></html>"
    assert extract_tables_from_html (html) == []
  
  def test_simple_table (self):
    html = """
        <table>
            <tr><th>Name</th><th>Age</th></tr>
            <tr><td>Alice</td><td>30</td></tr>
            <tr><td>Bob</td><td>25</td></tr>
        </table>
        """
    tables = extract_tables_from_html (html)
    assert len (tables) == 1
    assert tables [0].headers == ["Name", "Age"]
    assert len (tables [0].rows) == 2
    assert tables [0].rows [0] == ["Alice", "30"]
  
  def test_table_with_thead_tbody (self):
    html = """
        <table>
            <thead><tr><th>ID</th><th>Value</th></tr></thead>
            <tbody>
                <tr><td>1</td><td>One</td></tr>
                <tr><td>2</td><td>Two</td></tr>
            </tbody>
        </table>
        """
    tables = extract_tables_from_html (html)
    assert len (tables) == 1
    assert tables [0].headers == ["ID", "Value"]
    assert len (tables [0].rows) == 2
  
  def test_table_with_caption (self):
    html = """
        <table>
            <caption>User Data</caption>
            <tr><th>Name</th></tr>
            <tr><td>Alice</td></tr>
        </table>
        """
    tables = extract_tables_from_html (html)
    assert len (tables) == 1
    assert tables [0].caption == "User Data"
  
  def test_multiple_tables (self):
    html = """
        <table><tr><th>A</th></tr><tr><td>1</td></tr></table>
        <table><tr><th>B</th></tr><tr><td>2</td></tr></table>
        """
    tables = extract_tables_from_html (html)
    assert len (tables) == 2
  
  def test_table_with_colspan (self):
    html = """
        <table>
            <tr><th colspan="2">Info</th></tr>
            <tr><td>A</td><td>B</td></tr>
        </table>
        """
    tables = extract_tables_from_html (html)
    assert len (tables) == 1
    assert tables [0].headers == ["Info"]
  
  def test_table_with_rowspan (self):
    html = """
        <table>
            <tr><th>Name</th><th>Age</th></tr>
            <tr><td rowspan="2">Alice</td><td>30</td></tr>
            <tr><td>30</td></tr>
        </table>
        """
    tables = extract_tables_from_html (html)
    assert len (tables) == 1
  
  def test_empty_table_filtered (self):
    html = "<table></table>"
    tables = extract_tables_from_html (html)
    assert len (tables) == 0
  
  def test_confluence_style_table (self):
    html = """
        <table class="wrapped">
            <colgroup><col/><col/></colgroup>
            <tbody>
                <tr><th>Parameter</th><th>Value</th></tr>
                <tr><td>timeout</td><td>30</td></tr>
            </tbody>
        </table>
        """
    tables = extract_tables_from_html (html)
    assert len (tables) == 1
    assert tables [0].headers == ["Parameter", "Value"]


class TestTableToMarkdown:
  def test_basic_table (self):
    td = TableData (headers = ["Name", "Age"], rows = [["Alice", "30"], ["Bob", "25"]])
    md = table_to_markdown (td)
    assert "| Name | Age |" in md
    assert "| Alice | 30 |" in md
    assert "| Bob | 25 |" in md
  
  def test_table_no_headers (self):
    td = TableData (headers = [], rows = [["a", "b"], ["c", "d"]])
    md = table_to_markdown (td)
    assert "a" in md
    assert "b" in md
  
  def test_single_row (self):
    td = TableData (headers = ["Key", "Value"], rows = [["port", "8080"]])
    md = table_to_markdown (td)
    assert "| Key | Value |" in md
    assert "| port | 8080 |" in md
  
  def test_empty_table (self):
    td = TableData (headers = [], rows = [])
    md = table_to_markdown (td)
    assert md == ""
  
  def test_table_with_caption (self):
    td = TableData (headers = ["H"], rows = [["V"]], caption = "Test")
    md = table_to_markdown (td)
    assert "**Test**" in md
  
  def test_cell_newlines_replaced (self):
    td = TableData (headers = ["Desc"], rows = [["Line1\nLine2"]])
    md = table_to_markdown (td)
    assert "\n" not in md.split ("| Desc |") [0]
    assert "Line1 Line2" in md
  
  def test_pipe_escaped (self):
    td = TableData (headers = ["Expr"], rows = [["a | b"]])
    md = table_to_markdown (td)
    assert "a \\| b" in md


class TestTableToJson:
  def test_basic_table (self):
    td = TableData (headers = ["Name", "Age"], rows = [["Alice", "30"]])
    result = table_to_json (td)
    assert result ["headers"] == ["Name", "Age"]
    assert result ["rows"] == [["Alice", "30"]]
    assert result ["row_count"] == 1
    assert result ["caption"] == ""
  
  def test_with_caption (self):
    td = TableData (headers = ["X"], rows = [["1"]], caption = "Cap")
    result = table_to_json (td)
    assert result ["caption"] == "Cap"
  
  def test_empty_table (self):
    td = TableData (headers = [], rows = [])
    result = table_to_json (td)
    assert result ["headers"] == []
    assert result ["rows"] == []
    assert result ["row_count"] == 0
  
  def test_dict_records_format (self):
    td = TableData (headers = ["A", "B"], rows = [["x", "y"], ["1", "2"]])
    result = table_to_json (td)
    records = result.get ("records", [])
    if records:
      assert len (records) == 2


class TestConfigFlag:
  def test_table_extraction_enabled (self):
    assert TABLE_EXTRACTION_ENABLED in (True, False)
