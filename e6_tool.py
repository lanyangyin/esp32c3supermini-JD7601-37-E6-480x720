# e6_tool.py — E6 图片转换工具（720×480 横向，检查+上传合并）
import sys
import io
import copy
import json
from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import (
    QPixmap, QImage, QColor, QPainter, QPen, QPainterPath, QFont,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFileDialog, QMessageBox, QLineEdit, QGroupBox,
    QComboBox, QSlider, QCheckBox, QScrollArea, QColorDialog, QDialog,
    QDialogButtonBox,
)

# ★ 从 e6_image_core 包导入
from e6_image_core.dithering import (
    PALETTES, DITHER_MODES, dither, block_to_image, pack, quantize,
    palette_to_rgb, palette_to_device_rgb, palette_to_indices,
)
from e6_image_core.tone import apply_all

# ---------- 配置路径：存在 e6_image_core 目录下 ----------
# 新位置：项目内 e6_image_core/e6_tool_config.json
CONFIG_PATH = Path(__file__).parent / "e6_image_core" / "e6_tool_config.json"
# 旧位置（迁移来源）：用户主目录
LEGACY_CONFIG_PATH = Path.home() / ".e6_tool_config.json"

BUILTIN_PALETTES = copy.deepcopy(PALETTES)
current_palettes = copy.deepcopy(PALETTES)

FIT_MODES = [
    ("铺满（裁剪）", "cover"),
    ("完整显示（白边）", "contain"),
]

CANVAS_W, CANVAS_H = 720, 480


# ---------- 配置读写 ----------

def load_config():
    """
    优先读取 e6_image_core/e6_tool_config.json；
    如果新位置不存在，尝试从旧的 ~/.e6_tool_config.json 迁移（读+写）。
    """
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    if LEGACY_CONFIG_PATH.exists():
        try:
            with open(LEGACY_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            save_config(data)  # 迁移到新位置
            print(f"[config] migrated {LEGACY_CONFIG_PATH} -> {CONFIG_PATH}")
            return data
        except Exception:
            pass

    return {}


def save_config(data):
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------- 等比缩放 + 偏移裁切 ----------

def resize_fit(img, w, h, mode="cover", x_offset=None, y_offset=None):
    img = img.convert("RGB")
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        return Image.new("RGB", (w, h), (255, 255, 255))

    if mode == "cover":
        scale = max(w / iw, h / ih)
        nw = max(w, int(round(iw * scale)))
        nh = max(h, int(round(ih * scale)))
        resized = img.resize((nw, nh), Image.LANCZOS)
        max_x = nw - w
        max_y = nh - h
        ox = max_x // 2 if x_offset is None else max(0, min(max_x, int(x_offset)))
        oy = max_y // 2 if y_offset is None else max(0, min(max_y, int(y_offset)))
        return resized.crop((ox, oy, ox + w, oy + h))

    scale = min(w / iw, h / ih)
    nw = min(w, max(1, int(round(iw * scale))))
    nh = min(h, max(1, int(round(ih * scale))))
    resized = img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), (255, 255, 255))
    canvas.paste(resized, ((w - nw) // 2, (h - nh) // 2))
    return canvas


def cover_limits(img, w, h):
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    nw = max(w, int(round(iw * scale)))
    nh = max(h, int(round(ih * scale)))
    return nw - w, nh - h


def pil_to_qpixmap(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return QPixmap.fromImage(QImage.fromData(buf.getvalue(), "PNG"))


def clean_ip(text):
    ip = (text or "").strip()
    if ip.startswith("http://"):
        ip = ip[7:]
    elif ip.startswith("https://"):
        ip = ip[8:]
    return ip.rstrip("/")


# ---------- 导航图 ----------

def make_nav_image(rotated, fit_mode, x_offset, y_offset, nav_max_w=300, nav_max_h=200):
    W, H = CANVAS_W, CANVAS_H
    iw, ih = rotated.size

    if fit_mode == "cover":
        scale = max(W / iw, H / ih)
        nw = max(W, int(round(iw * scale)))
        nh = max(H, int(round(ih * scale)))
        full_w, full_h = nw, nh
    else:
        full_w, full_h = W, H

    nav_scale = min(nav_max_w / full_w, nav_max_h / full_h)
    nav_w = max(1, int(full_w * nav_scale))
    nav_h = max(1, int(full_h * nav_scale))

    nav = Image.new("RGB", (nav_w, nav_h), (210, 210, 210))

    if fit_mode == "cover":
        small = rotated.resize((int(iw * scale * nav_scale),
                                int(ih * scale * nav_scale)), Image.LANCZOS)
        nav.paste(small, (0, 0))

        view_x = int(x_offset * nav_scale)
        view_y = int(y_offset * nav_scale)
        view_w = max(1, int(W * nav_scale))
        view_h = max(1, int(H * nav_scale))

        overlay = Image.new("RGBA", nav.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.rectangle([0, 0, nav_w, view_y], fill=(0, 0, 0, 130))
        od.rectangle([0, view_y + view_h, nav_w, nav_h], fill=(0, 0, 0, 130))
        od.rectangle([0, view_y, view_x, view_y + view_h], fill=(0, 0, 0, 130))
        od.rectangle([view_x + view_w, view_y, nav_w, view_y + view_h], fill=(0, 0, 0, 130))
        nav = Image.alpha_composite(nav.convert("RGBA"), overlay).convert("RGB")

        d = ImageDraw.Draw(nav)
        d.rectangle([view_x, view_y, view_x + view_w - 1, view_y + view_h - 1],
                    outline=(255, 50, 50), width=2)
    else:
        s = min(W / iw, H / ih)
        nw = max(1, int(round(iw * s)))
        nh = max(1, int(round(ih * s)))
        ox = (W - nw) // 2
        oy = (H - nh) // 2
        small = rotated.resize((int(nw * nav_scale), int(nh * nav_scale)), Image.LANCZOS)
        nav.paste(small, (int(ox * nav_scale), int(oy * nav_scale)))

        d = ImageDraw.Draw(nav)
        d.rectangle([0, 0, nav_w - 1, nav_h - 1], outline=(150, 150, 150), width=1)

    return nav


# ---------- 带描边的颜色按钮 ----------

class ColorButton(QPushButton):
    def __init__(self, color_hex, parent=None):
        super().__init__(parent)
        self.setFixedSize(90, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.color_hex = "#000000"
        self.set_color(color_hex)
        self.clicked.connect(self._pick_color)

    def set_color(self, color_hex):
        self.color_hex = color_hex
        self.update()

    def get_color(self):
        return self.color_hex

    def _pick_color(self):
        dialog = QColorDialog(QColor(self.color_hex), self)
        dialog.setOption(QColorDialog.DontUseNativeDialog, True)
        dialog.setStyleSheet("""
            QColorDialog { background-color: #f5f5f5; }
            QColorDialog QLabel { color: #222; background: transparent; }
            QColorDialog QLineEdit { color: #222; background: #fff; border: 1px solid #bbb; }
            QColorDialog QSpinBox { color: #222; background: #fff; border: 1px solid #bbb; }
            QColorDialog QPushButton { color: #222; background: #e8e8e8; border: 1px solid #bbb; padding: 4px 10px; }
            QColorDialog QPushButton:hover { background: #dcdcdc; }
            QColorDialog QComboBox { color: #222; background: #fff; }
            QColorDialog QComboBox QAbstractItemView { color: #222; background: #fff; }
            QColorDialog QGroupBox { color: #222; }
        """)
        if dialog.exec() == QColorDialog.Accepted:
            new_color = dialog.currentColor().name()
            if new_color:
                self.set_color(new_color)
                self.clicked.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(self.color_hex))
        painter.setPen(QPen(QColor(100, 100, 100), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()
        text = self.color_hex
        text_rect = fm.boundingRect(text)
        x = (self.width() - text_rect.width()) / 2 - text_rect.left()
        y = (self.height() + fm.ascent() - fm.descent()) / 2
        path = QPainterPath()
        path.addText(x, y, font, text)

        painter.setPen(QPen(QColor(0, 0, 0), 2.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawPath(path)


# ---------- 调色板编辑器 ----------

def _label(text):
    lbl = QLabel(text)
    lbl.setStyleSheet("color: #222; font-weight: 600; background: transparent;")
    return lbl


class PaletteEditorDialog(QDialog):
    def __init__(self, palette_name, palette_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"编辑调色板 - {palette_name}")
        self.resize(760, 540)
        self.setStyleSheet("""
            QLabel { color: #222; }
            QLineEdit { color: #222; background: #fff; border: 1px solid #bbb; padding: 2px 4px; }
            QPushButton { color: #222; background: #e8e8e8; border: 1px solid #bbb; padding: 4px 10px; }
            QPushButton:hover { background: #dcdcdc; }
        """)
        self.palette_name = palette_name
        self.palette_data = copy.deepcopy(palette_data)
        self.result_data = None

        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.rows_container = QWidget()
        self.rows_container.setStyleSheet("background: #f5f5f5;")
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(6, 6, 6, 6)
        scroll.setWidget(self.rows_container)
        layout.addWidget(scroll)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("添加颜色")
        add_btn.clicked.connect(self.add_row)
        btn_layout.addWidget(add_btn)
        reset_btn = QPushButton("重置为内置")
        reset_btn.clicked.connect(self.reset_palette)
        btn_layout.addWidget(reset_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.render_rows()

    def render_rows(self):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, entry in enumerate(self.palette_data):
            row = QWidget()
            row.setStyleSheet("background: #f5f5f5;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 2, 0, 2)

            name_edit = QLineEdit(entry.get("name", f"color{i}"))
            name_edit.setFixedWidth(100)
            rl.addWidget(name_edit)

            rl.addWidget(_label("校准色:"))
            color_btn = ColorButton(entry.get("color", "#000000"))
            rl.addWidget(color_btn)

            rl.addWidget(_label("设备色:"))
            device_btn = ColorButton(entry.get("deviceColor", "#000000"))
            rl.addWidget(device_btn)

            rl.addWidget(_label("索引:"))
            idx_label = _label(f"0x{entry.get('index', 0):02X}")
            idx_label.setFixedWidth(50)
            rl.addWidget(idx_label)

            del_btn = QPushButton("×")
            del_btn.setFixedWidth(30)
            del_btn.setStyleSheet(
                "color: #c00; font-weight: bold; background: #fff; border: 1px solid #bbb;")
            rl.addWidget(del_btn)
            rl.addStretch()

            def make_updater(idx, ne, cb, db):
                def update():
                    if 0 <= idx < len(self.palette_data):
                        self.palette_data[idx]["name"] = ne.text()
                        self.palette_data[idx]["color"] = cb.get_color()
                        self.palette_data[idx]["deviceColor"] = db.get_color()
                return update

            updater = make_updater(i, name_edit, color_btn, device_btn)
            name_edit.textChanged.connect(updater)
            color_btn.clicked.connect(updater)
            device_btn.clicked.connect(updater)

            def make_deleter(idx):
                def delete():
                    if 0 <= idx < len(self.palette_data):
                        del self.palette_data[idx]
                        self.render_rows()
                return delete

            del_btn.clicked.connect(make_deleter(i))
            self.rows_layout.addWidget(row)

    def add_row(self):
        used = {p["index"] for p in self.palette_data}
        new_index = 0
        for candidate in [0x0, 0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7]:
            if candidate not in used:
                new_index = candidate
                break
        self.palette_data.append({
            "name": f"custom{len(self.palette_data)}",
            "color": "#000000",
            "deviceColor": "#000000",
            "index": new_index,
        })
        self.render_rows()

    def reset_palette(self):
        self.palette_data = copy.deepcopy(BUILTIN_PALETTES[self.palette_name])
        self.render_rows()

    def accept(self):
        self.result_data = self.palette_data
        super().accept()


# ---------- 数据源选择 ----------

class SourceSelectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择上传数据源")
        self.setFixedSize(420, 200)
        self.setStyleSheet("""
            QDialog { background: #f5f5f5; }
            QLabel { color: #222; }
            QPushButton { color: #222; background: #e8e8e8; border: 1px solid #bbb; padding: 6px 16px; }
            QPushButton:hover { background: #dcdcdc; }
        """)
        self.source = None

        layout = QVBoxLayout(self)
        title = QLabel("请选择要使用的数据：")
        title.setStyleSheet("color: #222; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        desc1 = QLabel("· Dithered：抖动·校准色（模拟真实观感）")
        desc1.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(desc1)

        desc2 = QLabel("· Device：设备原生色（实际写入硬件的像素）")
        desc2.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(desc2)

        layout.addSpacing(8)

        btn_row = QHBoxLayout()
        btn_dither = QPushButton("Dithered")
        btn_dither.clicked.connect(lambda: self._choose("dithered"))
        btn_row.addWidget(btn_dither)

        btn_device = QPushButton("Device")
        btn_device.clicked.connect(lambda: self._choose("device"))
        btn_row.addWidget(btn_device)

        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        layout.addLayout(btn_row)

    def _choose(self, source):
        self.source = source
        self.accept()


# ---------- 线程 ----------

class CheckWorker(QThread):
    finished = Signal(bool, str)

    def __init__(self, ip, timeout=4):
        super().__init__()
        self.ip = ip
        self.timeout = timeout

    def run(self):
        try:
            import requests
        except ImportError:
            self.finished.emit(False, "缺少 requests 库")
            return
        try:
            r = requests.get(f"http://{self.ip}/", timeout=self.timeout)
            if r.status_code == 200:
                self.finished.emit(True, "设备在线")
            else:
                self.finished.emit(False, f"HTTP {r.status_code}")
        except Exception as e:
            msg = str(e)
            if "timeout" in msg.lower() or "timed out" in msg.lower():
                msg = "连接超时"
            elif "refused" in msg.lower():
                msg = "连接被拒绝"
            elif "getaddrinfo" in msg.lower():
                msg = "地址解析失败"
            self.finished.emit(False, msg)


class UploadWorker(QThread):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, url, data):
        super().__init__()
        self.url = url
        self.data = data

    def run(self):
        try:
            import requests
            r = requests.post(self.url, data=self.data,
                              headers={"Content-Type": "application/octet-stream"},
                              timeout=120)
            self.finished.emit(f"{r.status_code} {r.text}")
        except Exception as e:
            self.failed.emit(str(e))


# ---------- 滑块行 ----------

class SliderRow(QWidget):
    def __init__(self, label, min_v, max_v, default, scale=100):
        super().__init__()
        self.scale = scale
        self.default = default
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(label), 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(min_v, max_v)
        self.slider.setValue(default)
        layout.addWidget(self.slider, 1)
        self.value = QLabel(self._fmt(default))
        self.value.setFixedWidth(50)
        layout.addWidget(self.value, 0)
        self.slider.valueChanged.connect(lambda v: self.value.setText(self._fmt(v)))

    def _fmt(self, v):
        return f"{v / self.scale:.2f}" if self.scale != 1 else str(v)

    def get(self):
        return self.slider.value() / self.scale

    def reset(self):
        self.slider.setValue(self.default)


# ---------- 主窗口 ----------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("E6 图片转换工具（720×480 横向）")
        self.resize(1400, 980)

        self.config = load_config()
        self.src_img = None
        self.rotation = 0
        self.worker = None
        self.check_worker = None

        self._upload_ip = ""

        self.fitted_img = None
        self.adjusted_img = None
        self.dithered_img = None
        self.device_img = None

        self.max_x = 0
        self.max_y = 0
        self._updating_offsets = False

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        left = QScrollArea()
        left.setWidgetResizable(True)
        left.setFixedWidth(380)
        left_w = QWidget()
        ll = QVBoxLayout(left_w)

        self.btn_choose = QPushButton("选择图片…")
        self.btn_choose.clicked.connect(self.on_choose)
        ll.addWidget(self.btn_choose)

        canvas_group = QGroupBox("画布 720×480")
        cg = QVBoxLayout(canvas_group)
        fit_row = QHBoxLayout()
        fit_row.addWidget(QLabel("填充方式:"))
        self.fit_combo = QComboBox()
        for name, _ in FIT_MODES:
            self.fit_combo.addItem(name)
        fit_row.addWidget(self.fit_combo)
        cg.addLayout(fit_row)
        ll.addWidget(canvas_group)

        offset_group = QGroupBox("裁切偏移（铺满模式）")
        og = QVBoxLayout(offset_group)

        x_row = QHBoxLayout()
        x_row.addWidget(QLabel("X 偏移:"))
        self.x_slider = QSlider(Qt.Horizontal)
        self.x_slider.setRange(0, 0)
        self.x_slider.setValue(0)
        x_row.addWidget(self.x_slider, 1)
        self.x_label = QLabel("0")
        self.x_label.setFixedWidth(50)
        x_row.addWidget(self.x_label)
        og.addLayout(x_row)

        y_row = QHBoxLayout()
        y_row.addWidget(QLabel("Y 偏移:"))
        self.y_slider = QSlider(Qt.Horizontal)
        self.y_slider.setRange(0, 0)
        self.y_slider.setValue(0)
        y_row.addWidget(self.y_slider, 1)
        self.y_label = QLabel("0")
        self.y_label.setFixedWidth(50)
        y_row.addWidget(self.y_label)
        og.addLayout(y_row)

        self.btn_center = QPushButton("居中")
        self.btn_center.clicked.connect(self.on_center)
        og.addWidget(self.btn_center)

        nav_row = QHBoxLayout()
        self.nav_label = QLabel()
        self.nav_label.setAlignment(Qt.AlignCenter)
        self.nav_label.setFixedSize(300, 200)
        self.nav_label.setStyleSheet("border: 1px solid #bbb; background: #eee;")
        nav_row.addWidget(self.nav_label)
        nav_row.addStretch()
        og.addLayout(nav_row)

        ll.addWidget(offset_group)

        tone_group = QGroupBox("色调调整")
        tl = QVBoxLayout(tone_group)
        self.exp = SliderRow("曝光", -100, 100, 0)
        self.sat = SliderRow("饱和度", -100, 100, 0)
        self.con = SliderRow("对比度", -100, 100, 0)
        self.cla = SliderRow("清晰度", 0, 200, 0)
        self.sha = SliderRow("阴影", 0, 100, 0)
        self.hig = SliderRow("高光", 0, 100, 0)
        for s in (self.exp, self.sat, self.con, self.cla, self.sha, self.hig):
            tl.addWidget(s)
        ll.addWidget(tone_group)

        dither_group = QGroupBox("抖动设置")
        dl = QVBoxLayout(dither_group)
        pal_row = QHBoxLayout()
        pal_row.addWidget(QLabel("调色板:"))
        self.palette_combo = QComboBox()
        for name in current_palettes:
            self.palette_combo.addItem(name)
        pal_row.addWidget(self.palette_combo)
        self.btn_edit_palette = QPushButton("编辑")
        self.btn_edit_palette.setFixedWidth(50)
        self.btn_edit_palette.clicked.connect(self.on_edit_palette)
        pal_row.addWidget(self.btn_edit_palette)
        dl.addLayout(pal_row)

        dither_row = QHBoxLayout()
        dither_row.addWidget(QLabel("算法:"))
        self.dither_combo = QComboBox()
        for name, _ in DITHER_MODES:
            self.dither_combo.addItem(name)
        dither_row.addWidget(self.dither_combo)
        dl.addLayout(dither_row)

        self.serp_check = QCheckBox("蛇形扫描")
        self.serp_check.setChecked(True)
        dl.addWidget(self.serp_check)
        ll.addWidget(dither_group)

        btn_row = QHBoxLayout()
        self.btn_reset = QPushButton("重置调整")
        self.btn_reset.clicked.connect(self.on_reset)
        btn_row.addWidget(self.btn_reset)
        self.btn_rotate = QPushButton("旋转 90°")
        self.btn_rotate.clicked.connect(self.on_rotate)
        btn_row.addWidget(self.btn_rotate)
        ll.addLayout(btn_row)

        self.btn_factory = QPushButton("恢复默认设置")
        self.btn_factory.clicked.connect(self.on_factory_reset)
        ll.addWidget(self.btn_factory)

        self.btn_export = QPushButton("导出 image.bin（720×480）")
        self.btn_export.clicked.connect(self.on_export)
        self.btn_export.setEnabled(False)
        ll.addWidget(self.btn_export)

        ug = QGroupBox("上传到设备（AP 模式）")
        ul = QVBoxLayout(ug)

        ip_row = QHBoxLayout()
        ip_row.addWidget(QLabel("设备 IP:"))
        self.edit_ip = QLineEdit("192.168.4.1")
        self.edit_ip.setPlaceholderText("例如 192.168.4.1")
        ip_row.addWidget(self.edit_ip)
        ul.addLayout(ip_row)

        self.lbl_conn_status = QLabel("就绪")
        self.lbl_conn_status.setStyleSheet("color: #888; font-weight: bold;")
        self.lbl_conn_status.setWordWrap(True)
        ul.addWidget(self.lbl_conn_status)

        self.btn_upload = QPushButton("检查连接并上传")
        self.btn_upload.clicked.connect(self.on_upload)
        self.btn_upload.setEnabled(False)
        ul.addWidget(self.btn_upload)

        ll.addWidget(ug)

        ll.addStretch()
        left.setWidget(left_w)
        main_layout.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        grid = QGridLayout()
        self.lbl_input = self._mk_label()
        self.lbl_adjusted = self._mk_label()
        self.lbl_dithered = self._mk_label()
        self.lbl_device = self._mk_label()

        grid.addWidget(self._title("Input（旋转+填充后）"), 0, 0)
        grid.addWidget(self._title("Adjusted（色调调整）"), 0, 1)
        grid.addWidget(self._title("Dithered（抖动·校准色）"), 2, 0)
        grid.addWidget(self._title("Device（设备原生色）"), 2, 1)
        grid.addWidget(self.lbl_input, 1, 0)
        grid.addWidget(self.lbl_adjusted, 1, 1)
        grid.addWidget(self.lbl_dithered, 3, 0)
        grid.addWidget(self.lbl_device, 3, 1)
        rl.addLayout(grid)
        self.lbl_info = QLabel("就绪")
        rl.addWidget(self.lbl_info)
        main_layout.addWidget(right, 1)

        self.statusBar().showMessage("请选择一张图片")

        for s in (self.exp, self.sat, self.con, self.cla, self.sha, self.hig):
            s.slider.valueChanged.connect(self.on_preview)
        self.palette_combo.currentIndexChanged.connect(self.on_preview)
        self.dither_combo.currentIndexChanged.connect(self.on_preview)
        self.serp_check.stateChanged.connect(self.on_preview)
        self.fit_combo.currentIndexChanged.connect(self.on_fit_changed)
        self.x_slider.valueChanged.connect(self.on_offset_changed)
        self.y_slider.valueChanged.connect(self.on_offset_changed)

        self.apply_config(self.config)

    def _mk_label(self):
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setFixedSize(480, 320)
        lbl.setStyleSheet("border: 1px solid #ccc; background: #fafafa;")
        return lbl

    def _title(self, text):
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("font-weight: bold; padding: 4px;")
        return lbl

    def current_size(self):
        return (CANVAS_W, CANVAS_H)

    def current_fit_mode(self):
        return FIT_MODES[self.fit_combo.currentIndex()][1]

    def get_rotated_img(self):
        if self.src_img is None:
            return None
        img = self.src_img
        if self.rotation:
            img = img.rotate(-self.rotation, expand=True)
        return img

    def _update_offset_ranges(self):
        rotated = self.get_rotated_img()
        if rotated is None:
            return
        W, H = self.current_size()
        mx, my = cover_limits(rotated, W, H)
        self.max_x = mx
        self.max_y = my

        self._updating_offsets = True
        self.x_slider.setRange(0, mx)
        self.y_slider.setRange(0, my)
        self.x_slider.setValue(mx // 2)
        self.y_slider.setValue(my // 2)
        self.x_label.setText(str(mx // 2))
        self.y_label.setText(str(my // 2))
        self._updating_offsets = False

        enabled = self.current_fit_mode() == "cover"
        self.x_slider.setEnabled(enabled)
        self.y_slider.setEnabled(enabled)
        self.btn_center.setEnabled(enabled)

    def on_fit_changed(self):
        rotated = self.get_rotated_img()
        if rotated is not None:
            self._update_offset_ranges()
        self.on_preview()

    def on_offset_changed(self):
        if self._updating_offsets:
            return
        self.x_label.setText(str(self.x_slider.value()))
        self.y_label.setText(str(self.y_slider.value()))
        self.on_preview()

    def on_center(self):
        self._updating_offsets = True
        self.x_slider.setValue(self.max_x // 2)
        self.y_slider.setValue(self.max_y // 2)
        self.x_label.setText(str(self.max_x // 2))
        self.y_label.setText(str(self.max_y // 2))
        self._updating_offsets = False
        self.on_preview()
        self.statusBar().showMessage("已居中裁切")

    # ---------- 配置 ----------

    def _choose_source(self):
        dialog = SourceSelectDialog(self)
        if dialog.exec() == QDialog.Accepted and dialog.source is not None:
            return dialog.source
        return None

    def _generate_bin(self, source):
        palette = current_palettes[self.palette_combo.currentText()]
        device_colors = palette_to_device_rgb(palette)
        palette_indices = palette_to_indices(palette)

        if source == "dithered":
            block = quantize(self.dithered_img, device_colors)
        else:
            block = quantize(self.device_img, device_colors)

        return pack(block, palette_indices)

    def apply_config(self, cfg):
        for name, data in cfg.get("palettes", {}).items():
            if name in current_palettes:
                current_palettes[name] = data

        self.exp.slider.setValue(cfg.get("exposure", 0))
        self.sat.slider.setValue(cfg.get("saturation", 0))
        self.con.slider.setValue(cfg.get("contrast", 0))
        self.cla.slider.setValue(cfg.get("clarity", 0))
        self.sha.slider.setValue(cfg.get("shadow", 0))
        self.hig.slider.setValue(cfg.get("highlight", 0))
        self.fit_combo.setCurrentIndex(cfg.get("fit_index", 0))

        pal_name = cfg.get("palette_name", "设备实测")
        idx = self.palette_combo.findText(pal_name)
        if idx >= 0:
            self.palette_combo.setCurrentIndex(idx)

        self.dither_combo.setCurrentIndex(cfg.get("dither_index", 0))
        self.serp_check.setChecked(cfg.get("serpentine", True))

        device_ip = cfg.get("device_ip", "").strip()
        if not device_ip and "url" in cfg:
            device_ip = clean_ip(cfg["url"])
        if not device_ip:
            device_ip = "192.168.4.1"
        self.edit_ip.setText(device_ip)

    def save_current_config(self):
        cfg = {
            "exposure": self.exp.slider.value(),
            "saturation": self.sat.slider.value(),
            "contrast": self.con.slider.value(),
            "clarity": self.cla.slider.value(),
            "shadow": self.sha.slider.value(),
            "highlight": self.hig.slider.value(),
            "fit_index": self.fit_combo.currentIndex(),
            "palette_name": self.palette_combo.currentText(),
            "dither_index": self.dither_combo.currentIndex(),
            "serpentine": self.serp_check.isChecked(),
            "device_ip": self.edit_ip.text().strip(),
            "palettes": current_palettes,
        }
        save_config(cfg)

    def closeEvent(self, event):
        self.save_current_config()
        super().closeEvent(event)

    # ---------- 事件 ----------

    def on_choose(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if not path:
            return
        try:
            self.src_img = Image.open(path).convert("RGB")
            self.rotation = 0
            self._update_offset_ranges()
            self.on_preview()
            self.btn_export.setEnabled(True)
            self.btn_upload.setEnabled(True)
            self.statusBar().showMessage(f"已加载：{path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载失败：{e}")

    def on_reset(self):
        for s in (self.exp, self.sat, self.con, self.cla, self.sha, self.hig):
            s.reset()
        self.rotation = 0
        self.fit_combo.setCurrentIndex(0)
        self._update_offset_ranges()
        self.on_preview()
        self.statusBar().showMessage("已重置所有调整")

    def on_factory_reset(self):
        # 同时清理新旧两个位置，彻底清除记忆
        for path in (CONFIG_PATH, LEGACY_CONFIG_PATH):
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass

        current_palettes.clear()
        current_palettes.update(copy.deepcopy(BUILTIN_PALETTES))
        self.apply_config({})
        self.rotation = 0
        self.lbl_conn_status.setText("就绪")
        self.lbl_conn_status.setStyleSheet("color: #888; font-weight: bold;")
        if self.src_img is not None:
            self._update_offset_ranges()
        self.on_preview()
        self.statusBar().showMessage("已恢复默认设置并清除记忆（新旧两个位置均已清除）")

    def on_rotate(self):
        self.rotation = (self.rotation + 90) % 360
        self._update_offset_ranges()
        self.on_preview()
        self.statusBar().showMessage(f"已旋转到 {self.rotation}°")

    def on_edit_palette(self):
        name = self.palette_combo.currentText()
        dialog = PaletteEditorDialog(name, current_palettes[name], self)
        if dialog.exec() == QDialog.Accepted and dialog.result_data is not None:
            current_palettes[name] = dialog.result_data
            self.on_preview()
            self.statusBar().showMessage(f"调色板「{name}」已更新")

    def on_preview(self):
        if self.src_img is None:
            return
        try:
            W, H = self.current_size()
            fit_mode = self.current_fit_mode()
            rotated = self.get_rotated_img()

            if fit_mode == "cover":
                fitted = resize_fit(rotated, W, H, "cover",
                                    self.x_slider.value(), self.y_slider.value())
            else:
                fitted = resize_fit(rotated, W, H, "contain")

            self.fitted_img = fitted

            self.lbl_input.setPixmap(pil_to_qpixmap(fitted).scaled(
                self.lbl_input.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

            adjusted = apply_all(
                fitted,
                exposure=self.exp.get(),
                saturation=self.sat.get(),
                contrast=self.con.get(),
                clarity=self.cla.get(),
                shadow=self.sha.get(),
                highlight=self.hig.get(),
            )
            self.adjusted_img = adjusted
            self.lbl_adjusted.setPixmap(pil_to_qpixmap(adjusted).scaled(
                self.lbl_adjusted.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

            palette_name = self.palette_combo.currentText()
            palette = current_palettes[palette_name]
            calibrated_colors = palette_to_rgb(palette)
            device_colors = palette_to_device_rgb(palette)

            mode = DITHER_MODES[self.dither_combo.currentIndex()][1]
            serpentine = self.serp_check.isChecked()
            block = dither(adjusted, mode, calibrated_colors, serpentine)

            dithered_img = block_to_image(block, calibrated_colors)
            self.dithered_img = dithered_img
            self.lbl_dithered.setPixmap(pil_to_qpixmap(dithered_img).scaled(
                self.lbl_dithered.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

            device_img = block_to_image(block, device_colors)
            self.device_img = device_img
            self.lbl_device.setPixmap(pil_to_qpixmap(device_img).scaled(
                self.lbl_device.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

            nav = make_nav_image(
                rotated, fit_mode,
                self.x_slider.value() if fit_mode == "cover" else 0,
                self.y_slider.value() if fit_mode == "cover" else 0,
            )
            self.nav_label.setPixmap(pil_to_qpixmap(nav))

            if fit_mode == "cover":
                self.lbl_info.setText(
                    f"{W}×{H}  铺满  偏移({self.x_slider.value()},{self.y_slider.value()})"
                    f"  {mode}  {palette_name}")
            else:
                self.lbl_info.setText(
                    f"{W}×{H}  完整   {mode}  {palette_name}")
        except Exception as e:
            self.lbl_info.setText(f"预览失败：{e}")
            self.statusBar().showMessage(f"预览失败：{e}")

    def on_export(self):
        if self.dithered_img is None or self.device_img is None:
            QMessageBox.warning(self, "提示", "请先选择图片")
            return

        source = self._choose_source()
        if source is None:
            return

        try:
            bin_data = self._generate_bin(source)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成数据失败：{e}")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "保存 image.bin（720×480）", "image.bin", "Binary (*.bin)")
        if not path:
            return
        try:
            with open(path, "wb") as f:
                f.write(bin_data)
            label = "Dithered" if source == "dithered" else "Device"
            self.statusBar().showMessage(
                f"已保存（{label}）：{path}（{len(bin_data)} 字节）")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：{e}")

    def _set_upload_busy(self, busy):
        self.btn_upload.setEnabled(not busy)
        self.btn_export.setEnabled(not busy)
        self.btn_choose.setEnabled(not busy)

    def on_upload(self):
        if self.dithered_img is None or self.device_img is None:
            QMessageBox.warning(self, "提示", "请先选择图片")
            return

        ip = clean_ip(self.edit_ip.text())
        if not ip:
            QMessageBox.warning(self, "提示", "请输入设备 IP 地址")
            return

        try:
            import requests  # noqa: F401
        except ImportError:
            QMessageBox.warning(self, "缺少依赖", "pip install requests")
            return

        self._upload_ip = ip
        self._set_upload_busy(True)
        self.lbl_conn_status.setText(f"正在检查 {ip} …")
        self.lbl_conn_status.setStyleSheet("color: #888; font-weight: bold;")
        self.statusBar().showMessage(f"正在检查 {ip} 连接…")

        self.check_worker = CheckWorker(ip)
        self.check_worker.finished.connect(self.on_upload_check_done)
        self.check_worker.start()

    def on_upload_check_done(self, online, message):
        ip = self._upload_ip

        if not online:
            self.lbl_conn_status.setText(f"✗ {message}（上传已取消）")
            self.lbl_conn_status.setStyleSheet("color: #c00; font-weight: bold;")
            self.statusBar().showMessage(f"设备 {ip} 离线：{message}，上传已取消")
            self._set_upload_busy(False)
            QMessageBox.critical(
                self, "连接失败",
                f"设备 {ip} 无法连接：{message}\n\n上传已取消，请检查 IP 和设备状态。")
            return

        self.lbl_conn_status.setText(f"✓ {message}，正在准备上传…")
        self.lbl_conn_status.setStyleSheet("color: #0a7a0a; font-weight: bold;")
        self.statusBar().showMessage(f"设备 {ip} 在线")

        source = self._choose_source()
        if source is None:
            self.lbl_conn_status.setText(f"✓ {message}（用户取消上传）")
            self.statusBar().showMessage("已取消上传")
            self._set_upload_busy(False)
            return

        try:
            bin_data = self._generate_bin(source)
        except Exception as e:
            self.lbl_conn_status.setText(f"✓ {message}（生成数据失败）")
            self._set_upload_busy(False)
            QMessageBox.critical(self, "错误", f"生成数据失败：{e}")
            return

        url = f"http://{ip}/upload"
        label = "Dithered" if source == "dithered" else "Device"
        self.lbl_conn_status.setText(f"↑ 上传中（{label}）…")
        self.lbl_conn_status.setStyleSheet("color: #06c; font-weight: bold;")
        self.statusBar().showMessage(
            f"上传中（{label}，720×480）到 {ip}…")

        self.worker = UploadWorker(url, bin_data)
        self.worker.finished.connect(self.on_upload_ok)
        self.worker.failed.connect(self.on_upload_fail)
        self.worker.start()

    def on_upload_ok(self, msg):
        self._set_upload_busy(False)
        self.lbl_conn_status.setText(f"✓ 上传完成")
        self.lbl_conn_status.setStyleSheet("color: #0a7a0a; font-weight: bold;")
        self.statusBar().showMessage(f"上传完成：{msg}")

    def on_upload_fail(self, msg):
        self._set_upload_busy(False)
        self.lbl_conn_status.setText(f"✗ 上传失败")
        self.lbl_conn_status.setStyleSheet("color: #c00; font-weight: bold;")
        self.statusBar().showMessage("上传失败")
        QMessageBox.critical(self, "上传失败", msg)


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()