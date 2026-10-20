## Native host matrix: Linux x86_64

- commit `190fec6f7febed41f9d9e793c6474699ed68bee5`, rustc 1.99.0 (b940084d7 2026-09-28)
- CPU: AMD EPYC 9V74 80-Core Processor; logical CPUs 4
- **passed: True**
- max abs difference from the official reference: 3.58e-06
- old 28-case Native gate (28 cases): max abs difference 3.7550926208496094e-06 (a different build and dependencies; descriptive)

### gemm CACHE_INFO

| CACHE_INFO (bytes/ways) | pinned CPUs | unpinned processes |
| --- | --- | ---: |
| 16384/8 / 524288/8 / 33554432/16 | 0-3 | 3 |

### Processes

| arm | threads | process / CPUs | rc | decisions | gate | bit mismatches | max abs vs reference | load s | wall s | peak |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 1.86 | 670.4 | rss 2,212.1 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 1.85 | 376.2 | rss 2,276.8 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 1.85 | 379.3 | rss 2,281.6 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 1.82 | 377.9 | rss 2,277.7 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 1.82 | 376.7 | rss 2,276.7 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 1.89 | 668.5 | rss 2,212.0 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 1.84 | 137.5 | rss 1,179.7 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 1.84 | 84.5 | rss 1,186.2 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 1.86 | 136.8 | rss 1,187.1 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 1.84 | 97.5 | rss 1,196.5 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 4.523209968, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 4.679781205, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1.79 | 10.38 | 43.55 | 145.00 |
| 2 | 1.06 | 5.85 | 24.34 | 80.18 |
| 4 | 1.25 | 6.03 | 23.82 | 75.76 |
