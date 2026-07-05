import os
import json
from .models import SiloConfig
from .exceptions import ConfigError


FEDERATION_MODE = os.getenv("FEDERATION_MODE", "auto")
FEDERATION_INSTANCES_JSON = os.getenv("FEDERATION_INSTANCES_JSON", "[]")
FEDERATION_INSTANCES_FILE = os.getenv("FEDERATION_INSTANCES_FILE", "")
FEDERATION_MERGE_STRATEGY = os.getenv("FEDERATION_MERGE_STRATEGY", "weighted_rrf")
FEDERATION_MERGE_K = int(os.getenv("FEDERATION_MERGE_K", "60"))
FEDERATION_RRF_K = int(os.getenv("FEDERATION_RRF_K", "60"))
FEDERATION_TOTAL_TIMEOUT_S = int(os.getenv("FEDERATION_TOTAL_TIMEOUT_S", "30"))
FEDERATION_PER_INSTANCE_TIMEOUT_S = int(os.getenv("FEDERATION_PER_INSTANCE_TIMEOUT_S", "10"))
FEDERATION_CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("FEDERATION_CIRCUIT_BREAKER_THRESHOLD", "5"))
FEDERATION_CIRCUIT_BREAKER_RECOVERY_S = int(os.getenv("FEDERATION_CIRCUIT_BREAKER_RECOVERY_S", "30"))
FEDERATION_LLM_ENDPOINT = os.getenv("FEDERATION_LLM_ENDPOINT", "")
FEDERATION_LLM_MODEL = os.getenv("FEDERATION_LLM_MODEL", "")
FEDERATION_AUTO_SLM_ENABLED = os.getenv("FEDERATION_AUTO_SLM_ENABLED", "true").lower() == "true"


def _load_json_silos(json_str: str) -> list[SiloConfig]:
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid FEDERATION_INSTANCES_JSON: {e}")
    if not isinstance(data, list):
        raise ConfigError("FEDERATION_INSTANCES_JSON must be a JSON array")
    silos = []
    for item in data:
        try:
            silos.append(SiloConfig(
                id=item["id"],
                name=item["name"],
                proxy_url=item["proxy_url"],
                weight=float(item.get("weight", 1.0)),
                access_groups=item.get("access_groups", []),
                collections=item.get("collections", []),
                api_key=item.get("api_key"),
                timeout_s=int(item.get("timeout_s", 10)),
                is_primary=bool(item.get("is_primary", False)),
            ))
        except KeyError as e:
            raise ConfigError(f"Missing required field {e} in silo config")
    return silos


def load_silos() -> list[SiloConfig]:
    if FEDERATION_INSTANCES_FILE:
        with open(FEDERATION_INSTANCES_FILE) as f:
            json_str = f.read()
    else:
        json_str = FEDERATION_INSTANCES_JSON
    return _load_json_silos(json_str)


def get_primary_silo(silos: list[SiloConfig]) -> SiloConfig | None:
    primaries = [s for s in silos if s.is_primary]
    if len(primaries) > 1:
        import logging
        logging.getLogger("federation").warning(
            f"Multiple primary silos configured: {[s.id for s in primaries]}. Using {primaries[0].id}."
        )
    return primaries[0] if primaries else None
