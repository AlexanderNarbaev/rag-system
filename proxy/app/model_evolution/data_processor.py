"""Data processor: assemble training datasets from HITL feedback."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TrainingDataset:
    slm_data: list[dict[str, Any]] = field(default_factory=list)
    llm_data: list[dict[str, Any]] = field(default_factory=list)
    reranker_data: list[dict[str, Any]] = field(default_factory=list)


class DataProcessor:
    def __init__(self, hitl_log_path: str = "logs/hitl.jsonl"):
        self.hitl_log_path = Path(hitl_log_path)

    def export_training_dataset(self, output_dir: str = "data/training") -> TrainingDataset:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        dataset = TrainingDataset()

        if not self.hitl_log_path.exists():
            return dataset

        entries = []
        with open(self.hitl_log_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        for entry in entries:
            query = entry.get("query", "")
            answer = entry.get("answer", entry.get("response", ""))
            correction = entry.get("correction", "")
            intent = entry.get("intent", entry.get("predicted_intent", ""))
            relevance = entry.get("relevance", entry.get("score", 0.5))
            source_chunks = entry.get("chunks", entry.get("sources", []))

            if query and intent:
                dataset.slm_data.append({"query": query, "intent": intent})

            if query and correction:
                dataset.llm_data.append(
                    {
                        "instruction": query,
                        "input": answer or "",
                        "output": correction,
                    },
                )

            if query and source_chunks:
                for chunk in source_chunks:
                    dataset.reranker_data.append(
                        {
                            "query": query,
                            "chunk": chunk.get("text", chunk) if isinstance(chunk, dict) else str(chunk),
                            "relevance": relevance,
                        },
                    )

        self._save_jsonl(output / "slm_intent.jsonl", dataset.slm_data)
        self._save_jsonl(output / "llm_instruction.jsonl", dataset.llm_data)
        self._save_jsonl(output / "reranker_pairs.jsonl", dataset.reranker_data)

        return dataset

    def split_train_val_test(
        self,
        data: list[dict[str, Any]],
        train_ratio: float = 0.8,
        val_ratio: float = 0.1,
        test_ratio: float = 0.1,
        seed: int = 42,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        import random

        rng = random.Random(seed)
        shuffled = list(data)
        rng.shuffle(shuffled)
        n = len(shuffled)
        train_end = int(n * train_ratio)
        val_end = train_end + int(n * val_ratio)
        return shuffled[:train_end], shuffled[train_end:val_end], shuffled[val_end:]

    def format_for_slm(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"text": d["query"], "label": d.get("intent", "")} for d in data]

    def format_for_llm(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "messages": [
                    {"role": "user", "content": d.get("instruction", d.get("query", ""))},
                    {"role": "assistant", "content": d.get("output", d.get("correction", ""))},
                ],
            }
            for d in data
        ]

    def _save_jsonl(self, path: Path, data: list[dict[str, Any]]) -> None:
        with open(path, "w") as f:
            f.writelines(json.dumps(item, ensure_ascii=False) + "\n" for item in data)
