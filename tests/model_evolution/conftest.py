import sys
from pathlib import Path

# Add project root to path so tests can import from proxy.app.model_evolution
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
