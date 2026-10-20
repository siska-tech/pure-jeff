## Native host matrix: Linux aarch64

- commit `190fec6f7febed41f9d9e793c6474699ed68bee5`, rustc 1.99.0 (b940084d7 2026-09-28)
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
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 5.25 | 1357.4 | rss 2,235.1 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 5.21 | 757.3 | rss 2,300.2 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 5.19 | 447.8 | rss 2,301.2 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 5.20 | 458.9 | rss 2,301.2 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 5.21 | 745.2 | rss 2,300.1 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 5.20 | 1354.3 | rss 2,235.1 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.27 | 267.8 | rss 1,186.0 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.22 | 91.9 | rss 1,188.3 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.36 | 261.5 | rss 1,186.0 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.32 | 132.8 | rss 1,201.4 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 9.176505229, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 3.071234009, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 3.14 | 20.86 | 92.99 | 303.35 |
| 2 | 1.76 | 11.44 | 51.55 | 168.43 |
| 4 | 1.20 | 6.68 | 30.08 | 100.82 |
