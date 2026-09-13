# Master Implementation Plan (v4 Final) - Mandatory LLM Fallback Gate

This plan maps out the final architectural evolution of the pipeline: moving the compositional zone parser to Tier 2a (Fast Path) and introducing a strict mathematical completeness gate that mandates LLM escalation when structural heuristics fail.

## User Review Required

> [!IMPORTANT]
> **LLM API Configuration**
> To fulfill the Tier 2c (Real LLM Escaltion) requirement, the system needs to make real external API calls. I will implement this using the `google-generativeai` SDK (Gemini Free Tier) as the primary provider, with a documented path to swap to Ollama (Local) or OpenAI.
> 
> **Are you okay with using Gemini via an environment variable (e.g. `GEMINI_API_KEY`), or would you prefer I implement a Mock LLM that specifically simulates the output for Test 5 just for this hackathon demo so you don't leak API keys on stage?**

## Proposed Changes

### 1. `main.py` (The Architecture Core)
- **The Pipeline Loop Redesign:**
  1. `features = parser.fingerprint(log)`
  2. Check cache. If hit, execute cached rule and return.
  3. If miss, run `Tier 2a: Fast-path Zone Detectors`.
  4. **Completeness Gate:** Calculate `classified_chars / total_chars`. If this ratio is `< 80%` or `< 2 zones found`, escalate.
  5. If Escalate: call `LLMEngine.decompose(log)`.
  6. Cache whichever rule (Fast-path or LLM) ultimately won.

### 2. `pipeline/parser.py` (Tier 2a: Fast Path & Execution)
- Expand the `compositional` extraction method to include the exhaustive list from Section 5:
  - **Leading IP Detector:** Hunt for IPv4/IPv6 strings.
  - **Quoted Segments & HTTP Routing:** Extract `"..."` and specifically check the first quote for `METHOD /path HTTP/x.x` using regexes.
  - **Standalone Numbers & Hashes:** Extract bare digits, UUIDs, MACs, and Emails.
- Make the extraction strictly non-destructive. What remains after all extractions becomes `message`.

### 3. [NEW] `pipeline/llm_engine.py` (Tier 2c: LLM Fallback)
- Implement `decompose(log_entry)` which constructs a strict JSON-schema prompt instructing the LLM to act as a structural decomposing agent.
- Validate that the LLM's response actually maps fields correctly.
- Add configuration logic to swap between `GEMINI` and `OLLAMA` providers.

### 4. Frontend (`static/index.html` & `static/app.js`)
- Add **Test 3 (Web server combined log format)** and **Test 5 (Completeness Gate Test)** to the sample dropdown.
- Update the Result Cards to explicitly display the **Completeness Score (e.g., 94% Classified)** and whether the mode was **Fast-path**, **LLM-escalated**, or **Cached**.

## Verification Plan

I will verify all 5 required tests from Section 7:
1. **Unseen Format (Test 1):** Ensure it scores < 80% on fast-path and escalates to LLM.
2. **Application Logger (Test 2):** Ensure fast-path cleanly hits 100% classification.
3. **Web Server Combined (Test 3):** Ensure HTTP verbs, quoted strings, and IPs are parsed with 0% unclassified text (message is null).
4. **Cache Correctness (Test 4):** Verify `< 5ms` execution times on repeat lines.
5. **Completeness Gate (Test 5):** Hard-test the 80% threshold logic.
