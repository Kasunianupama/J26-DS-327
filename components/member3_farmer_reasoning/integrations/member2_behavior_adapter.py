"""Member 3 adapter for the current Member 2 behavioral-intelligence contract."""
from components.member2_behavioral_intelligence.services.demo_service import farm_behavior


class Member2BehaviorAdapter:
    """Normalizes Member 2 output without changing Member 2 business logic."""

    def get_herd_context(self, farm_id: str) -> dict:
        result = farm_behavior(farm_id)
        behavior = result["behavior"]
        welfare = result["welfare"]
        return {
            "routine_label": behavior.label,
            "routine_confidence": behavior.confidence,
            "welfare_score": welfare.welfare_score,
            "welfare_summary": welfare.summary,
            "modalities": result["available_modalities"],
        }

    def response_context(self, farm_id: str) -> dict:
        """Expose Member 2's herd-level result in Member 3's response shape."""
        context = self.get_herd_context(farm_id)
        return {
            "routine": context["routine_label"].replace("_", " "),
            "confidence": context["routine_confidence"],
            "welfare_score": context["welfare_score"],
            "welfare_summary": context["welfare_summary"],
            "modalities": context["modalities"],
            "scope": "herd-level",
        }
