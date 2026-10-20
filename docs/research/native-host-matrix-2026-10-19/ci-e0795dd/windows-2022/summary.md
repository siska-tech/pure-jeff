## Native host matrix: Windows AMD64

- commit `10a0a1ab4874c1b6da084ae521ef8da3e8883695`, rustc 1.99.0 (b940084d7 2026-09-28)
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
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 2.07 | 591.2 | working_set 2,085.2 MiB / private 1,187.3 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 2.00 | 366.1 | working_set 2,141.6 MiB / private 1,192.3 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 1.98 | 338.2 | working_set 2,147.6 MiB / private 1,199.7 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 1.94 | 337.8 | working_set 2,148.1 MiB / private 1,200.8 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 1.96 | 365.0 | working_set 2,135.9 MiB / private 1,190.9 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 1.98 | 593.6 | working_set 2,085.6 MiB / private 1,186.5 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 1.84 | 121.1 | working_set 1,111.3 MiB / private 202.9 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 1.89 | 73.4 | working_set 1,116.1 MiB / private 202.9 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 1.93 | 122.4 | working_set 1,111.9 MiB / private 203.0 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 1.92 | 78.4 | working_set 1,115.3 MiB / private 202.9 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 3.6210142, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 3.9572709, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1.51 | 9.62 | 39.54 | 125.21 |
| 2 | 0.97 | 5.64 | 23.54 | 77.55 |
| 4 | 0.94 | 5.42 | 21.75 | 68.75 |
