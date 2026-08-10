
from saas_words_two.contracts import validate_title, validate_title_set


def test_valid_title():
    assert validate_title("Vendor Guard").valid


def test_invalid_title_formats():
    assert not validate_title("vendor Guard").valid
    assert not validate_title("Vendor-Guard").valid
    assert not validate_title("Vendor Guard Tool").valid


def test_detects_reverse_and_history_duplicates():
    errors = validate_title_set(
        ["Vendor Guard", "Guard Vendor"],
        target_count=2,
        history=["Permit Flow"],
    )
    assert any("reverse_duplicate" in e for e in errors)


def test_exact_count_required():
    errors = validate_title_set(["Vendor Guard"], target_count=2)
    assert any(e.startswith("wrong_count") for e in errors)
