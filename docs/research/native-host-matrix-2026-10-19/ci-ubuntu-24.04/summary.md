## Native host matrix: Linux x86_64

- commit `5b729b92be67039821905aec482b590aaccd3b6f`, rustc 1.99.0 (b940084d7 2026-09-28)
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
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 1.94 | 793.0 | rss 2,212.3 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 1.98 | 439.4 | rss 2,277.2 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 1.91 | 419.5 | rss 2,290.0 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 1.98 | 421.0 | rss 2,294.4 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 1.98 | 452.0 | rss 2,276.9 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 1.99 | 787.9 | rss 2,212.0 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 1.91 | 155.8 | rss 1,179.1 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 1.90 | 88.0 | rss 1,189.4 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 1.89 | 156.3 | rss 1,195.1 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 2.01 | 101.7 | rss 1,195.4 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 4.916003626, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 5.1617973, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1.96 | 12.53 | 52.23 | 171.16 |
| 2 | 1.22 | 7.07 | 29.04 | 95.27 |
| 4 | 1.19 | 6.67 | 27.24 | 88.49 |
