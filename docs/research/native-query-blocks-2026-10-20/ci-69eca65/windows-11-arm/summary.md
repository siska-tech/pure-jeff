## Native host matrix: Windows ARM64

- commit `69eca65be265d42b3f2f0f5b9720bb5ca5c77063`, rustc 1.99.0 (b940084d7 2026-09-28)
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
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 5.36 | 1333.8 | working_set 2,077.1 MiB / private 1,180.7 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 5.37 | 752.1 | working_set 2,084.1 MiB / private 1,182.1 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 5.35 | 468.9 | working_set 2,090.2 MiB / private 1,183.3 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 5.35 | 462.3 | working_set 2,134.9 MiB / private 1,183.4 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 5.31 | 751.6 | working_set 2,083.8 MiB / private 1,182.0 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 5.32 | 1334.5 | working_set 2,077.2 MiB / private 1,180.6 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.35 | 273.7 | working_set 1,086.2 MiB / private 214.8 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 5.45 | 104.0 | working_set 1,111.9 MiB / private 214.7 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.34 | 273.3 | working_set 1,101.0 MiB / private 214.8 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 5.37 | 161.7 | working_set 1,109.1 MiB / private 214.8 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 8.6535674, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 5.7384343, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 3.22 | 21.62 | 90.12 | 285.22 |
| 2 | 1.87 | 12.13 | 50.18 | 158.93 |
| 4 | 1.16 | 7.49 | 30.24 | 95.70 |
