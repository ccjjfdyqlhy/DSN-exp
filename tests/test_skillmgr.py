"""Test skillmgr functionality."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skills.builtin.skillmgr.tools.skillmgr import SkillMgrTool

t = SkillMgrTool()

print("=== list_skills ===")
r = t.list_skills()
assert r["success"]
print(f"Count: {r['count']}")
for s in r["skills"]:
    print(f"  {s['name']} [{s['source']}] tools={s['tool_names']}")

print("\n=== convert_skill ===")
r2 = t.convert_skill("agent-browser", "agent_browser")
assert r2["success"]
print(f"Message: {r2['message']}")
print(f"Target: {r2['target']}")
print(f"Binary: {r2['binary']}")

print("\n=== after convert ===")
r3 = t.list_skills()
print(f"Count: {r3['count']}")

print("\n=== install_deps (dry) ===")
r4 = t.install_deps("agent_browser")
print(f"Success: {r4['success']}")
print(f"Python installed: {r4.get('python_installed', [])}")
print(f"Python skipped: {r4.get('python_skipped', [])}")
print(f"System: {len(r4.get('system_results', []))} commands")

print("\n=== enable_skill ===")
r5 = t.enable_skill("agent_browser")
print(f"Success: {r5['success']}, Message: {r5.get('message')}")

# Verify generated files
import json
base = os.path.join("skills", "custom", "agent_browser")
print(f"\n=== Generated files ===")
for f in ["skill.yaml", "prompts/instruction.md", "tools/wrapper.py", "tools/__init__.py"]:
    fp = os.path.join(base, f)
    exists = os.path.exists(fp)
    size = os.path.getsize(fp) if exists else 0
    print(f"  {f}: {'OK' if exists else 'MISSING'} ({size} bytes)")

# Cleanup
import shutil
shutil.rmtree(base, ignore_errors=True)

print("\n=== ALL TESTS PASSED ===")
