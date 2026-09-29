from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from app.agentflow_adapter.intent_router import IntentRouter
from app.agentflow_adapter.schemas import IntentDecision
from app.agentflow_adapter.runtime import route_consistency


def _macro_f1(rows: list[tuple[str, str]]) -> float:
    labels = sorted({label for pair in rows for label in pair})
    scores = []
    for label in labels:
        tp = sum(actual == label and predicted == label for actual, predicted in rows)
        fp = sum(actual != label and predicted == label for actual, predicted in rows)
        fn = sum(actual == label and predicted != label for actual, predicted in rows)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(scores) / len(scores) if scores else 0.0


def evaluate(path: Path | None = None) -> dict:
    data_path = path or Path(__file__).parent / "data" / "intent_cases.json"
    cases = json.loads(data_path.read_text(encoding="utf-8-sig"))
    router = IntentRouter()
    rows: list[tuple[str, str]] = []
    routes: list[bool] = []
    by_class: dict[str, list[bool]] = defaultdict(list)
    for case in cases:
        decision = router.classify(case["text"], has_image=case.get("has_image", False))
        expected = case["expected_intent"]
        correct = decision.primary_intent == expected
        rows.append((expected, decision.primary_intent))
        by_class[expected].append(correct)
        expected_route = case.get("expected_route")
        if expected_route:
            expected_decision = IntentDecision(
                primary_intent=expected,
                intent_group="evaluation",
                primary_agent="evaluation",
                confidence=1.0,
            )
            routes.append(route_consistency(expected_decision, expected_route) is True)
    correct_count = sum(actual == predicted for actual, predicted in rows)
    return {
        "total": len(cases),
        "correct": correct_count,
        "accuracy": correct_count / len(cases) if cases else 0.0,
        "macro_f1": _macro_f1(rows),
        "route_consistency": sum(routes) / len(routes) if routes else None,
        "per_intent": {label: {"total": len(values), "correct": sum(values), "accuracy": sum(values) / len(values)} for label, values in sorted(by_class.items())},
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
