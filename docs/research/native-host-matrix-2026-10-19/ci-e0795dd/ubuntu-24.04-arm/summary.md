## Native host matrix: Linux aarch64

- commit `10a0a1ab4874c1b6da084ae521ef8da3e8883695`, rustc 1.99.0 (b940084d7 2026-09-28)
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
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 5.34 | 1350.8 | rss 2,235.1 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 5.27 | 729.4 | rss 2,300.3 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 5.24 | 434.0 | rss 2,301.3 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 5.23 | 438.7 | rss 2,301.2 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 5.23 | 731.2 | rss 2,300.2 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 5.24 | 1347.8 | rss 2,234.9 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.25 | 266.7 | rss 1,186.0 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.28 | 92.6 | rss 1,201.8 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.33 | 271.9 | rss 1,186.0 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.32 | 134.6 | rss 1,201.7 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 9.382591226, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 5.804040559, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 3.17 | 21.03 | 91.25 | 299.05 |
| 2 | 1.75 | 11.29 | 49.15 | 161.56 |
| 4 | 1.18 | 6.56 | 28.70 | 95.09 |
