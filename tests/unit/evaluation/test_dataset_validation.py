from pathlib import Path

from src.evaluation.schemas import EvaluationSample

DATASET_PATH = Path(__file__).resolve().parents[3] / "data" / "evaluation" / "benchmark_100-3.jsonl"


def test_benchmark_set_valid():
    samples: list[EvaluationSample] = []
    out_of_domain = 0

    with open(DATASET_PATH, encoding="utf-8") as f:
        for _line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            samples.append(EvaluationSample.model_validate_json(line))

        for sample in samples:
            if sample.expected_refusal_reason == "out_of_domain":
                out_of_domain = out_of_domain + 1

        out_of_domain = [s for s in samples if s.expected_refusal_reason == "out_of_domain"]

        weak_evidence = [s for s in samples if s.expected_refusal_reason == "insufficient_evidence"]

        standard_cases = [s for s in samples if not s.should_escalate]

    assert len(samples) == 100, f"Expected exactly 100 records, got {len(samples)}"

    assert len(out_of_domain) == 15, f"Expected 15 out_of_domain cases, got {len(out_of_domain)}"

    assert len(weak_evidence) == 15, f"Expected 15 weak_evidence cases, got {len(weak_evidence)}"

    assert len(standard_cases) == 70, (
        f"Expected 70 non-escalated extraction cases, got {len(standard_cases)}"
    )

    risk_tiers = {s.risk_tier for s in samples}
    assert risk_tiers == {
        "low",
        "medium",
        "high",
    }, f"Missing risk tiers: {risk_tiers}"
