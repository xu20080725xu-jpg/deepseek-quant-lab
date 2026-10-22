"""Read .env and validate authentication; does not spend generation tokens."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from quantlab.config import api_config
from quantlab.deepseek_client import DeepSeekClient, AIError
from quantlab.storage import Store

try:
    names = DeepSeekClient(Store()).models()
    configured = api_config()["model"]
    print("Official authentication succeeded. Models:", ", ".join(names))
    print("Configured model available:", configured in names)
except AIError as exc:
    print(str(exc))
    sys.exit(2)
