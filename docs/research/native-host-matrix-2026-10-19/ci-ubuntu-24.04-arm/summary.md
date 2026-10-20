## Native host matrix: Linux aarch64

- commit `5b729b92be67039821905aec482b590aaccd3b6f`, rustc 1.99.0 (b940084d7 2026-09-28)
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
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 5.19 | 1360.2 | rss 2,235.1 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 5.14 | 718.3 | rss 2,300.1 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 5.16 | 434.0 | rss 2,301.2 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 5.14 | 434.1 | rss 2,301.2 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 5.17 | 733.5 | rss 2,300.1 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 5.21 | 1343.2 | rss 2,235.1 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.16 | 263.9 | rss 1,185.9 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.17 | 90.3 | rss 1,193.0 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.18 | 266.4 | rss 1,185.9 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.21 | 131.8 | rss 1,185.6 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 8.852847718, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 5.688921961, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 3.20 | 21.11 | 90.89 | 296.05 |
| 2 | 1.75 | 11.19 | 48.93 | 160.21 |
| 4 | 1.17 | 6.54 | 28.61 | 94.08 |
