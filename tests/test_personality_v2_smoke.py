"""Smoke test for PersonalitySystemV2 — all three modules + persistence."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.dsn.prompt.personality_v2 import PersonalitySystemV2
from apps.dsn.prompt.personality_v2.emotion import EmotionModule, EmotionalStimulus, StimulusAnalyzer
from apps.dsn.prompt.personality_v2.affinity import AffinityModule, ActionClassifier, AFFINITY_LEVELS
from apps.dsn.prompt.personality_v2.habit import HabitModule, Habit, PatternObserver


def test_emotion():
    print("=== Test 1: EmotionModule ===")
    e = EmotionModule()
    e.reset(baselines={"joly": 0.55, "sorw": 0.25, "angr": 0.15, "fear": 0.20, "meta": 0.65})
    print(f"  Initial display: {e.get_display_emotion()}")

    stim = EmotionalStimulus(delta_joly=0.06, delta_sorw=-0.02, delta_meta=-0.02)
    e.apply_stimulus(stim)
    print(f"  After praise: raw={e.get_raw_values()}")
    mood = e.get_mood_profile()
    print(f"  Mood: {mood['label']}")
    assert mood is not None
    assert e.get_raw_values()["joly"] > 0.55
    print("  PASSED")


def test_affinity():
    print("\n=== Test 2: AffinityModule ===")
    a = AffinityModule()
    a.reset(initial=20.0)
    r = a.apply_action({"id": "P_PRAISE", "delta": 4, "cooldown_minutes": 60, "max_per_day": 8})
    assert r == 4.0
    print(f"  After P_PRAISE: delta={r}, value={a.value}, level=L{a.get_level()}")

    r2 = a.apply_action({"id": "P_PRAISE", "delta": 4, "cooldown_minutes": 60, "max_per_day": 8})
    assert r2 == 0.0, f"Cooldown should block duplicate, got {r2}"
    print(f"  Duplicate blocked: delta={r2}")

    for i in range(10):
        a.apply_action({"id": "P_THANK", "delta": 2, "cooldown_minutes": 10, "max_per_day": 10})
    print(f"  After 10x P_THANK: value={a.value}, level=L{a.get_level()}")
    assert a.get_level() >= 1
    print("  PASSED")


def test_habit():
    print("\n=== Test 3: HabitModule ===")
    h = HabitModule()
    h.load_innate({
        "catchphrases": [
            {"content": "哼", "strength": 0.9},
            {"content": "随便你", "strength": 0.7},
        ],
        "patterns": [
            {"content": "先说反话再帮忙", "strength": 0.9},
        ],
        "tones": [
            {"content": "爱用省略号", "strength": 0.5},
        ],
    })
    active = h.select_active(top_n=5)
    assert len(active) >= 3
    print(f"  Active habits: {len(active)}")
    for ah in active:
        print(f"    [{ah.source}] {ah.content} (strength={ah.strength:.2f})")
    print("  PASSED")


def test_observer():
    print("\n=== Test 4: PatternObserver ===")
    obs = PatternObserver(window=20)
    for msg in ["你好呀~", "今天天气不错~", "真的吗~", "太好了~", "谢谢你~"]:
        obs.feed(msg)
    candidates = obs.observe()
    print(f"  Candidates found: {len(candidates)}")
    for c in candidates:
        print(f"    [{c.type}] {c.content}")
    print("  PASSED")


def test_persistence():
    print("\n=== Test 5: Persistence ===")
    db_path = os.path.join(tempfile.gettempdir(), "test_personality_v2.db")
    from apps.dsn.db.chat import ChatDBManager
    db = ChatDBManager(db_path=db_path)

    p2 = PersonalitySystemV2(db=db)
    p2.init_table()
    p2._store.ensure_exists(uid=99, preset_name="default")

    row = p2._store.load(99)
    assert row is not None
    print(f"  Row uid=99 exists, joly={row['joly']:.2f}, affinity={row['affinity']:.1f}")

    # test save
    e = EmotionModule()
    a = AffinityModule()
    h = HabitModule()
    p2._store.save(
        uid=99,
        emotion_dict=e.to_dict(),
        affinity_dict=a.to_dict(),
        habits_list=h.to_list(),
        preset_name="test",
    )
    p2._store.force_flush()

    row2 = p2._store.load(99)
    assert row2 is not None and row2["preset_name"] == "test"
    print(f"  After save: preset={row2['preset_name']}")

    db.close_connection()
    try:
        os.remove(db_path)
    except OSError:
        pass
    print("  PASSED")


def test_action_classifier():
    print("\n=== Test 6: ActionClassifier ===")
    classifier = ActionClassifier([])
    actions = classifier.classify("谢谢你帮我解决了问题")
    print(f"  Actions detected: {[a['id'] for a in actions]}")
    assert any(a["id"] == "N_INSULT" for a in actions) is False
    print("  PASSED")


def test_stimulus_analyzer():
    print("\n=== Test 7: StimulusAnalyzer ===")
    rules = [
        {
            "id": "thanks",
            "pattern": ["谢谢", "感谢", "多谢"],
            "stimulus": {"delta_joly": 0.04},
        },
        {
            "id": "praise",
            "pattern": ["厉害", "聪明", "太强了"],
            "target": "ai",
            "stimulus": {"delta_joly": 0.06, "delta_sorw": -0.02, "delta_meta": -0.02},
        },
    ]
    analyzer = StimulusAnalyzer(rules)
    stim = analyzer.analyze("谢谢你，你太厉害了！")
    print(f"  Stimulus: {stim.to_dict()}")
    assert stim.delta_joly >= 0.10, f"Should get combined joly >= 0.10, got {stim.delta_joly}"
    print("  PASSED")


if __name__ == "__main__":
    test_emotion()
    test_affinity()
    test_habit()
    test_observer()
    test_persistence()
    test_action_classifier()
    test_stimulus_analyzer()
    print("\n" + "=" * 40)
    print("  ALL SMOKE TESTS PASSED")
    print("=" * 40)
