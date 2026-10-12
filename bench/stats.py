"""Fixed statistics of the benchmark (registered before measuring; no third-party imports).

Unit of replication: the block. In each block every arm runs one fresh resident session over
the same job in the same order, so observations within a session are not independent of each
other but blocks are. For each block and input group the statistic is
    r = geometric mean over the group's cases of (median Native wall / median Jeff wall),
and the equivalence verdict uses the one-sided 95% t bound on mean(log r) across blocks."""
import math
import statistics

# One-sided 95% quantiles of Student's t, df 1..30.
T95 = [6.314, 2.920, 2.353, 2.132, 2.015, 1.943, 1.895, 1.860, 1.833, 1.812, 1.796, 1.782, 1.771, 1.761, 1.753,
       1.746, 1.740, 1.734, 1.729, 1.725, 1.721, 1.717, 1.714, 1.711, 1.708, 1.706, 1.703, 1.701, 1.699, 1.697]
MIN_BLOCKS = 5
POINT_MAX = 1.00
UPPER_MAX = 1.05
REGRESSION = 1.05
RULES = {
    "unit": "block (one fresh session per arm over the same job and order); observations within a session are "
            "summarised by their median first",
    "statistic": "per block and input group: geometric mean over the group's cases of median Native wall / median "
                 "Jeff wall (API boundary, warm, warm-up excluded)",
    "interval": "one-sided 95% Student t bound of mean(log ratio) across blocks, back-transformed",
    "equivalent": f"point estimate <= {POINT_MAX:.2f} and upper bound <= {UPPER_MAX:.2f}, with at least {MIN_BLOCKS} blocks",
    "slower": f"lower bound > {POINT_MAX:.2f} (Native slower with 95% confidence)",
    "insufficient": "anything else; never pooled across groups, so a short-input regression is not offset by "
                    "long inputs",
    "regression": f"one-shot median wall or peak working set of the default path above {REGRESSION:.2f} x the "
                  "baseline for any case (descriptive, no interval)",
}


def t95(df):
    if df < 1:
        raise ValueError("at least two blocks are needed")
    return T95[min(df, len(T95)) - 1]


def geomean(values):
    values = list(values)
    return math.exp(math.fsum(math.log(v) for v in values) / len(values))


def describe(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return {"n": 0}
    return {"n": len(values), "median": statistics.median(values), "min": values[0], "max": values[-1],
            "mean": statistics.fmean(values)}


def equivalence(ratios):
    """Verdict over per-block ratios (Native / Jeff) of one input group."""
    ratios = [r for r in ratios if r is not None]
    if len(ratios) < 2:
        return {"blocks": len(ratios), "verdict": "insufficient", "reason": "fewer than two blocks"}
    logs = [math.log(r) for r in ratios]
    mean = statistics.fmean(logs)
    half = t95(len(logs) - 1) * statistics.stdev(logs) / math.sqrt(len(logs))
    point, lower, upper = math.exp(mean), math.exp(mean - half), math.exp(mean + half)
    if len(ratios) < MIN_BLOCKS:
        verdict = "insufficient"
    elif point <= POINT_MAX and upper <= UPPER_MAX:
        verdict = "equivalent"
    elif lower > POINT_MAX:
        verdict = "slower"
    else:
        verdict = "insufficient"
    return {"blocks": len(ratios), "ratios": ratios, "point": point, "lower95": lower, "upper95": upper,
            "verdict": verdict}


def regression(baseline, candidate):
    """Ratio candidate / baseline and whether it exceeds the registered 5% threshold."""
    if not baseline or candidate is None:
        return {"ratio": None, "regressed": None}
    ratio = candidate / baseline
    return {"ratio": ratio, "regressed": ratio > REGRESSION}
