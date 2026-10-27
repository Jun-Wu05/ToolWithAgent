# #412 Classification counts implementation plan

**Goal:** Successful JSON/KV/Header classification details expose real aggregate counts.

**Architecture:** Keep deterministic aggregation as the count authority; populate retained and backfilled details once in sanitize_classification_details. No frontend count reconstruction.

**Tech Stack:** Python, pytest; existing V2 backend and frontend regression gates.

1. Establish a green root/backend/frontend baseline in this isolated worktree.
2. Run `python -X utf8 -m pytest tests/test_classification_counts.py -q --basetemp=.pytest-tmp-412-red`; expect three assertion failures for missing/LLM counts.
3. Modify agent/tools/pipeline/common/llm_postprocessor.py to assign aggregate count after type alignment; run the same tests to green.
4. Regenerate docs/source-code-analysis.html with scripts/generate_source_code_analysis.py.
5. Run root pytest, venv backend tests, frontend test/lint/build; review the diff.
6. User reviews PR text before publication; provide manual browser acceptance for count/result consistency.
