from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SiloConfig:
    id: str
    name: str
    proxy_url: str
    weight: float = 1.0
    access_groups: list[str] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)
    api_key: Optional[str] = None
    timeout_s: int = 10
    is_primary: bool = False

    def is_accessible_by(self, user_groups: list[str]) -> bool:
        return bool(set(user_groups) & set(self.access_groups))


@dataclass
class SiloSearchResult:
    silo_id: str
    silo_name: str
    chunks: list[dict]
    latency_ms: float
    error: Optional[str] = None
    partial: bool = False


@dataclass
class FederatedSearchResult:
    query: str
    merged_chunks: list[dict]
    silo_results: list[SiloSearchResult]
    total_latency_ms: float
    errors: list[str] = field(default_factory=list)
    skipped_silos: list[str] = field(default_factory=list)


@dataclass
class FederationContext:
    mode: str
    target_silos: list[str]
    merge_strategy: str
    merge_k: int
    rrf_k: int
    user_groups: list[str]
    cross_silo: bool = False
    query: str = ""
