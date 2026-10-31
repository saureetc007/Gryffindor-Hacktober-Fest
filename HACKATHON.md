# HACKATHON.md

## Team name

Gryffindor

## Team members

- Saureet Chakrabarti
- Krish Saini
- Pavitr Makhija
- Aadarsh Bhardwaj

## Problem statement

**Problem 06: Open Source Decision Intelligence and Knowledge Recovery**

DecisionTrace recovers historical engineering decisions, rejected alternatives, and technical reasoning from open-source discussions. It connects recovered decisions to relevant code changes and surfaces historical context during pull requests, with verifiable evidence from original discussions.

## Models we use and why

**Gemma 4 12B**

Gemma 4 12B is used as the main AI model in our project.

It reads GitHub discussions, issues, pull requests, and technical conversations. It finds important decisions, rejected ideas, and the reasons behind them.

For every result, it gives:

Decision status: accepted, rejected, or uncertain

Reason for the decision

Rejected alternatives

Exact supporting quote

Original GitHub source link

**Qwen 3.5 4B**

Qwen 3.5 4B is used as our coding assistant during development.

It helps us build the frontend, backend, login system, database, GitHub integration, APIs, and tests.


Both models run locally on our laptops using Ollama.
 Project data is processed locally, and only public GitHub data is collected for analysis.


