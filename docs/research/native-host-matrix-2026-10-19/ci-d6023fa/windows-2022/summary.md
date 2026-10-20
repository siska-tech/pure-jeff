## Native host matrix: Windows AMD64

- commit `190fec6f7febed41f9d9e793c6474699ed68bee5`, rustc 1.99.0 (b940084d7 2026-09-28)
- CPU: {"Name":"AMD EPYC 7763 64-Core Processor                ","NumberOfCores":2,"NumberOfLogicalProcessors":4,"MaxClockSpeed":2445,"L2CacheSize":null,"L3CacheSize":0}; logical CPUs 4
- **passed: True**
- max abs difference from the official reference: 3.52e-06
- old 28-case Native gate (28 cases): max abs difference 3.546476364135742e-06 (a different build and dependencies; descriptive)

### gemm CACHE_INFO

| CACHE_INFO (bytes/ways) | pinned CPUs | unpinned processes |
| --- | --- | ---: |
| 32768/8 / 524288/8 / 0/0 | 0-3 | 3 |

### Processes

| arm | threads | process / CPUs | rc | decisions | gate | bit mismatches | max abs vs reference | load s | wall s | peak |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 2.57 | 853.7 | working_set 2,085.6 MiB / private 1,191.7 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 2.61 | 535.9 | working_set 2,084.7 MiB / private 1,189.0 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 2.58 | 496.1 | working_set 2,095.9 MiB / private 1,197.5 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 2.51 | 492.7 | working_set 2,095.7 MiB / private 1,197.4 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 2.50 | 534.0 | working_set 2,095.4 MiB / private 1,197.4 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 2.53 | 854.6 | working_set 2,087.2 MiB / private 1,195.6 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 2.68 | 178.0 | working_set 1,111.0 MiB / private 202.3 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 2.59 | 113.1 | working_set 1,114.6 MiB / private 202.4 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 2.64 | 176.5 | working_set 1,106.3 MiB / private 202.3 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 2.57 | 119.9 | working_set 1,115.0 MiB / private 202.3 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 5.4974606, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 5.7707882999999995, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 2.33 | 13.68 | 56.52 | 181.70 |
| 2 | 1.59 | 8.16 | 34.49 | 112.91 |
| 4 | 1.54 | 7.85 | 30.60 | 98.50 |
