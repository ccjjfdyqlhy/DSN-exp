import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from PIL import Image

# 加载模型（首次运行会自动下载）
model_id = "vikhyatk/moondream2"
revision = "2025-01-09"  # 指定版本

model = AutoModelForCausalLM.from_pretrained(
    model_id,
    revision=revision,
    trust_remote_code=True,
    device_map="auto",  # 自动选择设备（CPU/GPU/MPS）
    torch_dtype=torch.float16  # 如果GPU支持，使用半精度节省显存
)

# 加载图像
image = Image.open("path/to/image.jpg")

# 生成描述
caption = model.caption(image)["caption"]
print("描述:", caption)

# 提问
answer = model.query(image, "这张图片里有什么？")["answer"]
print("回答:", answer)