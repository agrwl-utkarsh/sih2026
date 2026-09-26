# SIH 2026 – Resequenced Slide 2 & Slide 4 – Paste-Ready Text

> Color palette: Navy #0A1931, Orange #FF6B35, Teal #2EC4B6, Green #22C55E
> Fonts: Calibri (existing deck convention)
> Do not touch Slides 1 and 6

---

## SLIDE 2 – Idea & Proposed Solution – NEW TOP-TO-BOTTOM SEQUENCE

### Visual Layout – 6 Blocks Stacked Vertically

**Header (existing):** `Idea & Proposed Solution` – keep navy header bar

#### BLOCK 1 – Problem Statement (NEW – before tagline) – Navy left border, white fill
```
🚨 PROBLEM: Security and IT teams today must hand-write a custom parser for every different log format (syslog, JSON, CSV, proprietary formats); this doesn't scale, breaks whenever a new system or format appears, and creates blind spots that attackers can exploit.
```
- Font: Calibri 12pt, Navy #0A1931, left-aligned, with 🚨 emoji
- Box: White fill, Navy border 2pt, left accent bar 6pt Navy #0A1931, rounded corners, shadow
- Position: Top 0.9" – this is the first thing judges see

#### BLOCK 2 – Real-world Stakes (MOVED from Slide 4 Viability → Real need) – Orange
```
⚖️ REAL-WORLD STAKES: CERT-In requires every organization to keep 180 days of logs and report incidents within 6 hours. Manual parsing can't meet this deadline.
```
- Font: Calibri 11pt Bold, Orange Dark #9A3412
- Box: Light Orange #FFEDD5 fill, Orange #FF6B35 border 1.5pt, left accent bar Orange, 0.5" height
- This bullet is REMOVED from Slide 4 (see below)

#### BLOCK 3 – Who This Affects (MOVED from Slide 5 Impact, but KEEP on Slide 5 as well) – Teal
```
👥 WHO IT AFFECTS: Security teams at organizations like NTRO, NCIIPC, banks, telecom operators, and power utilities – all critical infrastructure where log blind spots = national risk.
```
- Font: Calibri 11pt, Teal Dark #0F766E
- Box: Light Teal #E8FAF9 fill, Teal #2EC4B6 border 1.5pt, left accent bar Teal
- Keep reference on Slide 5 as well (duplicate allowed)

#### BLOCK 4 – Concrete Messy Logs Example as Visual Proof (MOVED from Slide 3, DUPLICATE – keep on Slide 3 too) – 3 columns side by side
```
Title: 📂 VISUAL PROOF – Same event, three different languages (why parsers break):

[Column 1 – SYSLOG]
SYSLOG (Linux / sshd)
Oct 12 10:00:23 server sshd[123]:
Failed password for root
from 192.168.1.1 port 22

[Column 2 – JSON]
JSON (App / Cloud)
{"ts":"2026-10-12T10:00:23Z",
 "event":"auth_failure",
 "user":"root","ip":"192.168.1.1"}

[Column 3 – WEB / NCSA]
WEB / NCSA (Apache / Nginx)
192.168.1.1 - - [12/Oct:10:00:23]
"POST /login 401"
"Failed password for root"
```
- Font: Title 11pt Bold Navy, Code blocks 8pt Consolas/Calibri, Gray #3C3C3C, light gray background #F5F7FA, border #E2E8F0
- Layout: Three rounded boxes 4.0" wide each, side by side at Top 3.1", Height 1.0", with shadow
- This proves problem BEFORE solution. Keep same example on Slide 3 as "how we solve it" demo – can be slightly trimmed on Slide 3 if crowded.

#### BLOCK 5 – Tagline (EXISTING – keep exactly as is, now positioned as answer)
```
💡 Tagline: "Every log speaks a different language. We make them speak one."
```
- Font: Calibri 13pt Bold, White on Navy #0A1931 fill, centered, rounded box, shadow
- Position: Top 4.2", Height 0.5"
- Keep exact wording

#### BLOCK 5b – Differentiation Callout (from earlier edit – keep as highlighted one-liner near top of solution section)
```
Unlike tools that need a hand-written parser config for every new format, ours uses an LLM to write that rule automatically — once — then reuses it for free.
```
- Font: Calibri 10pt Bold, Orange Dark #9A3412, centered
- Box: Light Orange #FFEDD5, Orange border 2pt, positioned immediately after tagline at Top 4.75"

#### BLOCK 6 – 3-Step Solution Summary (EXISTING – keep exactly as is)
```
[Box 1 – COLLECT & IDENTIFY – Teal border]
① COLLECT & IDENTIFY
• Ingestion: Bash/syslog collector + FastAPI API (Python, FastAPI, Vercel)
• Classification: scikit-learn checks known vs novel, Drain3 groups patterns
• Tools: Python, Bash, FastAPI

[Box 2 – UNDERSTAND & MAP – Green border]
② UNDERSTAND & MAP
• FAST PATH (green): Rule Store Upstash – cached rules, instant reuse
• SLOW PATH (orange): LLM Rule Writer – writes rule once for unseen format
• Review queue for edge cases (annotation)
• Tools: Upstash, LLM Gemini/Groq/Claude

[Box 3 – CLEAN & DELIVER – Navy border]
③ CLEAN & DELIVER
• Normalization: Field normalization + Common Schema (Python, Pandas)
• Output: Standardized JSON → SIEM / Monitoring / Analytics
• 0.28 ms/line, 99.5% fast path, <$15/yr
```
- Font: Title 11pt Bold (Teal Dark / Green Dark / Navy), Body 9pt Regular #323232
- Layout: Three boxes 3.9" wide, 1.8" tall, side by side at Top 5.4", with shadows
- Keep exact 3-step wording as in existing deck: Collect & Identify → Understand & Map → Clean & Deliver

**Visual Balance Note:** Slide 2 now has more content at top, so shrink tagline/solution block to 9-10pt (instead of 12pt) and tighten line spacing to 1.0 to avoid overcrowding – do NOT cut content.

---

## SLIDE 4 – Feasibility and Viability – REMOVE ONE BULLET

### Original Slide 4 Structure (keep everything except one bullet):

**Left Column – Feasibility (KEEP EXACTLY AS IS):**
```
🔧 Feasibility
• Drain3: 0.016 ms/line, 97.2% grouping accuracy on 12 Loghub systems
• FormatGate: 100% known-family, 95.2% novel recall (Loghub real logs)
• LLM discovery: Once per template → Upstash persistence, survives cold start
• Vercel serverless: 285 MB bundle (<500 MB limit), cold start = joblib.load
• Pandas offline: saves 75MB bundle, not in hot path
• 0.28 ms/line end-to-end, 99.5% fast path

Challenges → Our Fix table:
[Keep existing table exactly as is]
```

**Right Column – Viability – REMOVE "Real need" bullet:**

BEFORE (old):
```
Viability
• Real need: CERT-In requires 180 days logs, 6 hours reporting  <-- DELETE THIS
• Can stay in India
• Business model
• Grows easily
• Wide market
```

AFTER (new – keep remaining bullets exactly as is):
```
💼 Viability (Real need bullet moved to Slide 2)

• Can stay in India: Built on open-source (Python, FastAPI, Drain3, scikit-learn) + Indian cloud (Vercel KV / Upstash), no foreign dependency, data stays local

• Business model: Freemium for SMEs, enterprise license for NTRO/NCIIPC/banks/telecom/power – <$15/yr LLM cost vs $1000s, saves SOC toil

• Grows easily: Horizontal scale – FastAPI stateless, Vercel serverless, Bash collectors work anywhere (syslog, journalctl, docker, kubectl), 3.5k logs/sec per instance

• Wide market: Every org with >1 log source needs this – banks, telecom, power, government (NTRO, NCIIPC), healthcare, e-commerce. TAM = all of India's digital infra

Note: CERT-In 180 days / 6 hours requirement now appears on Slide 2 as real-world stakes (moved per resequencing instructions) – not duplicated here to avoid repetition.
```
- Keep Feasibility column, Challenges → Our Fix table, and remaining Viability bullets exactly as is
- Only deletion: the CERT-In "Real need" bullet

---

## SLIDE 3 & SLIDE 5 – No Structural Changes (per instructions)

- **Slide 3 (Technical Approach):** Keep architecture diagram (final icon version), tech stack box on right, messy logs example at bottom – can be trimmed slightly to "✅ HOW WE SOLVE IT – Same messy logs from Slide 2 → clean JSON: ..." since example now also appears on Slide 2 as problem proof. Your judgment – keep whichever fits space better, but do NOT delete entirely.

- **Slide 5 (Impact):** Keep three stat visuals (Cost for one year, Share of logs sent to LLM, etc.) + small caption. Keep NTRO/NCIIPC naming on this slide as well (duplicate allowed). No structural changes.

---

## General Constraints Met

- ✅ Total slide count: 6 (no increase)
- ✅ CERT-In stat: moved from Slide 4 to Slide 2, not removed from deck
- ✅ NTRO/NCIIPC naming: added to Slide 2, kept on Slide 5 (repeated as reminder)
- ✅ Messy-log example: added to Slide 2 as problem proof, kept on Slide 3 as solution demo (duplicated, not removed)
- ✅ Color palette: Navy #0A1931, Orange #FF6B35, Teal #2EC4B6, Green #22C55E for fast path – unchanged
- ✅ Fonts: Calibri, existing sizes (tightened slightly on Slide 2 to balance weight)
- ✅ Formatting: Bold, bullet style, color accents match existing deck conventions

---

## Ready-to-Use Files

- `SIH2026_Resequenced_v3.pptx` – Full 6-slide deck with resequenced Slide 2 & Slide 4 implemented
- This markdown – Paste-ready text for manual rebuild in PowerPoint
