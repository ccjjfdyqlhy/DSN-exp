"""Integration test for Impression system."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.dsn.db.chat import ChatDBManager
from apps.dsn.prompt.impression import ImpressionManager

db_path = os.path.join(tempfile.gettempdir(), "test_impressions.db")

# Clean up from previous run
try:
    os.remove(db_path)
except OSError:
    pass

print("=== Test 1: DB table creation ===")
db = ChatDBManager(db_path=db_path)
db.add_or_update_user(uid=1, nickname="test_user")
db.add_or_update_user(uid=2, nickname="test_user_2")
im = ImpressionManager(db=db)
assert im.has_db
print("  PASSED")

print("\n=== Test 2: Add impressions ===")
im.add(uid=1, category="兴趣", content="用户喜欢玩游戏", confidence=0.8, source="declared")
im.add(uid=1, category="技能", content="用户会Python", confidence=0.9, source="observed")
im.add(uid=1, category="工作", content="后端工程师", confidence=0.7, source="inferred")
im.add(uid=1, category="兴趣", content="喜欢动漫", confidence=0.5, source="protocol")
assert im.count(uid=1) == 4
print(f"  Count: {im.count(uid=1)}")

print("\n=== Test 3: Query impressions ===")
results = im.query(uid=1)
assert len(results) == 4
for r in results:
    print(f"  [{r['category']}] {r['content']} (conf={r['confidence']}, src={r['source']})")

by_cat = im.query(uid=1, category="兴趣")
assert len(by_cat) == 2
print(f"  By category '兴趣': {len(by_cat)} results")

by_conf = im.query(uid=1, min_confidence=0.8)
assert len(by_conf) == 2
print(f"  By confidence >=0.8: {len(by_conf)} results")

print("\n=== Test 4: Categories ===")
cats = im.categories(uid=1)
assert len(cats) == 3
assert "兴趣" in cats
print(f"  Categories: {cats}")

print("\n=== Test 5: Summary ===")
summary = im.summary(uid=1)
print(summary[:200])

print("\n=== Test 6: Prompt context ===")
ctx = im.prompt_context(uid=1)
print(ctx[:300])
assert "你对用户的了解" in ctx
assert "用户喜欢玩游戏" in ctx

print("\n=== Test 7: SSP suggestion ===")
assert im.should_propose_ssp(uid=1, affinity_level=0)  # low affinity + low count
assert im.should_propose_ssp(uid=2, affinity_level=0)  # no impressions at all
print(f"  uid=1 suggest: {im.should_propose_ssp(1, 0)} (low affinity)")
print(f"  uid=2 suggest: {im.should_propose_ssp(2, 0)} (no data)")

print("\n=== Test 8: Merge duplicates ===")
im.add(uid=1, category="兴趣", content="用户喜欢玩游戏", confidence=0.3, source="inferred")
assert im.count(uid=1) == 5
merged = im.merge_similar(uid=1)
assert merged >= 1
print(f"  Merged: {merged}, after: {im.count(uid=1)}")

print("\n=== Test 9: Delete impression ===")
impressions = im.query(uid=1)
assert len(impressions) > 0
deleted = im.delete(impressions[0]["impression_id"])
assert deleted
print(f"  Deleted impression {impressions[0]['impression_id']}: {deleted}")

print("\n=== Test 10: Parse from text ===")
sample_text = """考察结果：
IMPRESSION:兴趣:喜欢机器学习:85
IMPRESSION:技能:熟练使用PyTorch:90
这是一些无关文本
IMPRESSION:项目:正在做一个NLP项目:75
"""
added = im.load_impressions_from_text(uid=2, text=sample_text, source="protocol")
assert added == 3
print(f"  Parsed {added} impressions from text")
for r in im.query(uid=2):
    print(f"  [{r['category']}] {r['content']} (conf={r['confidence']})")

# Cleanup
db.close_connection()
try:
    os.remove(db_path)
except OSError:
    pass

print("\n=== ALL TESTS PASSED ===")
