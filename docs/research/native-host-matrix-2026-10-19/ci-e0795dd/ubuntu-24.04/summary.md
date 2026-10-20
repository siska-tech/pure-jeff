## Native host matrix: Linux x86_64

- commit `10a0a1ab4874c1b6da084ae521ef8da3e8883695`, rustc 1.99.0 (b940084d7 2026-09-28)
- CPU: AMD EPYC 9V45 96-Core Processor; logical CPUs 4
- **passed: True**
- max abs difference from the official reference: 3.99e-06
- old 28-case Native gate (28 cases): max abs difference 3.7848949432373047e-06 (a different build and dependencies; descriptive)

### gemm CACHE_INFO

| CACHE_INFO (bytes/ways) | pinned CPUs | unpinned processes |
| --- | --- | ---: |
| 24576/12 / 524288/16 / 33554432/16 | 0-3 | 3 |

### Processes

| arm | threads | process / CPUs | rc | decisions | gate | bit mismatches | max abs vs reference | load s | wall s | peak |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 1.54 | 624.2 | rss 2,213.2 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 1.54 | 354.1 | rss 2,277.6 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 1.57 | 348.7 | rss 2,278.4 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 1.49 | 335.0 | rss 2,278.4 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 1.53 | 349.4 | rss 2,277.7 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 1.48 | 599.6 | rss 2,213.0 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 1.48 | 104.8 | rss 1,183.7 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 1.46 | 61.2 | rss 1,186.4 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 1.56 | 108.8 | rss 1,196.2 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 1.47 | 76.1 | rss 1,205.0 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 4.230367236, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 4.66375848, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1.34 | 8.59 | 41.85 | 149.08 |
| 2 | 0.79 | 5.15 | 24.43 | 84.70 |
| 4 | 0.86 | 4.70 | 23.21 | 80.88 |
