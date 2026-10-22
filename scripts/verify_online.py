"""Explicit live smoke test: bounded real history fetch plus unauthenticated API reachability."""
from pathlib import Path
import json
import sys
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from quantlab.data import AKShareProvider, DataError

report = {}
for source in ("tencent", "eastmoney"):
    try:
        data = AKShareProvider(source).history("000001", "2024-09-01", "2024-12-31")
        report[source] = {"status": "passed", "rows": len(data.frame), "meta": data.meta,
                          "fingerprint": data.fingerprint}
    except (DataError, ValueError) as exc:
        report[source] = {"status": "failed", "message": str(exc)}
try:
    with httpx.Client(timeout=15) as client:
        response = client.get("https://api.deepseek.com/models")
    report["deepseek_without_key"] = {"http_status": response.status_code,
        "meaning": "仅网络连通性；没有Key，不能证明鉴权、模型生成或余额可用"}
except httpx.HTTPError as exc:
    report["deepseek_without_key"] = {"status": "failed", "error_class": type(exc).__name__}
target = Path(__file__).resolve().parent.parent / "work" / "online_verification.json"
target.write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2))
