# mmd-desktop-pet

把一个 **MMD / PMX 3D 模型**渲染成 Windows 桌面宠物：无边框、逐像素透明、置顶、
轻微摆身、可拖动。纯 Python（PySide6 + OpenGL），不依赖 MMD 本体。

代码是从一个真实项目里抽出来的，**踩过的坑全部写在注释和 [docs/PITFALLS.md](docs/PITFALLS.md) 里** ——
如果你也在 Windows 上用 Qt 做透明 OpenGL 窗口，这里大概率能省你几天。

## 它解决的具体问题

| 问题 | 这里怎么解 |
|---|---|
| PMX 2.0 解析 | `pmx.py`：纯标准库，**兼容一个非标准导出器**（17 字节头 / 权重块 +4 填充 / 骨骼 1 字节 flags） |
| 窗口逐像素透明 | `Qt.WA_TranslucentBackground` + `Qt.Tool` |
| `QOpenGLWidget` 渲染了但屏幕上没有 | **CPU 合成**：每帧 `grabFramebuffer()` → `QLabel` 贴图（Qt 在 Windows 上不合成 GL 子部件） |
| 模型被放大成极端特写 | `QMatrix4x4(*flatten())` 是**行主序**，喂转置矩阵 = 投影全错 |
| 高 DPI 下截图/定位全错 | 明确 DPR：`pixmap.setDevicePixelRatio()`；截图不要假设 1:1 |
| `glDrawElements` 报 `GL_INVALID_OPERATION` | 改用 `glDrawArrays`（先把索引展开成顶点数组） |
| shader 属性被优化掉导致不渲染 | 查询 `attributeLocation()`，`-1` 时跳过而不是判失败 |

## 快速开始

```bash
pip install PySide6 numpy

# 1. 放你的模型（自备，见下方版权说明）
#    assets/model.pmx  +  assets/tex/...（PMX 里引用的贴图）
#    或设置环境变量
set PET_MODEL=D:\models\your.pmx

# 2. 跑
python pet.py

# 3. 想先看静态效果（不用开窗口）
python preview.py 0        # 正面
python preview.py 180      # 背面
```

## 结构

```
pmx.py         PMX 2.0 解析器（零依赖）
pet.py         渲染 + 桌面窗口（PySide6 / OpenGL）
preview.py     离屏渲染到 PNG，便于调 UV / 相机
assets/        放你自己的模型（不进仓库）
docs/          踩坑记录
```

## 已知限制（诚实清单）

- **恒等蒙皮**：只渲染顶点自带姿势，没有骨骼动画（眨眼/挥手需要完整的骨骼+变形解析）。
  这个非标准导出器的骨骼段布局仍未攻克，`pmx.py` 会抛错并降级为空骨骼列表。
- **球面贴图（spa）未启用**：金属/头发高光缺失，金饰是平面黄。
- **toon 渐变纹理未采样**：用统一的二段式近似。
- **材质 diffuse/ambient 只用了 alpha 通道**，rgb 未乘。

想继续做的话，这几条就是路线图。

## 版权 / 许可

- **代码**：MIT（见 LICENSE）
- **模型不是代码**：本仓库**不包含任何模型或贴图**。MMD 模型通常有严格条款
  （禁止二次配布、禁止商用、角色版权归原厂）。请自备并遵守原作者许可。
  `assets/README.md` 里有说明。

## 致谢

格式细节来自 PMX 公开规范；踩坑过程记录在 `docs/PITFALLS.md`。
