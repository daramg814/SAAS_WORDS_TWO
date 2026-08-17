from saas_words_two import cli
from saas_words_two.word_pipeline import RecoveryRequired, RetryRequired


def _run(monkeypatch, capsys, side_effect):
    def fake_run_pipeline(options):
        raise side_effect

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)
    exit_code = cli.main(["--mode", "qa"])
    return exit_code, capsys.readouterr().out


def test_retry_required_default_status_prints_retrying(monkeypatch, capsys):
    exit_code, out = _run(monkeypatch, capsys, RetryRequired("no eligible candidates"))
    assert exit_code == 4
    assert out.startswith("RETRYING:")


def test_retry_required_capability_stagnation_status_is_reported_verbatim(monkeypatch, capsys):
    """cli.py must report the exception's actual status, not hardcode
    RETRYING - CAPABILITY_STAGNATION is distinct from RETRYING and that
    distinction is lost if the CLI prints the wrong label."""
    exit_code, out = _run(
        monkeypatch, capsys, RetryRequired("zero progress", status="CAPABILITY_STAGNATION")
    )
    assert exit_code == 4
    assert out.startswith("CAPABILITY_STAGNATION:")


def test_recovery_required_prints_distinct_status_and_exit_code(monkeypatch, capsys):
    exit_code, out = _run(monkeypatch, capsys, RecoveryRequired("cache increment mismatch"))
    assert exit_code == 5
    assert out.startswith("RECOVERY_REQUIRED:")
