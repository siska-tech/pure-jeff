## Native host matrix: Windows AMD64

- commit `5b729b92be67039821905aec482b590aaccd3b6f`, rustc 1.99.0 (b940084d7 2026-09-28)
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
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 0 | 2.94 | 936.4 | working_set 2,076.9 MiB / private 1,187.5 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 0 | 2.78 | 579.3 | working_set 2,088.4 MiB / private 1,190.1 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 0 | 2.84 | 526.2 | working_set 2,092.0 MiB / private 1,194.4 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 0 | 2.84 | 526.3 | working_set 2,089.1 MiB / private 1,192.3 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 0 | 2.80 | 578.7 | working_set 2,095.3 MiB / private 1,197.2 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 0 | 2.91 | 929.4 | working_set 2,080.2 MiB / private 1,186.2 MiB |
| pinned | 1 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 2.83 | 193.1 | working_set 1,111.0 MiB / private 202.3 MiB |
| pinned | 4 | cache-group-0 (0-3) | 0 | 35 | 0 | 0 | 0 | 2.96 | 118.4 | working_set 1,114.9 MiB / private 202.6 MiB |
| pinned | 1 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 2.77 | 191.3 | working_set 1,111.0 MiB / private 202.3 MiB |
| pinned | 4 | without-cpu0 (1-3) | 0 | 35 | 0 | 0 | 0 | 2.78 | 127.0 | working_set 1,115.0 MiB / private 202.3 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 5.8343673, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 3.0776684, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 2.50 | 15.07 | 61.53 | 199.06 |
| 2 | 1.61 | 8.89 | 36.65 | 122.60 |
| 4 | 1.60 | 8.42 | 32.92 | 105.48 |
