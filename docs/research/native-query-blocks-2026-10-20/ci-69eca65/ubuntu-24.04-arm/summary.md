## Native host matrix: Linux aarch64

- commit `69eca65be265d42b3f2f0f5b9720bb5ca5c77063`, rustc 1.99.0 (b940084d7 2026-09-28)
- CPU: CPU implementer 0x41, CPU variant 0x0, CPU part 0xd49; logical CPUs 4
- **passed: True**
- max abs difference from the official reference: 5.3e-06
- old 28-case Native gate (28 cases): max abs difference 2.205371856689453e-06 (a different build and dependencies; descriptive)

### gemm CACHE_INFO

| CACHE_INFO (bytes/ways) | pinned CPUs | unpinned processes |
| --- | --- | ---: |
| 65536/4 / 1048576/8 / 134217728/16 | 0-3 | 3 |

### Processes

| arm | threads | process / CPUs | rc | decisions | gate | bit mismatches | max abs vs reference | load s | wall s | peak |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 5.19 | 1321.6 | rss 2,395.6 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 5.14 | 726.2 | rss 2,460.7 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 5.17 | 435.3 | rss 2,461.8 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 5.14 | 436.1 | rss 2,461.8 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 5.26 | 728.0 | rss 2,460.7 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 5.17 | 1333.1 | rss 2,395.5 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.24 | 265.4 | rss 1,281.5 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.16 | 90.2 | rss 1,271.2 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.25 | 261.8 | rss 1,268.9 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.20 | 131.8 | rss 1,288.8 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 8.871202456, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 5.666373357, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 3.15 | 20.77 | 90.38 | 292.80 |
| 2 | 1.75 | 11.29 | 49.41 | 160.02 |
| 4 | 1.16 | 6.53 | 28.76 | 94.86 |
