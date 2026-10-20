## Native host matrix: Windows AMD64

- commit `95e122dc7e98fe6a513fef4c8b743d58fe126368` (dirty), rustc 1.99.0 (b940084d7 2026-09-28)
- CPU: {"Name":"13th Gen Intel(R) Core(TM) i7-1360P","NumberOfCores":12,"NumberOfLogicalProcessors":16,"MaxClockSpeed":2200,"L2CacheSize":9216,"L3CacheSize":18432}; logical CPUs 16
- **passed: False** — {"bit_mismatches": [["pinned", "cache-group-1", 1, 0, "pinned/policy-top1-above"], ["pinned", "cache-group-1", 1, 0, "pinned/policy-top1-below"], ["pinned", "cache-group-1", 1, 0, "pinned/special-token-text"], ["pinned", "cache-group-1", 1, 0, "pinned/policy-near-tie"], ["pinned", "cache-group-1", 1, 0, "pinned/policy-margin-near"], ["pinned", "cache-group-1", 1, 0, "pinned/asr-unicode"], ["pinned", "cache-group-1", 1, 0, "pinned/synthetic-ocr-ja-2-127"], ["pinned", "cache-group-1", 1, 0, "pinned/candidate-request"], ["pinned", "cache-group-1", 1, 0, "pinned/synthetic-asr-mixed-2-128"], ["pinned", "cache-group-1", 1, 0, "pinned/synthetic-asr-unicode-2-128"], ["pinned", "cache-group-1", 1, 0, "pinned/synthetic-ocr-ascii-3-128"], ["pinned", "cache-group-1", 1, 0, "pinned/synthetic-ocr-ja-2-128"], ["pinned", "cache-group-1", 1, 0, "pinned/synthetic-ocr-ja-2-129"], ["pinned", "cache-group-1", 1, 0, "pinned/synthetic-asr-mixed-2-256"], ["pinned", "cache-group-1", 1, 0, "pinned/synthetic-asr-unicode-2-256"], ["pinned", "cache-group-1", 1, 0, "pinned/synthetic-ocr-ascii-3-256"], ["pinned", "cache-group-1", 1, 0, "pinned/synthetic-ocr-ascii-8-256"], ["pinned", "cache-group-1", 1, 0, "pinned/synthetic-ocr-ja-2-256"], ["pinned", "cache-group-1", 1, 0, "pinned/synthetic-asr-mixed-2-384"], ["pinned", "cache-group-1", 1, 0, "pinned/synthetic-asr-unicode-2-384"], ["pinned", "cache-group-1", 1, 0, "pinned/synthetic-ocr-ascii-3-384"], ["pinned", "cache-group-1", 1, 0, "pinned/synthetic-ocr-a
- max abs difference from the official reference: 4.74e-06
- old 28-case Native gate (28 cases): max abs difference 0.0 (a different build and dependencies; descriptive)

### gemm CACHE_INFO

| CACHE_INFO (bytes/ways) | pinned CPUs | unpinned processes |
| --- | --- | ---: |
| 49152/12 / 1310720/10 / 18874368/12 | 0-7 | 3 |
| 32768/8 / 2097152/16 / 18874368/12 | 8-15 | 0 |

### Processes

| arm | threads | process / CPUs | rc | decisions | gate | bit mismatches | load s | wall s | peak |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| matrix | 1 | p0 | 0 | 78 | 0 | 0 | 1.96 | 693.1 | working_set 2,140.7 MiB / private 1,189.4 MiB |
| matrix | 2 | p0 | 0 | 78 | 0 | 0 | 1.98 | 469.9 | working_set 2,148.1 MiB / private 1,198.1 MiB |
| matrix | 4 | p0 | 0 | 78 | 0 | 0 | 1.92 | 389.2 | working_set 2,142.7 MiB / private 1,193.6 MiB |
| matrix | 8 | p0 | 0 | 78 | 0 | 0 | 1.95 | 406.1 | working_set 2,146.6 MiB / private 1,201.0 MiB |
| matrix | 16 | p0 | 0 | 78 | 0 | 0 | 1.98 | 373.7 | working_set 2,156.5 MiB / private 1,217.3 MiB |
| matrix | 16 | p1 | 0 | 78 | 0 | 0 | 1.91 | 374.6 | working_set 2,151.3 MiB / private 1,211.6 MiB |
| matrix | 8 | p1 | 0 | 78 | 0 | 0 | 1.91 | 406.5 | working_set 2,147.1 MiB / private 1,201.2 MiB |
| matrix | 4 | p1 | 0 | 78 | 0 | 0 | 1.97 | 393.4 | working_set 2,144.4 MiB / private 1,195.7 MiB |
| matrix | 2 | p1 | 0 | 78 | 0 | 0 | 1.98 | 465.4 | working_set 2,147.6 MiB / private 1,197.5 MiB |
| matrix | 1 | p1 | 0 | 78 | 0 | 0 | 1.94 | 702.1 | working_set 2,137.2 MiB / private 1,185.7 MiB |
| pinned | 1 | cache-group-0 | 0 | 35 | 0 | 0 | 2.01 | 140.5 | working_set 1,112.0 MiB / private 202.2 MiB |
| pinned | 4 | cache-group-0 | 0 | 35 | 0 | 0 | 2.01 | 84.4 | working_set 1,116.4 MiB / private 202.3 MiB |
| pinned | 16 | cache-group-0 | 0 | 35 | 0 | 0 | 1.93 | 113.3 | working_set 1,123.7 MiB / private 202.4 MiB |
| pinned | 1 | cache-group-1 | 0 | 35 | 0 | 33 | 3.02 | 376.2 | working_set 1,116.6 MiB / private 202.1 MiB |
| pinned | 4 | cache-group-1 | 0 | 35 | 0 | 33 | 3.01 | 142.2 | working_set 1,116.0 MiB / private 202.5 MiB |
| pinned | 16 | cache-group-1 | 0 | 35 | 0 | 33 | 2.99 | 121.8 | working_set 1,119.8 MiB / private 202.5 MiB |
| pinned | 1 | without-cpu0 | 0 | 35 | 0 | 0 | 1.90 | 139.6 | working_set 1,116.8 MiB / private 202.2 MiB |
| pinned | 4 | without-cpu0 | 0 | 35 | 0 | 0 | 1.94 | 92.9 | working_set 1,116.7 MiB / private 202.5 MiB |
| pinned | 16 | without-cpu0 | 0 | 35 | 0 | 0 | 1.97 | 98.8 | working_set 1,123.8 MiB / private 202.5 MiB |

### timeout_reuse

- t1: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 4.3587551, "timeout": true}
- t4: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 4.4468514, "timeout": true}
- t16: rc=0 {"deadline_s": 3.0, "reuse_bitwise_equal": true, "stopped_after_s": 3.649749, "timeout": true}

### Median decision wall time (s, descriptive)

| threads | 128 tokens | 874 tokens | 3206 tokens | 8192 tokens |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1.77 | 10.90 | 46.32 | 150.16 |
| 2 | 1.25 | 7.39 | 30.55 | 97.07 |
| 4 | 1.25 | 6.24 | 24.30 | 79.53 |
| 8 | 1.34 | 6.73 | 24.34 | 76.87 |
| 16 | 1.43 | 6.06 | 22.14 | 69.30 |
