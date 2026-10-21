## Native host matrix: Linux aarch64

- commit `f5175979e9066e1ee38fd2eabcd03d7f447c4e32`, rustc 1.99.0 (b940084d7 2026-09-28)
- CPU: CPU implementer 0x41, CPU variant 0x0, CPU part 0xd49; logical CPUs 4
- **passed: True**
- max abs difference from the official reference: 3.31e-06
- old 28-case Native gate (28 cases): max abs difference 3.4570693969726562e-06 (a different build and dependencies; descriptive)

### gemm CACHE_INFO

| CACHE_INFO (bytes/ways) | pinned CPUs | unpinned processes |
| --- | --- | ---: |
| 65536/4 / 1048576/8 / 134217728/16 | 0-3 | 3 |

### Processes

| arm | threads | process / CPUs | rc | decisions | gate | bit mismatches | max abs vs reference | load s | wall s | peak |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 5.20 | 1312.9 | rss 2,206.9 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 5.17 | 720.4 | rss 2,271.6 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 5.14 | 432.8 | rss 2,272.1 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 5.21 | 429.4 | rss 2,272.2 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 5.17 | 714.6 | rss 2,271.5 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 5.15 | 1314.4 | rss 2,211.0 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.18 | 259.5 | rss 1,177.7 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.21 | 90.5 | rss 1,199.2 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.19 | 259.9 | rss 1,177.8 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.20 | 138.3 | rss 1,183.7 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 8.842913464, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 5.596157487, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 3.10 | 20.49 | 88.70 | 290.59 |
| 2 | 1.72 | 11.08 | 48.68 | 158.32 |
| 4 | 1.20 | 6.49 | 28.34 | 93.18 |
