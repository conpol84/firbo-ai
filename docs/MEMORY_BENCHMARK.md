# Synthetic memory recall benchmark

This benchmark uses **invented data only**. It does not contain owner memories, production conversations, account information, or exported application data.

It compares two deterministic retrieval baselines:

1. `lexical` — normalized token overlap.
2. `hybrid` — lexical overlap + character n-gram similarity + a small synthetic concept-alias signal.

The concept-alias signal is intentionally limited to the benchmark fixture. It is a reproducible semantic-contract baseline, **not** a production embedding model and must not be described as one.

Run:

```bash
python -m benchmarks.memory_recall
```

The fixture includes Greek, English and Greeklish-style queries so regressions in multilingual recall can be detected without using private memory.
