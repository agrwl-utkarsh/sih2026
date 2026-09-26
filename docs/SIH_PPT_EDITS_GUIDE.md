# SIH 2026 – PPT Edits Implementation Guide
Team: AlgoRhytm | PS ID: 26156 | Theme: Blockchain & Cybersecurity
Project: Universal Log Pre-processing Framework

> All edits preserve 6-slide count, navy blue (#0A1931), orange (#FF6B35), teal (#2EC4B6) palette, and existing fonts. Slides 4 and 6 untouched per request.

---

## 1. Slide 1 (Cover) – Team ID

**Original text:** `Team ID –`

**New text:**
```
Team ID – [INSERT YOUR ACTUAL TEAM ID]
```

- Keep same font, size, position.
- Just replace the placeholder with your actual ID from SIH portal.
- File already has this in the edited PPT: `/docs/SIH2026_AlgoRhytm_PS26156_Universal_Log_Framework_EDITED.pptx`

---

## 2. Slide 2 (Idea / Proposed Solution) – Differentiation Callout

**Add this exact line as a highlighted one-liner near the top, NOT buried in bullets:**

> **"Unlike tools that need a hand-written parser config for every new format, ours uses an LLM to write that rule automatically — once — then reuses it for free."**

**PowerPoint build instructions:**

- Position: Top of slide content area, below slide header (0.9" from top)
- Box: Width 12.3", Height 0.7", Fill: #FFEDD5 (light orange 255,237,213), Border: #FF6B35, 2pt
- Text: Font Calibri 16pt Bold, Color #9A3412 (dark orange), Left-aligned, with 8pt padding
- Effect: This creates visual distinction from Logstash/Fluentd/Elastic – judges see it first.

Already implemented in Slide 2 of edited PPT.

---

## 3. Slide 3 (Technical Approach) – Full Diagram Redesign

**Requirement:** Replace "METHODOLOGY: HOW EVERY LOG FLOWS" logic-flowchart (7-step) with proper layered system architecture diagram. Keep tech stack box on right and "messy logs in → clean logs out" example at bottom.

### Final Diagram – 7 Boxes Total (Legible)

```
Left labels (navy vertical tags, white text): INGESTION | CLASSIFICATION | RULE | PROCESSING | OUTPUT

Layer 1 – INGESTION (top row, side-by-side):
[LOG SOURCES] → [INGESTION COLLECTOR]
- LOG SOURCES: "Servers, Firewalls, Apps (Python/Bash)" – white fill, navy border #0A1931
- INGESTION COLLECTOR: "Bash/syslog + FastAPI API (Python, FastAPI, Vercel)" – light blue #EEF5FF, navy border
- Arrow: Navy #0A1931, 2.5pt, solid

Layer 2 – CLASSIFICATION (center, wide):
[CLASSIFICATION ENGINE] – teal border #2EC4B6, light teal fill #E8FAF9
- Line1: "scikit-learn: known vs novel?"
- Line2: "Drain3: groups & extracts patterns"
- Tool tag bottom: "scikit-learn, Drain3, Python" – small gray box

Split from bottom of Classification Engine:
- GREEN arrow left-down labeled FAST PATH (green #22C55E, 4pt, label box #DCFCE7 background, #15803D text)
- ORANGE arrow right-down labeled SLOW PATH (orange #FF6B35, 4pt, label box #FFEDD5 background, #9A3412 text)

Layer 3 – RULE (two boxes side-by-side):
Left – [RULE STORE (Upstash)] – green border #22C55E, light green fill #F0FDF4
- "Cached rules for known formats - instant reuse (Upstash, Python)"
- This is FAST PATH destination

Right – [LLM RULE WRITER] – orange border #FF6B35, light orange fill #FFF7ED
- "Writes a new rule once for unseen formats (LLM Gemini/Groq/Claude)"
- Annotation below in 9pt gray: "* review queue for edge cases" (NOT a separate box)

Connector: Orange arrow from LLM box left to Rule Store box labeled "cache once" 11pt orange

Layer 4 – PROCESSING (center):
[ NORMALIZATION & SCHEMA ] – navy border, light blue fill
- "- Field normalization + Common Schema enforcement (Python, Pandas)"
- Green arrow from Rule Store (left) down then right to this box

Layer 5 – OUTPUT (bottom center):
[OUTPUT: STANDARDIZED JSON → Downstream SIEM / Monitoring / Analytics (JSON, Python)]
- Navy border, white fill, bold title

Arrows:
- Navy #0A1931 for main flow (Ingestion → Classification → Output)
- Green #22C55E for FAST PATH (known format, no LLM)
- Orange #FF6B35 for SLOW PATH (new format, LLM-assisted)
```

### Assets Provided:

1. **Ready-to-use PNG (recommended):** 
   - `/docs/slide3_architecture_diagram_v2.png` – clean vector-style, 1600px wide, transparent-friendly
   - `/static/slide3_architecture_diagram_v2.png` – same for web preview
   - `/docs/slide3_architecture_diagram.png` – earlier Pillow version (fallback)

   Insert into Slide 3: Place at Left 0.3", Top 0.9", Width 8.5", Height 5.8", keep tech stack box at Right 9.2", Top 0.9", Width 3.8", Height 4.0".

2. **Box-by-box rebuild in PowerPoint** (if you prefer native shapes):
   - Use Rectangle shapes with rounded corners (0.1" radius)
   - Fonts: Calibri Bold 14pt for titles, Calibri 11-12pt for subtitles
   - Colors as hex above
   - Arrows: Insert → Shapes → Arrow, set weight 2.25-3pt for navy, 3-4pt for fast/slow emphasis

**Tool labels included per requirement:** Python, FastAPI, Drain3, scikit-learn, LLM, Pandas, Upstash, Vercel, JSON – all visible in small tag at bottom of each box.

**Fast vs Slow path distinction:** Two different colored lanes, keeping existing green FAST PATH emphasis style (green box + green arrow + "FAST PATH" label with green background).

---

## 4. Slide 5 (Impact and Benefits) – Caption for Modeled Figures

**Under the three stat visuals (Cost for one year, Share of logs sent to LLM), add:**

**Small unobtrusive caption (9pt, gray #787878, left-aligned, 0.4" high box):**

```
Caption: Modeled / estimated figures — assumes 1M logs/day, ~15-25 distinct log formats/month, ~8 sightings to graduate a novel template; LLM = Gemini Flash / Groq gpt-oss-20b pricing; fast-path 99.5% measured on synthetic + Loghub replay.
```

**Placement:**
- Directly below the three stat cards, at Top 4.5", Left 0.5", Width 12.3"
- Should read as caption, not new section – use italic or lighter gray, no border, no background fill.

**Why this wording works:**
- Clarifies cost ($<15/year) and <2% LLM share are modeled, not billed.
- States assumption: 1M logs/day, 15-25 new formats/month (from your pipeline docs: Drain3 + FormatGate)
- References graduation threshold (TPL_GRADUATE_AFTER=8 from README)
- Mentions pricing model and measured fast-path.

Already implemented in edited PPT Slide 5.

---

## Files Delivered

- **Edited PPT (6 slides, ready to submit):** `docs/SIH2026_AlgoRhytm_PS26156_Universal_Log_Framework_EDITED.pptx`
- **Architecture Diagram v2 (recommended):** `docs/slide3_architecture_diagram_v2.png`
- **Architecture Diagram v1 (Pillow fallback):** `docs/slide3_architecture_diagram.png`
- **This guide:** `docs/SIH_PPT_EDITS_GUIDE.md`

---

## Checklist – What NOT to change

- [x] Do not add new slides (still 6)
- [x] Do not remove existing content beyond specified diagram rebuild
- [x] Do not change wording elsewhere
- [x] Do not touch Slide 4 (Feasibility) and Slide 6 (References) content
- [x] Preserve color palette: navy #0A1931, orange #FF6B35, teal #2EC4B6, green #22C55E for FAST PATH
- [x] Keep "messy logs in → clean logs out" example at bottom of Slide 3
- [x] Keep tech stack box on right of Slide 3

---

## Quick Rebuild Steps in PowerPoint

1. Open your original 6-slide deck.
2. Slide 1: Select "Team ID –" text box → change to "Team ID – [INSERT YOUR ACTUAL TEAM ID]" → replace bracket with real ID later.
3. Slide 2: Insert → Text Box at top → paste callout line → Format Shape → Fill #FFEDD5, Line #FF6B35 2pt → Font Bold 16pt #9A3412.
4. Slide 3: Delete only the central flowchart (keep right tech stack and bottom example). Insert → Pictures → `slide3_architecture_diagram_v2.png` → resize to 8.5" wide.
5. Slide 5: Below stat visuals, Insert → Text Box → paste caption → Font 9pt gray.
6. Save as PPTX, verify 6 slides.

Ready for internal hackathon / SIH submission.
