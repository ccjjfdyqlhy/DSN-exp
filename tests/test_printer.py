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

def main():
    """主函数：测试打印功能 — 打印 test_docs/1.pdf 的第一页"""
    import os

    doc_path = os.path.join(os.path.dirname(__file__), "test_memory.py")
    if not os.path.exists(doc_path):
        print(f"❌ 文档不存在: {doc_path}")
        return

    printers = conn.getPrinters()
    if not printers:
        print("❌ 未发现任何打印机")
        return

    printer_name = list(printers.keys())[1]
    print(f"使用打印机: {printer_name}")
    print(f"打印文档: {doc_path}")

    options = {"page-ranges": "1"}
    job_id = print_file(doc_path, printer_name=printer_name, options=options)
    if job_id:
        print(f"✅ 打印任务 {job_id} 已提交（仅第 1 页）")
    else:
        print("❌ 打印失败")


def print_file(file_path, printer_name='G3010_series', copies=1, options=None):
    """
    使用 CUPS 打印文件
    :param file_path: 要打印的文件路径（支持 PDF、JPG、PNG、TXT 等）
    :param printer_name: 打印机名称（默认使用 Canon_G3010_series）
    :param copies: 打印份数
    :param options: 其他打印选项字典，例如 {'media': 'A4', 'ColorModel': 'RGB'}
    """
    if options is None:
        options = {}
    # 如果指定了份数，添加到 options
    if copies > 1:
        options['copies'] = str(copies)
    try:
        job_id = conn.printFile(printer_name, file_path, "Python 打印任务", options)
        print(f"✅ 打印任务已提交！任务ID: {job_id}")
        return job_id
    except Exception as e:
        print(f"❌ 打印失败: {e}")
        return None


if __name__ == "__main__":
    main()