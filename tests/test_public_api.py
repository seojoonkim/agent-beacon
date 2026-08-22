"""The documented v0.2 public import surface remains available."""


def test_core_ledger_api_is_public():
    from agent_beacon import (
        CorruptLedgerError,
        RunConflictError,
        RunLedger,
        RunRecord,
        RunTransition,
        TerminalRunError,
        UnknownRunError,
        UserInputOpenResult,
    )

    assert all(
        value is not None
        for value in (
            RunLedger,
            RunRecord,
            RunTransition,
            UserInputOpenResult,
            UnknownRunError,
            RunConflictError,
            TerminalRunError,
            CorruptLedgerError,
        )
    )


def test_hermes_handoff_api_is_public():
    from agent_beacon_hermes import ResumeHandoffProjection, read_resume_handoff

    assert ResumeHandoffProjection is not None
    assert callable(read_resume_handoff)