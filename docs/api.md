# HTTP API 参考

设备上运行的是**MicroPython 实现的同步阻塞 HTTP 服务器**。它一次只处理一个请求，所有端点都是串行执行——包括耗时 30~90 秒的屏幕刷新接口。理解这一点对正确使用这些接口至关重要。

本文档列出所有端点、参数、请求/响应格式，以及一些使用上的陷阱。如果你想自己写客户端(比如用 Python 脚本批量上传 BIN),或者扩展现有的 Web 界面,这里就是完整参考。

## 通用约定

### 基础地址

| 访问方式 | 基础 URL |
| --- | --- |
| AP 直连 | http://192.168.4.1 |
| STA 同网段 | http://<设备STA-IP> |
| mDNS(未实现) | 无 |

设备启动后 REPL 会打印两个 IP。都是本地局域网地址,**不要暴露到公网**。

### CORS

所有响应都带以下头:

```text
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, OPTIONS
Access-Control-Allow-Headers: Content-Type
```

`OPTIONS`请求直接返回`200`,无 body。这意味着任意网页都能跨域调用这些接口。局域网内使用没问题,但**不要暴露到公网**——没有鉴权,任何人都能控制屏幕。

### 数据格式

三个约定:

| 场景 | 格式 |
| --- | --- |
| BIN / 缩略图 / 字模 | 二进制,Content-Type: application/octet-stream |
| JSON API | Content-Type: application/json |
| 状态查询等简单响应 | text/plain 或 application/json |

### 4bpp BIN 帧数据

所有涉及"图像"的接口(BIN、背景、屏幕显示)都使用同一种格式:**172 800 字节的 4bpp 数据**。

#### 格式细节

- 尺寸:720×480 像素
- 每像素 4 bit,每字节存 2 像素(**高 4 位 = 左,低 4 位 = 右**)
- 每行 720 像素 = 360 字节
- 480 行 =**172 800 字节**

```text
字节 0:  [pix0_hi | pix0_lo]   → 像素 (0,0) 和 (1,0)
字节 1:  [pix2_hi | pix2_lo]   → 像素 (2,0) 和 (3,0)
...
字节 359: [pix718_hi | pix719_lo]  → 第 0 行最后两像素
字节 360: 第 1 行开始
...
字节 172799: 第 479 行最后两像素
```

#### 像素值

只有 6 个合法值:

| 值 | 颜色 |
| --- | --- |
| 0x0 | 黑 |
| 0x1 | 白 |
| 0x2 | 黄 |
| 0x3 | 红 |
| 0x5 | 蓝 |
| 0x6 | 绿 |

`0x4`保留(不用)。非法值会导致屏幕显示花屏,设备不会校验。

#### 快速验证

```python
>>> import os
>>> os.stat('/bins/0.bin')[6]
172800          # 大小正确

>>> with open('/bins/0.bin', 'rb') as f:
...     print(f.read(4).hex())
'11112233'      # 前两字节"11 11 22 33"= 白白黄红,正常
```

### 缩略图 THUMB 数据

**43 200 字节**,360×240 的 4bpp 数据(格式同上,只是尺寸不同)。

- 从 720×480 每 2×2 取左上角一像素生成
- 必须**由浏览器端在上传 BIN 时同步生成**,作为独立文件保存
- 旧 BIN 没有`.thumb`时,设备端会实时降采样(5~8 秒,慢但可用)

前端`generateThumb()`函数的实现:

```js
function generateThumb(bin){
  var tw = 360, th = 240;
  var thumb = new Uint8Array(tw * th / 2);
  for (var ty = 0; ty < th; ty++){
    var sy = ty * 2;
    var srcBase = sy * 360;
    var dstBase = ty * 180;
    for (var tx = 0; tx < tw; tx++){
      var sx = tx * 2;
      var b = bin[srcBase + (sx >> 1)];
      var nib = (b >> 4) & 0xF;
      if (tx & 1) thumb[dstBase + (tx >> 1)] |= nib;
      else        thumb[dstBase + (tx >> 1)]  = (nib << 4);
    }
  }
  return thumb;
}
```

---

## BIN 库

BIN 文件存放在两个位置:

| storage | 路径 |
| --- | --- |
| flash | /bins/{slot}.bin |
| sd | /sd/e6/bins/{slot}.bin |

槽位`slot`是非负整数,前端界面上显示为"槽位 N+1"。

### `GET /bins/list`

列出所有 BIN(Flash + SD 合并)。

**响应**:

```json
{
  "slots": [
    {"index": 0, "exists": true, "size": 172800, "note": "会议海报", "has_thumb": true, "storage": "flash"},
    {"index": 0, "exists": true, "size": 172800, "note": "封面", "has_thumb": true, "storage": "sd"},
    {"index": 2, "exists": true, "size": 172800, "note": "", "has_thumb": false, "storage": "sd"}
  ],
  "total": 3,
  "slot_size": 172800,
  "thumb_size": 43200,
  "sd_active": true,
  "free_sd": 12345678,
  "free_flash": 234567
}
```

`has_thumb`表示对应的`.thumb`文件是否存在。前端可据此选择"直接加载"还是"显示占位"。

### `GET /bins/get/{slot}?storage={sd|flash}`

下载完整 BIN。

**参数**:

- `slot`:槽位号
- `storage`:`sd`或`flash`,不传时先找 SD 再找 Flash

**响应**:`application/octet-stream`,172 800 字节。响应头`Cache-Control: no-store`(每次都重新读)。

**示例**:

```
curl -o image.bin "http://192.168.4.1/bins/get/0?storage=flash"
ls -l image.bin
# 172800
```

### `GET /bins/thumb/{slot}?storage={sd|flash}`

下载缩略图。

**行为**:

- 如果`{slot}.thumb`存在且大小正确(43 200 字节),直接发
- 否则从`.bin`实时降采样(5~8 秒,慢)

**响应**:`application/octet-stream`,43 200 字节。带`Cache-Control: max-age=3600`,1 小时缓存。

### `POST /bins/upload/{slot}?storage={sd|flash}&note={note}`

仅上传,不显示。

**请求**:

- Body:172 800 字节 4bpp 数据
- `note`可选,URL 编码的 UTF-8 字符串(最多 200 字符)

**行为**:

- 覆盖`{slot}.bin`
- **同时删除旧`.thumb`**(因为 bin 变了,旧缩略图失效)

**响应**:`200 OK`,body 是接收字节数(字符串形式的整数)。

```
curl -X POST \
     --data-binary @image.bin \
     "http://192.168.4.1/bins/upload/0?storage=flash&note=%E4%BC%9A%E8%AE%AE"
# → 172800
```

### `POST /bins/upload_and_display/{slot}?storage=&note=`

上传 + 立即显示。

- 行为同`/bins/upload/`
- 上传完后立即调用显示(30~60 秒)
- **整个请求约 60~90 秒**

**响应**:`200 OK`,body 是接收字节数。但请理解:客户端会等待约 1 分钟才收到响应。

### `POST /bins/thumb_upload/{slot}?storage={sd|flash}`

上传缩略图。

**请求**:

- Body:43 200 字节 4bpp 数据

**行为**:

- **必须在该 BIN 上传成功之后调用**(因为`upload`会删旧 thumb)
- 大小不对直接报错

**响应**:`200 OK`,body 是接收字节数(`43200`)。

### `POST /bins/delete/{slot}?storage={sd|flash}`

删除 BIN 和对应的`.thumb`。

**响应**:`200 OK`,body 是`OK`。

### `POST /bins/note/{slot}?storage={sd|flash}`

设置/清除备注。

**请求 Body**:

- `{"note": "会议海报"}`
- 或纯文本(服务端会尝试解码,失败则用空字符串)
- 空字符串 = 清除备注

**响应**:`200 OK`。

### `GET /bins/display/{slot}?storage={sd|flash}`

把 BIN 刷到屏幕。

**行为**:

- 该端点在设备端调用`_display_bin_file()`,阻塞 30~60 秒
- 响应要等到屏幕刷完才返回

**响应**:`200 OK`,body 是`OK`。

---

## 背景库

**完全同构**于 BIN 库,把`/bins/`换成`/bgs/`,路径映射:

| 库 | 路径 |
| --- | --- |
| /bins/* | /bins/, /sd/e6/bins/ |
| /bgs/* | /bgs/, /sd/e6/bgs/ |

端点清单:

| 方法 | 路径 |
| --- | --- |
| GET | /bgs/list |
| GET | /bgs/get/{slot}?storage= |
| GET | /bgs/thumb/{slot}?storage= |
| POST | /bgs/upload/{slot}?storage=&note= |
| POST | /bgs/thumb_upload/{slot}?storage= |
| POST | /bgs/delete/{slot}?storage= |
| POST | /bgs/note/{slot}?storage= |

**没有**`/bgs/display/`和`/bgs/upload_and_display/`——背景不直接刷屏,只用作文字的叠加图层。

---

## 显示与上传

### `POST /upload`

直接上传 172 800 字节并立即显示。不存储。

**请求 Body**:172 800 字节 4bpp 数据

**响应**:`200 OK`,body 是接收字节数。

**注意**:这是**最常用的接口**——图片转换页面、拼图页面、BIN 编辑器都用这个把结果刷到屏幕。会阻塞 30~60 秒。

```
curl -X POST --data-binary @image.bin http://192.168.4.1/upload
# (等待 30~60 秒)
# → 172800
```

### `GET /color/{name}`

全屏刷新为纯色。

**参数**`name`:

| name | 值 |
| --- | --- |
| black | 0x00 |
| white | 0x11 |
| yellow | 0x22 |
| red | 0x33 |
| blue | 0x55 |
| green | 0x66 |

**响应**:`200 OK`(30~60 秒后)。

---

## 文字渲染

这是最复杂的端点。设备端渲染整个画面需要 30~130 秒(取决于字体大小、字符数、样式),且**先应答后渲染**——收到请求后立即返回`started: true`,然后后台慢慢渲染,屏幕在此期间不响应其它请求。

### `POST /text/render`

**请求 Content-Type**:`application/json`

**请求 Body 结构**:

```json
{
  "text": "第一行\n第二行",
  "size": 32,
  "direction": 0,
  "font_paths": ["/www/fonts/base_32_0.bin"],
  "default_style": {...},
  "per_char": {...},
  "align": "left",
  "valign": "top",
  "line_height": 1.5,
  "line_extras": {},
  "margin_top": 20,
  "margin_bottom": 20,
  "margin_left": 20,
  "margin_right": 20,
  "background": null,
  "stream": true,
  "band_rows": 8,
  "dry_run": false
}
```

#### 参数详解

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| text | string | "" | 文本,\n 换行 |
| size | int | 32 | 字号,用于 _FONT_SIZES 检查(实际由 font_paths 决定) |
| direction | int | 0 | 0 / 90 / 180 / 270 |
| font_paths | list[str] | ["/www/fonts/font_{size}.bin"] | 字体 chunk 路径数组 |
| default_style | dict | {} | 默认样式 |
| per_char | dict | {} | 逐字符样式覆盖 |
| align | str | "left" | left / center / right |
| valign | str | "top" | top / center / bottom |
| line_height | float | 1.5 | 行高倍数(0 = 完全重叠) |
| line_extras | dict | {} | 每行额外像素偏移,key 是行号(0-based) |
| margin_* | int | 20 | 四边距(像素) |
| background | string | null | 背景 BIN 路径(如 /bgs/0.bin) |
| stream | bool | true | 流式渲染(推荐),false 走全缓冲(内存不足会失败) |
| band_rows | int | 8 | 每次处理的行数,越小越省内存 |
| dry_run | bool | false | 只渲染不显示,返回 172 800 字节 BIN |

#### `default_style`结构

```json
{
  "fg": {"type": "solid", "idx": 0},
  "bg": {"type": "solid", "idx": 1},
  "outline": null,
  "bold": false,
  "italic": false,
  "underline": false,
  "strikethrough": false,
  "letter_spacing": 0
}
```

颜色字段(`fg`/`bg`/`outline`)支持三种写法:

```json
// 1. 对象形式
{"type": "solid", "idx": 0}         // 纯色
{"type": "pseudo", "a": 0, "b": 1, "density": 8}  // 伪色

// 2. 字符串简写
"black"
"red+blue"
"red+blue:25"    // 25% 红 + 75% 蓝
"red+blue:50"    // 50% / 50%
"red+blue:75"    // 75% 红 + 25% 蓝

// 3. 数组简写
[0, 1]           // a=0, b=1, density=8
[0, 1, 4]        // a=0, b=1, density=4
```

`density`:4 / 8 / 12 分别对应 25% / 50% / 75% 的 Bayer 抖动比例。

#### `per_char`结构

key 是**不含`\n`的视觉字符索引**(0-based)。也就是说`"Hello\nWorld"`里:

- `H`=0,`e`=1,`l`=2,`l`=3,`o`=4
- (换行不占索引)
- `W`=5,`o`=6,`r`=7,`l`=8,`d`=9

value 可以覆盖`default_style`的任意字段:

```json
{
  "0": {"bold": true, "fg": "red"},
  "5": {"italic": true, "outline": null},
  "9": {"underline": true, "font_paths": ["/sd/e6/fonts/other_32_0.bin"]}
}
```

`font_paths`单独用于逐字符字体覆盖——比如混合两种字体,主字体用`default_style`,个别字符(如数学符号)用另一个字体的`font_paths`。

**注意**:`per_char`里出现的`font_paths`**不应与默认字体相同**,只列额外的。例如默认字体是`base_32_0.bin`,某个字符指定`font_paths: ["base_32_0.bin"]`是冗余的(服务端会跳过)。

#### `line_extras`结构

key 是行号(0-based),value 是额外像素偏移(可正可负):

```json
{
  "3": -15,    // 第 3 行到第 4 行的间距减 15 像素
  "4": -15,
  "7": 50      // 第 7 行到第 8 行的间距加 50 像素
}
```

实际行高 =`max_h × line_height + extra`。

#### 响应

**成功(流式)**:

```json
{"ok": true, "mode": "stream", "started": true, "band_rows": 8, "extra_fonts": 0, "bg": null}
```

**关键点**:`started: true`表示**服务器收到指令并开始渲染**,不是"已完成"。渲染在后台进行(30~130 秒),客户端**不应该**轮询等待。

**成功(dry_run)**:

```json
// Content-Type: application/octet-stream
// Body: 172 800 字节 BIN
```

**失败**:

```json
{"ok": false, "error": "字模加载失败"}
```

**空 OOM**:

```json
{"ok": false, "error": "OOM, free=12345"}
```

#### 典型用法

```
# 简单文本
curl -X POST http://192.168.4.1/text/render \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hello, World!",
    "font_paths": ["/www/fonts/base_32_0.bin"],
    "default_style": {"fg": "black", "bg": "white"}
  }'
# → {"ok": true, "mode": "stream", "started": true, ...}
# (立即返回,屏幕在 30 秒后刷新)
```

#### 常见陷阱

**陷阱 1:等响应**。`/text/render`返回`started: true`后**不应该**继续等待或轮询。屏幕在后台刷新,不响应其它请求。如果同一时间还有别的请求(比如`/status`),会被排队。

**陷阱 2:字体路径拼错**。设备端不会检查`font_paths`是否存在,直接打开失败。错误响应是`字模加载失败`,前端需要自己组织路径。

**陷阱 3:per_char 索引**。`per_char`的 key 是"视觉索引"(不含换行),不是 text 字符串的原始索引。如果前端从`text`字符串遍历,遇到`\n`要跳过。

**陷阱 4:OOM**。`band_rows`太大(比如 32)在 ESP32-C3 的 400KB SRAM 里会 OOM。默认 8 是安全的,如果加了额外的字符样式可能还需要降到 4。

**陷阱 5:`dry_run`的响应体**。当`dry_run: true`时,响应体是 172 800 字节的 BIN 文件(不是 JSON),`Content-Type: application/octet-stream`。前端要检测`Content-Type`区分。

### `GET /text/sizes`

返回 Flash 上可用的字号列表。

**响应**:

```json
{"sizes": [12, 16, 24, 32, 48]}
```

设备端调用`list_available_sizes()`,检查`/www/fonts/font_{size}.bin`是否存在。

---

## 字体

### `GET /fonts/list`

返回`/fonts_index.json`。这是`/fonts/list`的**唯一推荐路径**——如果索引文件不存在,设备会退化为现场扫描目录,1~2 秒超时后连接被重置。

**响应**:

```json
{
  "version": 1,
  "fonts": [
    {"family": "base", "size": 32, "storage": "flash", "chunk_count": 1},
    {"family": "sourcehan", "size": 32, "storage": "sd", "chunk_count": 30}
  ]
}
```

前端根据这些信息填充字体下拉菜单。

### `GET /fonts/get?storage={sd|flash}&name={name}`

下载字体 chunk。

**参数**:

- `storage`:`sd`或`flash`,默认`flash`
- `name`:chunk 基础名(不含`.bin`后缀),如`base_32_0`

**行为**:

- `flash`→`/www/fonts/{name}.bin`
- `sd`→`/sd/e6/fonts/{name}.bin`

**响应**:`application/octet-stream`,带`Cache-Control: max-age=3600`。

**安全检查**:`name`不能包含`/`、`\`、`..`,防止目录穿越。

```
curl -o base_32_0.bin \
  "http://192.168.4.1/fonts/get?storage=flash&name=base_32_0"
```

---

## 系统与网络

### `GET /status`

AP / STA 网络状态。

**响应**:

```json
{
  "ap": {
    "active": true,
    "ip": "192.168.4.1",
    "ssid": "E6-Panel"
  },
  "sta": {
    "connected": true,
    "ip": "192.168.8.240",
    "ssid": "cce",
    "rssi": -55
  }
}
```

`rssi`单位 dBm,负值,越接近 0 信号越好(-50 好,-80 差)。

### `GET /wifi/scan`

扫描周围 WiFi(需要 3~5 秒)。

**响应**:

```json
[
  {"ssid": "cce", "rssi": -55, "auth": 3},
  {"ssid": "TP-LINK_2.4G", "rssi": -72, "auth": 4}
]
```

`auth`:0=开放,1=WEP,2=WPA,3=WPA2,4=WPA/WPA2 混合。

**注意**:ESP32-C3 只支持**2.4GHz**,5GHz 网络不会出现在结果里。

### `GET /wifi/list`

已保存的网络列表(从`/networks.json`读取)。

**响应**:

```json
[
  {"ssid": "cce", "password": "12345678", "priority": 1},
  {"ssid": "TP-LINK", "password": "", "priority": 2}
]
```

**注意**:密码以**明文**返回。局域网内使用没问题,但**不要暴露到公网**。

### `POST /wifi/save`

保存网络。

**请求 Body**:

```json
{"ssid": "cce", "password": "12345678", "priority": 1}
```

- `ssid`已存在时覆盖
- `priority`越小越优先(启动时按优先级尝试)

**响应**:`200 OK`。

### `POST /wifi/delete`

删除网络。

**请求 Body**:

```json
{"ssid": "cce"}
```

**响应**:`200 OK`。

---

## 开机指定 BIN

### `GET /boot/bin`

查询开机指定 BIN 的配置。

**响应**:

```json
{"storage": "flash", "index": 2, "defined": true}
```

`defined: false`表示未指定(模式 11 会用 bins 里序号最大的)。

### `POST /boot/bin`

设置/清除开机指定。

**请求 Body**:

```json
// 设置
{"storage": "flash", "index": 2}

// 清除(传空对象)
{}
```

**响应**:`200 OK`,body 是`OK`(设置)或`cleared`(清除)。

---

## 静态文件

| 路径 | 文件 |
| --- | --- |
| / /index | /www/index.html |
| /convert | /www/converter.html |
| /edit | /www/bin_editor.html |
| /text | /www/text_panel.html |
| /mosaic | /www/mosaic.html |
| /wifi | /www/wifi.html |
| /nav.js | /www/nav.js |
| /xxx.bin | /www/xxx.bin(字体、字模等) |

**回退规则**:未匹配的路径(且不是`.js`/`.css`/`.json`/`.bin`等已知扩展名)都**回退到`/www/index.html`**。这是为了支持单页应用的路由(比如`/foo/bar`也返回主页)。

`.js`和`.css`的响应**禁用缓存**(`cache_seconds=0`),方便开发调试。其它静态文件默认缓存 600 秒。

---

## 错误码

| HTTP 状态码 | 含义 | 常见场景 |
| --- | --- | --- |
| 200 OK | 成功 | — |
| 400 Bad Request | 参数错误 | slot 不是整数、name 含非法字符 |
| 404 Not Found | 资源不存在 | slot 对应的 bin 不存在 |
| 500 Internal Server Error | 设备端异常 | OOM、SPI 错误、字体加载失败 |
| 507 Insufficient Storage | 存储空间不足 | 上传 BIN 时 Flash/SD 满 |

设备端异常会在 REPL 打印完整 traceback,HTTP 响应体只包含简短错误信息。

---

## 并发与超时

这是最容易踩坑的部分。

### 单连接阻塞

设备是**MicroPython`socket`+`while True: accept()`**,同一时刻只处理一个请求。

```text
客户端 A: GET /bins/list       ──► 立即响应
客户端 B: GET /bins/get/0      ──► 立即响应(等 A 完成后)
客户端 A: POST /upload          ──► 等待 60 秒(阻塞)
客户端 B: GET /status          ──► 排队 60 秒后超时
```

**后果**:

- 同时开多个标签页操作页面,后面的会超时
- 屏幕刷新(`/upload`,`/bins/display`,`/text/render`)期间所有请求挂起
- 上传 BIN 时(172 800 字节)期间其它请求也挂起

**前端已经做的缓解**:

- 缩略图**串行队列 + IntersectionObserver**(一次只发一个请求,只对可见的加载)
- 上传按钮**防重复点击**
- 屏幕刷新请求**先应答后渲染**(见下文)

**前端没做的**:

- 跨标签页的互斥(用户开两个页面同时上传会打架)
- 请求超时重试

### 先应答后渲染

`/text/render`和`/bins/upload`的相关接口都有这个模式:

```text
客户端: POST /text/render
服务端: 先发 HTTP 200 + {"ok": true, "started": true}    ← 立即
        然后后台调用 render_and_display_stream()        ← 30~130 秒
        屏幕刷完
```

**为什么这么设计**:如果等渲染完才应答,HTTP 连接会保持 30~130 秒,前端浏览器或代理可能超时(默认 300 秒,但代理会更快)。先应答后渲染,HTTP 连接立即释放,前端拿到响应就完事,用户看屏幕刷新结果即可。

**代价**:前端拿到的`ok: true`只是"服务器已接收",**不代表屏幕刷完了**。用户需要自己看屏幕。

**前端处理方式**:

```js
const resp = await fetch('/text/render', {...});
const data = await resp.json();
if (data.started) {
  setStatus('已发送渲染指令 ✓  屏幕约 30~120 秒后更新');
}
```

用户看到这条提示后,自己去盯着屏幕。

### 客户端超时建议

| 端点 | 建议超时 | 说明 |
| --- | --- | --- |
| /status /bins/list /bgs/list | 10 秒 | 快速响应 |
| /bins/get /bins/thumb | 30 秒 | 172 800 / 43 200 字节 |
| /upload | 180 秒 | 60 秒刷新 + 上传 + 余量 |
| /bins/upload_and_display | 180 秒 | 同上 |
| /text/render (stream) | 30 秒 | 只等 started: true |
| /text/render (dry_run) | 180 秒 | 全部渲染完成才返回 BIN |

**不要在`/text/render`上设置 5 分钟以上超时**——你等的是`started: true`,它会在 1 秒内返回。设置长超时会导致真实错误(连接失败)迟迟不报。

---

## 使用示例

### 用 Python 批量上传 BIN

```python
import urllib.request
import os

def upload_bin(local_path, slot, storage='flash', note=''):
    url = f'http://192.168.4.1/bins/upload/{slot}?storage={storage}'
    if note:
        url += f'&note={urllib.parse.quote(note)}'
    with open(local_path, 'rb') as f:
        data = f.read()
    assert len(data) == 172800, f'大小错误: {len(data)}'
    req = urllib.request.Request(url, data=data,
                                  headers={'Content-Type': 'application/octet-stream'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode()

# 批量上传
for i, f in enumerate(['a.bin', 'b.bin', 'c.bin']):
    r = upload_bin(f, i, 'sd')
    print(f'slot {i}: {r}')
```

### 用 curl 检查设备

```
# 网络状态
curl http://192.168.4.1/status | jq

# 已有 BIN
curl http://192.168.4.1/bins/list | jq '.slots[] | {storage, index, note}'

# 纯色刷新
curl http://192.168.4.1/color/red

# 显示指定 BIN(阻塞约 60 秒)
curl "http://192.168.4.1/bins/display/0?storage=flash"
```

### 用 curl 渲染文字

```
curl -X POST http://192.168.4.1/text/render \
  -H "Content-Type: application/json" \
  -d '{
    "text": "ESP32-C3\nJD7601",
    "font_paths": ["/www/fonts/base_32_0.bin"],
    "default_style": {"fg": "black", "bg": "white", "letter_spacing": 2},
    "align": "center",
    "valign": "center"
  }'
# → {"ok": true, "mode": "stream", "started": true, ...}
```

---

## 尚未实现

以下功能暂未提供,如果将来扩展会更新本文档:

- **mDNS**:无法通过`e6-panel.local`访问,只能用 IP
- **WebSocket**:所有交互基于 HTTP
- **鉴权**:无密码保护,局域网内任何人可控制
- **WebREPL**:需要手动在`boot.py`里启用
- **OTA 升级**:需要手动上传文件

---

## 参考

- `web_server.py`源码:所有端点的实现
- 前端各页面的`<script>`里调用了哪些端点,可对照阅读
- [MicroPython`socket`文档](https://docs.micropython.org/en/latest/library/socket.html)