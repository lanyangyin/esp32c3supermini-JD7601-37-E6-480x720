# 字体格式详解

本项目的字模（glyph bitmap）使用自定义二进制格式，版本号**v4**，由`gen_font.py`从 TTF/OTF 生成。v4 支持 Unicode、多 chunk 切分、前端懒加载，是本项目唯一推荐使用的格式。


本文档面向需要：

- 自己写解析代码（比如扩展前端）
- 生成中文或自定义字符集的字体
- 理解`build_font_index`和前端懒加载的原理
- 排查"字符显示为空白"、"字体文件太大"、"chunk 太多"等问题

如果你只是想生成字体并上传，README 的"快速开始"章节已经够用。

## v4 文件组成

一个字体由三类文件共同描述：

| 文件 | 作用 | 大小 | 是否必需 |
| --- | --- | --- | --- |
| family_size_N.bin | 字模数据 chunk（N=0,1,2...） | 10KB~100KB | ✅ |
| family_size.idx | 顶层索引（JSON，覆盖所有 chunk 的码点范围） | 几百字节~几 KB | ✅ |
| family_size_N.map | 字符清单（文本，逐字符列出宽度） | 与 bin 相当 | ❌ 调试用 |

例如 Source Han Sans 32px：


```
sourcehan_32_0.bin    100KB
sourcehan_32_0.map    75KB
sourcehan_32_1.bin    100KB
sourcehan_32_1.map    68KB
...
sourcehan_32_29.bin   45KB
sourcehan_32_29.map   32KB
sourcehan_32.idx      2KB      ← 顶层索引
```

前端加载流程：


```
加载 sourcehan_32.idx（2KB）
  ↓
用户输入字符
  ↓
在 idx 里二分查找属于哪个 chunk
  ↓
只下载对应的 chunk（100KB），不下载其它 29 个
```

**这就是 v4 的核心设计**：用极小的`.idx`做路由，大体积的`.bin`按需下载。

---

## chunk 二进制格式

每个`.bin`是一个独立 chunk，结构分三段：


```
┌──────────────────────────────────┐
│ Header（6 字节）                 │
├──────────────────────────────────┤
│ Index（count × 6 字节）          │
├──────────────────────────────────┤
│ Glyph Data                       │
└──────────────────────────────────┘
```

### Header（6 字节）

| 偏移 | 长度 | 字段 | 说明 |
| --- | --- | --- | --- |
| 0 | 1 | version | 固定 0x04 |
| 1 | 1 | flags | bit0 = 1 表示 Unicode，0 表示 ASCII |
| 2 | 2 | count | uint16 LE，本 chunk 的字形数 |
| 4 | 2 | max_h | uint16 LE，本字体所有字符的最大高度（像素） |

**为什么统一 max_h**：所有字形用同一行高，前端读字形时直接用`max_h`算行偏移，O(1) 访问。不同字符的高度差异由字形的实际像素内容体现（上下留白），不影响存储结构。

**为什么 count 是 uint16**：单 chunk 最多 65535 字符。实际用`--max-chunk-kb=100`切分时一个 chunk 通常 500~3000 字符，远小于上限。

### Index（count × 6 字节）

按**code 升序**排列，用于二分查找：

| 偏移 | 长度 | 字段 | 说明 |
| --- | --- | --- | --- |
| 0 | 2 | code | uint16 BE，Unicode 码点（ASCII 模式下只用低字节） |
| 2 | 3 | offset | uint24 BE，字形数据在整个文件中的起始字节 |
| 5 | 1 | width | uint8，字形宽度（像素），0 表示空格或缺字符 |

**为什么按 code 升序**：前端拿到字符 code 后，在索引上二分（`O(log n)`），1~2 毫秒定位字形。如果乱序，就只能顺序扫描（`O(n)`），几千字符时会明显卡顿。

**为什么 offset 是 uint24**：单文件最大 16MB，24 位正好覆盖。实际 chunk 都在 100KB 级别。

**width 为 0 的字符**不占 Glyph Data 空间，只在索引里保留一条`width=0`的记录。前端遇到 width=0 直接用`space_width()`推进光标（空格、缺字符都是这种情况）。

### Glyph Data

每个字形的位图数据：

- 大小 =`((width + 7) // 8) * max_h`字节
- 格式：1bpp 位图，每行从左到右，**MSB first**
- 行与行之间**紧密排列，无 padding**

例如`width=16, max_h=32`的字形 =`2 字节/行 × 32 行 = 64 字节`。

**前端解析伪代码**：


```
for y in range(max_h):
    for x in range(width):
        byte_idx = offset + y * ((width + 7) // 8) + (x >> 3)
        bit_idx = 7 - (x & 7)
        if data[byte_idx] & (1 << bit_idx):
            # 该像素点亮
```

**示例**：一个`width=3, max_h=2`的小字形（假设位图是：


```
█ █ ░
░ █ █
```

即第 0 行"110"，第 1 行"011"）：

- `((3+7)//8) = 1 字节/行`
- 总大小 = 1 × 2 = 2 字节
- 第 0 行：`0b11000000 = 0xC0`（MSB first，110 左对齐）
- 第 1 行：`0b01100000 = 0x60`
- Glyph Data =`[0xC0, 0x60]`

---

## `.idx`顶层索引

每个`family_size.idx`覆盖该 family/size 所有 chunk 的码点范围。前端据此决定"要渲染某个字符需要下载哪个 chunk"。

示例`sourcehan_32.idx`：

```json
{
  "version": 1,
  "family": "sourcehan",
  "size": 32,
  "max_h": 40,
  "unicode": true,
  "count": 20992,
  "chunks": [
    {"min": 32, "max": 0x2FF, "ci": 0, "count": 512, "name": "sourcehan_32_0"},
    {"min": 0x300, "max": 0x4FF, "ci": 1, "count": 498, "name": "sourcehan_32_1"},
    {"min": 0x4E00, "max": 0x9FFF, "ci": 15, "count": 848, "name": "sourcehan_32_15"},
    {"min": 0x9E00, "max": 0xFFFF, "ci": 29, "count": 620, "name": "sourcehan_32_29"}
  ]
}
```

| 字段 | 用途 |
| --- | --- |
| min / max | 该 chunk 覆盖的码点范围（含两端） |
| ci | chunk 序号（0-based），对应文件名后缀 |
| count | 该 chunk 的字形数 |
| name | chunk 文件名（不含.bin 后缀） |

**前端工作流**：

1. 启动时加载`{family}_{size}.idx`（几 KB）
2. 用户输入文本，对每个字符在`chunks`数组里二分查`min ≤ code ≤ max`的 chunk
3. 只在**需要渲染时**才真正下载对应的`.bin`文件
4. 下载的 chunk 进 LRU 缓存（默认 4 个，约 400KB 内存）

**懒加载的实际效果**：

| 场景 | 下载量 |
| --- | --- |
| 页面打开，无输入 | 0 KB（只加载 idx） |
| 输入"你好" | 100KB（1 个 chunk） |
| 输入"你好世界和平"（分布在不同区域） | 可能 200~300KB（2~3 个 chunk） |
| 反复切换字体 | 每个字体加载时清零缓存，重新按需下载 |

**chunk 边界设计**：`gen_font.py`用`--max-chunk-kb`控制每个 chunk 的最大字节数。字符按 code 升序排列，累积到接近上限就切一个新 chunk。所以：

- **ASCII 区（0x20~0x7E）几乎总在第一个 chunk**
- **CJK 基本区（0x4E00~0x9FFF）通常集中在中部几个 chunk**
- 具体属于哪个 chunk 只能读`.idx`查，不是固定的

---

## `.map`字符清单

每个 chunk 附带`family_size_N.map`，是**人类可读**的字符清单：


```
# E6 font map
# family: sourcehan
# size: 32
# format: v4
# max_h: 40
# count: 848
# missing: 2
# charset: cjk
# source: SourceHanSans.ttf
# chunk: 15 of 30
# generated: 2026-10-22 14:00:00
# columns: code<TAB>char<TAB>width
0x4E00	'一'	32
0x4E01	'丁'	32
0x4E02	'丂'	0
...
```

| 用途 | 说明 |
| --- | --- |
| 调试缺字 | width=0 说明 TTF 里没有这个字形 |
| 查字符宽度 | 不用加载.bin 就能知道宽度（用于排版预估） |
| 检查字符集 | wc -l xxx.map 快速统计实际字符数 |
| diff 字体版本 | 比较两份.map 看哪个字符变了 |

**`.map`不是必需的**。设备端和前端都**不读**`.map`，只读`.bin`和`.idx`。`.map`纯粹给开发者调试用。

生成时用`--no-map`可以跳过，节省磁盘和上传时间。

---

## `gen_font.py`用法

`gen_font.py`是 PC 端工具，需要 Python 3 和`pillow`、`fonttools`：


```
pip install pillow fonttools
```

### 核心参数

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| TTF | 字体文件路径（必需） | — |
| --sizes | 字号列表 | 全部 16 个字号 |
| --charset | 字符集 | auto（TTF cmap） |
| --family | 字体族名 | TTF 文件名 |
| --out | 输出目录 | esp/www/fonts |
| --max-chunk-kb | 每 chunk 最大 KB | 100 |

`--sizes`支持的关键字：

- `all`→ 全部 16 个：8/10/12/14/16/18/20/24/28/32/40/48/56/64/72/96
- `reasonable`→ 16/24/32
- `mini`→ 16/24
- `small`→ 12/16/20/24
- `big`→ 32/48/64

也可以显式列：`--sizes=24,32,48`。

### 字符集选项

| --charset= | 覆盖范围 | 字符数 |
| --- | --- | --- |
| auto | TTF cmap 里的所有 BMP 码点 | 因字体而异 |
| ascii | 0x20~0x7E | 95 |
| basic / latin1 | 0x20~0xFF | 224 |
| symbols | 图形符号、箭头、数学符号等 | 约 130 |
| full | basic + symbols | 约 430 |
| cjk | CJK 基本区 + ASCII | 约 2 万 |
| none | 空基础集，只用 --chars/--file 补充 | 0 |

**`auto`依赖`fonttools`**。没装`fonttools`会退化到`full`（431 字符，不含中文）。**生成中文字体必须装`fonttools`**或显式用`--charset=cjk`。

### 典型用法

**1. 生成基础 ASCII 字体（Flash，最常用）**


```
python gen_font.py SomeMono.ttf \
    --charset=ascii \
    --sizes=24,32,48 \
    --family=base \
    --out=esp/www/fonts
```

生成 3 个字号，每个字号 1 个 chunk（ASCII 只有 95 字符，远小于 100KB）：


```
base_24_0.bin  base_24_0.map  base_24.idx
base_32_0.bin  base_32_0.map  base_32.idx
base_48_0.bin  base_48_0.map  base_48.idx
```

**2. 生成中文字体（SD 卡）**


```
python gen_font.py SourceHanSans.ttf \
    --charset=cjk \
    --sizes=24,32 \
    --family=sourcehan \
    --max-chunk-kb=100 \
    --out=esp/sd/fonts
```

CJK 约 2 万字符，32px 单字号约 2~3MB，切分成 20~30 个 chunk。

**3. 只生成指定字符（最快最省）**

只显示固定几十个字（如菜单文字），直接列出：


```
python gen_font.py SomeFont.ttf \
    --charset=none \
    --chars="设置菜单开关音量亮度色彩" \
    --sizes=32 --family=menu
```

生成 1 个 chunk，几十 KB。比生成整个 CJK 省 99% 空间。

**4. 从 UTF-8 文件读字符集**

命令行传特殊字符容易编码出问题，写进文件最稳妥：


```
python gen_font.py SomeFont.ttf \
    --charset=none \
    --file chars.txt \
    --sizes=32 --family=custom
```

`chars.txt`是 UTF-8 文本，逐字符读取（自动去重、跳过换行）。

**5. 检查字体是否含某字符**

生成前先检查：


```
python gen_font.py SomeFont.ttf --check "∠・⌒"
```

输出：


```
字符   码点      Unicode 块                          cmap  渲染  宽
--------------------------------------------------------------------
∠    U+2220   Mathematical Operators                ✗    ✓    24
・   U+30FB   Katakana                              ✗    ✓    24
⌒    U+2312   Miscellaneous Technical               ✗    ✓    24
```

**`cmap ✗`说明 TTF 里没有这个码点**。`渲染 ✓ 宽 24`是 PIL 画出的`.notdef`（空心方框），并非真字形。`cmap ✗`的字符不要生成。

### 输出命名


```
{family}_{size}_{chunk_index}.bin    字模 chunk
{family}_{size}_{chunk_index}.map    字符清单
{family}_{size}.idx                  顶层索引
```

例如`sourcehan_32_0.bin`、`sourcehan_32.idx`。

---

## 字体部署

### Flash 布局（`/www/fonts/`）

**只放 ASCII 小字体**。Flash 只有 4MB，MicroPython 固件和 Web 资源已占 1~2MB。


```
/www/fonts/
├── base_12_0.bin      5KB
├── base_12.idx
├── base_24_0.bin      7KB
├── base_24.idx
├── base_32_0.bin     10KB    ← 开机画面用的 32px
└── base_32.idx
```

一个 ASCII 字号通常 5~10KB，三个字号不到 30KB。

### SD 卡布局（`/sd/e6/fonts/`）

**放 CJK 字体**。SD 卡容量大，2~3MB 不心疼。


```
/sd/e6/fonts/
├── sourcehan_24_0.bin    100KB
├── sourcehan_24_1.bin    100KB
├── ...
├── sourcehan_24.idx       2KB
├── sourcehan_32_0.bin    100KB
├── sourcehan_32_1.bin    100KB
├── ...
└── sourcehan_32.idx       2KB
```

### 生成索引文件（设备端，必须做一次）

在 REPL 里跑：


```
import build_font_index
build_font_index.build()
```

它扫描`/www/fonts/`和`/sd/e6/fonts/`下的所有`.idx`文件，生成`/fonts_index.json`（几 KB）。

**为什么必须有这个文件**：`GET /fonts/list`端口如果找不到`fonts_index.json`，会退化为**现场扫描目录**——遍历 1710 个文件（`os.listdir`+ 逐个`stat`）需要几秒，Web 请求会超时。有索引文件时`/fonts/list`直接返回静态 JSON，秒回。

**添加新字体后**：上传字体 → 再跑一次`build_font_index.build()`。

---

## 前端字体加载流程

完整时序（以`/text`页面渲染"你好"为例）：


```
1. 页面加载
   GET /fonts/list
   → /fonts_index.json
   → [{family: 'base', size: 32, ...}, {family: 'sourcehan', size: 32, ...}]

2. 用户选择 "sourcehan 32px"
   GET /sd/e6/fonts/sourcehan_32.idx
   → {chunks: [{min: 32, max: 0x2FF, ci: 0}, {min: 0x4E00, max: 0x9FFF, ci: 15}, ...]}

3. 用户输入"你好"
   查 idx：「你」(U+4F60) 和「好」(U+597D) 都在 ci=15
   GET /sd/e6/fonts/sourcehan_32_15.bin
   → 下载 100KB，1~2 秒
   → 解析 bin，构建 chunk 15 的字形索引缓存

4. 渲染
   从 chunk 15 的缓存取字形 → 画到 canvas

5. 用户又输入"世界"
   「世」(U+4E16) 和「界」(U+754C) 也在 ci=15
   → 无需下载，直接用缓存
```

**缓存策略**：

- **`.idx`**：内存常驻（几 KB），切换字号时重新加载
- **`.bin`**：LRU 缓存 4 个 chunk（约 400KB 内存）
- **HTTP 缓存**：浏览器缓存 1 小时（`Cache-Control: max-age=3600`），刷新页面不重新下载

**换字体时**：切换到另一个 family/size 后，旧 chunk 缓存清空。

---

## 常见问题

### 字符显示为空白或方块

**排查顺序**：

1. **字体本身不含该字符**—— 用`--check "字符"`检查，`cmap ✗`就是没有
2. **字形 width=0**—— 查看`.map`里该字符宽度。width=0 说明 TTF 里没有有效字形
3. **前端用了错误的字体**—— 中文内容选了`[Flash] base`（只含 ASCII）。应该选`[SD] sourcehan`或其他 CJK 字体

**PC 端检查**：


```
python gen_font.py SomeFont.ttf --check "你"
```

**设备端检查**：

```python
from text_renderer import font_supports
font_supports('/sd/e6/fonts/sourcehan_32_0.bin', '你')
True
```

### 生成的文件太大（几 MB）

**中文字体的正常体积**。2 万字符 × 40 字节/字符 ≈ 800KB/字号，3 个字号 2.4MB。

**缩小办法**：

| 办法 | 效果 |
| --- | --- |
| 减小 --sizes（只生成 24, 32） | 线性缩小 |
| 只生成常用字符（3500 常用字） | 缩到 15~20% |
| 用 --chars 精确列举 | 按需，最小 |

**放在哪**：SD 卡不心疼，Flash 只放 ASCII 小字体。

### 修改字体后前端还是旧字形

**浏览器缓存**。`/fonts/get`的响应带`Cache-Control: max-age=3600`，1 小时内浏览器不重新下载。

**清缓存**：

- 硬刷新：`Ctrl+Shift+R`（Windows）或`Cmd+Shift+R`（macOS）
- 或 F12 → Network → 勾选 "Disable cache" → 刷新
- 或改文件名（`base_32_0_v2.bin`），前端当新字体加载

### chunk 数量太多（100+）

`--max-chunk-kb`设置太小。

**平衡点**：每 chunk 100~200KB。

- **100KB**：每个 chunk 下载快（1~2 秒），但文件数多
- **200KB**：下载稍慢（2~4 秒），文件数减半
- **500KB**：下载慢（5~10 秒），文件数少

推荐 100KB。

### `build_font_index.build()`很慢

**首次运行会扫描所有`.idx`**，字体很多时（170+ 个）需要 1~2 分钟。**之后不再需要重跑**，除非添加/删除字体。

如果索引文件损坏：删除`/fonts_index.json`，重跑会重新生成。

### 字体上传很慢

MicroPython 的`mpremote cp`对小文件效率低。3MB 中文字体可能需要 1~2 分钟。

**加速**：

- `mpremote cp -r`批量上传（一次连接传多个文件）
- 用`ampy`或`rshell`替代
- 中文字体放 SD 卡，不必反复上传

---

## 参考

- `gen_font.py`源码：本仓库根目录
- `text_renderer.py`的`MultiChunkV4Font`类：v4 格式的设备端解析
- `text_panel.html`的`makeLazyV4Font`函数：v4 格式的前端解析
