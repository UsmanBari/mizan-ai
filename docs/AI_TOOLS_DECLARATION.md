# Declaration of AI tools used

Group: Usman Bari (23i-0680), Syed Burhan Ahmad (23i-0757), Section A. Project: Mizan AI.

| Tool | Used for | How we checked it |
|---|---|---|
| Claude (Anthropic) | Picking the idea, analysing the assignment brief and rubric, drafting the proposal text, and writing most of the first version of the code, tests, evaluation scripts and notebooks | We read and ran all of the code, ran the test suite, reproduced the evaluation numbers ourselves, and each of us can explain our own modules (see docs/DEMO_AND_VIVA.md) |
| Claude (Anthropic), later sessions | UI redesign of the web app and several bug fixes (Gemini 3.x tool-call signatures, grounding tokenizer, OCR switch, extraction fallback); preparing **draft** gold labels for the PSX test set from the PDF text | Every draft label was verified by hand against the cited PDF page by a group member before being used as gold (labeller column = the member's name) |
| Gemini API (Google), model gemini-3.5-flash-lite | Runtime language model inside the product (answering, extraction, alert summaries) and the judge for non-numeric answers in evaluation | This is the product's AI component. Its outputs are evaluated in eval/ |
| Antigravity (Google, agentic IDE) | Running the evaluation scripts, writing the ratio library, facts store, compute_ratio tool, PSX QA v2 test-set builder, stage/abstention scoring, figures, and doc updates from our prompts | We reviewed every change, ran the 97 tests, and checked every reported number against eval/results/summary.json |
| Gemini (eval/draft_labels.py) | Drafting some PSX gold labels from the PDF text | Every value verified by hand against the PDF page before use; drafts not yet verified (APL, BERG, DADX, ATRL H1, DGKC Q1) are not used in any result |

All evaluation numbers in the proposal and the demo come from scripts in `eval/` and can be re-run on request. References in the proposal were checked by opening each source.
