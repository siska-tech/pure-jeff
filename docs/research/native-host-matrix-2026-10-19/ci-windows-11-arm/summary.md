## Native host matrix: Windows ARM64

- commit `5b729b92be67039821905aec482b590aaccd3b6f`, rustc 1.99.0 (b940084d7 2026-09-28)
- CPU: {"Name":"Cobalt 100","NumberOfCores":4,"NumberOfLogicalProcessors":4,"MaxClockSpeed":3400,"L2CacheSize":4096,"L3CacheSize":0}; logical CPUs 4
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
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 5.28 | 1314.4 | working_set 2,082.4 MiB / private 1,180.7 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 5.24 | 736.0 | working_set 2,083.4 MiB / private 1,181.5 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 5.30 | 452.8 | working_set 2,133.1 MiB / private 1,182.6 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 5.29 | 449.6 | working_set 2,090.0 MiB / private 1,182.9 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 5.27 | 739.3 | working_set 2,087.9 MiB / private 1,181.5 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 5.28 | 1315.4 | working_set 2,082.2 MiB / private 1,180.8 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.26 | 270.5 | working_set 1,085.8 MiB / private 214.9 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.27 | 98.9 | working_set 1,113.3 MiB / private 214.8 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.26 | 270.6 | working_set 1,085.7 MiB / private 215.8 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.27 | 158.7 | working_set 1,107.5 MiB / private 214.8 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 8.5187163, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 5.5245046, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 3.17 | 21.41 | 88.89 | 279.80 |
| 2 | 1.84 | 12.01 | 49.34 | 154.88 |
| 4 | 1.15 | 7.34 | 29.46 | 92.64 |
