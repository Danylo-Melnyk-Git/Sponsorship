"""Explicit live check. Writes only synthetic QA records, retained for inspection."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('GOOGLE_APPLICATION_CREDENTIALS', str(ROOT / 'secrets/firebase-service-account.json'))

from packages.domain.storage import open_store
from packages.domain.service import ResearchService
from packages.domain.models import ConflictError


def main():
    store = open_store('firestore://sponsoradar-1580e')
    service = ResearchService(store)
    state = service.create({'title': 'Firebase QA — синтетическая проверка', 'kind': 'synthetic',
                            'request': 'Синтетическая проверка записи/чтения. Не рабочее исследование.',
                            'brief': {}})
    research_id = state['id']
    assert store.get(research_id) == state
    changed = store.update(research_id, 1, 'qa_check', 'synthetic_qa', {},
                           lambda value: value.update(title='Firebase QA — чтение и запись проверены'))
    assert store.get(research_id) == changed
    assert store.snapshot(research_id, 1) == state
    assert len(store.history(research_id)) == 2
    assert any(value['id'] == research_id for value in store.list())
    try:
        store.update(research_id, 1, 'qa_stale', 'synthetic_qa', {}, lambda value: None)
    except ConflictError:
        pass
    else:
        raise AssertionError('Не отклонена устаревшая revision')
    def fail(value):
        value['title'] = 'Не должно сохраниться'
        raise ValueError('synthetic rollback')
    try:
        store.update(research_id, 2, 'qa_rollback', 'synthetic_qa', {}, fail)
    except ValueError:
        pass
    assert store.get(research_id) == changed
    result = {'project': store.project, 'research_id': research_id, 'revision': 2,
              'synthetic': True, 'create_read_update_history_snapshot_list_conflict_rollback': 'PASS'}
    target = ROOT / 'data/qa/firebase-live.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
