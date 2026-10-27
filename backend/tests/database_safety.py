"""Guards for integration tests that write directly to PostgreSQL."""
from sqlalchemy.engine import make_url


def validate_test_database_url(url: str):
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("Les tests d'intégration exigent une URL PostgreSQL dédiée.")
    if not parsed.database or not parsed.database.endswith(("_test", "_tests")):
        raise ValueError(
            "La base d'intégration doit se terminer par _test ou _tests."
        )
    return parsed
