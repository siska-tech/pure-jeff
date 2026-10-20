## Native host matrix: Linux x86_64

- commit `69eca65be265d42b3f2f0f5b9720bb5ca5c77063`, rustc 1.99.0 (b940084d7 2026-09-28)
- CPU: Intel(R) Xeon(R) 6973P-C; logical CPUs 4
- **passed: True**
- max abs difference from the official reference: 3.99e-06
- old 28-case Native gate (28 cases): max abs difference 3.7848949432373047e-06 (a different build and dependencies; descriptive)

### gemm CACHE_INFO

| CACHE_INFO (bytes/ways) | pinned CPUs | unpinned processes |
| --- | --- | ---: |
| 24576/12 / 1048576/16 / 503316480/16 | 0-3 | 3 |

### Processes

| arm | threads | process / CPUs | rc | decisions | gate | bit mismatches | max abs vs reference | load s | wall s | peak |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 1.80 | 713.9 | rss 2,372.8 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 1.86 | 418.5 | rss 2,437.2 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 1.83 | 396.5 | rss 2,438.4 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 2.04 | 415.3 | rss 2,438.3 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 1.87 | 428.2 | rss 2,437.4 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 1.88 | 749.0 | rss 2,372.7 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 1.84 | 150.8 | rss 1,266.1 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 1.88 | 85.3 | rss 1,279.5 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 1.85 | 149.4 | rss 1,266.1 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 1.82 | 97.3 | rss 1,283.4 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 4.941909445, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 4.921524437, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1.85 | 11.61 | 48.98 | 159.40 |
| 2 | 1.15 | 6.66 | 27.82 | 90.95 |
| 4 | 1.16 | 6.34 | 26.54 | 84.91 |
