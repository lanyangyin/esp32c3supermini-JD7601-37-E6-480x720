# 固件文件

此目录用于存放 MicroPython 固件 `.bin` 文件，便于本地烧录和版本管理。

固件文件**不入 Git**（见 `.gitignore` 中 `firmware/*.bin`），避免仓库膨胀和历史残留。你需要自己下载后放到这里。

## 下载地址

- **LOLIN C3 MINI 专用**：https://micropython.org/download/LOLIN_C3_MINI/
- 通用 ESP32-C3（如果专用固件不可用）：https://micropython.org/download/ESP32_GENERIC_C3/

## 推荐版本

**MicroPython v1.28.0** —— 与本项目的 `mpy-cross==1.28.0` 匹配。

文件形如 [`LOLIN_C3_MINI-20260406-v1.28.0.bin`](LOLIN_C3_MINI-20260406-v1.28.0.bin)，放到本目录即可。

## 烧录

```bash
esptool --chip esp32c3 --port <PORT> erase_flash
esptool --chip esp32c3 --port <PORT> write_flash -z 0x0 firmware/LOLIN_C3_MINI-20260406-v1.28.0.bin