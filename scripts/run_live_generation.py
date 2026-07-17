"""Live LLM-path run: extracted map -> Groq worker -> validator -> result.

Usage: python scripts/run_live_generation.py <map.json> <platform> [conventions]
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generation.pipeline import generate_validated_driver
from generation.provider import GroqProvider


def main() -> int:
    map_path, platform = sys.argv[1], sys.argv[2]
    conventions = sys.argv[3] if len(sys.argv) > 3 else "snake_case, C99, no dynamic allocation"
    retries = int(os.environ.get("GEN_RETRIES", "3"))
    with open(map_path, encoding="utf-8") as f:
        register_map = json.load(f)

    provider = GroqProvider()
    print(f"provider: {provider.name}")
    result = generate_validated_driver(
        register_map, platform, provider, conventions=conventions,
        max_retries=retries,
    )

    print(f"status   : {result['status']}")
    print(f"decision : {result['decision']['path']} / {result['decision'].get('framing')}")
    print(f"attempts : {result.get('attempts')}")
    if result.get("workdir"):
        print(f"workdir  : {result['workdir']}")
    last = result["reports"][-1] if result.get("reports") else {}
    print(f"checks   : {last.get('checks')}")
    for uf in last.get("unverified_fields", [])[:10]:
        print(f"  unverified: {uf['define']} {uf['claimed_bits']} "
              f"(reg {uf['register']}, comment={uf['has_unverified_comment']})")
    for fail in (result.get("validation_failures") or last.get("failures", []))[:12]:
        print(f"  FAIL [{fail['check']}] {fail['file']}:{fail.get('line')}: "
              f"{fail['message'][:160]}")
    return 0 if result["status"] != "unvalidated" else 1


if __name__ == "__main__":
    sys.exit(main())
