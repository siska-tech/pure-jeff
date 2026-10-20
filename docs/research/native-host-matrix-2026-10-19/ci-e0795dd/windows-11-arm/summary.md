## Native host matrix: Windows ARM64

- commit `10a0a1ab4874c1b6da084ae521ef8da3e8883695`, rustc 1.99.0 (b940084d7 2026-09-28)
- CPU: {"Name":"Cobalt 100","NumberOfCores":4,"NumberOfLogicalProcessors":4,"MaxClockSpeed":3399,"L2CacheSize":4096,"L3CacheSize":131072}; logical CPUs 4
- **passed: True**
- max abs difference from the official reference: 3.78e-06
- old 28-case Native gate (28 cases): max abs difference 3.7848949432373047e-06 (a different build and dependencies; descriptive)

### gemm CACHE_INFO

| CACHE_INFO (bytes/ways) | pinned CPUs | unpinned processes |
| --- | --- | ---: |
| 16384/8 / 524288/8 / 1048576/8 | 0-3 | 3 |

### Processes

| arm | threads | process / CPUs | rc | decisions | gate | bit mismatches | max abs vs reference | load s | wall s | peak |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 5.39 | 1322.4 | working_set 2,077.2 MiB / private 1,180.6 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 5.36 | 738.7 | working_set 2,084.0 MiB / private 1,181.6 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 5.30 | 447.9 | working_set 2,089.5 MiB / private 1,182.6 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 5.33 | 447.2 | working_set 2,091.0 MiB / private 1,183.0 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 5.32 | 736.6 | working_set 2,083.4 MiB / private 1,181.5 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 5.32 | 1316.5 | working_set 2,082.2 MiB / private 1,180.6 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.28 | 270.7 | working_set 1,084.8 MiB / private 214.8 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.33 | 100.7 | working_set 1,110.6 MiB / private 214.9 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.37 | 276.0 | working_set 1,084.2 MiB / private 214.8 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.32 | 160.8 | working_set 1,106.8 MiB / private 214.9 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 8.6322293, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 5.6881005, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 3.20 | 21.40 | 88.71 | 280.09 |
| 2 | 1.85 | 11.96 | 48.92 | 154.24 |
| 4 | 1.14 | 7.30 | 29.18 | 91.04 |
