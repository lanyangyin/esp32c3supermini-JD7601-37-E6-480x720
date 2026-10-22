# 开机模式详解

设备启动时会读取**GPIO20 + GPIO21**两个拨动开关的组合,执行对应动作。这个设计让设备无需联网、无需电脑,仅靠物理开关就能切换启动行为——比如日常用"无动作"快速进 Web 管理,展览时用"指定 BIN"直接展示画面。

本文档覆盖:四种模式的行为、硬件接线、完整时序、指定 BIN 配置文件、REPL 调试方法、以及常见的开关读数问题。

## 四种模式

| GPIO20 | GPIO21 | 模式 | 二进制 | 动作 | 显示时机 |
| --- | --- | --- | --- | --- | --- |
| 断开 | 断开 | 00 | 0b00 | 什么都不做 | — |
| 断开 | 连通 | 01 | 0b01 | 随机显示一个 BIN | 先显示 → 再连 STA |
| 连通 | 断开 | 10 | 0b10 | 显示网络信息 | 先连 STA → 后显示 |
| 连通 | 连通 | 11 | 0b11 | 显示指定 BIN | 先显示 → 再连 STA |

**语义**:`1 = 开关连通(短接到 GND)`。

- `1`对应代码里`MODE_ACTIVE_VALUE = 0`——内部`PULL_UP`时,开关连通把引脚拉到 0,Git 代码把这个 0 解读为"逻辑 1(连通)"
- `0`对应"开关断开"——内部上拉保持高电平

为什么把"读到 0"映射为"逻辑 1"?这是为了让模式表的语义更直观:开关拨到"开"位置就是 1,拨到"关"位置就是 0。而不是"读到 0 就是 0"那种反直觉。

## 硬件接线

```text
GPIO20 ──[ 开关 A ]── GND
GPIO21 ──[ 开关 B ]── GND
```

两个开关都是**单刀单掷**,一端接 GPIO,另一端接 GND。断开时内部上拉保持 1,连通时短接到 GND 读到 0。

代码配置(`boot_screen.py`顶部):

```python
MODE_PIN_PULL = Pin.PULL_UP      # 内部上拉
MODE_ACTIVE_VALUE = 0             # 读到 0 = 开关连通
```

**如果开关另一端接的是 VCC**,配置要反过来:

```python
MODE_PIN_PULL = Pin.PULL_DOWN
MODE_ACTIVE_VALUE = 1
```

详细接线图、GPIO20/21 的 UART0 冲突分析见 **[hardware.md](hardware.md)**。

## 启动时序

### 模式 00 — 什么都不做

```text
boot.py            挂载 SD (< 3 秒)
  ↓
main.py
  ├─ 读 GPIO → 00
  ├─ 连接 STA (10~80 秒)
  ├─ 启动 AP
  └─ 启动 Web 服务器 (永久阻塞)
```

**总启动时间**:约 10~80 秒(主要看 STA 连接快慢)。屏幕保持断电前最后的画面。

适合:日常使用。开机后立刻能通过浏览器管理,不占用屏幕。

### 模式 01 — 随机 BIN

```text
main.py
  ├─ 读 GPIO → 01
  ├─ 从 bins 库随机选一张
  ├─ 显示到屏幕 (30~60 秒)      ← 不等 STA,先显示
  ├─ 连接 STA (10~80 秒)
  ├─ 启动 AP
  └─ 启动 Web 服务器
```

**总启动时间**:约 40~140 秒。其中"显示"和"连接 STA"是**串行**执行,不并行。

适合:日常展示。每次开机随机显示一张收藏的图片,有点"盲盒"的感觉。

### 模式 10 — 网络信息

```text
main.py
  ├─ 读 GPIO → 10
  ├─ 连接 STA (10~80 秒)         ← 必须先连 STA
  ├─ 启动 AP
  ├─ 显示网络信息 (60~130 秒)    ← 才能显示正确的 IP
  └─ 启动 Web 服务器
```

**总启动时间**:约 70~210 秒。

适合:首次配置、排查网络。开机画面会显示当前 AP/STA 的 SSID、密码、IP,即使手边没有电脑也能知道怎么连接。

**为什么必须先连 STA**:网络信息里包含 STA 的 SSID 和 IP,如果先显示后连 STA,画面上只能显示占位符`(not connected)`和`0.0.0.0`,毫无意义。所以模式 10 的时序和其他模式相反。

### 模式 11 — 指定 BIN

```text
main.py
  ├─ 读 GPIO → 11
  ├─ 从配置文件读指定 BIN 路径
  ├─ 显示指定 BIN (30~60 秒)     ← 不等 STA,先显示
  ├─ 连接 STA (10~80 秒)
  ├─ 启动 AP
  └─ 启动 Web 服务器
```

**总启动时间**:约 40~140 秒。和模式 01 一样,先显示后 STA。

适合:固定展示某个内容——比如会议室门口的"今日会议"、家庭中控的固定面板。配置一次,之后每次开机都自动显示。

**未指定时**回退到"bins 里序号最大的一个",这样即使忘了配置也不会黑屏。

### 时序对比

```text
模式 00:  [读GPIO][----STA----][AP][Web]
模式 01:  [读GPIO][--显示--][----STA----][AP][Web]
模式 10:  [读GPIO][----STA----][AP][--显示--][Web]
模式 11:  [读GPIO][--显示--][----STA----][AP][Web]
```

**关键设计**:01/11 把"显示"放在 STA 之前,因为**显示不依赖网络**。这样:

- 屏幕刷新期间 WiFi 没连接,不受干扰
- 用户等待屏幕的 60 秒里,STA 在后台准备——虽然 MicroPython 单线程不能真并行,但逻辑上"先做不需要等的事"更合理
- 即使 WiFi 完全连不上(比如路由器关了),屏幕依然能正常刷新,只是进不了 Web

模式 10 反过来,因为显示内容依赖 WiFi 状态。

## 指定 BIN 配置文件

文件:`/boot_cfg.json`

格式:

```json
{"storage": "flash", "index": 2}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| storage | string | "flash" 或 "sd" |
| index | int | 槽位号(0-based,界面上显示为"槽位 N+1") |

文件不存在、格式错误、或指向的 BIN 已被删除,都会回退到"序号最大的 BIN"。

### 通过 Web 设置

1. 打开`http://192.168.4.1/`(AP)或 STA IP
2. 首页找到"开机指定 BIN"紫色面板
3. 每个 BIN 卡片上有`开机`按钮
4. 点一下 → 该 BIN 边框变紫 +`★ 开机`标记
5. 再点一次或点面板"清除指定" → 恢复

设置后**立即写入**`/boot_cfg.json`,下次重启生效。

### 通过 REPL 设置

```python
import boot_screen

# 设置 Flash 槽位 3(内部 0-based index=2,界面显示"槽位 3")
boot_screen.set_designated('flash', 2)
[BOOT] 已设置开机指定: flash 槽位 3

# 设置 SD 槽位 1(index=0)
boot_screen.set_designated('sd', 0)
[BOOT] 已设置开机指定: sd 槽位 1

# 查看
boot_screen.get_designated()
{'storage': 'flash', 'index': 2}

# 清除
boot_screen.clear_designated()
[BOOT] 已清除开机指定
```

### 通过 HTTP 设置

```bash
# 设置
curl -X POST -H "Content-Type: application/json" \
     -d '{"storage":"flash","index":2}' \
     http://192.168.4.1/boot/bin
# → OK

# 查看
curl http://192.168.4.1/boot/bin
# → {"storage":"flash","index":2,"defined":true}

# 清除
curl -X POST -H "Content-Type: application/json" \
     -d '{}' \
     http://192.168.4.1/boot/bin
# → cleared
```

## 开关检测逻辑

`boot_screen._read_mode()`的实现:

```python
def _read_mode():
    # 1. 初始化两个引脚,内部上拉
    pa = Pin(20, Pin.IN, Pin.PULL_UP)
    pb = Pin(21, Pin.IN, Pin.PULL_UP)

    # 2. 等引脚稳定(机械开关有触点抖动)
    time.sleep_ms(100)

    # 3. 各采样 10 次
    sa = [pa.value() for _ in range(10)]
    sb = [pb.value() for _ in range(10)]

    # 4. 多数表决:如果 10 次里过半读到 0,判定为"连通(逻辑 1)"
    va = 1 if sum(1 for v in sa if v == 0) > 5 else 0
    vb = 1 if sum(1 for v in sb if v == 0) > 5 else 0

    # 5. 组合成 2 位二进制数
    return (va << 1) | vb
```

**为什么采样 10 次**:机械开关接通瞬间有 1~20ms 的抖动(快速通断),单次读取可能随机得到 0 或 1。多次采样 + 多数表决能稳定判定。

**100ms 延迟**:从`Pin()`初始化到第一次读取,等 100ms 让内部上拉把引脚电压拉到稳定值。太短可能读到过渡态。

## REPL 调试

### 读当前模式

```python
import boot_screen
mode = boot_screen._read_mode()
[BOOT] GPIO20 采样 [1,1,1,1,1,1,1,1,1,1] → 0
[BOOT] GPIO21 采样 [0,0,0,0,0,0,0,0,0,0] → 1
print(mode)
1   # 01 模式
```

采样值`[0,0,...]`表示 10 次全读到低电平,即开关连通。`_read_mode()`返回的`0/1`是**逻辑值**(已转成"连通=1"),不是原始电平。

### 强制指定模式(跳过 GPIO 检测)

```python
boot_screen.run_mode(0)  # 什么都不做
boot_screen.run_mode(1)  # 随机 BIN
boot_screen.run_mode(2)  # 网络信息
boot_screen.run_mode(3)  # 指定 BIN
```

`run_mode()`不读 GPIO,直接执行对应动作。用于测试代码路径,或者临时刷屏。

### 单引脚检查

```python
from machine import Pin
p20 = Pin(20, Pin.IN, Pin.PULL_UP)
p21 = Pin(21, Pin.IN, Pin.PULL_UP)
print('GPIO20 =', p20.value())  # 断开=1,连通=0
print('GPIO21 =', p21.value())
```

### 持续监控(手动拨动开关观察变化)

```python
import test_gpio
test_gpio.watch()
```

输出:

```text
================================================================
持续监控 GPIO20/21(Ctrl+C 停止)
请手动拨动开关,观察读数变化
================================================================
[12345] GPIO20=1 GPIO21=1 → 00 无动作
[23456] GPIO20=0 GPIO21=1 → 10 网络
[34567] GPIO20=0 GPIO21=0 → 11 指定
[45678] GPIO20=1 GPIO21=0 → 01 随机
^C
[watch] 已停止
```

## 常见问题

### 读数永远是 1(断开方向)

**开关没接通**——用万用表量开关通断,或换个开关试。

### 读数永远是 0(连通方向)

两种可能:

1. **开关没断开**——检查开关是否真的在"关"位置
2. **UART0 占用引脚**——用 UART 桥接板做 REPL 时,GPIO20/21 被 UART0 独占,读到的是 UART 空闲电平

判断方法:

```python
import test_gpio
test_gpio.test_uart0()
```

如果多个测试都显示同样的读数,且与手动拨动开关无关,基本可以确认是 UART0 占用。解决方案:换用原生 USB Serial JTAG 做 REPL,或者`UART(0).deinit()`释放引脚。

### 读数乱跳(0/1 混着)

**确定是 UART0 占用**。UART0 在收发数据时会拉低/拉高引脚,和开关信号叠加。

解决方案同上一节。

### 开关接 VCC 时读数不对

`boot_screen.py`默认配置是"接 GND + PULL_UP"。如果开关另一端接的是 VCC,需要改:

```python
MODE_PIN_PULL = Pin.PULL_DOWN
MODE_ACTIVE_VALUE = 1
```

改完后读数语义不变:连通(短接 VCC)=逻辑 1,断开(内部下拉)= 逻辑 0。

### 开机画面太慢(超过 2 分钟)

字体大小、`outline`、`bold`是三大耗时因素。三个方法:

- **去掉 outline**:`default_style.outline = None`(省 50% 时间)
- **去掉 bold**:`per_char`里不加`bold`(省 30%)
- **减小字号**:`size=32`→`24`(省 40%)

模式 01/11 的显示时间会减半,因为不需要等 STA。

### 开关选择但屏幕没变化

按顺序检查:

1. **模式 00**→ 不显示是正常的
2. **模式 01**→ 检查`bins`库是否有内容(`os.listdir('/bins')`)
3. **模式 11**→ 检查配置文件`/boot_cfg.json`是否存在,指定的 BIN 是否被删
4. **模式 10**→ 检查屏幕是否正常(用`boot_screen.run_mode(2)`手动触发一次)

如果`run_mode`能正常刷屏,但`check_and_run`不刷,说明 GPIO 检测有问题。

### 想跳过开机画面直接进 Web

把两个开关都拨到"断开"(模式 00),或者临时注释掉`main.py`里的`boot_screen.run_mode()`。

REPL 里也可以:

```python
import web_server
web_server.start_server()  # 跳过 main.py 后续步骤,直接启动 Web
```

---

## 参考

- `boot_screen.py`— 模式检测和动作实现
- `main.py`— 编排逻辑(决定了启动顺序)
- `test_gpio.py`— GPIO 诊断工具
- [hardware.md](hardware.md)— GPIO20/21 的 UART0 冲突详解

