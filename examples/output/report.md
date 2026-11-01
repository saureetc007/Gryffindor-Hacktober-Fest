# DecisionLens Recovery Report

**Total Decisions Recovered:** 1

---

## 1. Retain C implementation for parser

- **ID:** `DEC-001`
- **Status:** `REJECTED`
- **Decided:** The team decided to keep the existing C implementation for parser/core.c. To address memory safety concerns and buffer overflow risks, the team will instead integrate AddressSanitizer and LibFuzzer into the CI pipeline.
- **Discussion:** [#issue-142 Proposal: Rewrite parser/core.c in Rust for memory safety](https://github.com/example-org/fastparser/issues/142)

### Rejected Alternatives
- **Rewrite parser/core.c in Rust:** The Rust prototype resulted in a 2x performance regression (145 MB/s vs 295 MB/s) due to mandatory slice bounds checks and UTF-8 verification. Additionally, there were concerns regarding the introduction of cargo/rustc as mandatory build dependencies and the potential loss of C99 portability for embedded toolchains.

### Linked Code
- `parser/core.c`
- `MB/s`

### Sources & Verbatim Quotes
- **Comment [`c1`](https://github.com/example-org/fastparser/issues/142#issuecomment-1001):**
  > "I propose that we rewrite parser/core.c in Rust. Our recent security audit flagged several memory safety concerns and buffer overflow risks in the C parser."

- **Comment [`c2`](https://github.com/example-org/fastparser/issues/142#issuecomment-1002):**
  > "introducing Rust adds cargo and rustc as mandatory build dependencies. Our project has always targeted strict C99 portability across embedded toolchains."

- **Comment [`c3`](https://github.com/example-org/fastparser/issues/142#issuecomment-1003):**
  > "The routines in parser/core.c are called millions of times per second in hot loops by our C engine. Any foreign function interface crossing could degrade parsing throughput."

- **Comment [`c5`](https://github.com/example-org/fastparser/issues/142#issuecomment-1005):**
  > "The Rust prototype in parser/core.c is 2x slower in benchmarks compared to the C implementation (145 MB/s vs 295 MB/s). The regression comes from mandatory slice bounds checks and UTF-8 verification."

- **Comment [`c7`](https://github.com/example-org/fastparser/issues/142#issuecomment-1007):**
  > "Sprinkling unsafe defeats the original motivation of adopting Rust for memory safety."

- **Comment [`c7`](https://github.com/example-org/fastparser/issues/142#issuecomment-1007):**
  > "A 2x slowdown in parser/core.c is a dealbreaker for production workloads."

- **Comment [`c8`](https://github.com/example-org/fastparser/issues/142#issuecomment-1008):**
  > "PR #145 was reverted and parser/core.c will remain implemented in C."

- **Comment [`c8`](https://github.com/example-org/fastparser/issues/142#issuecomment-1008):**
  > "We will integrate AddressSanitizer and LibFuzzer into our CI pipeline to catch memory issues."

### Unverified Notes
- *All claims and quotes verified against ground truth.*

---
