# HACKATHON.md

## Team name

Gryffindor

## Team members

- Saureet Chakrabarti
- Krish Saini
- Pavitr Makhija
- Aadarsh Bhardwaj

## Problem statement

**Problem 06: Open Source Decision Intelligence and Knowledge Recovery — DecisionLens**

DecisionLens recovers historical engineering decisions, rejected alternatives, and technical reasoning from open-source discussions (GitHub issues, pull requests, and saved PEP discussions in plain text or JSON). It connects recovered decisions to relevant code changes and warns developers when a new pull request touches code tied to a past decision, backing every insight with verifiable verbatim evidence from the original discussions.

## Models we use and why

### `gemma4:12b`

The project's runtime AI is **ONLY** `gemma4:12b` (Gemma, open-weight, run locally through Ollama). We never add or use OpenAI, Anthropic, Gemini, or any other proprietary API, SDK, or key.

- **Role:** `gemma4:12b` is the only runtime model used for all reading, comparison, and decision judgment across DecisionLens.
- **Why we use it:**
  - **Open-Weight & Local Execution:** Runs locally via Ollama, ensuring complete privacy, zero external data leakage of repository discussions, and full offline execution capability.
  - **Deep Reasoning & Interpretation:** Provides strong language comprehension necessary to parse complex technical arguments, recognize consensus, and extract structured decisions and rejected alternatives.
  - **Deterministic Code Boundary:** The model only interprets text. Deterministic code (not the model) produces and manages all IDs, URLs, and file paths, and verifies that quotes appear verbatim in the source comments before any claim is accepted.

## Development Tools

- **Antigravity:** Used solely as the coding assistant tool during development, not as a runtime project model.
