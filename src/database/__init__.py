from src.database.models import Database

__all__ = ["Database", "AirtableSync"]


def __getattr__(name: str):
    if name == "AirtableSync":
        from src.database.airtable_sync import AirtableSync
        return AirtableSync
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
