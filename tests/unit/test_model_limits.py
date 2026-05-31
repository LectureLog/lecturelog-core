from lecturelog.infrastructure.llm.model_limits import limits_for


def test_known_model_returns_positive_rpm_rpd():
    rpm, rpd = limits_for("gemini-3.5-flash")
    assert rpm > 0 and rpd > 0


def test_unknown_model_returns_conservative_default():
    rpm, rpd = limits_for("nonexistent-model-xyz")
    assert rpm > 0 and rpd > 0
