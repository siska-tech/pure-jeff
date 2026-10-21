## Native host matrix: Windows ARM64

- commit `f5175979e9066e1ee38fd2eabcd03d7f447c4e32`, rustc 1.99.0 (b940084d7 2026-09-28)
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
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 5.28 | 1324.8 | working_set 2,074.4 MiB / private 1,180.7 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 5.43 | 750.8 | working_set 2,084.4 MiB / private 1,182.0 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 5.37 | 468.1 | working_set 2,090.5 MiB / private 1,186.4 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 5.39 | 461.5 | working_set 2,135.1 MiB / private 1,183.5 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 5.32 | 747.4 | working_set 2,093.2 MiB / private 1,181.9 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 5.29 | 1330.5 | working_set 2,068.3 MiB / private 1,180.7 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.34 | 273.2 | working_set 1,086.6 MiB / private 214.7 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.34 | 102.4 | working_set 1,111.2 MiB / private 214.8 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.33 | 273.4 | working_set 1,086.8 MiB / private 214.7 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.34 | 161.1 | working_set 1,108.0 MiB / private 214.7 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 8.5840119, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 5.6137129, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 3.20 | 21.57 | 89.58 | 282.99 |
| 2 | 1.86 | 12.17 | 49.89 | 157.91 |
| 4 | 1.19 | 7.56 | 30.12 | 95.16 |
