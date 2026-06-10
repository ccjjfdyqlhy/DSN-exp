#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI模型API费用计算器
- 根据用户选择的模型、输入/输出Token数计算费用
- 输出：美元、人民币（汇率7.2）、T单位（1 T = 最贵模型单Token价格的百万分之一 = 1.8e-10 USD）
- 辅助输出：pT单位（1 pT = 1000 T）
"""

# 模型数据库：名称、输入价格(USD/1M tokens)、输出价格(USD/1M tokens)
MODELS = [
    ("DeepSeek-V4-Flash", 0.0027778, 0.27778),
    ("MiMo-V2.5-Pro", 0.0034722, 0.83333),
    ("Qwen-Plus", 0.11111, 0.66667),
    ("GPT-4.1 nano", 0.10, 0.40),
    ("DeepSeek-V3", 0.27778, 1.1111),
    ("Gemini 2.5 Flash-Lite", 0.10, 0.40),
    ("Qwen-Long", 0.069444, 0.27778),
    ("GPT-4.1 mini", 0.40, 1.60),
    ("GPT-4.1", 2.00, 8.00),
    ("Claude Sonnet 4", 3.00, 15.00),
    ("o3-mini", 1.10, 4.40),
    ("DeepSeek-V4-Pro", 0.41667, 0.83333),
    ("MiMo-V2.5", 0.13889, 0.27778),
    ("Gemini 2.5 Pro", 1.25, 10.00),
    ("GPT-4o", 2.50, 10.00),
    ("Claude Opus 4.6", 5.00, 25.00),
    ("GPT-5.5 (标准版)", 8.00, 24.00),
    ("GPT-5.5", 5.00, 30.00),
    ("Qwen3.7-Max", 1.6667, 5.00),
    ("GPT-5.4 Pro", 30.00, 180.00),
    ("Claude Opus 4 (旧版)", 15.00, 75.00),
    ("GPT-5.5 Pro", 30.00, 180.00),
    ("Claude Opus 4.8 (Fast)", 10.00, 50.00),
]

# 常数定义
USD_TO_CNY = 7.2                # 美元兑人民币汇率
T_PER_USD = 1 / 1.8e-10         # 1美元 = 5.555...e9 T (因为1 T = 1.8e-10 USD)
PT_PER_T = 0.001                # 1 pT = 1000 T → 1 T = 0.001 pT

def calculate_cost(model_idx, input_tokens, output_tokens):
    """计算总费用并返回各项数值"""
    name, price_in, price_out = MODELS[model_idx]
    # 总费用（美元）= (输入Token/1e6)*输入单价 + (输出Token/1e6)*输出单价
    total_usd = (input_tokens / 1_000_000) * price_in + (output_tokens / 1_000_000) * price_out
    total_cny = total_usd * USD_TO_CNY
    total_T = total_usd * T_PER_USD          # T数
    total_pT = total_T * PT_PER_T            # pT数
    return {
        "model": name,
        "input_price": price_in,
        "output_price": price_out,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_usd": total_usd,
        "total_cny": total_cny,
        "total_T": total_T,
        "total_pT": total_pT
    }

def main():
    print("=" * 60)
    print("AI 模型 API 费用计算器 (基于 2026-05 价格)")
    print("=" * 60)
    print("\n可选模型列表：")
    for i, (name, _, _) in enumerate(MODELS):
        print(f"{i+1:2d}. {name}")
    print("0. 退出程序")

    while True:
        try:
            choice = input("\n请选择模型序号 (0-{}): ".format(len(MODELS)))
            if choice == '0':
                print("感谢使用，再见！")
                break
            idx = int(choice) - 1
            if idx < 0 or idx >= len(MODELS):
                print("序号错误，请重新输入。")
                continue

            # 输入Token数
            input_tokens = int(input("请输入输入Token数 (整数): "))
            output_tokens = int(input("请输入输出Token数 (整数): "))
            if input_tokens < 0 or output_tokens < 0:
                print("Token数不能为负数！")
                continue

            # 计算
            res = calculate_cost(idx, input_tokens, output_tokens)

            # 输出结果
            print("\n" + "-" * 50)
            print(f"模型：{res['model']}")
            print(f"输入价格：{res['input_price']:.6f} USD/百万Token")
            print(f"输出价格：{res['output_price']:.6f} USD/百万Token")
            print(f"输入Token数：{res['input_tokens']:,}")
            print(f"输出Token数：{res['output_tokens']:,}")
            print(f"\n💰 总费用：")
            print(f"  美元：${res['total_usd']:.6f}")
            print(f"  人民币：¥{res['total_cny']:.6f}")
            print(f"  T单位：{res['total_T']:.2f} T")
            print(f"  pT单位：{res['total_pT']:.2f} pT   (1 pT = 1000 T)")
            print("-" * 50)

        except ValueError:
            print("输入无效，请输入数字。")
        except KeyboardInterrupt:
            print("\n\n程序已中断。")
            break

if __name__ == "__main__":
    main()