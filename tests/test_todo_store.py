# tests/test_todo_store.py
# Todo plans: the store every app shares (item state, progress, events,
# persistence and the legacy flat-list file).

from __future__ import annotations

import json
import threading

import pytest

from aicf.harness.todo import TodoItem, TodoPlan, TodoStore, default_todo_path


def _plan(store, titles=('one', 'two')):
    return store.create_plan([{'title': title} for title in titles])


def test_a_plan_counts_progress_and_ends_when_every_item_is_settled():
    store = TodoStore()
    plan = _plan(store, ('a', 'b', 'c'))
    assert plan.status == 'executing'
    assert plan.progress == 0.0
    assert [item.id for item in plan.items] == ['item-00', 'item-01', 'item-02']

    store.update_item(plan.plan_id, 'item-00', status='completed')
    store.update_item(plan.plan_id, 'item-01', status='in_progress')
    assert plan.progress == pytest.approx(1 / 3)
    assert plan.current is not None and plan.current.id == 'item-01'

    store.update_item(plan.plan_id, 'item-02', status='failed')
    store.update_item(plan.plan_id, 'item-01', status='completed')
    assert plan.progress == 1.0
    assert plan.status == 'completed', 'all settled -> the plan is done'
    assert plan.done_count == 3 and plan.open_count == 0


def test_creating_a_plan_with_items_and_adding_later():
    store = TodoStore()
    plan = store.create_plan([{'title': 'a', 'description': 'why',
                               'priority': 2}])
    assert plan.items[0].description == 'why' and plan.items[0].priority == 2
    item = store.add_item(plan.plan_id, 'b', status='in_progress')
    assert item is not None and item.id == 'item-01'
    assert plan.current.id == 'item-01'
    with pytest.raises(ValueError):
        store.add_item(plan.plan_id, '   ')


def test_an_unknown_status_is_rejected():
    store = TodoStore()
    plan = _plan(store)
    with pytest.raises(ValueError):
        store.update_item(plan.plan_id, 'item-00', status='banana')
    assert plan.items[0].status == 'pending'


def test_remove_item_keeps_the_other_ids_stable():
    store = TodoStore()
    plan = _plan(store, ('a', 'b', 'c'))
    assert store.remove_item(plan.plan_id, 'item-01') is True
    assert [item.id for item in plan.items] == ['item-00', 'item-02']
    assert store.remove_item(plan.plan_id, 'item-99') is False


def test_listeners_see_every_change_and_the_revision_moves():
    store = TodoStore()
    events = []
    store.add_listener(events.append)
    plan = _plan(store, ('a',))
    store.update_item(plan.plan_id, 'item-00', status='completed')
    store.set_completed(plan.plan_id, 'all done')
    kinds = [event['type'] for event in events]
    assert kinds == ['plan_created', 'item_updated', 'plan_completed'], kinds
    assert events[-1]['revision'] == store.revision == 3
    assert events[1]['item']['title'] == 'a'

    store.remove_listener(events.append)
    store.add_item(plan.plan_id, 'b')
    assert len(events) == 3


def test_a_breaking_listener_does_not_break_the_store():
    store = TodoStore()

    def boom(event):
        raise RuntimeError('listener bug')

    store.add_listener(boom)
    plan = _plan(store, ('a',))
    assert store.get_plan(plan.plan_id) is not None


def test_active_plan_is_the_newest_unfinished_one():
    store = TodoStore()
    first = _plan(store, ('a',))
    store.set_completed(first.plan_id, 'done')
    assert store.active_plan() is None
    current = _plan(store, ('b',))
    assert store.active_plan().plan_id == current.plan_id
    store.set_failed(current.plan_id, 'nope')
    assert store.active_plan() is None


def test_a_plan_survives_the_file(tmp_path):
    path = default_todo_path(tmp_path)
    store = TodoStore(path)
    plan = _plan(store, ('write it', 'test it'))
    store.update_item(plan.plan_id, 'item-00', status='completed',
                      result='ok')
    assert path.exists()

    reopened = TodoStore(path)
    restored = reopened.get_plan(plan.plan_id)
    assert restored is not None
    assert [item.title for item in restored.items] == ['write it', 'test it']
    assert restored.items[0].status == 'completed'
    assert restored.items[0].result == 'ok'
    assert restored.progress == pytest.approx(0.5)


def test_the_old_flat_list_file_is_read_instead_of_dropped(tmp_path):
    """The previous ``project.todo`` tool wrote ``[{text, status}]``."""
    path = default_todo_path(tmp_path)
    path.write_text(json.dumps([
        {'text': 'legacy one', 'status': 'pending'},
        {'text': 'legacy two', 'status': 'completed'},
    ]), encoding='utf-8')

    store = TodoStore(path)
    plan = store.active_plan() or next(iter(store.list_plans()), None)
    assert plan is not None
    loaded = store.get_plan(plan['plan_id'] if isinstance(plan, dict) else plan.plan_id)
    assert [item.title for item in loaded.items] == ['legacy one', 'legacy two']
    assert loaded.items[1].status == 'completed'
    assert loaded.meta.get('legacy') is True


def test_an_unreadable_file_is_kept_on_disk(tmp_path):
    path = default_todo_path(tmp_path)
    path.write_text('{"plans": [', encoding='utf-8')
    store = TodoStore(path)          # warns, does not raise
    assert store.active_plan() is None
    assert path.read_text(encoding='utf-8') == '{"plans": ['
    # a mutation keeps working and rewrites a valid file
    store.create_plan([{'title': 'fresh'}])
    assert json.loads(path.read_text(encoding='utf-8'))['plans']


def test_the_file_keeps_unfinished_plans_and_recent_history(tmp_path):
    path = default_todo_path(tmp_path)
    store = TodoStore(path)
    store.max_plans = 2
    for index in range(5):
        plan = store.create_plan([{'title': f't{index}'}])
        store.set_completed(plan.plan_id, 'done')
    live = store.create_plan([{'title': 'still going'}])
    store.save()
    reopened = TodoStore(path)
    finished = [row for row in reopened.list_plans() if row['status'] == 'completed']
    assert len(finished) == 2
    assert reopened.active_plan().plan_id == live.plan_id


def test_concurrent_updates_lose_nothing(tmp_path):
    store = TodoStore(default_todo_path(tmp_path))
    plan = store.create_plan([{'title': f'item {index}'} for index in range(20)])

    def finish(index):
        store.update_item(plan.plan_id, f'item-{index:02d}', status='completed',
                          result='ok')

    threads = [threading.Thread(target=finish, args=(index,))
               for index in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert plan.done_count == 20
    assert reopened_progress(store, plan.plan_id) == 1.0


def reopened_progress(store, plan_id):
    return store.get_plan(plan_id).progress


def test_plan_and_item_round_trip_through_dicts():
    plan = TodoPlan.from_dict({
        'plan_id': 'todo-x', 'status': 'executing', 'progress': 0.5,
        'meta': {'chat_id': 3},
        'items': [{'id': 'item-00', 'title': 'a', 'status': 'completed'},
                  {'title': 'b'}],     # no id: assigned by position
    })
    assert [item.id for item in plan.items] == ['item-00', 'item-01']
    assert plan.meta == {'chat_id': 3}
    again = TodoPlan.from_dict(plan.to_dict())
    assert again.to_dict() == plan.to_dict()


def test_an_item_accepts_the_legacy_text_field():
    item = TodoItem.from_dict({'text': 'old shape', 'status': 'done'})
    assert item.title == 'old shape'
    assert item.status == 'completed', 'done -> completed'
