# Assignment 3: what we still have to do

**U** = Usman · **B** = Burhan · **Both** = together
Tick boxes as you go. The order matters: later steps need earlier ones.

> ⚠ Remember the rubric: if a member is absent from the demo they get **zero**, and each person is asked about **their own code** in the viva (8 marks each).

## Status, 22 Nov 2026
- ✅ Code merged (Burhan's redesign + fixes, Usman's follow-ups); **39 tests pass**
- ✅ Model fixed to **gemini-3.5-flash** everywhere (prices 1.50 / 9.00)
- ✅ PSX test set: 9 FY2026 reports, draft labels → **verify by hand** (Burhan: LUCK, PIOC, OGDC, POL, PRL · Usman: HUBC, AGIL, GHNI, POWER) with `eval/verify_labels.py`
- ⏳ Replace INDU (B) · Re-run notebook 02 (U) · Run notebook 03 (B) · Real numbers into the proposal (U)
- See `docs/CHANGES_FOR_USMAN.md` and `docs/CHANGES_FOR_BURHAN.md` for details

---

## Step 0: Get on the same page (today, 30 min)
- [ ] **B** Read `docs/BURHAN_GUIDE.md` fully
- [ ] **Both** Read `docs/MIZAN_AI_PROJECT.md` and the proposal doc
- [ ] **Both** Quick call: agree on who owns what (table in Step 2)

## Step 1: GitHub repo (U, 30 min)
- [ ] **U** Create the repo `mizan-ai` on github.com/usmanbari-ub (private is fine)
- [ ] **U** Settings → Collaborators → add Burhan's GitHub account
- [ ] **U** Also add the **instructor / TA** (the rubric checks "repository link with instructor access")
- [ ] **U** First commit: README, `.gitignore`, `.env.example`, `docker-compose.yml`, `.github/`

## Step 2: Push the code, each person their own part (both, 1 hr)
The rubric (C6) checks "meaningful commits from every member", so each of you pushes **your own** folders from **your own** account, in a few commits each (not one giant commit).

| Usman pushes | Burhan pushes |
|---|---|
| `backend/mizan/api/` | `backend/mizan/ingest/` |
| `backend/mizan/agent/` | `backend/mizan/extraction/` |
| `backend/mizan/retrieval/` | `backend/mizan/alerts/` |
| `backend/mizan/calculator.py`, `llm.py`, `store.py`, `config.py`, `models.py`, `services.py` | `backend/mizan/worker.py`, `cli.py` |
| `backend/tests/` | `frontend/` (whole Next.js app) |
| `eval/run_retrieval.py`, `eval/run_qa.py`, `eval/common.py`, notebooks 01, 02, 04 | `eval/run_extraction.py`, `build_psx_testset.py`, `fetch_psx_reports.py`, notebook 03 |
| `backend/Dockerfile`, CI | `frontend/Dockerfile` |

- [ ] **Both** Check that `cd backend && pytest -q` shows **39 passed** on your own laptop

## Step 3: Keys and accounts (30 min)
- [ ] **U** Free Gemini key: aistudio.google.com → Get API key → put it in `backend/.env` as `MIZAN_LLM_API_KEY` (**never commit `.env`**)
- [ ] **B** Telegram bot: open Telegram → @BotFather → `/newbot` → copy the token into `MIZAN_TELEGRAM_BOT_TOKEN`
- [ ] **B** Get your chat id: message your bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` → copy `chat.id`
- [ ] **Both** Run it locally: backend `uvicorn mizan.api.main:app --reload`, frontend `npm install && npm run dev` → open localhost:3000

## Step 4: PSX test set (B leads, both label, about 2–3 hrs)
This gives us 3 test sets at once (extraction, QA, retrieval on Pakistani data).
- [ ] **B** Fill `eval/data/psx_reports.csv` with 10 annual report PDF links (dps.psx.com.pk/company/SYMBOL → Financial Reports)
- [ ] **B** `python eval/fetch_psx_reports.py`
- [ ] **Both** Label 5 reports each in `eval/data/psx_labels.csv`: 6 fields per report (revenue, profit before tax, profit after tax, EPS, total assets, total equity), **this year + last year**, the unit, and the PDF page number. Use the consolidated statements.
- [ ] **Both** Cross-check 6 rows of each other's labels; write any disagreement in `notes`
- [ ] **Both** `python eval/verify_labels.py --who <you>` → check each row in the PDF → set `labeller` to your name
- [ ] **B** `python eval/build_psx_testset.py` → now 54 extraction / 81 QA; 60 / ~90 once INDU is replaced

## Step 5: Run the experiments (Colab, about 3–4 hrs total)
- [ ] **U** Notebook `01_retrieval_experiment`: run on Colab so the dense / hybrid / rerank rows fill in
- [ ] **U** Notebook `02_qa_experiment`: first the 5-question smoke test, then the full run (4 modes × 140 questions, 3 runs if the free key's limits allow; at least 1 run)
- [ ] **B** Notebook `03_extraction_and_psx`: rules vs Gemini (add the local Qwen model if Ollama works on your laptop) + PSX QA
- [ ] **Both** Commit `eval/results/` (summary.json, failure files, figures) so the results can be reproduced

## Step 6: Error analysis (both, 1 hr)
The rubric (D4) wants **≥ 10 failures per component, grouped by cause, with fixes**.
- [ ] **U** Read 10+ QA failures and 10+ retrieval failures; fill the "manual note" column in notebooks 01/02
- [ ] **B** Read 10+ extraction failures; note the cause and the fix in notebook 03

## Step 7: Update the proposal with the real numbers (U, 1 hr)
- [ ] **U** Section 6 table: add the dense / hybrid / rerank rows
- [ ] **U** Section 13 "First experiment": add the RQ1 numbers (accuracy rag_direct vs rag_calc, McNemar p)
- [ ] **U** Section 10: replace the estimated cost per question with the measured `cost_per_request_usd`
- [ ] **U** Export the proposal as **PDF** (or Word)

## Step 8: Demo material (B leads, 1–2 hrs)
- [ ] **B** 6–8 slides: problem → product → architecture → retrieval results → QA results (RQ1) → extraction results → 10+ failures grouped → latency & cost → functional tests 38/38
- [ ] **Both** Charts come from `eval/results/figures/` and the web app's **Evaluation** page
- [ ] *(optional, +2 marks C5)* **U** Deploy: frontend on Vercel, backend on Render. If not deployed, "runs from the repo with the README steps" also counts.

## Step 9: Final paperwork (U, 30 min)
- [ ] Finalise `docs/AI_TOOLS_DECLARATION.md` (add any other tools you used) → export as PDF
- [ ] Track declaration: one line, "Track: R&D Product" (it's also under the proposal title)
- [ ] Fill the **Group Self-Evaluation** column in the rubric form (bring it to the demo)

## Step 10: Submit on GCR (one package, U uploads)
- [ ] Proposal (PDF/Word)
- [ ] Approval evidence (the sent email thread; attach whatever exists)
- [ ] Track declaration
- [ ] GitHub repo link (+ deployed link if any)
- [ ] Evaluation slides
- [ ] AI tool declaration

## Step 11: Rehearse (both, 1 hr, the day before)
- [ ] Run the 10-minute demo in `docs/DEMO_AND_VIVA.md` twice; time it
- [ ] Each person explains the **other's** part once (the viva can ask anything)
- [ ] Backup plan: screenshots + saved `summary.json` in case the internet or the API dies

---

### Time estimate
About **12–15 hours of work total**, split between two people. Doable in 3–4 days if you start now.
