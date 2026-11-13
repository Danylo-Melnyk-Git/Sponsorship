"""Firestore research store; server credentials never reach the browser."""

from copy import deepcopy
import json

from .models import ConflictError, ValidationError, identifier, utcnow


def encode(value):
    result = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(result.encode('utf-8')) > 900_000:
        raise ValidationError('Документ превышает безопасный лимит Firestore (900 КБ)')
    return result


class FirestoreStore:
    def __init__(self, project, collection='sponsorship_research'):
        from google.cloud import firestore
        self.client = firestore.Client(project=project)
        self.collection = self.client.collection(collection)
        self.project = project

    def _ref(self, research_id):
        if not research_id or '/' in research_id:
            raise ValidationError('Неверный ID исследования')
        return self.collection.document(research_id)

    def create(self, state):
        value = deepcopy(state)
        value['id'] = identifier('research')
        value['revision'] = 1
        value['created_at'] = value['updated_at'] = utcnow()
        encoded = encode(value)
        ref = self._ref(value['id'])
        batch = self.client.batch()
        batch.create(ref, {'document': encoded, 'updated_at': value['updated_at']})
        batch.create(ref.collection('history').document('1'), {
            'revision': 1, 'at': value['created_at'], 'action': 'create',
            'actor': 'owner', 'payload': '{}', 'snapshot': encoded})
        batch.commit(timeout=20)
        return value

    def get(self, research_id):
        snapshot = self._ref(research_id).get(timeout=20)
        if not snapshot.exists:
            raise KeyError('Исследование не найдено')
        return json.loads(snapshot.to_dict()['document'])

    def list(self):
        return [json.loads(row.to_dict()['document']) for row in
                self.collection.order_by('updated_at', direction='DESCENDING').stream(timeout=20)]

    def update(self, research_id, revision, action, actor, payload, mutate):
        from google.cloud import firestore
        ref = self._ref(research_id)

        @firestore.transactional
        def apply(transaction):
            snapshot = ref.get(transaction=transaction, timeout=20)
            if not snapshot.exists:
                raise KeyError('Исследование не найдено')
            state = json.loads(snapshot.to_dict()['document'])
            if state['revision'] != revision:
                raise ConflictError('Данные изменились. Обновите исследование перед сохранением.')
            mutate(state)
            state['revision'] += 1
            state['updated_at'] = utcnow()
            encoded = encode(state)
            transaction.set(ref, {'document': encoded, 'updated_at': state['updated_at']})
            transaction.create(ref.collection('history').document(str(state['revision'])), {
                'revision': state['revision'], 'at': state['updated_at'], 'action': action,
                'actor': actor, 'payload': encode(payload), 'snapshot': encoded})
            return state

        return apply(self.client.transaction(max_attempts=3))

    def history(self, research_id):
        self.get(research_id)
        rows = self._ref(research_id).collection('history').order_by('revision').stream(timeout=20)
        return [{k: (json.loads(v) if k == 'payload' else v)
                 for k, v in row.to_dict().items() if k != 'snapshot'} for row in rows]

    def snapshot(self, research_id, revision):
        row = self._ref(research_id).collection('history').document(str(revision)).get(timeout=20)
        if not row.exists:
            raise KeyError('Версия не найдена')
        return json.loads(row.to_dict()['snapshot'])
