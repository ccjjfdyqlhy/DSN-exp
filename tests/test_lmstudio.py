
# tests/test_lmstudio.py
# PASSED v1_260326

"""
LMStudio连接测试脚本
"""
import requests
import json

def test_lmstudio_connection(base_url="http://localhost:4501", timeout=10):
    """测试LMStudio连接"""
    print(f"测试连接到: {base_url}")

    # 测试基本连接
    try:
        response = requests.get(f"{base_url}/v1/models", timeout=timeout)
        if response.status_code == 200:
            models = response.json()
            print("✓ 连接成功")
            print(f"可用模型: {models.get('data', [])}")
        else:
            print(f"✗ HTTP状态码: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("✗ 无法连接到LMStudio服务器")
        print("请确保:")
        print("1. LMStudio正在运行")
        print("2. 本地服务器已启动 (端口4501)")
        print("3. 模型已加载")
        return False
    except requests.exceptions.Timeout:
        print(f"✗ 连接超时 ({timeout}秒)")
        return False
    except Exception as e:
        print(f"✗ 连接错误: {e}")
        return False

    # 测试摘要生成
    print("\n测试摘要生成...")
    test_text = "用户: 你好\n助手: 你好！有什么可以帮助您的吗？"
    payload = {
        "model": "default",
        "messages": [{"role": "user", "content": f"请概括以下对话:\n{test_text}"}],
        "max_tokens": 50,
        "temperature": 0.3
    }

    try:
        response = requests.post(
            f"{base_url}/v1/chat/completions",
            json=payload,
            timeout=30
        )
        if response.status_code == 200:
            result = response.json()
            if "choices" in result and result["choices"]:
                summary = result["choices"][0]["message"]["content"]
                print("✓ 摘要生成成功")
                print(f"摘要: {summary}")
                return True
            else:
                print("✗ 响应格式异常")
                return False
        else:
            print(f"✗ 摘要请求失败: {response.status_code}")
            print(f"响应: {response.text}")
            return False
    except requests.exceptions.Timeout:
        print("✗ 摘要生成超时 (30秒)")
        return False
    except Exception as e:
        print(f"✗ 摘要生成错误: {e}")
        return False

if __name__ == "__main__":
    success = test_lmstudio_connection()
    if success:
        print("\n🎉 LMStudio连接正常，可以启用记忆功能")
    else:
        print("\n⚠️  LMStudio连接失败，建议在config.py中设置MEMORY_ENABLED=False")