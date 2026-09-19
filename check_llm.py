#!/usr/bin/env python3
"""
Universal Log Pipeline - LLM API Diagnostic & Health Checker

Usage:
    python check_llm.py
"""

import os
import sys
import json
from pipeline.format_detector import DiscoveryEngine, _resolve_gemini_model, _resolve_anthropic_model, DEFAULT_MODEL

def main():
    print("=" * 65)
    print("  Universal Log Pre-processing Pipeline - LLM API Diagnostics")
    print("=" * 65)
    
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    raw_model = os.environ.get("DISCOVERY_MODEL", DEFAULT_MODEL)
    
    print("\n[1] Environment Configuration:")
    print(f"  • GEMINI_API_KEY:    {'Configured (' + gemini_key[:4] + '...' + gemini_key[-4:] + ')' if gemini_key else 'Not set'}")
    print(f"  • GOOGLE_API_KEY:    {'Configured (' + os.environ['GOOGLE_API_KEY'][:4] + '...)' if 'GOOGLE_API_KEY' in os.environ else 'Not set'}")
    print(f"  • ANTHROPIC_API_KEY: {'Configured (' + anthropic_key[:4] + '...' + anthropic_key[-4:] + ')' if anthropic_key else 'Not set'}")
    print(f"  • DISCOVERY_MODEL:   {raw_model}")
    
    engine = DiscoveryEngine()
    print("\n[2] Running Active Connectivity Check...")
    diag = engine.check_llm()
    
    print(f"\n[3] Diagnostic Result:")
    status = diag.get("status", "unknown").upper()
    print(f"  • Status:      {status}")
    print(f"  • Provider:    {diag.get('provider') or 'None'}")
    print(f"  • Model:       {diag.get('model')}")
    
    if diag.get("latency_ms"):
        print(f"  • Latency:     {diag['latency_ms']} ms")
        
    if diag.get("status") == "ok":
        print(f"  • Test Rule:   {json.dumps(diag.get('test_rule', {}))}")
        print("\n✅ SUCCESS: LLM API is WORKING and ready for log format discovery.")
        sys.exit(0)
    elif diag.get("status") == "not_configured":
        print(f"\n⚠️  NOTICE: {diag.get('error')}")
        print("\nPipeline is operating in high-performance HEURISTIC FALLBACK mode.")
        print("To enable LLM-powered discovery:")
        print("  export GEMINI_API_KEY=\"your_gemini_api_key\"")
        print("  or")
        print("  export ANTHROPIC_API_KEY=\"your_anthropic_api_key\"")
        sys.exit(0)
    else:
        print(f"\n❌ ERROR: {diag.get('error')}")
        print("\nPlease check your API key, network egress permissions, and quota.")
        sys.exit(1)

if __name__ == "__main__":
    main()
