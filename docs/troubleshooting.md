# 故障排查

按症状查找解决方案。每条包含:**现象 → 可能原因 → 排查步骤 → 解决方法**,遇到问题时先扫一眼"现象"列,匹配到相似的条目再深入。

本文档不覆盖"怎么用"和"为什么这样设计",那些在[hardware.md](hardware.md)、[font-format.md](font-format.md)、[api.md](api.md)、[boot-modes.md](boot-modes.md)、[development.md](development.md)里。

## 快速自检

在深入具体症状前,先做这几件事,能排除 80% 的问题:

```python
# 1. 设备启动了吗?
# 打开 REPL,看到这些说明正常启动:
# [BOOT] SD: yes
# [MAIN] STA: http://xxx
# [MAIN] AP: http://192.168.4.1
# [MAIN] 启动 Web 服务器...

# 2. 内存还剩多少?
import gc; gc.collect()
print(gc.mem_free())
# 低于 30000 时容易出问题

# 3. 文件都在吗?
import os
os.listdir('/')
os.listdir('/www')
os.listdir('/www/fonts')

# 4. SD 卡挂载了吗?
import sd_helper
sd_helper.is_sd_active()
# True / False

# 5. 字体索引生成了吗?
os.stat('/fonts_index.json')[6]
# 几 KB 说明有
```

哪个环节异常,直接跳到对应章节。

## 屏幕问题

### 刷屏后屏幕完全没变化

**现象**:调用`/upload`或`epd.write_chunk(...)`后,屏幕保持原样。

**可能原因**:

1. 电源电压不足(屏幕初始化失败)
2. SPI 引脚接错
3. BUSY 引脚接错(永远"忙",导致初始化卡住)
4. 复位时序错误

**排查**:

```python
# 最小测试:刷全黑
from jd7601 import JD7601
epd = JD7601()
epd.init()                    # 应该 < 1 秒返回
epd.begin_frame()
for _ in range(480):
    epd.write_chunk(b'\x00' * 360)
epd.end_frame()
epd.sleep()
```

如果`epd.init()`**超过 5 秒**或**卡住**→ BUSY 引脚问题。
如果`init()`快速返回但屏幕无反应 → SPI 或复位问题。

**解决**:

- 万用表量 3.3V,应稳定在 3.3±0.2V
- 对照[hardware.md](hardware.md)的引脚表逐个检查
- BUSY 引脚应接 GPIO2,**不要**接 VCC 或 GND
- 屏幕复位可能需更长时间,把`init()`里的`time.sleep_ms(20)`改成`time.sleep_ms(100)`

### 屏幕显示花屏 / 条纹 / 色彩错乱

**现象**:屏幕有变化但不是预期内容。

**可能原因**:

1. 帧数据大小不对(不是 172 800 字节)
2. 4bpp 索引有非法值(不是 0/1/2/3/5/6)
3. 上传过程中断(数据传了一半)
4. SPI 时序问题(SoftSPI 速度太快)

**排查**:

```python
# 检查 BIN 文件
import os
os.stat('/bins/0.bin')[6]
# 必须是 172800,否则文件损坏

# 检查前 8 字节是否有非法值
with open('/bins/0.bin', 'rb') as f:
    for b in f.read(8):
        hi = (b >> 4) & 0xF
        lo = b & 0xF
        print(f'{hi:X} {lo:X}', end=' ')
# 应该只有 0/1/2/3/5/6
```

**解决**:

- 重新上传 BIN(可能上次传输中断)
- 降低 SoftSPI 速度:`jd7601.py`里`baudrate=1_000_000`改成`500_000`
- 检查 USB 线(长线、劣质线可能导致掉电,数据传一半)

### 屏幕刷了一半停了

**现象**:上半部分正常,下半部分还是旧的。

**可能原因**:

1. 刷新过程中 Ctrl+C 中断
2. `MemoryError`(渲染到一半 OOM)
3. 电源在刷新中途跌落(掉到 3.0V 以下)

**排查**:看 REPL 是否打印异常。

**解决**:

- 重新刷一次
- 如果是 OOM,减小`band_rows`(见内存)
- 换个质量好的 USB 线或充电头

### 屏幕刷完后自动变白 / 变黑

**现象**:刷完画面正常 1~2 秒,然后屏幕清空。

**可能原因**:`end_frame()`里的休眠命令时序不对,屏幕进入了未定义状态。

**解决**:打开`jd7601.py`找到`end_frame()`:

```python
def end_frame(self):
    self._cmd(0x04); self._wait(10000); time.sleep_ms(10)
    self._cmd(0x12); self._data(bytes([0x00])); time.sleep_ms(10); self._wait(40000)
    self._cmd(0x02); self._data(bytes([0x00])); self._wait(2000); time.sleep_ms(20)
```

试着把最后的`_wait(2000)`和`time.sleep_ms(20)`各加倍:

```python
    self._cmd(0x02); self._data(bytes([0x00])); self._wait(4000); time.sleep_ms(50)
```

不同的 JD7601 模块对休眠时序要求略有不同。

## 缩略图问题

### 首页缩略图全黑

**现象**:首页 BIN 卡片是黑色方块,但点击"显示"能正常刷屏。

**原因**:旧 BIN 没有对应的`.thumb`文件,而设备的实时降采样有 bug(早期版本)或者超时了。

**排查**:

```python
import os
os.listdir('/bins')
['0.bin', '1.bin', '2.bin', 'meta.json']
# 没有 .thumb 文件 → 走了慢速降采样
```

**解决**:

1. 确认`web_server.py`是最新版本(修复了`readinto`bug)
2. **重新上传一次 BIN**。浏览器端的`generateThumb()`会生成`.thumb`并同步上传

```python
os.listdir('/bins')
['0.bin', '0.thumb', '1.bin', '1.thumb', '2.bin', '2.thumb', 'meta.json']
```

有`.thumb`后,首次加载仍是 1~2 秒,之后 1 小时内浏览器缓存。

### 缩略图加载很慢(5~8 秒/张)

**原因**:无`.thumb`文件,走设备实时降采样。

**解决**:重新上传。详见上一节。

如果**很多**旧 BIN 要一次性补全`.thumb`,可以写个脚本在浏览器控制台批量触发:

```js
// F12 → Console,依次上传每个 BIN
for (const slot of [0,1,2,3]) {
  const r = await fetch(`/bins/get/${slot}?storage=flash`);
  const bin = new Uint8Array(await r.arrayBuffer());
  const thumb = generateThumb(bin);
  await fetch(`/bins/thumb_upload/${slot}?storage=flash`, {
    method: 'POST',
    headers: {'Content-Type':'application/octet-stream'},
    body: thumb
  });
}
```

### 缩略图显示错乱(不是原图内容)

**原因**:缩略图文件损坏或大小不对。

**排查**:

```python
os.stat('/bins/0.thumb')[6]
43200   # 必须是这个数字
```

如果不是,删除后重新上传:

```python
os.remove('/bins/0.thumb')
```

然后重新上传 BIN(会同时重新生成 thumb)。

## 中文 / 字体问题

### 中文全部显示为空白

**现象**:英文字符正常,中文位置是空白。

**原因**:当前字体不含中文字形。

**排查**:

```python
# 1. 看设备上有哪些字体
import os
os.listdir('/www/fonts')
['base_32_0.bin', 'base_32.idx', ...]
# 只有 base → 只含 ASCII

os.listdir('/sd/e6/fonts')
['sourcehan_32_0.bin', ...]
# 有 sourcehan → 有中文

# 2. 检查字体是否含目标字符
from text_renderer import font_supports
font_supports('/sd/e6/fonts/sourcehan_32_0.bin', '你')
True    # 含
font_supports('/www/fonts/base_32_0.bin', '你')
False   # 不含
```

**解决**:

- 打开`/text`页面,**字体下拉选`[SD] sourcehan 32px`**(不是`[Flash] base`)
- 如果是开机画面(模式 10)或 BIN 编辑器里的文字,需要修改代码里使用的`font_paths`

### 部分中文字符缺失(显示为方块或空白)

**原因**:字体生成的字符集不完整。

**排查**:PC 端用`gen_font.py`检查:

```bash
python gen_font.py SomeFont.ttf --check "缺失的字"
```

如果`cmap ✗`→ TTF 里就没有这个字符,需要换字体。
如果`cmap ✓`但 width=0 → TTF 里这个字符是空的(极少数情况)。

**解决**:

- 换更全的字体(Source Han Sans、Noto Sans CJK 覆盖 2 万+ 常用汉字)
- 或者用`--chars="指定字符"`精确生成

详见[font-format.md](font-format.md)的"字符显示为空白或方块"。

### 中文渲染很慢(超过 3 分钟)

**原因**:CJK 字体 chunk 多,每个字符都 seek + read。

**优化**:

- 减小字号(32 → 24 快约 2 倍)
- 增大`--max-chunk-kb`(100 → 200,减少 chunk 数)
- 字体放 SD 卡(seek 比 Flash 稍快)
- 去掉`outline`(省 50% 时间)

### 修改字体后字形还是旧的

**两层缓存**:

1. **浏览器**:字体文件有 1 小时 HTTP 缓存。Ctrl+Shift+R 硬刷新
2. **设备**:`_font_cache`缓存了字体对象。调`clear_font_cache()`

```python
from text_renderer import clear_font_cache
clear_font_cache()
```

如果添加了**新字体文件**(不是覆盖),还需要重新生成索引:

```python
import build_font_index
build_font_index.build()
```

## 网络问题

### `/fonts/list`超时 /`Connection reset`

**现象**:打开`/text`页面,字体下拉一直加载中,或者报`ERR_CONNECTION_RESET`。

**原因**:`/fonts_index.json`不存在,`/fonts/list`退化为现场扫描目录(1710 个文件,几秒内扫不完,HTTP 超时)。

**解决**:

```python
import build_font_index
build_font_index.build()
```

完成后确认:

```python
import os
os.stat('/fonts_index.json')[6]
3512    # 几 KB
```

### 设备连不上 WiFi

**排查**:

```python
# 1. 能看到目标网络吗?
import wifi_manager
for ssid, rssi, auth in wifi_manager.scan_networks():
    print(f'{ssid:30s} {rssi:4d} dBm')
# 看不到 → 信号太弱或不在范围;或者是 5GHz(ESP32-C3 只支持 2.4GHz)

# 2. 手动连接
wifi_manager.connect_sta('cce', '12345678')
[STA] 尝试连接 cce(第 1/3 次)...
[STA] 已连接 cce, http://192.168.8.240
```

**常见原因**:

- **5GHz 网络**:ESP32-C3 只支持 2.4GHz
- **密码错误**:注意大小写,某些路由器对特殊字符敏感
- **信号太弱**:RSSI 低于 -80 dBm 时连接不稳定
- **WPA3**:不支持,需要路由器兼容 WPA2

### STA 连接后 IP 是 0.0.0.0

**原因**:DHCP 还没完成。`isconnected()`返回 True 但 IP 还没分配。

**解决**:等 5 秒再读 IP:

```python
import network, time
sta = network.WLAN(network.STA_IF)
start = time.time()
while sta.ifconfig()[0] == '0.0.0.0' and time.time() - start < 10:
    time.sleep(0.5)
print(sta.ifconfig()[0])
192.168.8.240
```

### 上传大文件时`Connection reset`

**原因**:设备是单连接阻塞服务器,同时间只能处理一个请求。多个并发请求会排队/超时。

**排查**:看是否有其他标签页在同时请求。

**解决**:

- 关闭其他浏览器标签页
- 上传期间不要操作其他页面
- 前端已经做了串行队列,但跨标签页的互斥还没实现

## GPIO 开关问题

### GPIO20/21 读数永远是 0

**原因**:上拉/下拉配置与接线方向不匹配。

**排查**:

```python
from machine import Pin
p20 = Pin(20, Pin.IN, Pin.PULL_UP)
print(p20.value())
```

- **断开开关读到 0**→ 外部有下拉或短路,检查接线
- **连通开关读到 0**→ 正常(接 GND 时应读 0)

如果你把开关另一端接的是**VCC**而不是 GND,需要改`boot_screen.py`:

```python
MODE_PIN_PULL = Pin.PULL_DOWN
MODE_ACTIVE_VALUE = 1
```

详见[hardware.md](hardware.md)的"为什么拨动开关接 GND"。

### GPIO20/21 读数乱跳(0/1 混着)

**原因**:**UART0 占用引脚**。用 UART 桥接板做 REPL 时,GPIO20/21 被 UART0 的数据信号干扰。

**排查**:

```python
import test_gpio
test_gpio.test_uart0()
```

**解决**:

1. **优先方案**:改用原生 USB Serial JTAG(如果有 USB-C 直连 ESP32-C3)
2. **备选方案**:释放 UART0(牺牲串口日志):

```python
# boot.py 开头
from machine import UART
try:
    UART(0).deinit()
except Exception:
    pass
```

之后只能通过 USB 或者重新烧录来连接 REPL(串口日志消失)。

### 开关选择但屏幕没变化

**排查顺序**:

```python
# 1. 直接跑模式,绕过 GPIO
import boot_screen
boot_screen.run_mode(3)   # 强制跑模式 11

# 2. 检查模式 00(无动作)—— 本来就不显示
boot_screen._read_mode()
0    # 两个都断开,正常不显示

# 3. 检查模式 01(随机)—— 看 bins 库
import os
len([n for n in os.listdir('/bins') if n.endswith('.bin')])
0    # 空库,没东西可显示

# 4. 检查模式 11(指定)—— 看配置文件
import boot_screen
boot_screen.get_designated()
{}   # 没设置,回退到序号最大的
```

## 内存问题

### `MemoryError`频繁出现

**排查**:

```python
import gc
gc.collect()
print('free:', gc.mem_free())
free: 15234
```

**`free`判断标准**:

| free | 状态 |
| --- | --- |
| > 60KB | 健康 |
| 30~60KB | 正常 |
| 15~30KB | 紧张,注意 |
| < 15KB | 危险,可能随时 OOM |

**解决**:

1. **重启设备**(软重启比`gc.collect()`更彻底)
2. **减小`band_rows`**(8 → 4,内存减半)
3. **减少`per_char`条目**(每个样式字典占 200~500 字节)
4. **清字体缓存**

```python
from text_renderer import clear_font_cache
clear_font_cache()
```

### 渲染中途 OOM

**现象**:正常文本(比如 100 字符)渲染到一半报`MemoryError`。

**原因**:

- `band_rows`太大(默认 8,内存紧张时需要 4 或 2)
- 加了大量`per_char`样式
- 字体 chunk 太大

**解决**:

```python
render_and_display_stream(epd, text, band_rows=4, ...)
```

如果还不行,改成 2 或 1。代价是循环次数增加,总时间可能长 10~30%。

### 堆碎片严重

**现象**:`gc.mem_free()`显示还有很多,但`MemoryError`频繁。

**排查**:

```python
import micropython
micropython.mem_info()
GC: total: 222112, used: 45000, free: 177112
 No. of 1-blocks: 892, 2-blocks: 45, 3-blocks: 12
```

**1-blocks 数量超过 800**→ 碎片严重。

**解决**:**软重启设备**。碎片无法通过`gc.collect()`彻底清理,MicroPython 的 GC 不做内存压缩。软重启是唯一有效的方法。

## 上传问题

### 上传 BIN 一直卡住

**现象**:`POST /bins/upload/{slot}`迟迟不返回。

**可能原因**:

1. 传输速度太慢(USB 线、WiFi 信号差)
2. 存储空间不足
3. 设备端写入时 OOM

**排查**:

```python
# 检查存储空间
import os
st = os.statvfs('/bins')
print('Free:', st[0] * st[3] // 1024, 'KB')
```

**解决**:

- 检查 WiFi 信号(RSSI 低于 -75 可能有问题)
- 清理旧 BIN(删除不用的)
- 重新上传一次(可能是网络抖动)

### `MPY: soft reboot`循环

**现象**:设备反复重启,REPL 一直打印`MPY: soft reboot`。

**原因**:启动代码崩溃触发 watchdog,自动重启。

**排查**:在 REPL 里按 Ctrl+C 打断启动,看完整 traceback:

```text
# 设备不断重启,连不上 REPL
# 用以下方法:
```

**救急方案**:

1. 先拔电
2. 按住 GPIO0 或类似方式进 Bootloader(取决于你的板子)
3. 用`mpremote`或者`esptool`擦除并重新烧录 MicroPython 固件
4. 重新上传代码,但**先不传有问题的那份**

如果只是某个文件有问题,可以只上传到临时目录测试:

```bash
mpremote cp 可疑文件.py :/tmp/test.py
mpremote run /tmp/test.py
```

确认没问题后再替换正式文件。

### `ValueError: incompatible.mpy file`

**原因**:`.mpy`编译时用的`mpy-cross`版本和设备固件不匹配。

**解决**:

```bash
pip install mpy-cross==1.28.0
python build_esp.py --clean
mpremote cp -r esp-x/* :
```

或者临时改成`.py`模式测试:

```bash
python build_esp.py --no-mpy --clean
```

## 开机模式问题

### 开机画面太慢(超过 2 分钟)

**优化**:

1. 去掉`outline`(省 50% 时间)
2. 去掉`bold`(省 30% 时间)
3. 减小字号(32 → 24)
4. 减少文本内容

详见[boot-modes.md](boot-modes.md)的"开机画面太慢"。

### 指定 BIN 不生效

**排查**:

```python
# 1. 配置文件存在吗?
import os
os.stat('/boot_cfg.json')
# 不存在 → 需要设置

# 2. 内容正确吗?
import json
print(json.load(open('/boot_cfg.json')))
{'storage': 'flash', 'index': 2}

# 3. 指定的 BIN 存在吗?
os.stat('/bins/2.bin')
# 报 OSError → BIN 被删了,需要重新指定
```

**解决**:重新在首页设置,或 REPL 里:

```python
import boot_screen
boot_screen.set_designated('flash', 2)
```

## 获取帮助

如果上面都没解决,提 [issue](https://github.com/lanyangyin/esp32c3supermini-JD7601-37-E6-480x720/issues)

**请提供以下信息**,能大幅提升排查效率:

```text
1. REPL 完整启动日志(从 MPY: soft reboot 到 [MAIN] 启动 Web 服务器)
2. 具体的错误信息(traceback 全文,不要只贴"报错了")
3. 硬件接线照片(如果能拍清楚)
4. 你最近改过什么
   - 上传了哪些文件
   - 是否改过源码
   - 是否换了硬件
5. 版本信息:
   import os
   os.uname()
   (sysname='esp32', nodename='esp32', release='1.28.0', ...)
6. 相关配置文件内容:
   print(open('/boot_cfg.json').read())
   print(open('/networks.json').read())
```
