# Stable evaluation artifacts

This directory keeps the final, reproducible evidence for the integrated
memory pipeline. Parameter sweeps, ablations, caches, state databases, and
intermediate server transfers are intentionally excluded.

- `observation`: formation quality and performance results.
- `episode`: final event and Observation grouping audits.
- `candidate`: layered memory-graph audit.
- `lifecycle`: activation, confidence, stability, and recession evaluation.
- `reflection`: final DeepSeek skill and lifecycle guard checks.
- `retrieval`: 47+530 and formal 1000-query retrieval results.
- `end_to_end`: representative full-chain API evaluation and rendered inputs.

Every artifact is immutable test evidence. New evaluations should add a new
named result rather than overwrite an existing result.
