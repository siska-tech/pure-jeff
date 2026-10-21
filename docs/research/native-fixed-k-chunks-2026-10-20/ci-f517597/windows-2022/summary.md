## Native host matrix: Windows AMD64

- commit `f5175979e9066e1ee38fd2eabcd03d7f447c4e32`, rustc 1.99.0 (b940084d7 2026-09-28)
- CPU: {"Name":"AMD EPYC 9V74 80-Core Processor                ","NumberOfCores":2,"NumberOfLogicalProcessors":4,"MaxClockSpeed":2596,"L2CacheSize":null,"L3CacheSize":0}; logical CPUs 4
- **passed: True**
- max abs difference from the official reference: 3.52e-06
- old 28-case Native gate (28 cases): max abs difference 3.546476364135742e-06 (a different build and dependencies; descriptive)

### gemm CACHE_INFO

| CACHE_INFO (bytes/ways) | pinned CPUs | unpinned processes |
| --- | --- | ---: |
| 32768/8 / 1048576/8 / 0/0 | 0-3 | 3 |

### Processes

| arm | threads | process / CPUs | rc | decisions | gate | bit mismatches | max abs vs reference | load s | wall s | peak |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 2.22 | 723.1 | working_set 2,089.0 MiB / private 1,189.7 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 2.20 | 444.6 | working_set 2,145.7 MiB / private 1,197.9 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 2.19 | 407.0 | working_set 2,142.4 MiB / private 1,195.9 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 2.20 | 406.4 | working_set 2,147.3 MiB / private 1,201.3 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 2.24 | 447.4 | working_set 2,145.9 MiB / private 1,198.6 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 2.19 | 719.9 | working_set 2,086.1 MiB / private 1,190.0 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 2.21 | 148.5 | working_set 1,107.0 MiB / private 202.6 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 2.19 | 91.2 | working_set 1,114.3 MiB / private 202.6 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 2.20 | 148.6 | working_set 1,106.6 MiB / private 202.5 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 2.20 | 98.6 | working_set 1,115.0 MiB / private 202.8 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 4.543689, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 4.788575, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1.93 | 11.65 | 47.87 | 153.33 |
| 2 | 1.26 | 6.90 | 28.53 | 94.19 |
| 4 | 1.23 | 6.49 | 25.60 | 81.50 |
