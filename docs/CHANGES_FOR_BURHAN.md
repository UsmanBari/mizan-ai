# Reply to Burhan: what Usman changed (22 Nov 2026)

Burhan, I took your zip as the new base. Your fixes to my files (thought signatures in `llm.py`, `answer_numbers` / `number_evidence` grounding, the page-image endpoint) are all good and kept as they are. **Tests: 39 passed.** The frontend type-checks and builds.

---

## 1. What I changed

| Area | Change | Why |
|---|---|---|
| Prices | `config.py` + `.env.example`: **1.50 / 9.00 USD per 1M tokens** (gemini-3.5-flash list price, checked 22 Nov). Flash-Lite noted as 0.30 / 2.50 | Your item 2. Note: 3.5 Flash is about **5× more expensive** than 2.5 Flash was |
| Notebook 02 | It still set `gemini-2.5-flash` and the old prices as defaults (that would have overridden the config). Now 3.5 Flash + new prices, a budget note (~USD 15–30 for the full run), and "delete old `qa_*.jsonl` first" | Results must all come from one model and the new grounding rule |
| `run_qa.py` | **Backoff on 503/429** (5 → 10 → 20 → 40 → 60 s, 6 tries). A resumed run now **retries failed questions** (before, an error line counted as "done" forever). Summary keeps the last record per question | Your QA issue 3 |
| `run_qa.py` | New metric **`inline_page_mismatch_rate`**: pages written in the answer text that aren't in the citations. Each record also stores `prompt_version` | Your QA issue 1 (citation precision) |
| `prompts.py` → **v1.1** | "Give pages ONLY in the citations field, never in the answer text." And: "If both consolidated and unconsolidated exist and the question doesn't say which, answer with consolidated and say so" | QA issues 1 and 2 |
| `build_psx_testset.py` (your file, sorry) | Every question now names the basis: *"According to its consolidated financial statements, what was…"*. For a **loss year (PRL)**, the % growth question becomes "by how much did it change (Rs '000)", because a % change from a negative base is meaningless. Also dropped "(total income for banks)" from revenue questions (no banks in our set) | QA issue 2 + the PRL note. Output: **54 extraction examples, 81 QA (26 growth %, 1 change in amount)** |
| **New `eval/verify_labels.py`** | Opens each labelled PDF page and prints the line where the current and prior values appear, flagging "NOT FOUND". `--who burhan` shows only your rows | Speeds up the human check. It doesn't replace it: you still look at each row |
| Docs | README (39 tests, model, PSX set), `MIZAN_AI_PROJECT.md`, `AI_TOOLS_DECLARATION.md` (added the lines you suggested: draft labels verified by hand, UI redesign + fixes with Claude) | Your item 7 |
| Proposal | Model → 3.5 Flash; cost section recalculated (pilot ≈ USD 140–175/month on Flash-Lite, ≈ 540–580 on Flash); PSX set → 9 FY2026 reports, 54 / 81; label verification split; F3 describes your green/blue/amber evidence UI; risks row mentions backoff + rule fallback; architecture diagram says 3.5 Flash | Your item 84 + consistency |

## 2. Still on you
- [ ] **Verify your 5 reports**: LUCK, PIOC, OGDC, POL, PRL. `python eval/fetch_psx_reports.py`, then `python eval/verify_labels.py --who burhan`, then check each row in the PDF and set `labeller` = burhan
- [ ] **Replace INDU** with another June-year-end company whose full annual report is on PSX, and label its 6 fields (takes us back to 60 / ~90)
- [ ] Run **notebook 03** (extraction: rules vs 3.5 Flash; local Qwen if Ollama runs) after labels are verified
- [ ] Rebuild: `python eval/build_psx_testset.py`

## 3. On me (Usman)
- [ ] Verify HUBC, AGIL, GHNI, POWER the same way
- [ ] Delete old QA results, then re-run notebook 02 (new grounding + prompt v1.1 + backoff)
- [ ] Put the real numbers into the proposal (Sections 6, 10, 13)

## 4. One risk I found: fonts at build time
`next/font/google` downloads Public Sans / Source Serif 4 **during `npm run build`/`dev`**. On a machine with no internet (or a blocked network on campus) the build fails with "Failed to fetch font". It's fine on our laptops and on Vercel. For the demo: build once at home and run `npm start` from that build, or switch to `next/font/local` with the font files in the repo. Your call, since it's your part.
