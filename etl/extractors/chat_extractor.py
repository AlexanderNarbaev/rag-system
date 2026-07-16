"""Chat history extractor for DeepSeek, ChatGPT, and Claude exports."""

import json
import logging
import re
from collections.abc import Generator
from pathlib import Path
from typing import Any

from etl.extractors.base_extractor import BaseExtractor, ExtractedDocument, ExtractorConfig

logging.basicConfig (level = logging.INFO, format = "%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger (__name__)


class ChatExtractor (BaseExtractor):
  """Extracts question-answer pairs, code blocks, and threading from chat exports."""

  FORMAT_DEEPSEEK = "deepseek"
  FORMAT_CHATGPT = "chatgpt"
  FORMAT_CLAUDE = "claude"
  FORMAT_GENERIC = "generic"

  def __init__ (self, config: ExtractorConfig):
    super ().__init__ (config)
    self._validated = False
    self._source_files: list [Path] = []

  async def validate_connection (self) -> bool:
    """Validate that source chat export files exist."""
    base_path = Path (self.config.base_url) if self.config.base_url else None
    if not base_path:
      logger.error ("No base_url provided for chat extractor")
      return False
    if not base_path.exists ():
      logger.error (f"Chat source directory does not exist: {base_path}")
      return False

    self._source_files = []
    for pattern in ("*.json", "*.jsonl", "*.txt"):
      self._source_files.extend (list (base_path.rglob (pattern)))

    if self.config.exclude_patterns:
      self._source_files = [f for f in self._source_files if
          not any (p in str (f) for p in self.config.exclude_patterns)]

    self._validated = len (self._source_files) > 0
    if self._validated:
      logger.info (f"Found {len (self._source_files)} chat export files in {base_path}")
    else:
      logger.warning (f"No chat export files found in {base_path}")
    return self._validated

  async def extract (self) -> Generator [ExtractedDocument, None, None]:
    """Extract chat conversations from all detected export files."""
    if not self._validated:
      await self.validate_connection ()

    for file_path in self._source_files:
      try:
        format_type = self._detect_format (file_path)
        conversations = await self._parse_file (file_path, format_type)

        for conv in conversations:
          docs = self._conversation_to_documents (conv, format_type, file_path)
          for doc in docs:
            yield doc
      except Exception as e:
        logger.error (f"Failed to extract chat file {file_path}: {e}", exc_info = True)

  async def _parse_file (self, file_path: Path, format_type: str) -> list [dict[str, Any]]:
    """Parse a chat export file based on detected format."""
    with open (file_path, encoding = "utf-8") as f:
      content = f.read ()

    try:
      if format_type == self.FORMAT_DEEPSEEK:
        return self._parse_deepseek (content)
      elif format_type == self.FORMAT_CHATGPT:
        return self._parse_chatgpt (content)
      elif format_type == self.FORMAT_CLAUDE:
        return self._parse_claude (content)
      elif format_type == self.FORMAT_GENERIC:
        return self._parse_generic_json (content)
    except json.JSONDecodeError:
      pass

    if file_path.suffix == ".jsonl":
      return self._parse_jsonl (content)
    return self._parse_generic_text (content)

  def _parse_deepseek (self, content: str) -> list [dict[str, Any]]:
    """Parse DeepSeek chat JSON export."""
    data = json.loads (content)
    conversations = []

    if isinstance (data, list):
      for item in data:
        conv = self._normalize_conversation (item, self.FORMAT_DEEPSEEK)
        if conv:
          conversations.append (conv)
    elif isinstance (data, dict):
      items = data.get ("conversations", data.get ("messages", [data]))
      if isinstance (items, list):
        for item in items:
          conv = self._normalize_conversation (item, self.FORMAT_DEEPSEEK)
          if conv:
            conversations.append (conv)
      else:
        conv = self._normalize_conversation (data, self.FORMAT_DEEPSEEK)
        if conv:
          conversations.append (conv)
    return conversations

  def _parse_chatgpt (self, content: str) -> list [dict[str, Any]]:
    """Parse ChatGPT export (typically JSON with conversations array)."""
    data = json.loads (content)
    conversations = []

    entries = data if isinstance (data, list) else data.get ("conversations", data.get ("data", [data]))
    if not isinstance (entries, list):
      entries = [entries]

    for entry in entries:
      conv = self._normalize_conversation (entry, self.FORMAT_CHATGPT)
      if conv:
        conversations.append (conv)
    return conversations

  def _parse_claude (self, content: str) -> list [dict[str, Any]]:
    """Parse Claude conversation export."""
    data = json.loads (content)
    conversations = []

    convos = data if isinstance (data, list) else data.get ("conversations", data.get ("chats", [data]))
    if not isinstance (convos, list):
      convos = [convos]

    for conv in convos:
      normalized = self._normalize_conversation (conv, self.FORMAT_CLAUDE)
      if normalized:
        conversations.append (normalized)
    return conversations

  def _parse_generic_json (self, content: str) -> list [dict[str, Any]]:
    """Parse a generic JSON chat export (best effort)."""
    data = json.loads (content)
    if isinstance (data, list):
      return [self._normalize_conversation (item, self.FORMAT_GENERIC) for item in data if item]
    return [self._normalize_conversation (data, self.FORMAT_GENERIC)]

  def _parse_jsonl (self, content: str) -> list [dict[str, Any]]:
    """Parse JSONL format (one JSON object per line)."""
    conversations = []
    for line in content.splitlines ():
      line = line.strip ()
      if not line:
        continue
      try:
        item = json.loads (line)
        conv = self._normalize_conversation (item, self.FORMAT_GENERIC)
        if conv:
          conversations.append (conv)
      except json.JSONDecodeError:
        continue
    return conversations

  def _parse_generic_text (self, content: str) -> list [dict[str, Any]]:
    """Parse plain text chat logs (fallback)."""
    qa_pattern = re.compile (r"^(?:Q|Question|User|Human|Человек)[:]\s*(.+?)\s*"
                             r"(?:A|Answer|Assistant|AI|Bot|Ассистент)[:]\s*(.+)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE, )
    pairs = qa_pattern.findall (content)

    if pairs:
      messages = []
      for question, answer in pairs:
        messages.append ({"role": "user", "content": question.strip ()})
        messages.append ({"role": "assistant", "content": answer.strip ()})
      return [{"title": "Chat Log", "messages": messages, "id": "generic_text_1"}]

    lines = [line.strip () for line in content.splitlines () if line.strip ()]
    segments = []
    current_role = None
    current_text = []

    speaker_re = re.compile (r"^\[?(\w+)\]?\s*[:：]\s*(.*)")
    for line in lines:
      m = speaker_re.match (line)
      if m:
        if current_text:
          segments.append ({"role": current_role or "unknown", "content": " ".join (current_text)})
        speaker = m.group (1).lower ()
        role = "user" if speaker in ("user", "human", "человек") else "assistant"
        current_role = role
        current_text = [m.group (2)]
      else:
        current_text.append (line)

    if current_text:
      segments.append ({"role": current_role or "unknown", "content": " ".join (current_text)})

    return [{"title": "Chat Log", "messages": segments, "id": "generic_text_1"}] if segments else []

  def _normalize_conversation (self, conv: dict [str, Any], source: str) -> dict [str, Any] | None:
    """Normalize conversation to a unified structure."""
    if not isinstance (conv, dict):
      return None

    messages = conv.get ("messages", conv.get ("conversation", conv.get ("chat", conv.get ("chat_messages", []))))
    if not messages:
      mapping = conv.get ("mapping", {})
      if mapping:
        messages = self._extract_from_mapping (mapping)
    if not messages:
      return None

    normalized_messages = []
    for msg in messages:
      if isinstance (msg, dict):
        role = msg.get ("role", msg.get ("author", {}).get ("role", ""))
        if isinstance (role, dict):
          role = role.get ("role", "")
        content = msg.get ("content", msg.get ("text", msg.get ("message", "")))
        if isinstance (content, dict):
          parts = content.get ("parts", [content.get ("text", "")])
          if isinstance (parts, list):
            content = " ".join (str (p) for p in parts if isinstance (p, str))
          else:
            content = str (parts)
        model = msg.get ("model", msg.get ("model_slug", ""))
        timestamp = msg.get ("create_time", msg.get ("created_at", msg.get ("timestamp", "")))

        if not role:
          if msg.get ("author", {}).get ("role") in ("user", "human"):  # noqa: SIM108
            role = "user"
          else:
            role = "assistant"

        normalized_messages.append ({
            "role": role, "content": str (content) if content else "", "model": str (model) if model else "",
            "timestamp": str (timestamp) if timestamp else "",
        })

    return {
        "id": conv.get ("id", conv.get ("conversation_id", conv.get ("uuid", ""))),
        "title": conv.get ("title", conv.get ("name", "")), "source": source, "messages": normalized_messages,
        "created_at": conv.get ("create_time", conv.get ("created_at", "")),
        "updated_at": conv.get ("update_time", conv.get ("updated_at", "")),
    }

  def _extract_from_mapping (self, mapping: dict [str, Any]) -> list [dict[str, Any]]:
    """Extract messages from ChatGPT conversation mapping format."""
    messages = []
    for _node_id, node in mapping.items ():
      if isinstance (node, dict):
        msg = node.get ("message")
        if msg:
          messages.append (msg)
    return sorted (messages, key = lambda m: m.get ("create_time", 0) or 0)

  def _conversation_to_documents (
      self, conv: dict [str, Any], format_type: str, file_path: Path, ) -> list [ExtractedDocument]:
    """Convert a conversation into Q&A pair documents."""
    documents = []
    messages = conv.get ("messages", [])
    conv_id = str (conv.get ("id", ""))
    conv_title = conv.get ("title", file_path.stem)

    qa_pairs = self._extract_qa_pairs (messages)
    for pair_idx, (question, answer) in enumerate (qa_pairs):
      code_blocks = self._extract_code_blocks (answer)

      doc = ExtractedDocument (source_id = f"chat_{conv_id}_{pair_idx}", source_type = "chat",
          title = f"{conv_title} — Q{pair_idx + 1}", content = answer, content_type = "text", metadata = {
              "conversation_id": conv_id, "conversation_title": conv_title, "format": format_type, "question": question,
              "pair_index": pair_idx, "total_pairs": len (qa_pairs), "code_blocks": code_blocks,
              "code_block_count": len (code_blocks), "model": messages [0].get ("model", "") if messages else "",
              "created_at": conv.get ("created_at", ""), "file_path": str (file_path),
          }, )
      documents.append (doc)

    if not documents:
      all_text = " ".join (m.get ("content", "") for m in messages)
      documents.append (ExtractedDocument (source_id = f"chat_{conv_id}_full", source_type = "chat", title = conv_title,
          content = all_text, content_type = "text", metadata = {
              "conversation_id": conv_id, "format": format_type, "message_count": len (messages),
              "file_path": str (file_path),
          }, ))

    return documents

  @staticmethod
  def _extract_qa_pairs (messages: list [dict [str, Any]]) -> list [tuple [str, str]]:
    """Extract question-answer pairs from message list."""
    pairs = []
    current_question = None

    for msg in messages:
      role = msg.get ("role", "").lower ()
      content = msg.get ("content", "")

      if role in ("user", "human"):
        current_question = content
      elif role in ("assistant", "ai", "bot", "model") and current_question is not None:
        pairs.append ((current_question, content))
        current_question = None

    return pairs

  @staticmethod
  def _extract_code_blocks (text: str) -> list [str]:
    """Extract code blocks from markdown-style text."""
    blocks = []
    pattern = re.compile (r"```(?:\w*)\n(.*?)```", re.DOTALL)
    for match in pattern.finditer (text):
      code = match.group (1).strip ()
      if code:
        blocks.append (code [:2000])
    return blocks

  def should_process (self, doc: ExtractedDocument, last_hash: str) -> bool:
    """Check if document needs processing based on content hash."""
    if not last_hash:
      return True
    return self.compute_hash (doc.content) != last_hash

  @staticmethod
  def _detect_format (file_path: Path) -> str:
    """Detect chat export format from file content and name."""
    try:
      with open (file_path, encoding = "utf-8") as f:
        head = f.read (4096)

      if "deepseek" in head.lower () or "deepseek" in str (file_path).lower ():
        return ChatExtractor.FORMAT_DEEPSEEK
      if "chatgpt" in head.lower () or "conversations" in head.lower ():
        return ChatExtractor.FORMAT_CHATGPT
      if "claude" in head.lower () or "anthropic" in head.lower ():
        return ChatExtractor.FORMAT_CLAUDE
    except Exception:
      pass

    fname = str (file_path).lower ()
    if "deepseek" in fname:
      return ChatExtractor.FORMAT_DEEPSEEK
    if "chatgpt" in fname or "gpt" in fname:
      return ChatExtractor.FORMAT_CHATGPT
    if "claude" in fname or "anthropic" in fname:
      return ChatExtractor.FORMAT_CLAUDE

    return ChatExtractor.FORMAT_GENERIC
