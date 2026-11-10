
# 勘察报告：设备 · 项目状态 · 生态环境

> 写作时间：2026-10-28 ｜ **复核时间：2026-11-06**
> 方法：静态阅读 `/proc`、`/sys`、仓库源码与 `~/Bonsai-demo`、`~/llama.cpp` 目录；
> 2026-10-28 初稿时**无命令执行工具**，故当时标注的「待复核」项已于 2026-11-06 全部实测结案，
> 结果见下文各节的「实测」标记；**初稿中被推翻的结论已就地改写**。
> 依据仓库约定：只写经过核实的事实，不确定的标注「未验证」。

---

## 一、设备

| 项 | 值 | 来源 |
|---|---|---|
| CPU | Intel Core i5-12400F（6 核 12 线程，3.2GHz 基础频率，无核显） | `/proc/cpuinfo:5` |
| 内存 | **54.8 GiB** 总量（= 57.4 GB），可用 46.4 GiB，缓存 39.2 GiB | `/proc/meminfo` |
| Swap | 7.6 GiB（`/dev/sdc7`），几乎未使用 | `/proc/swaps` |
| GPU × 2 | NVIDIA GeForce RTX 2080 Ti，Turing，驱动 580.196.07，**单卡 11264 MiB** | `nvidia-smi` |
| 显卡互连 | 无 NVLink（Pcie 总线，DMA 47bit） | 同上 `:8` |
| 计算能力 | `compute_cap = 7.5`（sm_75）；torch `arch_list` 含 `sm_75` | `nvidia-smi --query-gpu=compute_cap` |
| 操作系统 | **Ubuntu 22.04.5 LTS** / kernel 6.8.0-138-generic / x86_64 | `/etc/os-release` |
| 磁盘 | `/` 46G（**剩 7.8G，82%**）｜`/home` 616G（**剩 217G，63%**）｜`~/.cache` 已占 29G | `df -h` / `du` |

### 1.1 由硬件推出的三条硬约束

这三条决定了后面所有设计取舍：

1. **sm_75（Turing）没有原生 bf16** → 训练只能用 fp16 + GradScaler 或 fp32；
   PyTorch 官方 wheel 在 cu121 之后对 sm_75 的支持逐步收紧，**当时建议训练环境锁 cu121 / torch 2.3-2.4**。
   > **2026-11-06 实测修正**：torch **2.8.0+cu128** 在本机 2 张 2080Ti 上正常工作（cc 7.5），
   > 而 transformers 5.x **硬性要求 torch ≥ 2.6**（torch 2.3.1 会让 transformers 直接禁用 PyTorch）。
   > → **最终版本锚：torch 2.8.0+cu128 + transformers 5.20.2**。
   > **实测（2026-11）**：torch 2.8 的 bf16 在 sm_75 上**能跑**（软件模拟，非原生指令）。
   > 所以这是**性能问题不是正确性问题**——体检脚本应标成「可用但慢、显存翻倍」，
   > 不要写成「不可用」，否则用户看到能跑会困惑。计划二 §3.2 的 `bf16=False` 建议保留。
2. **没有 FlashAttention-2**（FA2 要求 sm_80+）→ 只能用 `sdpa` 或 xformers；
   8k 以上的长上下文训练成本会显著上升。
   > **实测（2026-11，已确认）**：强制 FLASH backend 直接报错
   > `RuntimeError: No available kernel. Aborting execution.`
   > （PyTorch 同时打印 `Flash attention only supports gpu architectures in the range [sm80, sm120]`）；
   > 可用的是 `EFFICIENT_ATTENTION` 与 `MATH`。
   > **这是硬结论：任何声称在本机跑 FA2 的方案都要否掉。**
3. **单卡 11GB 显存 × 2 = 22GB，且卡间走 PCIe** → 27B 级别模型的 4-bit 权重（约 15-16GB）
   勉强塞进双卡，跨卡分层会因 PCIe 带宽掉速；**微调迭代应该先在 4B/8B 档验证，再上 27B**。

---

## 二、Python 生态

| 环境 | 解释器 | 用途 | 备注 |
|---|---|---|---|
| `/home/darkstar/anaconda3` | Python 3.12.2 | **DSN-exp 运行时** | `requirements.txt` 20 个依赖，**不含 torch**；但**环境里已装** torch / transformers / accelerate（见 §2.2） |
| `.../envs/comfyui` | Python 3.10 | ComfyUI | `conda-meta` 只有基础包 → Python 包由 pip 安装 |
| `.../envs/vllm` | Python 3.12 | vLLM 相关 | 同上，pip 安装 |
| `.../envs/GPTSoVits` / `IndexTTS` / `obsidian-rag` | — | 语音/检索 | — |
| `/home/darkstar/Bonsai-demo/.venv` | Python 3.11 | Bonsai 官方 demo | 自带 `uv.lock` |
| `/home/darkstar/.unsloth/studio` | — | 曾用过 unsloth | 需查对应解释器 |

### 2.1 复核命令（已于 2026-11 执行，结果见 §2.2）

```bash
# DSN 运行时环境里到底有没有训练栈
python -c "import torch;print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_capability(0))"
pip list | grep -Ei "torch|transformers|peft|trl|unsloth|bitsandbytes|accelerate|datasets|gguf"

# 各 conda 环境各有一份什么
for e in comfyui vllm GPTSoVits; do
  ~/anaconda3/envs/$e/bin/pip list 2>/dev/null | grep -Ei "torch|transformers|peft|unsloth|bitsandbytes"
done

# Bonsai 自带二进制是否支持 LoRA 挂载（本计划的关键前置条件）
~/Bonsai-demo/bin/cuda/llama-server --help 2>&1 | grep -iE "lora|adapter"
```

### 2.2 实测结果（2026-11-06，原「没有训练栈」的结论已作废）

在 `/home/darkstar/anaconda3`（base，即 DSN 运行时）里直接跑：

```
torch: 2.8.0.dev20250327+cu128   cuda: 12.8   avail: True
arch_list: ['sm_75', 'sm_80', 'sm_86', 'sm_90', 'sm_100', 'sm_120', 'compute_120']
device0: NVIDIA GeForce RTX 2080 Ti   cap: (7, 5)
FP16 matmul OK   BF16 matmul OK   SDPA OK
transformers 4.57.6   accelerate 1.12.0
peft / trl / bitsandbytes / datasets / unsloth: MISSING
```

**修正后的结论**：

1. base 环境**已经有**一个可用的 CUDA 训练栈（torch + transformers + accelerate），只是版本很新且是 **dev 版 + cu128**；
2. 但 `peft / trl / bitsandbytes` 全缺，而这三个正是 LoRA/QLoRA 的必需件；
3. **仍然要建独立 conda 环境**，但理由从「base 没有训练栈」改成：
   - base 里是 **cu128 + torch 2.8.0.dev**（nightly），不适合当训练栈的版本锚；训练环境最终锁 **torch 2.8.0+cu128（正式版）+ transformers 5.20.2**（2026-11-06 实测可用）；
   - `requirements.txt` 声明的运行时依赖里**没有 torch**——训练依赖一旦装进 base，就会让 DSN 主进程多出 GB 级依赖与 CUDA 上下文污染；
   - 仓库既有不变量：**`apps/ infra/ harness/` 里零 `import torch`**，
     只有 [apps/dsn/models/asr_engine.py:92](../../apps/dsn/models/asr_engine.py#L92) 用 `sys.modules.get("torch")` 做「可能已被导入」的防御性检查。
     **这条不变量必须在引入训练栈后依然成立**（见计划二 §3.2 的 `environment()` 体检）。

---

## 三、DSN-exp 项目状态

### 3.1 仓库概览

- **提交**：HEAD = `8d7ccc1 feat(study,orchestrator): Obsidian MCP & JEV`；工作区有未提交改动（`docs/README.md` 增加了扩展计划组索引）。
- **规模**（2026-11 复核）：`apps/` **7 个应用** · `harness/` **14 个子模块** · `infra/` **14 个子模块** · `tests/` **90 个** `test_*.py`（`tests/` 下共 102 个 `.py`）。
  `apps/dsn` 约 **58.3k 行**；`apps/coding_agent` **229 行**。
- **分层**：`apps/ → harness/ → infra/`，箭头只向下（`docs/architecture.md:11-28`）。
  > **复核修正**：`infra/observability/core.py:12` 与 `infra/cache.py:10` 的两处 `infra → harness` 逆向依赖
  > **已于 2026-10 斩断**（`docs/technical-debt.md:320` 自标 `✅ 已斩断`，两处代码里也有「修复说明（2026-10 分层）」注释）。
  > `docs/architecture.md:38-43` 的「当前存在的两处违规」是同一份过期信息，待同步修订。
- **Web 形态**：`apps/dsn_ui` 是 **FastAPI**（`server.py:568 def create_app`；`:789` 是其内部的 `app = FastAPI(...)`），
  功能模块统一用 `register_xxx_routes(app, engine)` 模式挂载
  （`integration_api.py:367`、`system1_api.py:125`、`asr_api.py:32`、`onboarding_api.py:678`、`agent_runtime_api.py:222`）。
- **前端**：`apps/dsn_ui/frontend/` 是 **SvelteKit** 工程（`package.json` 的 `name` 为 `llama-ui`，
  `svelte-kit sync` + vitest + playwright + storybook），vite 只是其底层打包器——不是「一个 vite 工程」。

### 3.2 应用清单

| 应用 | 定位 | 与本计划的关系 |
|---|---|---|
| `dsn_ui` | Web 控制台，**默认入口** | Bonsai 已接入；微调 API 的落点 |
| `dsn` | 语音陪伴，规模最大（58k 行），拆 9 个 bundle | 情绪/世界/人格的重资产所在 |
| `dsn_study` | 学习助手，装配范式最规范 | 参考范式 |
| `coding_agent` | 186 行最小范例 | 参考范式 |
| `emotion_exp` | 情绪状态机实验 | **情绪实现之一（重复）** |
| `densechat` / `text_agent` | WebUI 复刻 / 占位 | — |

### 3.3 Bonsai 集成现状（已存在的资产）

`apps/dsn_ui/bonsai_integration.py` 已经把 Bonsai 接成了可调度模型：

| 项 | 现状 |
|---|---|
| 二进制 | `~/Bonsai-demo/bin/cuda/llama-server`（PrismML fork，ggml 0.21.0），自动注入 `LD_LIBRARY_PATH`（`:206`） |
| 权重 | `Ternary-Bonsai-2-27B-PQ2_0.gguf` **7.2 GB** + `Ternary-Bonsai-2-27B-mmproj-Q8_0.gguf` **629 MB** |
| 注册名 | `bonsai:bonsai2:27B`，优先级 60，走 `llama_cpp` 引擎（`logs/dsn_ui.log:33-36`） |
| 已支持参数 | `mmproj_path` / `mmproj_no_offload` / `image_max_tokens` / `no_kv_offload` / `tensor_split` / `flash_attn`（`infra/orchestrator/llamacpp.py:31-151`） |
| 视觉链路 | `server.py:199` 与 `:926` 已修过「带 mmproj 的模型被误判纯文本」的 bug |

**这套集成是后面一切工作的地基**：它证明了「DSN 能托管一个本地多模态大模型并做显存调度」这条路是通的。

### 3.3.1 同机还有第二个本地大模型：JEV-27B-VL（三份计划此前完全漏掉）

`~/qwen_weights/JEV-27B-VL/` 里的 **JEV-27B-VL** 是本机**更新的、也更重**的本地模型，
而且**已经接入 DSN**：`apps/dsn_ui/jev_integration.py`、`apps/dsn_ui/system1_api.py` 的 System-1 决策接口、
`apps/dsn_ui/engine.py:353-365` 自动注册。**HEAD commit `8d7ccc1` 的主角就是它**——
三份计划稿只写了 Bonsai，等于漏掉了当前最强的本地资产。

| 项 | 事实（实测） |
|---|---|
| 权重 | `JEV-27B-VL.Q4_K_M.gguf` **16.5 GB** + `JEV-27B-VL.mmproj-bf16.gguf` 931 MB |
| GGUF 元数据 | `general.architecture = qwen35`、`basename = JEV`、`finetune = VL`、`size_label = 27B`、`file_type = 15 (Q4_K_M)` |
| 与 Bonsai 的关系 | **两者架构同为 `qwen35`** → 它们是同一个 **`Qwen3.8-27B` 底座**的两种微调产物（实测两者 GGUF 的 `general.base_model.0.name = "Qwen3.8 27B"`，仓库 `Qwen/Qwen3.8-27B`） |
| 量化 | **标准 Q4_K_M**（不是 PQ2_0 那种越过 `GGML_TYPE_COUNT` 的私有类型）→ 上游 llama.cpp 可直接加载，`--lora` 路径对它成立 |
| 二进制 | 用**系统** `~/llama.cpp/build/bin/llama-server`，**不用** Bonsai fork |
| 显存 | 加载后**独占双卡**（约 10.5G / 9.7G）；`--n-gpu-layers` 必须 **99** |
| 速度（实测） | `-ngl 47 → 4.14 tok/s`；`-ngl 64 → 20.49`；`-ngl 99 → 29.14`（对比 Bonsai PQ2_0 的 46.26，差距来自权重体积） |

**两个必须记住的结论**：

1. **JEV 加载后占满双卡** → 「推理与训练可并行」在 JEV 在场时**不成立**（编排见计划二 §3.6）。
   > **2026-11-06 晚：这条事实最终决定了移除它** —— 16.5 GB 占满双卡，与「学生常驻 + 训练并行」互斥，
   > JEV 已从计划二/三整体移出（计划三 §10.4）。本节保留它的**事实**，不再保留它的**角色**。
2. **JEV 与 Bonsai 都不可作为被训练对象**（详见 §4.2）；2026-11-06 复测后，**底座 `Qwen3.8-27B` 在 transformers 5.20.2 下架构上可训**——但训它产不出 Bonsai/JEV 的能力，本项目不训它。

### 3.4 能力缺口

| 能力 | 状态 | 证据 |
|---|---|---|
| LoRA / 微调 / 训练 | **完全没有** | 全仓 grep `lora/finetune/train` 仅命中无关文本与 `apps/dsn_study/FEATURE_GAP.md` 的"微调"一词 |
| 模型训练产物管理 | 没有 | 无 adapter registry / promotion 状态机 |
| 情绪系统 | **三份实现并存** | `apps/emotion_exp/emotion_engine.py:44`、`apps/dsn_ui/emotion.py:50`（几乎是逐行复制）、`harness/personality/dynamics_engine.py:49`（冲量-回归 + 亲密度饱和） |
| 情绪→行为因果 | 只有文本注入 | `emotion.py:96 perception_prompt()` 只是把数值拼成 prompt |
| 生存/自主驱动 | 没有 | 无 drive / homeostasis 概念 |
| 自我改进 | 只有"每天推 PR 的机器人" | `apps/dsn/subapps/self_evolution/entry.py:22` |
| 世界模拟 | 已有 | `apps/dsn/world/engine.py:31`（WorldEngine v4：天时/天气/房间/命运骰子），`worlds/default.yaml` = "数字工作室"（EXA 住在用户电脑上） |

### 3.5 llama.cpp 侧已有的微调相关二进制

`~/llama.cpp/build/bin/`（ggml 0.22.0，主线）与 `~/Bonsai-demo/bin/cuda/`（fork，0.21.0）**都**包含：

- `llama-finetune`（实验性，**只支持 llama 架构**）
- `llama-export-lora`（导出 LoRA 适配器）
- `llama-quantize` / `llama-imatrix` / `llama-gguf-split`
- Python 侧：`~/llama.cpp/convert_lora_to_gguf.py`（HF PEFT → GGUF 适配器）、`convert_hf_to_gguf.py`

**注意**：这些是"主线 llama.cpp 的能力"，Bonsai fork 里的同名二进制**同样存在但语义不同**
（fork 有自己的 `PQ2_0` 类型与旋转基），不能混用。

---

## 四、关键约束：Bonsai-2 的权重形态决定了「不能直接微调它」

`~/Bonsai-demo/MODEL-FORMATS.md` 是决定性材料：

| band | bits/weight | 体积 | 位置 |
|---|---|---|---|
| `PTQ1_0` | 1.75 | 5.9 GB | `prism-ml/Ternary-Bonsai-2-27B-gguf` |
| `PQ2_0` | 2.13 | 7.2 GB | 同上（**当前使用的就是这个**） |
| `Q2_0` (group-64) | 2.25 | 7.6 GB | `...-gguf-dev`，仅测试用 |

原文关键句（`MODEL-FORMATS.md:43`）：

> All three store their weights in a **rotated basis** and need the **activation transform that only this
> demo's binaries carry** … There is no "works everywhere" option.

并且：

- `PQ2_0` / `PTQ1_0` 的 ggml type id 越过上游 `GGML_TYPE_COUNT`，**上游 llama.cpp 直接拒绝加载**（`:47`）；
- group-64 的 `Q2_0` 上游会**加载成功但输出乱码**（`:49-50`）；
- HF 上的发布物只有 **GGUF 与 MLX** 两种（`README.md:124-161`），**没有 safetensors/F16 权重**。

### 4.1 由此推出的四条结论

1. **没有 F16 起点** → 标准 LoRA/QLoRA（peft/unsloth）无法作用于 Bonsai-2。
2. **旋转基 + 私有激活变换** → 即便拿到适配器，上游 `llama-server --lora` 的张量名也对不上。
3. **自定义量化类型** → 重新量化必须用 PrismML fork 的 `llama-quantize`。
4. **结论**：*「给 GGUF 做微调」这件事必须做成通用的、与具体模型无关的底层设施*，
   而 **Bonsai-27B 在其中扮演的角色不是「被微调的对象」，而是「教师 / 执行器 / 评判者」**。
   **JEV-27B-VL 同理**（见 §4.2）。

### 4.2 复核补充：JEV 也不能被微调，**底座架构可训但不做**（2026-11-06 复测）

| 问题 | 实测结论 |
|---|---|
| 上游工具能读 Bonsai 的 PQ2_0 吗？ | **不能**。用上游 `~/llama.cpp/gguf-py` 读 `Ternary-Bonsai-2-27B-PQ2_0.gguf` 直接抛 `ValueError: 142 is not a valid GGMLQuantizationType`（142 正是越过 `GGML_TYPE_COUNT` 的私有 type id）。**这同时说明计划二 §3.5 的「复用 `~/llama.cpp/gguf-py` 读元数据」对 Bonsai 权重不可用**，需改用 PrismML fork 的版本或容错解析。 |
| JEV 能被微调吗？ | **不能直接微调这个 GGUF**：JEV = 底座 + **VL 视觉塔** + **System-1 决策头**，后两者是自定义权重，不是 LoRA 能表达的。 |
| 那能微调什么？ | **架构上能训底座，但本项目不训**（2026-11-06 复测）。JEV 与 Bonsai 的架构都是 `qwen35`，它们是同一个 **`Qwen3.8-27B`** 底座的微调产物；该底座在 HF 上的 `model_type` 是 **`qwen3_5`**，transformers **5.20.2 有对应模块**（见下一行）→ 架构上可训。但训出来的只是一个「没有 JEV 特殊能力、也不是 Bonsai」的模型，且 27B 在 22 GB 上训练代价过高 → **本项目只走 `qwen3` 学生线**。 |
| transformers 支持 `qwen35` 吗？ | base 环境的 `transformers 4.57.6` **不支持**（只有 qwen2 / qwen3 / qwen3_next / qwen3_vl / qwen3_moe / qwen3_omni_moe / qwen3_vl_moe）；但 **dsn-train 环境的 `transformers 5.20.2` 支持**——`models/` 下有 `qwen3_5` / `qwen3_5_moe` / `qwen4_exp`，`Qwen3_5ForCausalLM` 可用，AutoConfig 能加载 `Qwen/Qwen3.5-4B` 与 `Qwen/Qwen3.8-27B`（HF 侧叫 `qwen3_5`，llama.cpp 侧叫 `qwen35`，是同一个东西）。→ **M0.2 结论：底座架构可训，但本项目不训它**（产物无 Bonsai/JEV 能力，且与学生路线重复）。 |
| 本地还有能训的现成模型吗？ | 原本**没有**。全机扫描：本地只有 `JEV-27B-VL.Q4_K_M.gguf`（16.5 G）与 `DeepSeek-OCR-Q8_0.gguf`（3.1 G），**没有任何 4B/8B GGUF**；`~/.cache/huggingface` 仅 290 MB（whisper + laya）→ 学生模型必须**联网下载 HF 格式权重**。**2026-11-06 已完成**：`Qwen/Qwen3-4B` 已下载到 `/home/darkstar/qwen_weights/HF/Qwen3-4B`（7.6 G，3 个 safetensors 分片），走 `HF_ENDPOINT=https://hf-mirror.com`（本机 huggingface.co 的 DNS 被污染，直连 https 返回 000）。 |

> 这一条是三份文档里最重要的分叉点，见
> [02-gguf-finetune-extension.md](02-gguf-finetune-extension.md) §0（教师/学生分工）与 §6.1.1（学生模型选型），
> 以及 [03-existence-app.md](03-existence-app.md) §1.1（生存欲的两层拆分）与 §10（四层分工）。

---

## 五、勘察结论摘要

| 结论 | 影响 |
|---|---|
| 设备：6C/12T + **54.8 GiB** RAM + 2×11GB 2080Ti（sm_75） | 训练栈必须 fp16、禁 FA2、禁 bf16；27B 训练要跨卡，慢 |
| 磁盘：`/` 剩 7.8G（82%），`/home` 剩 217G | 模型/数据集/产物一律放 `/home`；`HF_HOME` 不要落在 `/` |
| base 环境**已有** torch 2.8.0.dev+cu128 / transformers 4.57.6 | 仍需独立 `dsn-train` 环境（理由是版本锚定与不污染 base，不是「没有训练栈」） |
| **FA2 在 sm_75 上实测直接报错** | 任何声称本机跑 FA2 的方案都要否掉；只能用 mem_efficient / math |
| Bonsai 集成已就绪（含视觉、显存调度、私有 .so 注入） | 微调产物可以直接复用同一条注册路径 |
| ~~**JEV-27B-VL 已就绪且更重（16.5G，独占双卡）**~~ | **已移出计划**（它一加载，学生与训练都无处安放）。现在卡上只住**学生 8B**（GPU 0）+ 训练作业（GPU 1），训练与推理**可以并行** |
| 全仓零微调能力 | 需要从 infra 层新建子系统，而非改现有模块 |
| 情绪有三份重复实现，且情绪不影响行为 | 新应用前先做一次情绪层收敛 |
| Bonsai-2 无 F16 权重、旋转基、私有量化 | Bonsai 不可被常规微调 → 走「蒸馏 + 推理期适应」路线 |
| **JEV 与 Bonsai 同为 `qwen3_5`（`qwen35`）底座的微调产物；transformers 4.57.6 不认它，5.20.2 认** | 底座架构在 5.x 下可训，但本项目只走 `qwen3` 学生线（M0.2 结论） |
| **本地原本没有任何 4B/8B 可训模型，HF 缓存仅 290 MB** | 学生模型必须联网下载 HF 权重（8B ≈ 16 GB）——**M0.1 已完成：`Qwen/Qwen3-4B` 落盘 `/home/darkstar/qwen_weights/HF/`** |
| `self_evolution` 只是 PR 机器人 | 「递归自我改进」需要全新设计，不是改它 |

---

## 六、下一步

1. [02-gguf-finetune-extension.md](02-gguf-finetune-extension.md) —— 底层扩展：可插拔训练后端、训练作业状态机、GPU 独占、适配器晋级与热切换。
2. [03-existence-app.md](03-existence-app.md) —— 上层应用：以生存欲与情感为首要目标的递归自我改进 DSN。

## 七、2026-11-06 复核后仍待办的事（按优先级）

| # | 待办 | 为什么现在做 |
|---|---|---|
| 1 | ~~确认 `qwen35` 架构的可训练性~~ → **已结论：transformers 5.20.2 支持 `qwen3_5`**，但本项目不训底座（产物不是 Bonsai/JEV）。学生固定为 `qwen3` 家族 | 已闭合，2026-11-06 复测 |
| 2 | ~~确认学生模型权重下载可行~~ → **已完成**：`Qwen/Qwen3-4B`（7.6 G）落盘 `/home/darkstar/qwen_weights/HF/Qwen3-4B`（走 hf-mirror） | 已闭合，2026-11-06 |
| 3 | 修 [docs/architecture.md:38-43](../../docs/architecture.md#L38-L43) 的过期「两处违规」 | 与本文件 §3.1 的复核结论冲突，两个文档不能各说各话 |
| 4 | 修计划二 §3.5 的 `gguf-py` 读元数据路径（对 PQ2_0 会抛异常） | 见 §4.2 第一行 |
| 5 | ~~把「JEV 独占双卡」写进计划二的 GPU 编排~~ → **已被更强的事实取代**：JEV 整体移出计划，改成「学生常驻 GPU 0、训练走 GPU 1」（计划三 §10.4） |
