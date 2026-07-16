"""
GraphRAG Community Detection

Implements Leiden algorithm for community detection in knowledge graphs.
Based on: https://arxiv.org/abs/2404.16130 (Microsoft GraphRAG)

Generates community summaries for global search mode.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Community:
    """A community in the knowledge graph."""

    id: str
    level: int
    members: list[str]  # Entity IDs
    summary: str = ""
    key_entities: list[str] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class CommunityDetector:
    """
    Detects communities in knowledge graphs using Leiden algorithm.

    Usage:
        detector = CommunityDetector()
        communities = detector.detect_communities(entities, relationships)
        summaries = detector.generate_summaries(communities)
    """

    def __init__(self, resolution: float = 1.0, min_community_size: int = 3):
        self.resolution = resolution
        self.min_community_size = min_community_size

    def detect_communities(
        self,
        entities: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
    ) -> list[Community]:
        """
        Detect communities using simple connected components + clustering.

        For production, use Neo4j GDS Leiden algorithm.
        This is a simplified version for demonstration.
        """
        # Build adjacency list
        adj: dict[str, set[str]] = {}
        for entity in entities:
            eid = entity.get("id", entity.get("name", ""))
            if eid not in adj:
                adj[eid] = set()

        for rel in relationships:
            source = rel.get("source", "")
            target = rel.get("target", "")
            if source in adj and target in adj:
                adj[source].add(target)
                adj[target].add(source)

        # Find connected components (simplified community detection)
        visited: set[str] = set()
        communities: list[Community] = []

        for entity_id in adj:
            if entity_id in visited:
                continue

            # BFS to find connected component
            component: list[str] = []
            queue = [entity_id]
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                component.append(current)
                for neighbor in adj.get(current, []):
                    if neighbor not in visited:
                        queue.append(neighbor)

            # Filter by minimum size
            if len(component) >= self.min_community_size:
                # Get relationships within this community
                community_rels = []
                for rel in relationships:
                    if rel.get("source") in component and rel.get("target") in component:
                        community_rels.append(rel)

                # Identify key entities (most connected)
                entity_connections = {}
                for eid in component:
                    entity_connections[eid] = len(adj.get(eid, set()) & set(component))
                key_entities = sorted(entity_connections, key=lambda k: entity_connections[k], reverse=True)[:5]

                community = Community(
                    id=f"community_{len(communities)}",
                    level=0,
                    members=component,
                    key_entities=key_entities,
                    relationships=community_rels,
                    metadata={"size": len(component)},
                )
                communities.append(community)

        logger.info(f"Detected {len(communities)} communities from {len(entities)} entities")
        return communities

    def generate_summaries(
        self,
        communities: list[Community],
        entities: list[dict[str, Any]],
        summary_fn: Callable[..., Any] | None = None,
    ) -> list[Community]:
        """
        Generate summaries for each community.

        Args:
            communities: Detected communities
            entities: Entity data for context
            summary_fn: Optional custom summary function
        """
        entity_map = {e.get("id", e.get("name", "")): e for e in entities}

        for community in communities:
            # Gather entity descriptions
            descriptions = []
            for eid in community.members[:10]:  # Limit to top 10
                entity = entity_map.get(eid, {})
                desc = entity.get("description", entity.get("name", ""))
                if desc:
                    descriptions.append(f"- {eid}: {desc}")

            # Generate summary
            if summary_fn:
                community.summary = summary_fn(descriptions)
            else:
                community.summary = self._default_summary(community, descriptions)

        return communities

    def _default_summary(self, community: Community, descriptions: list[str]) -> str:
        """Generate default community summary."""
        key_ents = ", ".join(community.key_entities[:5])
        desc_text = "\n".join(descriptions[:5])

        return (
            f"Community {community.id} contains {len(community.members)} entities. "
            f"Key entities: {key_ents}.\n"
            f"Main topics:\n{desc_text}"
        )

    def save_communities(self, communities: list[Community], path: str) -> None:
        """Save communities to JSON file."""
        import json
        from pathlib import Path

        data = []
        for comm in communities:
            data.append(
                {
                    "id": comm.id,
                    "level": comm.level,
                    "members": comm.members,
                    "summary": comm.summary,
                    "key_entities": comm.key_entities,
                    "metadata": comm.metadata,
                }
            )

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved {len(communities)} communities to {path}")
