# PC 端工具

设备本身已经内置了 Web 界面（`/convert`、`/edit`、`/text`、`/mosaic`），浏览器打开 `http://192.168.4.1` 就能用。本文档介绍另外两种**在 PC 上独立运行**的形态：

- **离线 HTML**（`pc/`）—— 双击打开，不装任何东西
- **Qt 桌面客户端**（`e6_tool.py` / `e6_editor.py` / `e6_studio.py`）—— PySide6 本地应用

三者功能范围重叠，但对设备、网络、安装依赖的要求各不相同，按需选一个即可。

## 三种形态对比

| | 设备内置网页 | 离线 HTML | Qt 桌面客户端 |
| --- | --- | --- | --- |
| 文件位置 | `esp/www/*.html` | `pc/*.html` | 仓库根目录 `.py` |
| 是否需要设备在线 | ✅ 是（页面本身就在设备上） | ❌ 否（可离线预览/导出） | ❌ 否（可离线预览/导出） |
| 是否需要装 Python 依赖 | ❌ 否 | ❌ 否 | ✅ 是（PySide6 + Pillow 等） |
| 上传到设备 | 相对路径，自动 | 手动填设备 IP | 手动填设备 IP |
| 支持 BIN 库（`/bins/`、`/bgs/`） | ✅ 完整 | ❌ 只做 `/upload` | ❌ 只做 `/upload` |
| 支持文字渲染 `/text/render` | ✅ | ❌ | ❌ |
| 支持 WiFi 配置 | ✅ | ❌ | ❌ |
| 支持开机模式配置 | ✅ | ❌ | ❌ |
| 处理速度 | 浏览器 JS（单线程） | 浏览器 JS（单线程） | 本地 Python（多线程可选） |
| 大图处理 | 受浏览器内存限制 | 受浏览器内存限制 | 受 PC 内存限制（更宽裕） |

**结论**：日常使用设备内置网页；只想离线调参 + 导出 BIN，用离线 HTML；需要频繁调参、保留历史、或者想在本地做复杂编辑，用 Qt 桌面客户端。

---

## 离线 HTML（`pc/`）

单文件、零依赖，用浏览器直接打开即可。适合拷到 U 盘、另一台电脑、或者没装 Python 的环境。

### 文件清单

| 文件 | 对应设备内置页面 | 功能 |
| --- | --- | --- |
| `pc/e6_converter_standalone.html` | `/convert` | 图片转换：调色板、13 种抖动内核、色调 / 清晰度 / 范围适配、下载 / 上传 |
| `pc/e6_editor_standalone.html` | `/edit` | BIN 编辑：双图层、画笔 / 橡皮 / 吸管、6 基础色 + 45 伪色、文字工具、撤销重做 |

### 与设备内置网页的差异

- 页面不在设备上，**首次使用需要手动填写设备 IP**（默认 `192.168.4.1`，保存在 localStorage）
- 可以离线预览、下载 BIN，完全不依赖设备
- 上传时通过 `fetch` 直接 POST 到 `http://<IP>/upload`，依赖设备端的 CORS 头（`web_server.py` 已内置）
- **不支持** `/bins/`、`/bgs/` 库操作，也不支持文字渲染和 WiFi 配置——只保留转换 / 编辑 / 上传三条路径
- 单文件、无构建步骤，文本编辑器就能改

### 使用步骤

1. 双击 `pc/e6_converter_standalone.html`（或把它拖进浏览器）
2. 页面顶部会显示"独立版 · 本地文件"和一个设备 IP 输入框
3. 填设备 IP（AP 模式默认 `192.168.4.1`），会自动保存
4. 正常操作：选图 → 调参 → 点"下载 image.bin"或"上传并显示"
5. 上传会 POST 到 `http://<IP>/upload`，屏幕刷新约 30~60 秒

### 常见问题

**上传失败，控制台报 CORS 错误**
检查设备是不是最新固件（`web_server.py` 的 `CORS_HEADERS` 已包含 `Access-Control-Allow-Origin: *`）。如果是旧固件，需要重新上传 `web_server.py`。

**填了 IP 还是连不上**
先在浏览器地址栏直接访问 `http://192.168.4.1/status`，能看到 JSON 说明设备在线、网络正常。连不上通常是 PC 没连设备 WiFi，或者 IP 填错（比如填成了 STA IP 但不在同一网段）。

**想同时用 BIN 库怎么办**
离线 HTML 故意不支持 BIN 库，因为要把整个库的列表、缩略图、备注、槽位管理搬过来，代码量会翻几倍。需要这些功能请用设备内置网页。

---

## Qt 桌面客户端

基于 PySide6，本地完成全部图像处理和编辑，通过 HTTP 上传到设备。适合频繁调参、需要保存历史、或者想在本地做复杂 BIN 编辑的场景。

### 三个工具的定位

| 文件 | 定位 | 对应设备内置页面 |
| --- | --- | --- |
| `e6_tool.py` | 图片转换 | `/convert` |
| `e6_editor.py` | BIN 编辑 | `/edit` |
| `e6_studio.py` | 一体化（转换 + 编辑 + 上传） | `/convert` + `/edit` 合体 |

三者的调色板、抖动算法、BIN 编解码逻辑**完全一致**，导出的 BIN 与浏览器端生成的字节级相同。

### 依赖安装

三者共用仓库根目录的 `pyproject.toml`，依赖包括：

- `pyside6` — Qt 界面
- `pillow` — 图像处理
- `requests` — 上传
- `epaper-dithering` — 抖动（`e6_studio.py` 使用）
- `fonttools` / `htmlmin` / `rjsmin` / `mpy-cross` — 构建和字模工具链

安装：

```bash
# 推荐用 uv
uv sync

# 或直接 pip
pip install -e .
```

### 启动

**必须从仓库根目录启动**，因为三个工具都通过 `from e6_image_core.dithering import ...` 导入共用核心，需要在 `PYTHONPATH` 里能找到 `e6_image_core/`。

```bash
python e6_tool.py
python e6_editor.py
python e6_studio.py
```

不要在 `pc/` 或 `e6_image_core/` 目录里直接运行，否则会报 `ModuleNotFoundError`。

### e6_tool.py（图片转换）

对应设备内置的 `/convert`，但**所有处理都在本地完成**：

- 左侧面板：图像填充方式、裁切偏移、色调调整（曝光 / 饱和度 / 对比度 / 清晰度 / 阴影 / 高光）、抖动设置（调色板、算法、蛇形扫描）
- 右侧四张预览：Input（旋转 + 填充后）、Adjusted（色调调整）、Dithered（校准色）、Device（设备原生色）
- 调色板编辑器：可以改每个颜色的校准值和设备值（十六进制），自定义后保存在 `e6_image_core/e6_tool_config.json`
- 导出 / 上传：会弹出"选择数据源"对话框，让你选 Dithered 还是 Device

顶部按钮"恢复默认设置"会清空配置并恢复内置调色板。

### e6_editor.py（BIN 编辑）

对应设备内置的 `/edit`：

- 双图层：导入层（读取的 BIN）+ 绘制层（你画的笔画）
- 工具：画笔、橡皮、吸管
- 颜色：6 基础色 + 45 种伪色（15 组 × 3 密度）
- 文字工具：输入文字、选字体 / 字号 / 行高 / 字间距 / 样式、点"放置文字"后在画布上单击锚点
- **导入层锁定**：勾选后橡皮只擦绘制层，不动 BIN
- **编辑锁**（额外功能）：勾选后整个画布不可操作，防止误触
- 顶部"打开 BIN / 保存 BIN / 显示到屏幕"，显示会刷屏 30~60 秒

### e6_studio.py（一体化）

三者里最完整的一个，流程是：

1. **选图 + 调参** → 四张预览（Input / Adjusted / Dithered / Device）
2. **选数据源** → 点"选择数据源…"按钮，选 Dithered 或 Device 作为最终编辑的底图
3. **继续编辑** → 在"最终预览板"上画笔、橡皮、吸管、文字，跟 `/edit` 一样
4. **上传** → 直接 `POST /upload`，或者"导出 BIN"保存到本地

也可以加载已有的 BIN 作为源：点"上传 BIN 作为数据源…"，选一个 172 800 字节的 `.bin` 文件，它就会被当作底图，之后可以继续在上面编辑。加载 BIN 后，`/bins/` 和 `/bgs/` 的调色板、背景管理也跟着生效。

### 配置文件

三个工具各自有一个 JSON 配置文件，位于 `e6_image_core/`：

| 文件 | 归属 | 内容 |
| --- | --- | --- |
| `e6_tool_config.json` | `e6_tool.py` | 设备 IP、色调参数、调色板、上次文件路径 |
| `e6_editor_config.json` | `e6_editor.py` | 设备 IP、笔刷大小、文字参数、编辑锁、上次文件路径 |
| `e6_studio_config.json` | `e6_studio.py` | 上面两者合并 + 数据源选择、缩放、填充模式 |

**这些文件里包含设备 IP 和自定义调色板，属于个人数据，建议加入 `.gitignore`**，不要提交到 git。

> `e6_studio.py` 的配置加载逻辑比较特别：如果 `e6_studio_config.json` 存在就直接用它；不存在时会从 `e6_tool_config.json` 和 `e6_editor_config.json` 合并生成一份，之后不再合并。所以第一次启动 `e6_studio.py` 前，可以让 `e6_tool.py` / `e6_editor.py` 先跑一遍生成配置，也可以直接手动编辑。

### 常见问题

**启动报 `ModuleNotFoundError: No module named 'e6_image_core'`**
不在仓库根目录启动。`cd` 到仓库根目录再运行。

**启动报 `ImportError: DLL load failed`（PySide6）**
PySide6 的 DLL 依赖需要 VC++ 运行库。Windows 上装一下 [Microsoft Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) 即可。

**上传到设备报"连接超时"**
检查设备 IP、PC 是否连着设备 WiFi。Qt 工具的"上传"会先 `GET /` 检查设备在线，4 秒超时；如果设备在刷屏，会连不上，等 30~60 秒再试。

**导出的 BIN 和浏览器端不一样**
先确认两边的调色板是否一致。Qt 工具的调色板存在 `e6_image_core/*_config.json`，浏览器端存在 localStorage（`e6-converter-palettes-v1`），两边是独立的。想对齐的话，在 Qt 工具里手动改调色板，或者把浏览器端的 JSON 复制过来。

---

## 共用核心 `e6_image_core/`

Qt 工具和部分构建脚本共用这个包，里面是纯 Python 的图像处理逻辑，不含 GUI：

| 文件 | 内容 |
| --- | --- |
| `dithering.py` | 调色板（`PALETTES`）、抖动算法（`dither`、`quantize`、`pack`）、颜色匹配（RGB / LAB） |
| `tone.py` | 色调调整（`apply_exposure` / `apply_saturation` / `apply_clarity` / `apply_shadow_boost` / `apply_highlight_compress`，入口 `apply_all`） |
| `__init__.py` | 版本号 |

这套逻辑同时被 `e6_tool.py` / `e6_editor.py` / `e6_studio.py` 使用，导出的 BIN 与设备内置网页的 `/convert` **字节级一致**（前提是调色板相同）。

浏览器端没有直接用这个包（浏览器里跑的是 JS），但算法参数是同一套——`e6_converter_standalone.html` 里的 `KERNELS` 对象和 `dithering.py` 里的 `KERNELS` 一一对应。

---

## 参考

- 设备内置网页的完整说明见 [README.md 的 Web 界面一节](../README.md#web-界面)
- 抖动算法和调色板的参数细节见 `e6_image_core/dithering.py`
- BIN 帧格式（172 800 字节 4bpp）见 [api.md](api.md)