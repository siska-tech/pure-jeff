## Native host matrix: Linux x86_64

- commit `f5175979e9066e1ee38fd2eabcd03d7f447c4e32`, rustc 1.99.0 (b940084d7 2026-09-28)
- CPU: AMD EPYC 9V45 96-Core Processor; logical CPUs 4
- **passed: True**
- max abs difference from the official reference: 3.58e-06
- old 28-case Native gate (28 cases): max abs difference 3.7550926208496094e-06 (a different build and dependencies; descriptive)

### gemm CACHE_INFO

| CACHE_INFO (bytes/ways) | pinned CPUs | unpinned processes |
| --- | --- | ---: |
| 24576/12 / 524288/16 / 33554432/16 | 0-3 | 3 |

### Processes

| arm | threads | process / CPUs | rc | decisions | gate | bit mismatches | max abs vs reference | load s | wall s | peak |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 1.62 | 617.0 | rss 2,213.0 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 1.69 | 365.6 | rss 2,277.3 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 1.57 | 351.8 | rss 2,278.1 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 1.64 | 347.0 | rss 2,278.0 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 1.49 | 352.3 | rss 2,277.3 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 1.53 | 619.2 | rss 2,213.0 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 1.61 | 108.1 | rss 1,188.6 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 1.50 | 63.2 | rss 1,185.6 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 1.53 | 107.4 | rss 1,196.2 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 1.51 | 77.4 | rss 1,188.6 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 4.330562382, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 4.713968118, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1.35 | 8.52 | 42.11 | 151.50 |
| 2 | 0.78 | 4.87 | 24.88 | 88.82 |
| 4 | 0.88 | 4.92 | 23.91 | 82.55 |
