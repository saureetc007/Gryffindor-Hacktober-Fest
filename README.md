# DecisionLens

**DecisionLens** is a decision recovery and intelligence system designed for open-source engineering codebases (Hackathon Problem 6: Decision Recovery).

It reads historical discussion threads (GitHub issues, pull requests, or saved PEP discussions in JSON or plain text), extracts accepted decisions, rejected alternatives, and technical reasoning, and warns developers when a new pull request touches code tied to a past decision.

---

## Setup

DecisionLens runs entirely locally using open-weight models via Ollama. It never calls or requires closed commercial APIs (OpenAI, Anthropic, or Gemini).

1. **Install Ollama:**
   Download and install from [ollama.com](https://ollama.com).

2. **Pull the model:**
   ```bash
   ollama pull gemma4:12b
   ```

3. **Install Python dependencies:**
   ```bash
   pip3 install -r requirements.txt
   ```

---

## CLI Usage

DecisionLens provides three primary commands:

### 1. `learn` — Recover Decisions from Discussion Threads
Parse and analyze historical discussion threads, extract proposals, verify claims, merge duplicates, and link touched code:
```bash
python3 -m decisionlens learn examples/sample_thread.json --out decisions.json
```

### 2. `check` — Warn When Pull Requests Touch Past Decisions
Analyze an incoming pull request against recovered decisions to detect potential conflicts:
```bash
python3 -m decisionlens check examples/sample_pr.json --decisions decisions.json
```
If a changed file or topic overlaps with a past decision (e.g., modifying `parser/core.c` when a Rust rewrite was previously rejected), DecisionLens outputs a warning with verifiable source links.

### 3. `report` — Generate Markdown Decision Reports
Export recovered decisions to a human-readable Markdown report:
```bash
python3 -m decisionlens report decisions.json --out report.md
```

---

## How Verification Works

DecisionLens enforces a strict deterministic code boundary to prevent AI hallucinations:

- **Model Only Interprets:** The model (`gemma4:12b`) is restricted solely to reading discussion text and judging consensus.
- **Code Produces Identity & Structure:** Python code generates and validates all IDs, URLs, and file paths. The model is never asked for URLs or paths.
- **Verbatim Quote Verification:** Every extracted claim requires a comment ID and a verbatim quote. Code normalizes whitespace and casing and deterministically checks that the quote appears in the referenced comment. If not, the claim is dropped. Proposals left with zero valid claims are discarded.
- **Deterministic Sources:** Source links are built by code directly from the ground-truth thread comments, anchoring every claim to its exact comment URL.

---

## Status Labels

Every recovered decision is classified with one of the following statuses:

- `ACCEPTED`: The proposal was accepted and implemented with consensus backed by verified quotes.
- `REJECTED`: The proposal or alternative was rejected or reverted with verified reasoning.
- `UNRESOLVED`: The debate was ongoing or no final consensus was reached.
- `LOW_CONFIDENCE`: A decision was synthesized, but the supporting status quote failed verbatim verification in the thread.

---

## Known Limits

- **Sarcasm and Rhetorical Reversals:** Local open-weight models can sometimes misinterpret sarcastic remarks, Devil's advocate arguments, or rhetorical debate styles as genuine consensus.
- **Verification Boundary:** Verbatim quote checking successfully prevents invented or hallucinated quotes from entering decision records. However, it verifies lexical existence, not semantic intent: if a model correctly quotes a user but misinterprets the context of what that quote meant, verbatim matching alone cannot detect the semantic misread.
