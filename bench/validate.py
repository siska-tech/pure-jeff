"""The common numeric gate, applied to every evaluated input of every arm.

An outcome passes only when it has the expected status for that arm (completed, or the expected
typed failure such as budget_exceeded), and when completed: the input ID (catalog case),
candidate IDs in request order, input token count (and input-ID digest when the arm reports it)
equal the catalog; every probability is a finite float in [0, 1]; their sum is within 1e-6 of 1;
the largest absolute difference from the official reference is at most 1e-4; and the judgment
(selected candidate or abstained) equals the reference. Anything malformed is a violation, never
skipped. No third-party imports."""
import math

PROBABILITY_MAX_ABS = 1e-4
PROBABILITY_SUM = 1e-6
GATE = {
    "input": "case ID, candidate IDs and order, input token count (and input-ID digest when reported) equal the catalog",
    "probability_max_abs_vs_official": PROBABILITY_MAX_ABS,
    "probability_sum_abs_error": PROBABILITY_SUM,
    "finite": "every probability is a finite float in [0, 1]",
    "judgment": "selected candidate or abstention equals the official reference",
    "status": "completed, or the catalog's expected failure for the arm (e.g. budget_exceeded over the limit)",
    "repeat": "within one arm and mode, every completed decision of a case has bitwise identical probabilities",
}


def _number(value):
    return isinstance(value, float) or (isinstance(value, int) and not isinstance(value, bool))


def check(case, arm, outcome):
    """Violations (strings) of one outcome of `arm` for catalog `case`; empty means it passed."""
    if not isinstance(outcome, dict) or outcome.get("status") not in ("completed", "failed"):
        return ["malformed outcome"]
    expected = case["expect"][arm]
    if outcome["status"] == "failed":
        if expected == "completed":
            return [f"failed with {outcome.get('failure')!r}, expected completed"]
        return [] if outcome.get("failure") == expected else [f"failure {outcome.get('failure')!r}, expected {expected!r}"]
    if expected != "completed":
        return [f"completed, expected {expected!r}"]
    violations = []
    reference = case["reference"]
    if outcome.get("candidate_ids") != case["candidate_ids"]:
        violations.append("candidate IDs or order differ")
    if outcome.get("input_tokens") != case["tokens"]:
        violations.append(f"input tokens {outcome.get('input_tokens')!r} != {case['tokens']}")
    if "input_ids_sha256" in outcome and outcome["input_ids_sha256"] != case["input_ids_sha256"]:
        violations.append("input IDs differ")
    if outcome.get("forwards", 1) != 1:
        violations.append("more than one forward")
    probabilities = outcome.get("probabilities")
    if not isinstance(probabilities, list) or len(probabilities) != len(reference["probabilities"]):
        return violations + ["probability count differs"]
    if not all(_number(p) and math.isfinite(p) and 0.0 <= p <= 1.0 for p in probabilities):
        return violations + ["non-finite or out-of-range probability"]
    if abs(math.fsum(probabilities) - 1.0) > PROBABILITY_SUM:
        violations.append(f"probability sum error {abs(math.fsum(probabilities) - 1.0):.3g}")
    error = max_abs(probabilities, reference["probabilities"])
    if error > PROBABILITY_MAX_ABS:
        violations.append(f"max abs difference {error:.3g} > {PROBABILITY_MAX_ABS}")
    if normalize_judgment(outcome.get("judgment")) != normalize_judgment(reference["judgment"]):
        violations.append(f"judgment {outcome.get('judgment')!r} != {reference['judgment']!r}")
    return violations


def max_abs(a, b):
    return max(abs(x - y) for x, y in zip(a, b, strict=True))


def normalize_judgment(value):
    if not isinstance(value, dict) or value.get("kind") not in ("selected", "abstained"):
        return ("malformed", repr(value))
    return (value["kind"], value.get("candidate_id") if value["kind"] == "selected" else None)


def repeat_violations(records):
    """`records`: (arm, mode, case_id, outcome). Cases whose completed probabilities differ in bits."""
    seen = {}
    for arm, mode, case_id, outcome in records:
        if isinstance(outcome, dict) and outcome.get("status") == "completed":
            bits = tuple(float(p).hex() for p in outcome["probabilities"])
            seen.setdefault((arm, mode, case_id), set()).add(bits)
    return sorted(f"{a}/{m}/{c}" for (a, m, c), values in seen.items() if len(values) != 1)
