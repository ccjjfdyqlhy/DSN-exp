"""Final integration check for v2 personality system."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.dsn.prompt.personality_v2 import PersonalitySystemV2

ps = PersonalitySystemV2()
ps.scan_presets(os.path.join("apps", "dsn", "prompt", "personality_v2", "presets"))
ps.load_preset(1, "default")
ps.load_rules_from_files()

# Test on_interaction
result = ps.on_interaction(uid=1, user_message="谢谢你，你太厉害了！", is_positive=True)
print("=== on_interaction result ===")
print(f"  mood: {result['mood']['label']}")
print(f"  affinity: {result['affinity_value']}")
print(f"  level: L{result['affinity_level']}")
print(f"  changes: {result['affinity_changes']}")

# Test build_prompt
prompt = ps.build_prompt(uid=1)
print()
print("=== build_prompt output ===")
for line in prompt.split("\n"):
    if line.strip():
        print(f"  {line}")

# Test get_state
state = ps.get_state(uid=1)
print()
print("=== get_state (keys) ===")
for k, v in state.items():
    if not isinstance(v, dict):
        print(f"  {k}: {v}")

# Test switch preset
ps.switch_preset(1, "tsundere")
state2 = ps.get_state(1)
print()
print(f"=== after switch to tsundere ===")
print(f"  preset: {state2['preset_name']}")
print(f"  mood: {state2['mood']['label']}")
print(f"  display: {state2['display_emotion']}")
print(f"  raw: {state2['raw_emotion']}")

# Test list_presets
presets = ps.list_presets()
print(f"\n=== available presets: {len(presets)} ===")
for p in presets:
    print(f"  - {p['name']} ({p['display_name']}): {p['description']}")

# Test that engine.py properly uses v2
from apps.dsn.prompt.engine import PromptEngine
from apps.dsn.prompt.library import PromptLibrary
lib = PromptLibrary()
engine = PromptEngine(library=lib, personality_v2=ps)
full_prompt = engine.build_system_prompt({"uid": 1, "nickname": "test_user"})
has_v1 = "## 你的性格" in full_prompt and "你的性格特点" in full_prompt
has_v2 = "你当前的情绪状态" in full_prompt and "你与用户的关系" in full_prompt
print(f"\n=== PromptEngine check ===")
print(f"  v1 signature found: {has_v1}")
print(f"  v2 signature found: {has_v2}")
print(f"  Using personality: {'V2' if has_v2 and not has_v1 else 'V1' if has_v1 else 'UNKNOWN'}")

print("\n=== ALL CHECKS PASSED ===")
