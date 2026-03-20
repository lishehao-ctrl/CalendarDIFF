from __future__ import annotations

from training.gmail_secondary_filter import train_distilbert as trainer


def test_compute_effective_weight_boosts_relevant_samples() -> None:
    weight = trainer.compute_effective_weight(
        label="relevant",
        relevant_like=True,
        risk_tier="critical",
        base_weight=1.0,
        relevant_weight=2.0,
        non_target_weight=1.0,
        uncertain_weight=1.0,
        relevant_like_uncertain_weight=1.5,
    )

    assert weight == 2.0


def test_compute_effective_weight_boosts_relevant_like_uncertain_samples() -> None:
    weight = trainer.compute_effective_weight(
        label="uncertain",
        relevant_like=True,
        risk_tier="high",
        base_weight=1.0,
        relevant_weight=2.0,
        non_target_weight=1.0,
        uncertain_weight=1.0,
        relevant_like_uncertain_weight=1.5,
    )

    assert weight == 1.5


def test_compute_effective_weight_keeps_non_target_default_weight() -> None:
    weight = trainer.compute_effective_weight(
        label="non_target",
        relevant_like=False,
        risk_tier="low",
        base_weight=1.0,
        relevant_weight=2.0,
        non_target_weight=1.0,
        uncertain_weight=1.0,
        relevant_like_uncertain_weight=1.5,
    )

    assert weight == 1.0


def test_compute_effective_weight_does_not_boost_medium_uncertain() -> None:
    weight = trainer.compute_effective_weight(
        label="uncertain",
        relevant_like=False,
        risk_tier="medium",
        base_weight=1.0,
        relevant_weight=2.0,
        non_target_weight=1.0,
        uncertain_weight=1.0,
        relevant_like_uncertain_weight=1.5,
    )

    assert weight == 1.0
