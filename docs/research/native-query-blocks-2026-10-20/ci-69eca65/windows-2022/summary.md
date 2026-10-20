## Native host matrix: Windows AMD64

- commit `69eca65be265d42b3f2f0f5b9720bb5ca5c77063`, rustc 1.99.0 (b940084d7 2026-09-28)
- CPU: {"Name":"AMD EPYC 9V45 96-Core Processor                ","NumberOfCores":2,"NumberOfLogicalProcessors":4,"MaxClockSpeed":2596,"L2CacheSize":null,"L3CacheSize":0}; logical CPUs 4
- **passed: True**
- max abs difference from the official reference: 4.74e-06
- old 28-case Native gate (28 cases): max abs difference 0.0 (a different build and dependencies; descriptive)

### gemm CACHE_INFO

| CACHE_INFO (bytes/ways) | pinned CPUs | unpinned processes |
| --- | --- | ---: |
| 49152/12 / 1048576/16 / 0/0 | 0-3 | 3 |

### Processes

| arm | threads | process / CPUs | rc | decisions | gate | bit mismatches | max abs vs reference | load s | wall s | peak |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 1.92 | 593.3 | working_set 2,086.1 MiB / private 1,186.2 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 1.92 | 376.1 | working_set 2,139.9 MiB / private 1,191.3 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 1.93 | 337.7 | working_set 2,148.1 MiB / private 1,201.3 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 1.92 | 339.4 | working_set 2,148.0 MiB / private 1,200.8 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 1.92 | 370.0 | working_set 2,146.7 MiB / private 1,198.6 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 1.94 | 600.4 | working_set 2,085.6 MiB / private 1,186.2 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 2.02 | 121.7 | working_set 1,111.3 MiB / private 202.7 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 1.85 | 72.2 | working_set 1,115.3 MiB / private 202.7 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 2.04 | 121.9 | working_set 1,110.8 MiB / private 202.5 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 1.92 | 80.1 | working_set 1,116.0 MiB / private 202.4 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 3.6465492, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 4.0130416, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1.51 | 9.76 | 39.97 | 126.75 |
| 2 | 0.99 | 5.78 | 24.00 | 79.99 |
| 4 | 0.92 | 5.45 | 21.56 | 69.49 |
