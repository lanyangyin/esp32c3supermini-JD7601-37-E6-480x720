# 硬件接线与电源

本文档详细说明 ESP32-C3 SuperMini + JD7601 墨水屏 + SD 卡 + 拨动开关的完整接线方案，包括引脚选择理由、电源要求和常见接线错误。

面向初次搭硬件，或屏幕不亮、SD 卡挂载失败、开关读数异常等情况。如果你只是想快速上手，README 里的引脚速查表已经够用。

## 元件清单

| 元件 | 型号 | 关键参数 |
| --- | --- | --- |
| 主控 | LOLIN C3 MINI | ESP32-C3FH4，4MB Flash，400KB SRAM，原生 USB Serial JTAG |
| 墨水屏 | JD7601 | 480×720，Spectra 6 六色（黑/白/黄/红/蓝/绿） |
| 存储 | MicroSD 卡 | FAT32，建议 8GB 或以下（大容量卡兼容性差） |
| 开关 | 拨动开关 × 2 | SPDT 或 SPST 均可，用于开机模式选择 |
| 电源 | USB-C 5V / 1A 以上 | 通过 C3 MINI 板载 LDO 供 3.3V |

## 引脚分配

### 屏幕：JD7601（SoftSPI）

| 屏幕引脚 | ESP32-C3 | 方向 | 说明 |
| --- | --- | --- | --- |
| SCK | GPIO4 | 输出 | SPI 时钟 |
| MOSI（DIN） | GPIO6 | 输出 | SPI 数据输入到屏幕 |
| CS | GPIO3 | 输出 | 片选，低电平有效 |
| DC | GPIO9 | 输出 | 数据/命令选择，低=命令，高=数据 |
| RST | GPIO8 | 输出 | 复位，低电平有效 |
| BUSY | GPIO2 | 输入 | 忙状态，低电平=忙，需内部上拉 |
| GND | GND | — | 地 |
| VCC | 3.3V | — | 电源（不要接 5V） |

### SD 卡：硬件 SPI slot=2

| SD 引脚 | ESP32-C3 | 方向 | 说明 |
| --- | --- | --- | --- |
| SCK（CLK） | GPIO10 | 输出 | SPI 时钟 |
| MOSI（CMD） | GPIO7 | 输出 | 主机到卡 |
| MISO（DAT0） | GPIO1 | 输入 | 卡到主机 |
| CS（DAT3） | GPIO5 | 输出 | 片选 |
| GND | GND | — | 地 |
| VCC | 3.3V | — | 电源（不要接 5V） |

### 拨动开关

| 开关 | GPIO | 另一端 | 说明 |
| --- | --- | --- | --- |
| 开关 A（高位） | GPIO20 | GND | 对应模式的 bit1 |
| 开关 B（低位） | GPIO21 | GND | 对应模式的 bit0 |

### 引脚占用总表

| GPIO | 用途 | 可复用 |
| --- | --- | --- |
| 1 | SD MISO | ❌ |
| 2 | 屏幕 BUSY | ❌ |
| 3 | 屏幕 CS | ❌ |
| 4 | 屏幕 SCK | ❌ |
| 5 | SD CS | ❌ |
| 6 | 屏幕 MOSI | ❌ |
| 7 | SD MOSI | ❌ |
| 8 | 屏幕 RST | ❌ |
| 9 | 屏幕 DC | ❌ |
| 10 | SD SCK | ❌ |
| 18 | USB D- | ❌（原生 USB） |
| 19 | USB D+ | ❌（原生 USB） |
| 20 | 开关 A / UART0 RX | ⚠️ 见下文 |
| 21 | 开关 B / UART0 TX | ⚠️ 见下文 |
| 0 | 未使用 | ⚠️ Boot strapping 引脚，不要拉低 |

## 引脚选择理由

### 为什么屏幕用 SoftSPI 而不是硬件 SPI

JD7601 是**只写不读**的设备，不需要 MISO，也不需要硬件 SPI 的读写双向能力。用`machine.SoftSPI`有三个好处：

1. **不占用硬件 SPI 资源**—— 硬件 SPI 留给 SD 卡（需要真正的 SPI host）
2. **引脚可自由指定**——`SoftSPI`允许任意 GPIO 做 SCK/MOSI，方便布线
3. **速度够用**—— 1MHz SoftSPI 在 ESP32-C3 上足够驱动 JD7601，瓶颈在屏幕自身的刷新时间（30~60 秒），不在 SPI 传输

代价：SoftSPI 是纯 Python 实现，速度比硬件 SPI 慢，但不影响实际体验。

**miso 占位**：`SoftSPI`构造时强制要求`sck`、`mosi`、`miso`三个参数。屏幕不读数据，`miso`用 GPIO0 占位。**GPIO0 是 ESP32-C3 的 Boot strapping 引脚**（上电时必须高电平），但 SoftSPI 只把它当占位引脚，不会真正驱动它，所以不影响启动。

### 为什么 SD 卡用 slot=2

ESP32-C3 有两个 SPI 控制器：

| 控制器 | 用途 |
| --- | --- |
| SPI0 | 接板载 Flash（不可用） |
| SPI1 | 接 PSRAM（C3 没有 PSRAM，但被预留） |
| SPI2 | 通用 SPI |

`machine.SDCard(slot=2)`明确使用 SPI2，避免与 Flash 冲突。

**`freq=400_000`**：SD 卡初始频率建议 400kHz（低速容错性最好）。等初始化成功后再切到高速（如果`sd_helper.py`里有实现）。太快容易在初始化阶段出错。

### 为什么拨动开关接 GND

两种接法对比：

| 接法 | 内部配置 | 断开读数 | 连通读数 | 风险 |
| --- | --- | --- | --- | --- |
| 接 GND | PULL_UP | 1 | 0 | 低 |
| 接 VCC | PULL_DOWN | 0 | 1 | 中 |

**选接 GND 的原因**：

- GPIO20/21 默认是 UART0 的 RX/TX，接 VCC 时如果代码误配为输出会短路
- 接 GND 后配合内部上拉是标准做法，任何意外情况最多读到 0，不会烧芯片
- 断开的引脚被内部上拉保持高电平，抗干扰能力强

代码对应：

```
MODE_PIN_PULL = Pin.PULL_UP
MODE_ACTIVE_VALUE = 0
```

如果你的开关已经接成了 VCC，把这两行改成：

```
MODE_PIN_PULL = Pin.PULL_DOWN
MODE_ACTIVE_VALUE = 1
```

## GPIO20/21 特别注意

这两个引脚是**UART0 的 RX/TX**。能不能用作普通 IO，取决于你的 REPL 走哪条通道。

### 情况 A：原生 USB Serial JTAG（推荐，LOLIN C3 MINI 默认）

LOLIN C3 MINI 的 USB-C 直接连到 ESP32-C3 的原生 USB 控制器（GPIO18/19）。这时：

- REPL 走 USB，不占用 UART0
- **GPIO20/21 完全空闲**，可以安全用作拨动开关输入
- 串口日志和 REPL 走 USB 虚拟串口

**这是推荐配置**，绝大多数用户就是这个情况。

### 情况 B：UART 桥接板（部分第三方 C3 SuperMini 板）

某些板子用 CH340/CP2102 芯片做 USB 转串口，走的是 GPIO20/21（UART0）。这时：

- GPIO20/21 被 UART0 独占
- 拨动开关接上会导致串口通信异常
- 开关读数会乱跳（0/1 混着），因为 UART0 的数据干扰

**判断方法**：在 REPL 里跑

```
import test_gpio
test_gpio.test_uart0()
```

如果读数稳定且与手动拨动一致 → 情况 A。
如果读数乱跳 → 情况 B。

**情况 B 的两种解决方案**：

1. **改用 USB Serial JTAG**（如果有原生 USB 接口）—— 最干净
2. **释放 UART0**（牺牲 REPL 的串口日志）：

```
# boot.py 里，导入 SD 卡之前
from machine import UART
try:
    UART(0).deinit()
except Exception:
    pass
```

`UART(0).deinit()`把 GPIO20/21 从 UART 外设释放回普通 GPIO。之后可以用`Pin(20, Pin.IN, Pin.PULL_UP)`正常读取。代价是串口日志会消失，但 REPL 本身可以走 WebREPL 或 USB。

### 为什么不做 GPIO20/21 的硬件保护

**没有**加外部上拉电阻或保护二极管，因为：

- ESP32-C3 内部上拉（约 45kΩ）足够
- 拨动开关是机械触点，不会产生静电或反向电流
- 外部电阻增加焊接复杂度，对个人项目不划算

如果是长期运行或工业场景，建议加 10kΩ 外部上拉 + 100nF 到 GND 做 RC 去抖。

## 电源

### 电压要求

| 设备 | 电压 | 容许范围 |
| --- | --- | --- |
| ESP32-C3 | 3.3V（板载 LDO 输出） | 3.0~3.6V |
| JD7601 屏幕 | 3.3V | 3.0~3.6V，绝对不要 5V |
| SD 卡 | 3.3V | 2.7~3.6V |

C3 MINI 板载 USB-C 接收 5V，通过 LDO 转 3.3V 给芯片和所有外设。

### 电流需求

| 场景 | 电流 | 说明 |
| --- | --- | --- |
| 空闲（WiFi 待机） | 约 40mA | 屏幕不刷新，WiFi 保持连接 |
| WiFi 连接/传输 | 120mA 峰值 | 瞬态，持续几毫秒 |
| 屏幕刷新 | 30mA | JD7601 刷新时的电流 |
| SD 卡读写 | 100mA 峰值 | 短时突发 |
| 综合峰值 | 约 250mA | 屏幕刷新 + WiFi + SD 读写同时 |

**建议 USB 电源 500mA 以上**。劣质 USB 线或充电头在 WiFi 峰值时可能掉电，导致设备重启。

### 去耦电容

如果遇到"偶尔重启"或"SD 卡挂载偶发失败"，在 3.3V 和 GND 之间加：

- **100μF 电解电容**（稳压，抗突发电流）
- **0.1μF 陶瓷电容**（高频去耦）

尽量靠近 ESP32-C3 的 3V3 引脚和 SD 卡的 VCC 引脚。

### 电池供电

不推荐。C3 在 WiFi 峰值时电流达 120mA，而 JD7601 刷新 30~60 秒期间电流也不低。普通 3.7V 锂电池 + LDO 方案在 WiFi 峰值时电压可能跌到 3.0V 以下，触发棕色复位（brownout reset）。

如果一定要电池供电：

- 加 470μF 以上储能电容
- 用低压差 LDO（如 AMS1117-3.3，压差 1.1V）
- 屏幕刷新期间关闭 WiFi（本项目的默认流程已经是这样：模式 01/11 先显示再连 WiFi）

## 接线检查清单

屏幕不亮、SD 卡挂载失败、开关读数异常时，按顺序检查：

### 1. 电源

- 万用表量 3.3V 引脚，应该是 3.3±0.2V
- 上电瞬间看电压是否跌落（如果跌到 3.0V 以下说明电源不够）
- USB 线换成短的、粗的（充电线有时候比数据线更粗，电压更稳）

### 2. 屏幕初始化

REPL 里跑：

```
from jd7601 import JD7601
epd = JD7601()
epd.init()
```

预期：

- `init()`期间屏幕 BUSY 引脚有短暂的拉低动作（万用表可以量到跳变）
- `init()`返回后不报错

如果`init()`后屏幕完全没反应，说明 SPI 或复位没接好。

### 3. 屏幕刷测试

```
epd.begin_frame()
for _ in range(480):
    epd.write_chunk(b'\x00' * 360)   # 全黑
epd.end_frame()
epd.sleep()
```

大约 40~60 秒后屏幕应该变全黑。如果还是原样 → SPI 不通或复位没成功。

### 4. SD 卡挂载

```
import sd_helper
sd_helper.mount_sd()
[SD] mounted at /sd (hardware SPI)
sd_helper.is_sd_active()
True
```

返回`False`或报错 → 见"常见硬件问题"。

### 5. 拨动开关

```
import test_gpio
test_gpio.test()
```

如果读数稳定且与手动拨动一致 → 开关和 GPIO 都 OK。

## 常见硬件问题

### 屏幕显示全黑 / 花屏

**症状**：刷屏后屏幕不变，或者变成一半黑一半白、条纹等异常图案。

**按可能性排序排查**：

1. **SPI 引脚接错**—— 对照上面引脚表逐个检查。`jd7601.py`里`__init__`的默认参数就是接线标准
2. **BUSY 引脚接法错误**—— BUSY 应该接到 GPIO2，内部`PULL_UP`。**不要**接 VCC（永远"忙"），也**不要**接 GND（永远"闲"但可能导致时序问题）
3. **复位时序**—— 部分 JD7601 模块需要更长的复位低电平（比如 100ms 而不是 20ms）。可以改`jd7601.py`里`init()`的`time.sleep_ms`
4. **电源电压不足**—— 万用表量 3.3V，低于 3.1V 屏幕可能初始化失败

### 屏幕显示全黑（正确）但下一秒变白

**原因**：屏幕刷完后进入了错误的休眠状态，或者`sleep()`命令发送时机不对。

**解决**：检查`jd7601.py`的`end_frame()`：

```
def end_frame(self):
    self._cmd(0x04); self._wait(10000); time.sleep_ms(10)
    self._cmd(0x12); self._data(bytes([0x00])); time.sleep_ms(10); self._wait(40000)
    self._cmd(0x02); self._data(bytes([0x00])); self._wait(2000); time.sleep_ms(20)
```

如果`0x02`（Power Off）命令发送后没等够时间，屏幕可能进入未定义状态。可以试着把`_wait(2000)`改成`_wait(4000)`。

### SD 卡挂载失败

**按可能性排序**：

1. **卡格式不是 FAT32**—— exFAT 和 NTFS 都**不支持**。用电脑重新格式化为 FAT32
2. **卡容量太大**—— 32GB 以上的卡在 MicroPython 上兼容性差。建议 8GB 或以下
3. **电源不足**—— SD 卡初始化峰值电流可能 100mA，3.3V 电压跌落会导致初始化失败
4. **CS 引脚接错**—— 检查是否接到 GPIO5
5. **SPI 频率太快**——`sd_helper.py`里`freq=400_000`是低速，如果还失败可以降到 100_000

**判断卡是否损坏**：换到电脑上看能不能读。

### 拨动开关读数永远不变

见上文 GPIO20/21 特别注意章节。总结：

- 读数永远是 1（断开方向） → 上拉正常，检查开关是否真的接通
- 读数永远是 0（连通方向） → 可能 UART0 占用引脚，跑`test_uart0()`
- 读数乱跳 → 确定是 UART0 占用，需要原生 USB 或`UART(0).deinit()`

### WiFi 信号差

- ESP32-C3 只有板载 PCB 天线，信号比 ESP32-WROOM 弱
- 尽量远离金属物体、电池、USB 3.0 线缆
- 天线方向：板载天线在 USB 接口的对面，使用时避免被手挡住
- STA 建议在 5 米内使用

### 设备频繁重启

- **电源问题**（最常见）：WiFi 峰值掉电。换 USB 线、加去耦电容
- **内存耗尽**：`gc.mem_free()`低于 20KB 时容易触发 watchdog。重启后观察
- **代码异常**：REPL 里看`machine.reset_cause()`的返回值

### 屏幕刷新时 WiFi 断开

**正常现象**。屏幕刷新期间（30~90 秒）CPU 全部占用，无法处理 WiFi 中断。刷新完成后 WiFi 会自动重连。

如果刷新时间超过 2 分钟，Web 请求会超时。这是设计限制，不是 bug。

## 参考数据

- ESP32-C3 数据手册：[https://www.espressif.com/sites/default/files/documentation/esp32-c3_datasheet_en.pdf](https://www.espressif.com/sites/default/files/documentation/esp32-c3_datasheet_en.pdf)
- LOLIN C3 MINI 引脚图：[https://www.wemos.cc/en/latest/c3/c3_mini.html](https://www.wemos.cc/en/latest/c3/c3_mini.html)
- MicroPython ESP32-C3 文档：[https://docs.micropython.org/en/latest/esp32/quickref.html](https://docs.micropython.org/en/latest/esp32/quickref.html)
- JD7601 数据手册：供应商提供（部分厂商只提供命令表，没有完整手册）

