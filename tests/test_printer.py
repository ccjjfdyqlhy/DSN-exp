import cups

# 连接到CUPS服务器
conn = cups.Connection()

# 获取所有打印机
printers = conn.getPrinters()

# 打印出打印机名称和状态
for name, info in printers.items():
    print(f"打印机名称: {name}")
    print(f"  状态: {info['printer-state']}")  # 3: 空闲, 4: 打印中, 5: 停止
    print(f"  描述: {info.get('printer-info', 'N/A')}")

import subprocess
import re

def get_scanner_device():
    """自动获取第一个可用的扫描仪设备名称"""
    try:
        result = subprocess.run(['scanimage', '-L'], capture_output=True, text=True, check=True)
        output = result.stdout
        # 匹配形如 device `genesys:libusb:...' 或 `airscan:...' 的设备名
        match = re.search(r"device `([^']+)'", output)
        if match:
            return match.group(1)
        else:
            raise RuntimeError("未找到任何扫描仪，请检查连接")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"执行 scanimage -L 失败: {e}")

def scan_to_file(device_name, output_file='scan.png', resolution=300, mode='Color', format='png'):
    """
    执行扫描并保存为文件
    :param device_name: 扫描仪设备名（由 get_scanner_device 返回）
    :param output_file: 输出文件路径
    :param resolution: 扫描分辨率（DPI），建议值 100, 200, 300, 600
    :param mode: 扫描模式，可选 'Color', 'Gray', 'Lineart'
    :param format: 输出格式，常用 'png', 'jpeg', 'tiff'
    """
    # 构建命令（使用 shell=True 以便重定向输出到文件）
    cmd = (
        f"scanimage --device-name '{device_name}' "
        f"--resolution {resolution} --mode {mode} --format {format} "
        f"> '{output_file}'"
    )
    try:
        subprocess.run(cmd, shell=True, check=True)
        print(f"✅ 扫描成功！文件已保存为: {output_file} (分辨率: {resolution} DPI)")
    except subprocess.CalledProcessError as e:
        print(f"❌ 扫描失败: {e}")

# ===== 使用示例 =====
if __name__ == "__main__":
    try:
        # 1. 自动获取扫描仪
        scanner = get_scanner_device()
        print(f"📠 使用扫描仪: {scanner}")

        # 2. 以 600 DPI 扫描（这是 G3010 的光学极限）
        scan_to_file(scanner, '/home/darkstar/Desktop/scan.png')

        # 也可以尝试 300 DPI（更快的速度、更小的文件）
        # scan_to_file(scanner, 'scan_300dpi.png', resolution=300)
    except Exception as e:
        print(f"❌ 发生错误: {e}")