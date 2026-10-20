# 踩坑记录（Windows / Qt / OpenGL / PMX）

每一条都是实际卡住过的问题，附带「怎么发现的」和「最终解」。
如果你在这套技术栈上做东西，这份清单能省你不少时间。

---

## 1. PMX 头是 17 字节，不是 20

```
'PMX ' (4) + version float (4) + 设置字节数 (1) + 设置 (8) = 17
```

按 20 读设置的后果：读到的是**模型名字节**，于是索引尺寸变成
`0/97/0/111`（97='a'，111='o'），后面所有解析全是垃圾。

**怎么发现的**：hexdump 前 64 字节，看到 `Y.a.o.y.a.o` 正好落在我以为的设置区。

---

## 2. 权重块后面多 4 字节填充

顶点布局（标准）：

```
pos(12) normal(12) uv(8) [附加UV] weightType(1) weights...
```

这个导出器在**每个权重块后面多写 4 字节**（一个 1.0 的 float 填充）。
不跳过它，第二个顶点的 weightType 就读到 140（非法值）。

**怎么发现的**：解不出来时不要硬猜——用**锚点反解**：
贴图段的字符串在文件里的位置可以搜到（UTF-16 的 `tex\颜.png`），
于是顶点段的结束位置已知；再用 `顶点数 × 每顶点字节数 + 索引段 = 贴图段起点`
反推每顶点字节数，暴力枚举出 `+4` 这一项。

**通用方法**：格式解析卡住时，从**已知锚点反推长度**，比逐个字段猜快得多。

---

## 3. 骨骼 flags 是 1 字节，尾段布局非标

标准 PMX 的骨骼 flags 是 2 字节，且尾段有多种可选结构（付与 / 軸固定 /
ローカル軸 / 外部親 / IK）。这个导出器全改了：flags 1 字节，尾段长度对不上。

硬猜了几轮（枚举 / DFS+回溯 / 前缀校验）全部失败：
浮点数据里凑巧出现的「像字符串」的假锚点太多，每根骨骼有 10+ 个候选。

**最终解法**：放弃理解尾段，改用**字符串锚定**——

1. 扫描骨骼区所有「长度合理 + 全可见字符」的 UTF-16 字符串
2. JP 名与上一个字符串的间隔 ≥ 22 字节；EN 名紧跟 JP（间隔 0）
3. 按此分类得到的起点数必须**等于声明的骨骼数**，否则报错

代价：只能拿到 name / pos / parent，拿不到尾段语义（IK、付与等）。
**结论：够渲染就用，不要为了「完整」把时间耗在没有消费方的字段上。**

---

## 4. `QOpenGLWidget` 渲染正常但屏幕上没有

症状：`grabFramebuffer()` 有内容（模型好好的），窗口 `IsWindowVisible=True`、
`WS_EX_TOPMOST` 也在、z 序也在最前，但**屏幕上就是看不到**。

排查顺序（都很关键，别跳）：

1. **先用 Qt 自己抓桌面**：`QScreen.grabWindow(0)`
   —— 我之前一直用外部脚本 `CopyFromScreen` 截图，结果是 **DPI 虚拟化**后
   的 1707×960，而真实桌面是 2560×1440。窗口在物理 (2019,598)，我的裁剪在
   逻辑 (1346,399)，**永远裁错地方**。
2. 用 `PrintWindow(hwnd, hdc, 2)` 抓窗口自身 → 有内容，说明窗口有渲染
3. 结论：**Qt 在 Windows 上不把 QOpenGLWidget 的内容合成到透明窗口**

**解法（CPU 合成）**：

```python
# 每帧：GL 渲染 → 读帧缓冲 → 贴到 QLabel（普通 QPainter，透明像素天然正确）
fb = gl_view.grabFramebuffer()
pm = QPixmap.fromImage(fb)
pm.setDevicePixelRatio(self.devicePixelRatioF())   # ← 不做这步只显示左上角一块
label.setPixmap(pm)
```

并且 `QLabel` 必须是 GL 部件的**兄弟**（`raise_()`），不能是子部件
（Qt 里 GL 部件的子部件不会画在它上面）。

---

## 5. `QMatrix4x4(*16 floats)` 是行主序

numpy 算出的 mvp 是行主序。我传了 `mvp.T.flatten()`（列主序），
Qt 按行主序解释 → **矩阵被转置** → 投影完全错乱，模型被放大成极端特写。

正确：`QMatrix4x4(*mvp.flatten())`。

类似地：模型中心平移到原点和相机 target 都做了偏移 → 双重偏移，人沉到画面外。
**一个变换只能应用一次**。

---

## 6. `glDrawElements` 报 `GL_INVALID_OPERATION (1282)`

PySide6 的 `QOpenGLFunctions.glDrawElements(mode, count, type, indices)`：
- 传 int offset → `TypeError: wrong argument values`
- 传 `ctypes.c_void_p(offset)` → 不崩但 `glGetError() == 1282`

**排查方法**：在 paintGL 里多点插桩 `glGetError()`，定位到「第一笔 draw 就 1282」。

**解法**：改用 `glDrawArrays`，渲染前把索引展开成顶点数组
（`interleaved[indices]`）。30 万顶点 × 32B ≈ 10MB，完全可接受。

---

## 7. shader 属性被编译器优化掉

把光照去掉后（`vec3 base = tex.rgb;`），`a_norm` 不再被使用，
GLSL 编译器**把属性优化没了** → `attributeLocation("a_norm") == -1`。

如果代码里写了「任一属性 < 0 就判定失败」，就会得到**空白帧且没有报错**。

**解法**：`-1` 的属性跳过绑定即可；只把 `a_pos` / `a_uv` 缺失当错误。

---

## 8. 贴图朝向：一次只翻一次

- `QImage.mirrored()` **默认翻水平**（`mirrored(horizontal=True, vertical=False)`）
- shader 里又翻 V

两者叠加 = 180° 旋转 → UV 全部采到错误区域（头发从棕色变奶油白）。

**正确做法**：二选一。本仓库用 `(u, v)` 直接采样 + 原样上传。

> 验证 UV 朝向的笨办法但很有效：把 4 种朝向
> `(u,v) / (u,1-v) / (v,1-u) / (v,u)` 各渲染一张，用参考图对。
> 注意 `(u,v)` 和 `(u,1-v)` 在小图上差别不明显，**看五官位置**最准。

---

## 9. 透明窗口 + 混合

MMD 模型的「白目 / 目 / 睫眉 / 歯 / 口舌」是**半透明叠加层**。
不开 `GL_BLEND` 的话，它们会像不透明白块糊在脸上，
结果是一张**没有五官的苍白面具**。

```python
gl.glEnable(GL_BLEND)
gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
```

并且按 `material.diffuse[3]` 排序：不透明先画，半透明后画。

---

## 10. 进程被父进程「隐藏」

用 `Start-Process -WindowStyle Hidden` 或 `CREATE_NO_WINDOW` 启动时，
`STARTF_USESHOWWINDOW = SW_HIDE` 会传染给第一个窗口 →
**桌宠窗口不可见**，且 `deiconify()` / `lift()` 都不够。

解法（Win32，直接拉）：

```python
hwnd = user32.GetParent(self.winId())   # Qt 的顶层窗口是子控件的父
user32.ShowWindow(hwnd, 9)              # SW_RESTORE
user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0,
                    0x0001 | 0x0002 | 0x0040 | 0x0010)  # NOSIZE|NOMOVE|SHOWWINDOW|NOACTIVATE
```

---

## 11. PowerShell 脚本的两个 BOM 坑（顺带记一下）

- Windows PowerShell 5.1 读 `.ps1` 时**没 BOM 按 GBK 解码** → 中文注释乱码，
  语法报「字符串缺少终止符」
- 加了 BOM 之后又被程序加一遍 → `EF BB BF EF BB BF` → `param()` 块失效，
  所有参数变 null

正确：`"\ufeff" + src.lstrip("\ufeff")`，且 `param()` 必须在第一行。

---

## 方法论小结

格式逆向 / 渲染调试这类工作，最有效的顺序是：

1. **先用已知锚点反推长度**，不要逐字段猜
2. **让程序自己存证据**（`grabFramebuffer` / `PrintWindow` / `glGetError` 插桩），
   不要只依赖外部截图
3. **数值验证优先于视觉验证**：投影包围盒、非透明像素比例、平均色，
   比"看起来对不对"可靠得多
4. 视觉模型（尤其是小的本地模型）**描述不了 3D 渲染**，别拿它当裁判
