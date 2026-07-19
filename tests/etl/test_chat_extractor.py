# ruff: noqa: E501
"""Tests for the ChatExtractor with sample JSON data."""

import json

import pytest

from etl.extractors.base_extractor import ExtractedDocument, ExtractorConfig
from etl.extractors.chat_extractor import ChatExtractor


@pytest.fixture
def chat_config(tmp_path):
    return ExtractorConfig(
        source_name="test-chats",
        source_type="chat",
        base_url=str(tmp_path),
    )


@pytest.fixture
def sample_deepseek_conversation():
    return {
        "id": "conv-001",
        "title": "Python async patterns",
        "messages": [
            {"role": "user", "content": "How do I use asyncio.gather?"},
            {"role": "assistant", "content": "Use `asyncio.gather(*coroutines)` to run them concurrently."},
        ],
    }


@pytest.fixture
def sample_chatgpt_conversation():
    return {
        "conversation_id": "chat-001",
        "title": "TypeScript tips",
        "messages": [
            {"role": "user", "content": "What are generics?"},
            {
                "role": "assistant",
                "content": "Generics allow type parameters: ```ts\nfunction identity<T>(arg: T): T { return arg; }\n```",
            },
        ],
    }


@pytest.fixture
def sample_claude_conversation():
    return {
        "uuid": "claude-001",
        "name": "System design",
        "chat_messages": [
            {"role": "human", "content": "How to design a rate limiter?"},
            {"role": "assistant", "content": "Use token bucket algorithm with Redis for distributed systems."},
        ],
    }


class TestChatExtractorInit:
    def test_init_with_config(self, chat_config):
        ext = ChatExtractor(chat_config)
        assert ext.config.source_name == "test-chats"
        assert ext.config.source_type == "chat"
        assert ext._validated is False
        assert ext._source_files == []


class TestChatExtractorValidateConnection:
    def test_empty_directory(self, chat_config, tmp_path):
        ext = ChatExtractor(chat_config)
        import asyncio

        result = asyncio.run(ext.validate_connection())
        assert result is False

    def test_with_json_file(self, chat_config, tmp_path):
        (tmp_path / "chat.json").write_text('{"test": true}')
        ext = ChatExtractor(chat_config)
        import asyncio

        result = asyncio.run(ext.validate_connection())
        assert result is True
        assert len(ext._source_files) == 1

    def test_with_exclude_patterns(self, tmp_path):
        config = ExtractorConfig(
            source_name="test",
            source_type="chat",
            base_url=str(tmp_path),
            exclude_patterns=["archive"],
        )
        (tmp_path / "active.json").write_text("{}")
        (tmp_path / "archive").mkdir()
        (tmp_path / "archive" / "old.json").write_text("{}")
        ext = ChatExtractor(config)
        import asyncio

        result = asyncio.run(ext.validate_connection())
        assert result is True
        assert len(ext._source_files) == 1


class TestChatExtractorFormatDetection:
    def test_detect_deepseek(self, chat_config, tmp_path):
        f = tmp_path / "deepseek_export.json"
        f.write_text('{"conversations": [{"id": "d1"}]}')
        ext = ChatExtractor(chat_config)
        result = ext._detect_format(f)
        assert result == ChatExtractor.FORMAT_DEEPSEEK

    def test_detect_chatgpt(self, chat_config, tmp_path):
        f = tmp_path / "chatgpt_export.json"
        f.write_text('{"conversations": [{"conversation_id": "c1"}]}')
        ext = ChatExtractor(chat_config)
        result = ext._detect_format(f)
        assert result == ChatExtractor.FORMAT_CHATGPT

    def test_detect_claude(self, chat_config, tmp_path):
        f = tmp_path / "claude_conversations.json"
        f.write_text('{"chats": [{"uuid": "u1"}]}')
        ext = ChatExtractor(chat_config)
        result = ext._detect_format(f)
        assert result == ChatExtractor.FORMAT_CLAUDE

    def test_detect_generic(self, chat_config, tmp_path):
        f = tmp_path / "unknown.json"
        f.write_text('{"messages": []}')
        ext = ChatExtractor(chat_config)
        result = ext._detect_format(f)
        assert result == ChatExtractor.FORMAT_GENERIC


class TestChatExtractorParsing:
    def test_parse_deepseek_list(self, chat_config, sample_deepseek_conversation):
        ext = ChatExtractor(chat_config)
        data = json.dumps([sample_deepseek_conversation])
        result = ext._parse_deepseek(data)
        assert len(result) == 1
        assert result[0]["id"] == "conv-001"
        assert len(result[0]["messages"]) == 2

    def test_parse_deepseek_dict(self, chat_config, sample_deepseek_conversation):
        ext = ChatExtractor(chat_config)
        data = json.dumps({"conversations": [sample_deepseek_conversation]})
        result = ext._parse_deepseek(data)
        assert len(result) == 1

    def test_parse_chatgpt(self, chat_config, sample_chatgpt_conversation):
        ext = ChatExtractor(chat_config)
        data = json.dumps([sample_chatgpt_conversation])
        result = ext._parse_chatgpt(data)
        assert len(result) == 1
        assert result[0]["id"] == "chat-001"

    def test_parse_claude(self, chat_config, sample_claude_conversation):
        ext = ChatExtractor(chat_config)
        conv_data = {
            "uuid": "claude-001",
            "name": "System design",
            "messages": sample_claude_conversation["chat_messages"],
        }
        data = json.dumps({"chats": [conv_data]})
        result = ext._parse_claude(data)
        assert len(result) == 1
        assert result[0]["id"] == "claude-001"

    def test_parse_jsonl(self, chat_config):
        ext = ChatExtractor(chat_config)
        content = '{"id": "1", "messages": [{"role": "user", "content": "Q"}]}\n{"id": "2", "messages": []}'
        result = ext._parse_jsonl(content)
        assert len(result) == 1  # Second has no messages, filtered out

    def test_parse_generic_text(self, chat_config):
        ext = ChatExtractor(chat_config)
        content = "Q: What is Python?\nA: Python is a programming language."
        result = ext._parse_generic_text(content)
        assert len(result) == 1
        assert len(result[0]["messages"]) == 2
        assert result[0]["messages"][0]["role"] == "user"


class TestChatExtractorNormalization:
    def test_normalize_deepseek(self, chat_config, sample_deepseek_conversation):
        ext = ChatExtractor(chat_config)
        result = ext._normalize_conversation(sample_deepseek_conversation, ChatExtractor.FORMAT_DEEPSEEK)
        assert result is not None
        assert result["id"] == "conv-001"
        assert result["title"] == "Python async patterns"
        assert result["source"] == ChatExtractor.FORMAT_DEEPSEEK
        assert len(result["messages"]) == 2
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][1]["role"] == "assistant"

    def test_normalize_claude_messages_field(self, chat_config, sample_claude_conversation):
        ext = ChatExtractor(chat_config)
        result = ext._normalize_conversation(sample_claude_conversation, ChatExtractor.FORMAT_CLAUDE)
        assert result is not None
        assert result["id"] == "claude-001"

    def test_normalize_empty_conversation(self, chat_config):
        ext = ChatExtractor(chat_config)
        result = ext._normalize_conversation({}, ChatExtractor.FORMAT_GENERIC)
        assert result is None


class TestChatExtractorQAPairs:
    def test_extract_qa_pairs(self, chat_config):
        ext = ChatExtractor(chat_config)
        messages = [
            {"role": "user", "content": "Question 1?"},
            {"role": "assistant", "content": "Answer 1."},
            {"role": "user", "content": "Question 2?"},
            {"role": "assistant", "content": "Answer 2."},
        ]
        pairs = ext._extract_qa_pairs(messages)
        assert len(pairs) == 2
        assert pairs[0] == ("Question 1?", "Answer 1.")
        assert pairs[1] == ("Question 2?", "Answer 2.")

    def test_extract_qa_pairs_unmatched_user(self, chat_config):
        ext = ChatExtractor(chat_config)
        messages = [
            {"role": "user", "content": "Unanswered question?"},
        ]
        pairs = ext._extract_qa_pairs(messages)
        assert len(pairs) == 0

    def test_extract_qa_pairs_empty(self, chat_config):
        ext = ChatExtractor(chat_config)
        pairs = ext._extract_qa_pairs([])
        assert pairs == []


class TestChatExtractorCodeBlocks:
    def test_extract_code_blocks(self, chat_config):
        ext = ChatExtractor(chat_config)
        text = "Here is some code:\n```python\nprint('hello')\n```\nMore text."
        blocks = ext._extract_code_blocks(text)
        assert len(blocks) == 1
        assert "print('hello')" in blocks[0]

    def test_extract_code_blocks_multiple(self, chat_config):
        ext = ChatExtractor(chat_config)
        text = "```js\nconst x = 1;\n```\nSome text\n```ts\ntype T = string;\n```"
        blocks = ext._extract_code_blocks(text)
        assert len(blocks) == 2

    def test_extract_code_blocks_none(self, chat_config):
        ext = ChatExtractor(chat_config)
        blocks = ext._extract_code_blocks("No code here.")
        assert blocks == []


class TestChatExtractorConversationToDocuments:
    def test_converts_to_documents(self, chat_config, sample_deepseek_conversation, tmp_path):
        ext = ChatExtractor(chat_config)
        conv = ext._normalize_conversation(sample_deepseek_conversation, ChatExtractor.FORMAT_DEEPSEEK)
        assert conv is not None
        docs = ext._conversation_to_documents(conv, ChatExtractor.FORMAT_DEEPSEEK, tmp_path / "test.json")
        assert len(docs) == 1
        assert docs[0].source_type == "chat"
        assert docs[0].source_id == "chat_conv-001_0"
        assert docs[0].metadata["conversation_id"] == "conv-001"
        assert docs[0].metadata["format"] == ChatExtractor.FORMAT_DEEPSEEK

    def test_conversation_without_messages(self, chat_config, tmp_path):
        ext = ChatExtractor(chat_config)
        conv = {"id": "empty", "title": "Empty", "messages": [], "source": "generic"}
        docs = ext._conversation_to_documents(conv, "generic", tmp_path / "test.json")
        assert len(docs) == 1
        assert docs[0].source_id == "chat_empty_full"


class TestChatExtractorShouldProcess:
    def test_no_last_hash(self, chat_config):
        ext = ChatExtractor(chat_config)
        doc = ExtractedDocument(source_id="d", source_type="chat", title="T", content="C", content_type="text")
        assert ext.should_process(doc, "") is True

    def test_changed_content(self, chat_config):
        ext = ChatExtractor(chat_config)
        doc = ExtractedDocument(source_id="d", source_type="chat", title="T", content="new", content_type="text")
        assert ext.should_process(doc, "oldhash") is True

    def test_same_content(self, chat_config):
        ext = ChatExtractor(chat_config)
        doc = ExtractedDocument(source_id="d", source_type="chat", title="T", content="same", content_type="text")
        h = ext.compute_hash("same")
        assert ext.should_process(doc, h) is False


class TestChatExtractorExtract:
    def test_extract_from_json_file(self, chat_config, sample_deepseek_conversation, tmp_path):
        f = tmp_path / "deepseek_export.json"
        f.write_text(json.dumps([sample_deepseek_conversation]))
        ext = ChatExtractor(chat_config)
        import asyncio

        async def collect():
            await ext.validate_connection()
            docs = []
            async for doc in ext.extract():
                docs.append(doc)
            return docs

        docs = asyncio.run(collect())
        assert len(docs) == 1
        assert docs[0].source_type == "chat"
