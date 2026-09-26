#!/usr/bin/env python3
import os, sys, json
from pipeline.format_detector import DiscoveryEngine, DEFAULT_MODEL

def mask(k): return f"Configured ({k[:4]}...{k[-4:]})" if k else "Not set"

def main():
    print("="*65 + "\n  Universal Log Pipeline - LLM Diagnostics\n" + "="*65)
    keys = {
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"),
        "GROQ_API_KEY": os.environ.get("GROQ_API_KEY"),
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY"),
    }
    print("\n[1] Env:")
    for k,v in keys.items():
        print(f"  • {k}: {mask(v) if v else 'Not set'}")
    print(f"  • DISCOVERY_MODEL: {os.environ.get('DISCOVERY_MODEL', DEFAULT_MODEL)}")

    diag = DiscoveryEngine().check_llm()
    print("\n[2] Connectivity check...")
    print("\n[3] Result:")
    print(f"  • Status: {diag.get('status','unknown').upper()}\n  • Provider: {diag.get('provider') or 'None'}\n  • Model: {diag.get('model')}")
    if diag.get("latency_ms"): print(f"  • Latency: {diag['latency_ms']} ms")
    if diag.get("status")=="ok":
        print(f"  • Test Rule: {json.dumps(diag.get('test_rule',{}))}\n\n✅ LLM API WORKING")
        sys.exit(0)
    if diag.get("status")=="not_configured":
        print(f"\n⚠️ {diag.get('error')}\n\nHeuristic fallback mode. Set GROQ_API_KEY or GEMINI_API_KEY to enable LLM.")
        sys.exit(0)
    print(f"\n❌ {diag.get('error')}\nCheck API key / network / quota.")
    sys.exit(1)

if __name__=="__main__": main()
