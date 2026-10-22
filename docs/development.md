# 开发指南

本文档面向**修改源码**或**扩展功能**的开发者,覆盖:

- 项目内各模块的职责与依赖关系
- 本地开发环境配置
- `build_esp.py`构建流程(py→mpy、minify)
- 设备端调试技巧
- 修改代码后**不生效**的排查
- 添加新 HTTP 端点 / 新渲染参数的示例
- 性能优化的方向

如果你只是想运行项目,README 已经够用;如果你想改点东西,从这里开始。

## 模块职责

```text
boot.py                启动入口:挂载 SD → main.py
main.py                编排:读模式 → WiFi → 显示 → Web
boot_screen.py         GPIO 检测 + 4 种开机动作
web_server.py          HTTP 服务器(所有路由)
wifi_manager.py        WiFi 扫描 / 保存 / 自动连接
jd7601.py              墨水屏驱动(SoftSPI)
sd_helper.py           SD 卡挂载 + 存储路径
mosaic.py              网格拼图(流式,不占内存)
text_renderer.py       文字渲染核心(v4 字体解析 + 排版)
text_console.py        文字渲染的简单封装
build_font_index.py    扫描字体目录生成索引(设备端跑一次)

gen_font.py            字体生成(TTF → v4 字模)
build_esp.py           构建工具(py→mpy、HTML/JS minify)
test_gpio.py           GPIO 连通性诊断
```

**依赖关系**(从上到下,越往下越基础):

```text
main.py
  ├─ boot_screen.py
  │    ├─ mosaic.py
  │    │    └─ text_renderer.py(间接)
  │    ├─ text_renderer.py
  │    └─ jd7601.py
  └─ web_server.py
       ├─ jd7601.py
       ├─ text_renderer.py
       ├─ sd_helper.py
       └─ wifi_manager.py
```

`text_renderer.py`是最大、最复杂的模块(约 1800 行),负责:

- v4 字体解析(`MultiChunkV4Font`)
- 字体缓存(`_font_cache`)
- 颜色解析(`parse_color_spec`)
- 排版(`_compute_line_metrics`)
- 逐行绘制(`_draw_line_to_band`)
- 旋转(`_stream_rotated`)

绝大多数功能扩展都集中在这个文件。改之前先通读全文,理解两遍扫描的流式渲染策略。

## 本地开发环境

### Python 依赖

```bash
# 推荐用 uv
pip install uv
uv sync

# 或直接 pip
pip install pillow fonttools mpremote
pip install mpy-cross==1.28.0   # 必须匹配设备固件版本
pip install rjsmin htmlmin      # build_esp.py 可选依赖
```

**`mpy-cross`版本必须严格匹配设备固件**。设备是 MicroPython v1.28.0,就用`mpy-cross==1.28.0`。版本不对会报`ValueError: incompatible.mpy file`,而且这个错误发生在设备端加载时,不是编译时——容易误导你以为代码错了。

验证:

```bash
python -m mpy_cross --version
# → mpy-cross 1.28.0
```

### 编辑器

- **PyCharm**+ MicroPython 插件(推荐):能直接在设备上编辑+运行
- **VS Code**+[RT-Thread MicroPython 插件](https://marketplace.visualstudio.com/items?itemName=rt-thread.rt-thread-micropython)
- **Thonny**:内置 MicroPython 支持,开箱即用

三者都支持在 REPL 里直接跑代码、上传文件、软重启,选顺手的即可。

## build_esp.py — 构建工具

把`esp/`目录编译成`esp-x/`,用于上传到设备。

### 处理规则

| 源文件 | 处理 | 目的 |
| --- | --- | --- |
| boot.py / main.py | 原样复制 | 便于 REPL 现场查看、修改 |
| 其他.py | mpy-cross →.mpy | 体积 ↓50%,加载快 2~3 倍 |
| .html /.htm | htmlmin 压缩 | 去掉注释和多余空白 |
| .js | rjsmin 压缩 | 同上 |
| .bin /.map /.idx | 原样复制 | 二进制和文本,无需处理 |
| __pycache__/ | 跳过 | — |

### 为什么 boot.py / main.py 保持.py

**MicroPython 加载模块时优先加载`.mpy`而不是`.py`**。如果`boot.py`和`boot.mpy`同时存在,加载的是`.mpy`,你改`.py`后**不会生效**——这是最容易踩的坑。

把这两个启动入口保持为`.py`:

- 改完直接上传,立刻生效(不需要重新编译)
- REPL 里可以`print(open('main.py').read())`现场看内容
- 出问题时 traceback 的行号能对上源码

代价:`boot.py`和`main.py`总共不到 100 行,`.py`和`.mpy`体积差异 < 1KB,可以忽略。

**其他`.py`编译成`.mpy`**:

- `text_renderer.py`: 41KB → 28KB
- `web_server.py`: 32KB → 22KB
- 加载速度提升 2~3 倍(不用解析源码)
- 总节省约 100KB Flash,在 4MB 里占比不大,但启动明显更快

### 用法

```bash
# 默认:esp/ → esp-x/
python build_esp.py

# 先清空输出
python build_esp.py --clean

# 不编译 mpy,只压缩 html/js(调试用)
python build_esp.py --no-mpy

# 自定义路径
python build_esp.py -s my_esp -d my_esp_x
```

### 上传

```bash
mpremote cp -r esp-x/* :
```

或者只上传修改过的文件:

```bash
mpremote cp esp-x/web_server.mpy :/web_server.mpy
mpremote cp esp-x/www/converter.html :/www/converter.html
```

## 调试技巧

### Ctrl+C 中断

MicroPython 的 REPL 里,任何阻塞操作都可以 Ctrl+C 中断:

- `socket.accept()`— 通常需要**按两次**才能真正打断
- `render_and_display_stream()`— 一次中断,但屏幕会停在半刷新状态
- `time.sleep()`— 立刻打断

**屏幕半刷新状态的修复**:

```python
from jd7601 import JD7601
epd = JD7601()
try: epd.end_frame()
except: pass
try: epd.sleep()
except: pass
```

然后重新渲染一次即可。

### 跳过 main.py,只跑 boot.py

临时需要进 REPL 调试,不想等开机画面。在`boot.py`末尾加:

```python
import sys
sys.exit()
```

设备会直接进 REPL,`main.py`不执行。调完记得删掉。

### 手动触发开机画面

```python
import boot_screen
boot_screen.run_mode(2)   # 跳过 GPIO,直接跑网络信息模式
```

或指定具体模式:

```python
boot_screen.run_mode(0)   # 无动作
boot_screen.run_mode(1)   # 随机 BIN
boot_screen.run_mode(3)   # 指定 BIN
```

### 内存诊断

```python
import gc
gc.collect()
print('free:', gc.mem_free())
print('alloc:', gc.mem_alloc())

# 堆碎片情况
import micropython
micropython.mem_info()
stack: 1000 out of 1536
GC: total: 222112, used: 12345, free: 209767
 No. of 1-blocks: 234, 2-blocks: 89, 3-blocks: 45, ...
```

**判断标准**:

- `free`低于 30KB 时容易 OOM
- `1-blocks`数量过多(>500)说明碎片化严重
- 碎片严重时**软重启**(Ctrl+D)比`gc.collect()`更有效

### 字体缓存清空

```python
from text_renderer import clear_font_cache
clear_font_cache()
```

修改字模文件或换了字体后,前端和设备都可能有缓存。设备端清缓存后需要重新加载字体。

前端清缓存:**Ctrl+Shift+R**硬刷新,或 F12 → Network → Disable cache。

### Web 请求诊断

```python
import socket
s = socket.socket()
s.connect(('127.0.0.1', 80))
s.send(b'GET /status HTTP/1.0\r\n\r\n')
while True:
    d = s.recv(1024)
    if not d: break
    print(d)
```

在设备本地发请求看响应,绕过浏览器和网络层,直接验证后端逻辑。

## 常见"改了没生效"排查

### 症状 1:改了`.py`但设备行为没变

**最可能原因**:设备上同时存在`.py`和`.mpy`,加载的是`.mpy`。

```python
import os
os.listdir('/')
['boot.py', 'main.py', 'main.mpy', 'web_server.mpy', ...]
```

`main.mpy`的存在意味着`main.py`不会被加载。解决:

```python
os.remove('/main.mpy')
```

或者重新上传正确的`.py`。

**避免方法**:用`build_esp.py --no-mpy`上传纯`.py`,开发期间不编译。

### 症状 2:改了`.html`但页面没变

**浏览器缓存**。静态文件默认缓存 600 秒,`.js`/`.css`禁用缓存但`.html`有。

**解决**:

- Ctrl+Shift+R 硬刷新
- F12 → Network → Disable cache → 刷新
- 或者改文件名(比如`converter.html`→`converter2.html`),前端`<script>`里对应改

### 症状 3:改了字模但字形还是旧的

**两层缓存**:

1. 设备端:`_font_cache`缓存了字体对象。调`clear_font_cache()`
2. 浏览器端:字体文件有 1 小时缓存。硬刷新

另外检查`/fonts_index.json`是否需要重新生成(添加了新字体时):

```python
import build_font_index
build_font_index.build()
```

### 症状 4:改了`boot.py`但开机日志没变

**`.mpy`优先级**问题,同上。或者`sys.exit()`还在 boot.py 里忘了删。

**验证**:

```python
print(open('boot.py').read())
```

看到底加载的是哪份内容。

## 添加新功能

### 示例 1:添加新的 HTTP 端点

**需求**:新增`GET /system/time`,返回设备的`time.time()`。

**步骤**:

**1. 在`web_server.py`里添加处理函数**(放在`_system_status`附近):

```python
def _handle_system_time(conn):
    import time
    _send_json(conn, {"time": time.time(), "ticks_ms": time.ticks_ms()})
```

**2. 在`start_server()`的路由表里添加**(找到`elif headers.startswith(b"GET /status"):`附近):

```python
elif headers.startswith(b"GET /system/time"):
    _handle_system_time(conn)
```

**3. 前端调用**:

```js
const r = await fetch('/system/time');
const data = await r.json();
console.log('设备时间:', data.time);
```

**注意**:路由判断顺序很重要。`GET /system/time`必须在`GET /system`之前,否则前者会被截断匹配后者。本项目里没有这个冲突,但扩展时要注意。

### 示例 2:添加新的渲染参数

**需求**:新增`opacity`参数,控制文字透明度(0~255)。

**步骤**:

**1.`text_renderer.py`的`_parse_default_style`**:

```python
def _parse_default_style(default_style):
    if default_style is None:
        default_style = {}
    try:
        opacity = int(default_style.get('opacity', 255))
    except (TypeError, ValueError):
        opacity = 255
    return {
        ...
        'opacity': max(0, min(255, opacity)),
    }
```

**2. 在绘制时使用**(比如`_blit_char_to_band`):

```python
def _blit_char_to_band(idx_buf, inner_w, band_start, band_end,
                       cx, cy, glyph, style, font_h):
    ...
    opacity = style.get('opacity', 255)
    if opacity < 128:
        return   # 完全透明,不画
    # 或者用 opacity 混合两种颜色
    ...
```

**3. 前端`text_panel.html`**:

```js
defaultStylePayload.opacity = 200;
```

**4. 更新`docs/api.md`里`default_style`的字段表**。

### 示例 3:添加新的抖动内核

**需求**:加一种`bayer8x8`抖动。

**步骤**:

**1.`converter.html`的`KERNELS`对象**:

```js
const KERNELS = {
  ...
  bayer8x8: [],  // 空数组,表示用 Bayer 矩阵而不是误差扩散
};
```

**2. 在`dither()`函数里处理**:

```js
if (opts.kernel === 'bayer8x8') {
  // 用 8×8 Bayer 有序抖动
  const M = makeBayer(8);
  ...
  return block;
}
```

**3. HTML 里加选项**:

html

复制

下载

运行

```
<select id="kernel">
  ...
  <option value="bayer8x8">Bayer 8×8</option>
</select>
```

**4. 更新`docs/api.md`(如果这个参数通过 API 暴露的话)**。

## 性能优化

### 屏幕刷新慢(超过 90 秒)

三个最大的耗时点:

| 因素 | 时间占比 | 优化方法 |
| --- | --- | --- |
| outline | +100% | 关闭(视觉变化明显,但值得) |
| bold | +50% | 关闭(字体变细) |
| 大字号 | 32px 比 24px 慢 2 倍 | 用更小字号 |

**优化示例**:

```python
# 慢版本(约 130 秒)
default_style = {
    'outline': {'type': 'pseudo', 'a': 0, 'b': 1, 'density': 4},
    ...
}
per_char = {str(i): {'bold': True} for i in range(200)}

# 快版本(约 40 秒)
default_style = {'outline': None, ...}
per_char = {}   # 不用 bold
```

### 内存不足(`MemoryError`)

**减少`band_rows`**:

```python
# 默认 8,内存紧张时降到 4
render_and_display_stream(epd, text, band_rows=4, ...)
```

每次处理 4 行而不是 8 行,条带缓冲区从`8 * 720 * 1`(约 5.7KB) 降到`4 * 720`(约 2.8KB)。代价是循环次数翻倍,总时间略增 5~10%。

**减少`per_char`**:

每个字符的样式字典约 200~500 字节(取决于字段数)。200 个字符全加样式 = 40~100KB,在 400KB SRAM 里是显著开销。只有真正需要差异化的字符才加。

**清字体缓存**:

```python
from text_renderer import clear_font_cache
clear_font_cache()
```

### Web 响应慢

**静态文件**:

- 默认 600 秒缓存,足够
- `.js`/`.css`禁用缓存方便调试,但每次刷新都要重新下载。稳定后可改成 3600 秒

**缩略图**:

- 优先用`.thumb`文件(1~2 秒)
- 无`.thumb`时实时降采样(5~8 秒)。生产环境必须保证有`.thumb`

**字体索引**:

- 确保`/fonts_index.json`存在。否则`/fonts/list`会现场扫描(1~2 分钟)

## 提交代码

```bash
# 从 main/master 开分支
git checkout -b feature/my-feature

# 修改代码,本地测试(用 mpremote 上传到设备验证)

# 提交
git add .
git commit -m "feat: 添加 XXX 功能"
git push origin feature/my-feature

# 在 GitHub 上开 Pull Request
```

**Commit 前缀**(推荐,便于生成 changelog):

| 前缀 | 用途 |
| --- | --- |
| feat: | 新功能 |
| fix: | bug 修复 |
| docs: | 文档 |
| chore: | 杂项(构建、依赖、gitignore) |
| refactor: | 重构(不改行为) |
| perf: | 性能优化 |

**提交前检查**:

```bash
# 所有 .py 能通过语法检查(注意:这是 CPython 语法检查,不是 MicroPython)
python -m py_compile esp/*.py

# 没有意外提交构建产物
git status
```

## 参考

- `esp/*.py`— 设备端源码
- `build_esp.py`— 构建工具
- [docs/font-format.md](https://font-format.md/)— 字体格式和`gen_font.py`用法
- [docs/api.md](https://api.md/)— HTTP 端点列表
- MicroPython 官方文档:[https://docs.micropython.org/](https://docs.micropython.org/)
