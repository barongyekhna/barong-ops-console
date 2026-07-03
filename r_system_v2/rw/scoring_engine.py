"""R-W scoring decisions exposed to the live pipeline UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from r_system_v2.rw.core.models import DeepSeekScreening, RuleEvaluation


ScoreAction = Literal["pass", "reject", "pending_review"]


@dataclass(frozen=True)
class ScoreDecision:
    action: ScoreAction
    score: int | None
    reason: str

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "action": self.action,
            "score": self.score,
            "reason": self.reason,
        }


class ScoringEngine:
    """Normalize rule and DeepSeek output into pass/reject/review states."""

    def score_rule(self, evaluation: RuleEvaluation) -> ScoreDecision:
        if evaluation.passed:
            return ScoreDecision(
                action="pending_review",
                score=None,
                reason="规则预筛通过，等待 DeepSeek 初筛",
            )
        return ScoreDecision(
            action="reject",
            score=0,
            reason=",".join(evaluation.reasons) or "规则预筛拒绝",
        )

    def score_deepseek(self, screening: DeepSeekScreening) -> ScoreDecision:
        if screening.verdict == "cut" or screening.score < 60:
            return ScoreDecision(
                action="pending_review",
                score=screening.score,
                reason=screening.top_reason,
            )
        if screening.verdict == "hold" or screening.score < 75:
            return ScoreDecision(
                action="pending_review",
                score=screening.score,
                reason=screening.top_reason,
            )
        return ScoreDecision(
            action="pass",
            score=screening.score,
            reason=screening.top_reason,
        )
