import os
import sys
import math

# 尝试导入 Pillow 库
try:
    from PIL import Image, ImageDraw
except ImportError:
    print("❌ 缺少 Pillow 库，请先运行: pip install Pillow")
    sys.exit(1)

def create_app_icon():
    # 1. 确定保存路径
    # 根据您的项目结构: e:\桌面\blood_test\web_app\static
    base_dir = os.path.dirname(os.path.abspath(__file__))
    static_dir = os.path.join(base_dir, "web_app", "static")
    
    if not os.path.exists(static_dir):
        os.makedirs(static_dir)
        print(f"创建目录: {static_dir}")

    save_path = os.path.join(static_dir, "icon.png")

    # 2. 设置图标参数 (512x512 是 PWA 推荐的高清尺寸)
    size = 512
    bg_color = "#007bff"  # 蓝色，与您的 manifest.json 主题色一致
    icon_color = "white"

    # 3. 创建画布
    img = Image.new("RGB", (size, size), bg_color)
    draw = ImageDraw.Draw(img)

    # 4. 绘制心脏 (使用参数方程生成心形)
    # 公式: x = 16sin^3(t), y = 13cos(t) - 5cos(2t) - 2cos(3t) - cos(4t)
    heart_points = []
    scale = size / 35  # 缩放比例，适配 512x512 画布
    center_x = size / 2
    center_y = size / 2 + 20 # 稍微下移以视觉居中
    
    for i in range(0, 628): # 0 到 2pi (约6.28) * 100
        t = i / 100.0
        x = 16 * math.pow(math.sin(t), 3)
        y = 13 * math.cos(t) - 5 * math.cos(2*t) - 2 * math.cos(3*t) - math.cos(4*t)
        
        # 坐标变换 (Pillow 坐标系 Y 轴向下，需翻转 Y)
        px = center_x + x * scale
        py = center_y - y * scale 
        heart_points.append((px, py))

    heart_color = "#dc3545" # 鲜红色
    draw.polygon(heart_points, fill=heart_color)

    # 5. 绘制血管/监测线条 (白色心电折线)
    # 象征血管搏动和监测
    ecg_points = [
        (size * 0.2, size * 0.5),
        (size * 0.35, size * 0.5),
        (size * 0.42, size * 0.35), # 上波峰
        (size * 0.48, size * 0.65), # 下波谷
        (size * 0.55, size * 0.25), # 主波峰 (R波)
        (size * 0.62, size * 0.60), # 下波谷
        (size * 0.68, size * 0.5),
        (size * 0.8, size * 0.5)
    ]
    draw.line(ecg_points, fill="white", width=25, joint="curve")

    # 6. 保存文件
    img.save(save_path, "PNG")
    print(f"✅ 图标已成功生成: {save_path}")

if __name__ == "__main__":
    create_app_icon()