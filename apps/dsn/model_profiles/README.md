# 生效中的模型描述目录

`apps/dsn_ui` 启动时扫描本目录下的 `*.yaml`，逐个注册成模型。

| 文件 | 模型 | 来源 |
|---|---|---|
| `deepseek_ocr.yaml` | deepseek-ocr | LM Studio / 远程 |
| `glm_4_6v.yaml` | glm-4.6v | 远程 API |
| `google_gemma_3_4b.yaml` | google/gemma-3-4b | LM Studio / 远程 |
| `llama_3_2_1b_instruct.yaml` | llama-3.2-1b-instruct | LM Studio / 远程 |
| `text_embedding_nomic.yaml` | text-embedding-nomic-embed-text-v1.5@f16 | 嵌入模型 |

**本地 GGUF 模型请不要直接写在这里**，除非路径在本机确实存在 ——
写死的绝对路径会让别人的 clone 里出现一堆"看起来可用、实际加载必失败"的模型。

## 加一个自己的本地模型

模板在 `../model_profiles.example/`，照抄改路径即可：

```bash
cp apps/dsn/model_profiles.example/llama_cpp_local.yaml apps/dsn/model_profiles/
# 编辑 model_path / binary_path
# 重启 dsn_ui
```

或者用图形界面：Web 控制台 →「接入新实例」→ 扫描本地 GGUF → 自动写 profile。

## 检查路径是否有效

```bash
python3 installer.py --doctor
```

会列出所有指向不存在文件的 profile。
