"""Guard rules around resolving incidents a collector stopped reporting."""

from app.services import incident_service


class RecordingSession:
    """Records execute() calls without running any SQL."""

    def __init__(self, rowcount=0):
        self.statements = []
        self._rowcount = rowcount

    def execute(self, statement, *args, **kwargs):
        self.statements.append(statement)
        return type("Result", (), {"rowcount": self._rowcount})()


def test_empty_active_set_resolves_nothing():
    """An empty active set is indistinguishable from a collector that
    authenticated and returned nothing, so it must never be read as "the whole
    network recovered" — that would close every open incident at once and lose
    the real detection times."""
    db = RecordingSession(rowcount=999)

    assert incident_service.reconcile_open_incidents(db, "netxms", set()) == 0
    assert db.statements == []


def test_non_empty_active_set_issues_one_update():
    db = RecordingSession(rowcount=7)

    resolved = incident_service.reconcile_open_incidents(
        db, "netxms", {"netxms-alarm-1", "netxms-alarm-2"}
    )

    assert resolved == 7
    assert len(db.statements) == 1
