import sys
import struct
import serial
import serial.tools.list_ports
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QComboBox, QPushButton, 
                             QGroupBox, QGridLayout, QCheckBox, QSpinBox, QFrame)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QRect
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont

# --- CẤU HÌNH PROTOCOL (KHÔNG ĐỔI) ---
STRUCT_FMT_RX = '<BBHhhHhhHIB' 
PACKET_SIZE = struct.calcsize(STRUCT_FMT_RX)
HEADER_TO_PC = 0xA5
HEADER_FROM_PC = 0xA5

CMD_START = 0x02
CMD_STOP = 0x03
CMD_LED1 = 0x11
CMD_LED2 = 0x12
CMD_LED3 = 0x13

# --- PALETTE: LIME GREEN (XANH CHANH DỊU MẮT) ---
COLOR_BG = "#F1F8E9"       # Nền xanh bạc hà cực nhạt (Dịu mắt)
COLOR_WHITE = "#FFFFFF"    # Trắng
COLOR_BLACK = "#263238"    # Đen than chì (Không đen tuyền, đỡ gắt hơn)
COLOR_LIME_MAIN = "#C6FF00" # Xanh chanh chủ đạo (Accent)
COLOR_LIME_LIGHT = "#F4FF81" # Xanh chanh nhạt (Hover)
COLOR_LIME_DARK = "#76FF03"  # Xanh chanh đậm (Active/Check)
COLOR_STOP = "#FF8A80"     # Đỏ phấn nhẹ (Chỉ dùng cho nút Stop)

# Stylesheet CSS: Neo-Brutalism Fresh Style
STYLESHEET = f"""
    QMainWindow, QWidget {{
        background-color: {COLOR_BG};
        font-family: 'Consolas', 'Courier New', monospace; /* Đổi sang Consolas cho tròn trịa hơn */
        font-weight: bold;
        color: {COLOR_BLACK};
        font-size: 14px;
    }}

    QGroupBox {{
        background-color: {COLOR_WHITE};
        border: 2px solid {COLOR_BLACK};
        margin-top: 25px;
        font-size: 15px;
        border-radius: 4px; /* Bo nhẹ 1 chút cho đỡ cứng, đúng ý 'dịu mắt' */
    }}
    
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 15px;
        padding: 5px 15px;
        background-color: {COLOR_LIME_MAIN}; /* Tiêu đề nền xanh chanh */
        color: {COLOR_BLACK};
        border: 2px solid {COLOR_BLACK};
        bottom: 0px; 
    }}

    QPushButton {{
        background-color: {COLOR_WHITE};
        border: 2px solid {COLOR_BLACK};
        padding: 10px;
        border-radius: 4px;
        min-height: 30px;
    }}

    QPushButton:hover {{
        background-color: {COLOR_LIME_LIGHT}; /* Hover màu chanh nhạt */
        margin-top: -3px;
        margin-left: -3px;
        border-bottom: 5px solid {COLOR_BLACK}; /* Shadow dày */
        border-right: 5px solid {COLOR_BLACK};
    }}

    QPushButton:pressed {{
        background-color: {COLOR_LIME_MAIN};
        margin-top: 2px;
        margin-left: 2px;
        border: 2px solid {COLOR_BLACK};
    }}

    QPushButton:disabled {{
        background-color: #E0E0E0;
        border: 2px dashed #9E9E9E;
        color: #9E9E9E;
    }}

    QComboBox {{
        background-color: {COLOR_WHITE};
        border: 2px solid {COLOR_BLACK};
        padding: 5px 10px;
        border-radius: 4px;
    }}

    QComboBox::drop-down {{
        border-left: 2px solid {COLOR_BLACK};
        width: 30px;
        background-color: {COLOR_LIME_MAIN};
    }}

    QCheckBox {{
        spacing: 12px;
    }}

    QCheckBox::indicator {{
        width: 22px;
        height: 22px;
        border: 2px solid {COLOR_BLACK};
        background-color: {COLOR_WHITE};
        border-radius: 3px;
    }}

    QCheckBox::indicator:checked {{
        background-color: {COLOR_LIME_DARK};
        image: none;
        border: 2px solid {COLOR_BLACK};
    }}
    
    QSpinBox {{
        border: 2px solid {COLOR_BLACK};
        padding: 5px;
        background-color: {COLOR_WHITE};
        border-radius: 4px;
        selection-background-color: {COLOR_LIME_MAIN};
        selection-color: {COLOR_BLACK};
    }}
    
    QLabel {{
        font-weight: bold;
    }}
"""

# --- CUSTOM WIDGET: JOYSTICK VISUALIZER ---
class JoystickWidget(QWidget):
    def __init__(self, name="Joystick"):
        super().__init__()
        self.setMinimumSize(220, 220)
        self.az = 0
        self.el = 0
        self.name = name
        # Nền trắng, viền đen
        self.setStyleSheet(f"background-color: {COLOR_WHITE}; border: 2px solid {COLOR_BLACK}; border-radius: 4px;")

    def set_values(self, az, el):
        self.az = az
        self.el = el
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True) # Bật khử răng cưa cho dịu mắt hơn bản trước
        
        w, h = self.width(), self.height()
        center_x, center_y = w // 2, h // 2
        radius = min(w, h) // 2 - 25
        
        # 1. Vẽ trục tọa độ (Màu xám nhạt)
        pen_grid = QPen(QColor("#B0BEC5"), 1, Qt.DashLine)
        painter.setPen(pen_grid)
        painter.drawLine(center_x, 15, center_x, h - 15)
        painter.drawLine(15, center_y, w - 15, center_y)

        # 2. Vẽ vòng tròn giới hạn
        pen_border = QPen(QColor(COLOR_BLACK), 3)
        painter.setPen(pen_border)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(center_x - radius, center_y - radius, radius * 2, radius * 2)

        # 3. Tính toán vị trí
        x_pos = center_x + (self.az / 2048.0) * radius
        y_pos = center_y + (self.el / 2048.0) * radius
        
        # 4. Vẽ Handle (Hình vuông bo góc - Squircle)
        handle_size = 28
        rect_handle = QRect(int(x_pos) - handle_size//2, int(y_pos) - handle_size//2, handle_size, handle_size)
        
        painter.setPen(QPen(QColor(COLOR_BLACK), 2)) 
        painter.setBrush(QBrush(QColor(COLOR_LIME_MAIN))) # Handle màu chanh
        
        # Dây nối
        painter.drawLine(center_x, center_y, int(x_pos), int(y_pos))
        
        # Vẽ khối vuông bo góc (Rounded Rect)
        painter.drawRoundedRect(rect_handle, 6, 6)

        # 5. Vẽ Text
        painter.setPen(QPen(QColor(COLOR_BLACK), 1))
        font = QFont("Consolas", 10, QFont.Bold)
        painter.setFont(font)
        painter.drawText(15, 25, f"{self.name}")
        
        # Vẽ giá trị (Badge màu đen góc dưới)
        val_text = f"X: {self.az}  Y: {self.el}"
        fm = painter.fontMetrics()
        text_w = fm.width(val_text) + 20
        
        # Background badge
        painter.setBrush(QColor(COLOR_BLACK))
        painter.drawRoundedRect(w - text_w - 10, h - 35, text_w, 25, 4, 4)
        
        # Text value (Màu xanh chanh nổi bật trên nền đen)
        painter.setPen(QColor(COLOR_LIME_MAIN))
        painter.drawText(w - text_w, h - 18, val_text)

# --- SERIAL THREAD (GIỮ NGUYÊN) ---
class SerialThread(QThread):
    data_received = pyqtSignal(object)
    
    def __init__(self, port, baudrate=460800):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.running = True
        self.ser = None

    def run(self):
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=0.1)
            print(f"Connected to {self.port}")
            while self.running:
                if self.ser.in_waiting >= PACKET_SIZE:
                    if ord(self.ser.read(1)) == HEADER_TO_PC:
                        raw_data = self.ser.read(PACKET_SIZE - 1)
                        if len(raw_data) == PACKET_SIZE - 1:
                            full_buf = bytes([HEADER_TO_PC]) + raw_data
                            calc_sum = sum(full_buf[:-1]) & 0xFF
                            recv_sum = full_buf[-1]
                            if calc_sum == recv_sum:
                                try:
                                    unpacked = struct.unpack(STRUCT_FMT_RX, full_buf)
                                    data = {
                                        'di_pin': unpacked[2],
                                        'lgt1_az': unpacked[3], 'lgt1_el': unpacked[4], 'lgt1_sw': unpacked[5],
                                        'lgt2_az': unpacked[6], 'lgt2_el': unpacked[7], 'lgt2_sw': unpacked[8],
                                        'count': unpacked[9]
                                    }
                                    self.data_received.emit(data)
                                except: pass
        except: pass
        finally:
            if self.ser and self.ser.is_open: self.ser.close()

    def send_command(self, cmd, value=0):
        if self.ser and self.ser.is_open:
            data_bytes = struct.pack('<BBH', HEADER_FROM_PC, cmd, value)
            checksum = sum(data_bytes) & 0xFF
            self.ser.write(data_bytes + bytes([checksum]))

    def stop(self):
        self.running = False
        self.wait()

# --- MAIN WINDOW ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LIME JOYSTICK INTERFACE")
        self.resize(1000, 720)
        self.serial_thread = None
        
        self.setStyleSheet(STYLESHEET)
        
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setSpacing(25)
        main_layout.setContentsMargins(30, 30, 30, 30)

        # HEADER
        header_frame = QFrame()
        header_frame.setStyleSheet(f"background-color: {COLOR_BLACK}; border-radius: 6px;")
        header_layout = QHBoxLayout(header_frame)
        
        lbl_title = QLabel("STM32 CONTROLLER // VER 2.0")
        lbl_title.setStyleSheet(f"font-size: 20px; color: {COLOR_LIME_MAIN}; border: none;")
        lbl_status = QLabel("● DISCONNECTED")
        lbl_status.setStyleSheet(f"color: #FF5252; font-size: 14px; border: none;")
        self.lbl_status = lbl_status
        
        header_layout.addWidget(lbl_title)
        header_layout.addStretch()
        header_layout.addWidget(lbl_status)
        main_layout.addWidget(header_frame)

        # 1. Connection & Main Control
        top_group = QGroupBox("SYSTEM CONNECTION")
        top_layout = QHBoxLayout()
        
        self.combo_ports = QComboBox()
        self.combo_ports.setMinimumWidth(150)
        self.btn_refresh = QPushButton("REFRESH")
        self.btn_connect = QPushButton("CONNECT")
        self.btn_disconnect = QPushButton("DISCONNECT")
        self.btn_disconnect.setEnabled(False)
        
        top_layout.addWidget(QLabel("PORT:"))
        top_layout.addWidget(self.combo_ports)
        top_layout.addWidget(self.btn_refresh)
        top_layout.addWidget(self.btn_connect)
        top_layout.addWidget(self.btn_disconnect)
        top_layout.addStretch()
        
        # Data Control Buttons
        self.btn_start_data = QPushButton("▶ START STREAM")
        self.btn_stop_data = QPushButton("■ STOP STREAM")
        self.btn_start_data.setStyleSheet(f"background-color: {COLOR_LIME_MAIN}; border: 2px solid {COLOR_BLACK};")
        self.btn_stop_data.setStyleSheet(f"background-color: {COLOR_STOP}; border: 2px solid {COLOR_BLACK};") # Màu đỏ nhẹ cho Stop
        
        self.btn_start_data.setEnabled(False)
        self.btn_stop_data.setEnabled(False)
        
        top_layout.addWidget(self.btn_start_data)
        top_layout.addWidget(self.btn_stop_data)
        
        top_group.setLayout(top_layout)
        main_layout.addWidget(top_group)

        # 2. Joystick & Buttons Viz
        viz_layout = QHBoxLayout()
        
        # Left
        left_group = QGroupBox("LEFT CONTROL")
        left_layout = QVBoxLayout()
        self.joy1 = JoystickWidget("L-Stick")
        left_layout.addWidget(self.joy1)
        
        grid_l = QGridLayout()
        self.chk_l_btns = []
        for i in range(5):
            chk = QCheckBox(f"L-BTN {i+1}")
            chk.setAttribute(Qt.WA_TransparentForMouseEvents) 
            chk.setFocusPolicy(Qt.NoFocus)
            self.chk_l_btns.append(chk)
            grid_l.addWidget(chk, i//3, i%3)
        left_layout.addLayout(grid_l)
        left_group.setLayout(left_layout)
        
        # Right
        right_group = QGroupBox("RIGHT CONTROL")
        right_layout = QVBoxLayout()
        self.joy2 = JoystickWidget("R-Stick")
        right_layout.addWidget(self.joy2)
        
        grid_r = QGridLayout()
        self.chk_r_btns = []
        for i in range(5):
            chk = QCheckBox(f"R-BTN {i+1}")
            chk.setAttribute(Qt.WA_TransparentForMouseEvents)
            chk.setFocusPolicy(Qt.NoFocus)
            self.chk_r_btns.append(chk)
            grid_r.addWidget(chk, i//3, i%3)
        right_layout.addLayout(grid_r)
        right_group.setLayout(right_layout)

        # Switches (Middle)
        mid_layout = QVBoxLayout()
        sw_group = QGroupBox("SWITCHES")
        sw_inner = QVBoxLayout()
        self.chk_sws = [QCheckBox(f"SW-MODE {i+1}") for i in range(3)]
        for chk in self.chk_sws:
            chk.setAttribute(Qt.WA_TransparentForMouseEvents)
            sw_inner.addWidget(chk)
        sw_group.setLayout(sw_inner)
        
        # Info Box
        info_group = QGroupBox("STATS")
        info_inner = QVBoxLayout()
        self.lbl_count = QLabel("PACKETS\n000000")
        self.lbl_count.setAlignment(Qt.AlignCenter)
        self.lbl_count.setStyleSheet("font-size: 16px; color: #555;")
        info_inner.addWidget(self.lbl_count)
        info_group.setLayout(info_inner)

        mid_layout.addWidget(sw_group)
        mid_layout.addWidget(info_group)
        mid_layout.addStretch()

        viz_layout.addWidget(left_group, 3)
        viz_layout.addLayout(mid_layout, 2)
        viz_layout.addWidget(right_group, 3)
        main_layout.addLayout(viz_layout)

        # 3. LED Control
        led_group = QGroupBox("LED CONFIGURATION")
        led_layout = QHBoxLayout()
        
        led_layout.addWidget(QLabel("BLINK SPEED (MS):"))
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(0, 5000)
        self.spin_interval.setValue(500)
        self.spin_interval.setMinimumWidth(100)
        led_layout.addWidget(self.spin_interval)
        led_layout.addSpacing(20)
        
        self.btn_led1 = QPushButton("SET LED 1")
        self.btn_led2 = QPushButton("SET LED 2")
        self.btn_led3 = QPushButton("SET LED 3")
        
        led_layout.addWidget(self.btn_led1)
        led_layout.addWidget(self.btn_led2)
        led_layout.addWidget(self.btn_led3)
        led_group.setLayout(led_layout)
        main_layout.addWidget(led_group)

        # Events
        self.btn_refresh.clicked.connect(self.refresh_ports)
        self.btn_connect.clicked.connect(self.connect_serial)
        self.btn_disconnect.clicked.connect(self.disconnect_serial)
        self.btn_start_data.clicked.connect(lambda: self.send_cmd(CMD_START))
        self.btn_stop_data.clicked.connect(lambda: self.send_cmd(CMD_STOP))
        self.btn_led1.clicked.connect(lambda: self.send_cmd(CMD_LED1, self.spin_interval.value()))
        self.btn_led2.clicked.connect(lambda: self.send_cmd(CMD_LED2, self.spin_interval.value()))
        self.btn_led3.clicked.connect(lambda: self.send_cmd(CMD_LED3, self.spin_interval.value()))

        self.refresh_ports()

    def refresh_ports(self):
        self.combo_ports.clear()
        ports = serial.tools.list_ports.comports()
        for p in ports: self.combo_ports.addItem(p.device)

    def connect_serial(self):
        port = self.combo_ports.currentText()
        if not port: return
        self.serial_thread = SerialThread(port)
        self.serial_thread.data_received.connect(self.update_ui)
        self.serial_thread.start()
        
        self.btn_connect.setEnabled(False)
        self.btn_disconnect.setEnabled(True)
        self.btn_start_data.setEnabled(True)
        self.btn_stop_data.setEnabled(True)
        self.lbl_status.setText("● ONLINE")
        self.lbl_status.setStyleSheet(f"color: {COLOR_LIME_MAIN}; font-size: 14px;")

    def disconnect_serial(self):
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread = None
        
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        self.btn_start_data.setEnabled(False)
        self.btn_stop_data.setEnabled(False)
        self.lbl_status.setText("● DISCONNECTED")
        self.lbl_status.setStyleSheet(f"color: {COLOR_STOP}; font-size: 14px;")

    def send_cmd(self, cmd, val=0):
        if self.serial_thread: self.serial_thread.send_command(cmd, val)

    def update_ui(self, data):
        self.joy1.set_values(data['lgt1_az'], data['lgt1_el'])
        self.joy2.set_values(data['lgt2_az'], data['lgt2_el'])
        
        raw_l = data['lgt1_sw']
        for i in range(5): self.chk_l_btns[i].setChecked(bool((raw_l >> i) & 1))
            
        raw_r = data['lgt2_sw']
        for i in range(5): self.chk_r_btns[i].setChecked(bool((raw_r >> i) & 1))
            
        raw_sw = data['di_pin']
        for i in range(3): self.chk_sws[i].setChecked(bool((raw_sw >> i) & 1))

        self.lbl_count.setText(f"PACKETS\n{data['count']:06d}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())