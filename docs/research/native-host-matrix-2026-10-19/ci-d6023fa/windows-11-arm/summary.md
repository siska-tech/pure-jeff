## Native host matrix: Windows ARM64

- commit `190fec6f7febed41f9d9e793c6474699ed68bee5`, rustc 1.99.0 (b940084d7 2026-09-28)
- CPU: {"Name":"Cobalt 100","NumberOfCores":4,"NumberOfLogicalProcessors":4,"MaxClockSpeed":3399,"L2CacheSize":4096,"L3CacheSize":0}; logical CPUs 4
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
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 5.30 | 1318.9 | working_set 2,073.4 MiB / private 1,180.7 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 5.31 | 739.0 | working_set 2,083.8 MiB / private 1,181.5 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 5.34 | 458.1 | working_set 2,090.3 MiB / private 1,183.4 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 5.33 | 455.3 | working_set 2,090.3 MiB / private 1,182.7 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 5.33 | 742.3 | working_set 2,083.5 MiB / private 1,181.6 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 5.39 | 1320.0 | working_set 2,082.4 MiB / private 1,180.7 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.41 | 272.6 | working_set 1,084.7 MiB / private 215.7 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.32 | 101.0 | working_set 1,112.8 MiB / private 214.8 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.30 | 272.4 | working_set 1,084.5 MiB / private 214.8 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.27 | 160.3 | working_set 1,107.6 MiB / private 214.7 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 8.504918, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 5.515661, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 3.20 | 21.45 | 88.73 | 279.82 |
| 2 | 1.86 | 12.01 | 49.07 | 154.95 |
| 4 | 1.17 | 7.40 | 29.57 | 92.42 |
