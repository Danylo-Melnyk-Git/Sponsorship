"""Explicit backend selection; SQLite remains available without cloud packages."""

from .store import Store


def open_store(database):
    if str(database).startswith('firestore://'):
        from .firestore_store import FirestoreStore
        from .models import ValidationError
        project = str(database)[len('firestore://'):]
        if not project or '/' in project:
            raise ValidationError('Ожидается firestore://PROJECT_ID')
        return FirestoreStore(project)
    return Store(database)
