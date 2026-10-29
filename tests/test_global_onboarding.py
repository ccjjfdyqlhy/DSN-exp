# tests/test_global_onboarding.py
# 根目录 onboarding.py 的纯逻辑测试（不启动 Textual）。
#
# 这里只覆盖「不需要终端、不需要网络」的部分：
#   * 目录自检与依赖展开
#   * 需求 → 能力 → 应用 的映射
#   * .env 合并（保留注释、不重复写键）
#   * 执行计划的去重与开关
#   * 密钥掩码

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import onboarding


def test_catalog_is_consistent():
    assert onboarding.validate_catalog() == []


def test_goal_features_and_apps_are_mapped():
    features = onboarding.features_for_goals(["voice_companion"])
    assert "remote_api" in features
    assert "tts" in features
    assert "memory" in features
    assert onboarding.resolve_apps(["voice_companion"], features) == ["dsn"]

    ui_features = onboarding.features_for_goals(["web_console"])
    assert onboarding.resolve_apps(["web_console"], ui_features) == ["dsn_ui"]


def test_local_model_pulls_in_llamacpp_dependency():
    features = onboarding.resolve_features(["local_model"])
    assert features == ["local_llamacpp", "local_model"]

    plan = onboarding.build_plan(
        onboarding.OnboardingState(features=features), build_llama=False
    )
    repo_titles = [item.title for item in plan if item.kind == "repo"]
    assert any("llama.cpp" in title for title in repo_titles)


def test_build_plan_deduplicates_repos_and_respects_switches():
    state = onboarding.OnboardingState(
        features=["tts", "local_llamacpp", "local_model"],
        provider="local",
        model_resource="qwen25_3b",
        build_llama=False,
    )
    plan = onboarding.build_plan(
        state, clone_repos=False, install_packages=False, download_resources=False
    )
    kinds = [item.kind for item in plan]
    assert "repo" not in kinds
    assert "resource" not in kinds
    assert "pip" not in kinds
    assert kinds.count("env") == 1

    plan_all = onboarding.build_plan(state)
    repo_payloads = [item.payload["repo"] for item in plan_all if item.kind == "repo"]
    assert repo_payloads == ["llama_cpp", "gpt_sovits"]
    resources = [
        item.payload["resource"] for item in plan_all if item.kind == "resource"
    ]
    assert resources == ["qwen25_3b"]


def test_remote_provider_env_does_not_leak_into_other_features():
    state = onboarding.OnboardingState(
        features=["memory"], provider="remote", api_base="https://example.test/v1",
        api_key="sk-test", api_model="demo-model",
    )
    env = onboarding.provider_env(state)
    assert env["OPENAI_API_KEY"] == "sk-test"
    assert env["MAIN_MODEL_NAME"] == "demo-model"
    assert env["MAIN_MODEL_TYPE"] == "openai"
    assert "LLAMACPP_BIN" not in env


def test_update_env_preserves_comments_and_updates_in_place(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# 顶部注释\nFOO=1\nBAR=old\n# BAZ=commented\n",
        encoding="utf-8",
    )

    onboarding.update_env({"BAR": "new", "BAZ": "active"}, path=env_path)
    text = env_path.read_text(encoding="utf-8")

    assert "# 顶部注释" in text
    assert "FOO=1" in text
    assert "BAR=new" in text
    assert "BAR=old" not in text
    # 注释里的 BAZ 不应被改写；新增一个生效的 BAZ
    assert "# BAZ=commented" in text
    assert "\nBAZ=active" in text
    assert text.count("BAZ=") == 2


def test_mask_secret_never_returns_full_value():
    assert onboarding.mask_secret("") == "(未设置)"
    assert onboarding.mask_secret("short") == "***"
    masked = onboarding.mask_secret("sk-1234567890abcdef")
    assert masked != "sk-1234567890abcdef"
    assert "1234567890" not in masked


def test_plan_summary_mentions_features_and_download_size():
    state = onboarding.OnboardingState(
        goals=["local_models"],
        features=onboarding.resolve_features(["local_model"]),
        provider="local",
        model_resource="qwen25_3b",
    )
    items = onboarding.build_plan(state, clone_repos=False, build_llama=False)
    summary = onboarding.plan_summary(
        items, onboarding.resolve_features(state.features), state.goals
    )
    assert "本地" in summary
    assert "GB" in summary or "MB" in summary
    assert "DSN UI" in summary


def test_study_goal_also_writes_app_level_env():
    state = onboarding.OnboardingState(
        goals=["study"],
        features=onboarding.features_for_goals(["study"]),
        provider="remote",
        api_model="demo",
    )
    env_items = [
        item for item in onboarding.build_plan(state) if item.kind == "env"
    ]
    assert len(env_items) == 2
    assert any(
        item.payload.get("path", "").endswith("apps/dsn_study/.env")
        for item in env_items
    )


def test_launcher_default_application_is_dsn_ui(monkeypatch):
    import launcher

    monkeypatch.delenv("DSN_APP", raising=False)
    called: list[str] = []
    launcher.load_apps_config()
    monkeypatch.setattr(
        launcher, "resolve_entry", lambda name: lambda: called.append(name)
    )
    launcher.main([])
    assert called == ["dsn_ui"]
