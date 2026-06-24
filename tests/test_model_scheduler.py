import os
import threading
import time

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")

from models.scheduler import ModelScheduler


def _register(scheduler, name, events, priority=50, immediate=False, resident=False, orchestrated=True):
    scheduler.register(
        model_name=name,
        base_url="http://lmstudio.test",
        load_fn=lambda n=name: events.append(("load", n)) or True,
        unload_fn=lambda n=name: events.append(("unload", n)) or True,
        priority=priority,
        immediate=immediate,
        resident=resident,
        orchestrated=orchestrated,
    )


def test_immediate_model_temporarily_evicts_and_restores_higher_priority_model():
    events = []
    scheduler = ModelScheduler(max_concurrent=1)
    _register(scheduler, "chat", events, priority=90)
    _register(scheduler, "ocr", events, priority=10, immediate=True)

    with scheduler.use("chat", timeout=1):
        pass
    assert scheduler.snapshot()["chat"]["loaded"] is True

    with scheduler.use("ocr", timeout=1, immediate=True):
        assert scheduler.snapshot()["ocr"]["loaded"] is True

    snap = scheduler.snapshot()
    assert snap["ocr"]["loaded"] is False
    assert snap["chat"]["loaded"] is True
    assert events == [
        ("load", "chat"),
        ("unload", "chat"),
        ("load", "ocr"),
        ("unload", "ocr"),
        ("load", "chat"),
    ]


def test_lower_priority_normal_request_does_not_evict_loaded_higher_priority_model():
    events = []
    scheduler = ModelScheduler(max_concurrent=1)
    _register(scheduler, "chat", events, priority=90)
    _register(scheduler, "low", events, priority=10)

    with scheduler.use("chat", timeout=1):
        pass

    try:
        with scheduler.use("low", timeout=0.1):
            pass
    except TimeoutError:
        pass
    else:
        raise AssertionError("low priority normal request should wait instead of evicting")

    assert scheduler.snapshot()["chat"]["loaded"] is True
    assert ("unload", "chat") not in events


def test_model_queue_is_fifo():
    events = []
    scheduler = ModelScheduler(max_concurrent=1)
    _register(scheduler, "chat", events, priority=50)
    order = []
    entered = threading.Event()

    def worker(label, hold=0):
        with scheduler.use("chat", timeout=2):
            order.append(label)
            entered.set()
            if hold:
                time.sleep(hold)

    t1 = threading.Thread(target=worker, args=("first", 0.2))
    t2 = threading.Thread(target=worker, args=("second", 0))
    t1.start()
    entered.wait(1)
    t2.start()
    t1.join(2)
    t2.join(2)

    assert order == ["first", "second"]


def test_non_orchestrated_resident_model_does_not_consume_slot_or_get_unloaded():
    events = []
    scheduler = ModelScheduler(max_concurrent=1)
    _register(scheduler, "embedding", events, priority=100, resident=True, orchestrated=False)
    _register(scheduler, "chat", events, priority=50)
    _register(scheduler, "ocr", events, priority=10, immediate=True)

    with scheduler.use("embedding", timeout=1):
        pass
    with scheduler.use("chat", timeout=1):
        pass
    with scheduler.use("ocr", timeout=1, immediate=True):
        pass

    assert ("unload", "embedding") not in events
    assert scheduler.snapshot()["embedding"]["loaded"] is True
