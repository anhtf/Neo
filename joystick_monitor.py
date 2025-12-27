import sys
import struct
import serial
import serial.tools.list_ports
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QComboBox, QPushButton, 
                             QGroupBox, QGridLayout, QCheckBox, QSpinBox, QFrame)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QRect
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPalette

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

# --- NEO-BRUTALISM COLORS & STYLES ---
COLOR_BG = "#F0F0F0"       # Xám nhạt (nền tổng)
COLOR_WHITE = "#FFFFFF"    # Trắng (nền widget)
COLOR_BLACK = "#000000"    # Đen tuyệt đối (viền)
COLOR_ACCENT_1 = "#FF5252" # Đỏ cam (Joystick handle)
COLOR_ACCENT_2 = "#FFEB3B" # Vàng chanh (Hover)
COLOR_ACCENT_3 = "#448AFF" # Xanh (Active/Check)

# Stylesheet CSS cực gắt cho Neo-Brutalism
STYLESHEET = f"""
    QMainWindow, QWidget {{
        background-color: {COLOR_BG};
        font-family: 'Courier New', monospace;
        font-weight: bold;
        color: {COLOR_BLACK};
        font-size: 14px;
    }}

    QGroupBox {{
        background-color: {COLOR_WHITE};
        border: 3px solid {COLOR_BLACK};
        margin-top: 25px;
        font-size: 16px;
    }}
    
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 10px;
        padding: 5px 10px;
        background-color: {COLOR_BLACK};
        color: {COLOR_WHITE};
        border: 2px solid {COLOR_BLACK}; /* Tạo cảm giác block */
        bottom: 0px; 
    }}

    QPushButton {{
        background-color: {COLOR_WHITE};
        border: 3px solid {COLOR_BLACK};
        padding: 10px;
        border-radius: 0px; /* Vuông vức */
        min-height: 25px;
    }}

    QPushButton:hover {{
        background-color: {COLOR_ACCENT_2}; /* Hover màu vàng */
        margin-top: -2px; /* Hiệu ứng nhấc lên nhẹ */
        margin-left: -2px;
        border-bottom: 5px solid {COLOR_BLACK}; /* Giả lập bóng đổ cứng */
        border-right: 5px solid {COLOR_BLACK};
    }}

    QPushButton:pressed {{
        background-color: {COLOR_BLACK};
        color: {COLOR_WHITE};
        margin-top: 2px;
        margin-left: 2px;
        border: 3px solid {COLOR_BLACK};
    }}

    QPushButton:disabled {{
        background-color: #D3D3D3;
        border: 3px dashed {COLOR_BLACK};
        color: #808080;
    }}

    QComboBox {{
        background-color: {COLOR_WHITE};
        border: 3px solid {COLOR_BLACK};
        padding: 5px;
        border-radius: 0px;
    }}

    QComboBox::drop-down {{
        border-left: 3px solid {COLOR_BLACK};
        width: 30px;
        background-color: {COLOR_ACCENT_2};
    }}

    QCheckBox {{
        spacing: 10px;
    }}

    QCheckBox::indicator {{
        width: 20px;
        height: 20px;
        border: 3px solid {COLOR_BLACK};
        background-color: {COLOR_WHITE};
    }}

    QCheckBox::indicator:checked {{
        background-color: {COLOR_ACCENT_3}; /* Xanh khi check */
        image: none; /* Dùng màu block thay vì dấu tích */
        border: 3px solid {COLOR_BLACK};
    }}
    
    QSpinBox {{
        border: 3px solid {COLOR_BLACK};
        padding: 5px;
        background-color: {COLOR_WHITE};
    }}
    
    QLabel {{
        font-weight: bold;
    }}
"""

# --- CUSTOM WIDGET: JOYSTICK VISUALIZER (STYLED) ---
class JoystickWidget(QWidget):
    def __init__(self, name="Joystick"):
        super().__init__()
        self.setMinimumSize(220, 220)
        self.az = 0
        self.el = 0
        self.name = name
        # Set nền trắng cho widget joystick
        self.setStyleSheet(f"background-color: {COLOR_WHITE}; border: 3px solid {COLOR_BLACK};")

    def set_values(self, az, el):
        self.az = az
        self.el = el
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False) # Tắt khử răng cưa để nét sắc (Brutal)
        
        w, h = self.width(), self.height()
        center_x, center_y = w // 2, h // 2
        radius = min(w, h) // 2 - 20
        
        # 1. Vẽ trục tọa độ (Lưới đứt đoạn thô)
        pen_grid = QPen(QColor(COLOR_BLACK), 2, Qt.DashLine)
        painter.setPen(pen_grid)
        painter.drawLine(center_x, 10, center_x, h - 10)
        painter.drawLine(10, center_y, w - 10, center_y)

        # 2. Vẽ vòng tròn giới hạn (Viền dày)
        pen_border = QPen(QColor(COLOR_BLACK), 4) # Dày 4px
        painter.setPen(pen_border)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(center_x - radius, center_y - radius, radius * 2, radius * 2)

        # 3. Tính toán vị trí
        # Map AZ/EL (-2048 to 2048) to coordinate pixels
        x_pos = center_x + (self.az / 2048.0) * radius
        y_pos = center_y + (self.el / 2048.0) * radius
        
        # 4. Vẽ Handle (Hình vuông thay vì tròn - đặc trưng Brutalism)
        handle_size = 24
        rect_handle = QRect(int(x_pos) - handle_size//2, int(y_pos) - handle_size//2, handle_size, handle_size)
        
        painter.setPen(QPen(QColor(COLOR_BLACK), 3)) # Viền đen handle
        painter.setBrush(QBrush(QColor(COLOR_ACCENT_1))) # Ruột màu đỏ cam
        
        # Vẽ đường nối từ tâm đến điểm
        painter.drawLine(center_x, center_y, int(x_pos), int(y_pos))
        
        # Vẽ khối vuông
        painter.drawRect(rect_handle)

        # 5. Vẽ Text (Góc trái trên)
        painter.setPen(QPen(QColor(COLOR_BLACK), 1))
        font = QFont("Courier New", 10, QFont.Bold)
        painter.setFont(font)
        painter.drawText(10, 20, f"{self.name.upper()}")
        
        # Vẽ giá trị (Góc phải dưới - nền đen chữ trắng)
        val_text = f"AZ:{self.az:5} | EL:{self.el:5}"
        painter.fillRect(w - 180, h - 30, 180, 30, QColor(COLOR_BLACK))
        painter.setPen(QColor(COLOR_WHITE))
        painter.drawText(w - 170, h - 10, val_text)

# --- SERIAL THREAD (KHÔNG ĐỔI) ---
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
        self.setWindowTitle("NEO-BRUTALISM CONTROLLER")
        self.resize(1000, 750)
        self.serial_thread = None
        
        # Áp dụng Stylesheet
        self.setStyleSheet(STYLESHEET)
        
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setSpacing(20) # Tăng khoảng cách giữa các khối

        # HEADER TITLE
        lbl_title = QLabel("STM32 /// JOYSTICK INTERFACE")
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet(f"font-size: 24px; background-color: {COLOR_BLACK}; color: {COLOR_WHITE}; padding: 10px; border: 3px solid {COLOR_BLACK};")
        main_layout.addWidget(lbl_title)

        # 1. Connection Area
        conn_group = QGroupBox("CONN_SETTINGS")
        conn_layout = QHBoxLayout()
        
        self.combo_ports = QComboBox()
        self.combo_ports.setMinimumWidth(200)
        self.btn_refresh = QPushButton("REFRESH")
        self.btn_connect = QPushButton("CONNECT")
        self.btn_disconnect = QPushButton("DISCONNECT")
        self.btn_disconnect.setEnabled(False)
        
        conn_layout.addWidget(QLabel("PORT:"))
        conn_layout.addWidget(self.combo_ports)
        conn_layout.addWidget(self.btn_refresh)
        conn_layout.addWidget(self.btn_connect)
        conn_layout.addWidget(self.btn_disconnect)
        conn_group.setLayout(conn_layout)
        main_layout.addWidget(conn_group)

        # 2. Control Area
        ctrl_group = QGroupBox("DATA_STREAM_CONTROL")
        ctrl_layout = QHBoxLayout()
        self.btn_start_data = QPushButton("START DATA [0x02]")
        self.btn_stop_data = QPushButton("STOP DATA [0x03]")
        
        # Style riêng cho nút quan trọng
        self.btn_start_data.setStyleSheet(f"background-color: {COLOR_ACCENT_3}; color: white; border: 3px solid black; font-weight: bold;")
        self.btn_stop_data.setStyleSheet(f"background-color: {COLOR_ACCENT_1}; color: white; border: 3px solid black; font-weight: bold;")
        
        self.btn_start_data.setEnabled(False)
        self.btn_stop_data.setEnabled(False)
        ctrl_layout.addWidget(self.btn_start_data)
        ctrl_layout.addWidget(self.btn_stop_data)
        ctrl_group.setLayout(ctrl_layout)
        main_layout.addWidget(ctrl_group)

        # 3. Visualization Area
        viz_layout = QHBoxLayout()
        
        # Left Panel
        left_group = QGroupBox("L_AXIS_INPUT")
        left_layout = QVBoxLayout()
        self.joy1 = JoystickWidget("L_JOY")
        left_layout.addWidget(self.joy1)
        
        grid_l = QGridLayout()
        self.chk_l_btns = []
        for i in range(5):
            chk = QCheckBox(f"L_BTN_{i+1}")
            chk.setAttribute(Qt.WA_TransparentForMouseEvents) 
            chk.setFocusPolicy(Qt.NoFocus)
            self.chk_l_btns.append(chk)
            grid_l.addWidget(chk, i//3, i%3)
        left_layout.addLayout(grid_l)
        left_group.setLayout(left_layout)
        
        # Right Panel
        right_group = QGroupBox("R_AXIS_INPUT")
        right_layout = QVBoxLayout()
        self.joy2 = JoystickWidget("R_JOY")
        right_layout.addWidget(self.joy2)
        
        grid_r = QGridLayout()
        self.chk_r_btns = []
        for i in range(5):
            chk = QCheckBox(f"R_BTN_{i+1}")
            chk.setAttribute(Qt.WA_TransparentForMouseEvents)
            chk.setFocusPolicy(Qt.NoFocus)
            self.chk_r_btns.append(chk)
            grid_r.addWidget(chk, i//3, i%3)
        right_layout.addLayout(grid_r)
        right_group.setLayout(right_layout)

        # Switches & Info Panel (Middle)
        mid_layout = QVBoxLayout()
        sw_group = QGroupBox("SWITCHES")
        sw_inner = QVBoxLayout()
        self.chk_sws = [QCheckBox(f"SW_{i+1}") for i in range(3)]
        for chk in self.chk_sws:
            chk.setAttribute(Qt.WA_TransparentForMouseEvents)
            sw_inner.addWidget(chk)
        sw_group.setLayout(sw_inner)

        info_group = QGroupBox("METRICS")
        info_inner = QVBoxLayout()
        self.lbl_count = QLabel("PKT: 000000")
        self.lbl_count.setStyleSheet("font-size: 18px; color: #444;")
        info_inner.addWidget(self.lbl_count)
        info_group.setLayout(info_inner)

        mid_layout.addWidget(sw_group)
        mid_layout.addWidget(info_group)
        mid_layout.addStretch()

        viz_layout.addWidget(left_group, 3)
        viz_layout.addLayout(mid_layout, 2)
        viz_layout.addWidget(right_group, 3)
        main_layout.addLayout(viz_layout)

        # 4. LED Control Area
        led_group = QGroupBox("LED_EFFECTS_CONTROL")
        led_layout = QHBoxLayout()
        
        led_layout.addWidget(QLabel("INTERVAL (MS):"))
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(0, 5000)
        self.spin_interval.setValue(500)
        self.spin_interval.setMinimumWidth(100)
        led_layout.addWidget(self.spin_interval)
        
        self.btn_led1 = QPushButton("SET LED_1")
        self.btn_led2 = QPushButton("SET LED_2")
        self.btn_led3 = QPushButton("SET LED_3")
        
        led_layout.addWidget(self.btn_led1)
        led_layout.addWidget(self.btn_led2)
        led_layout.addWidget(self.btn_led3)
        led_group.setLayout(led_layout)
        main_layout.addWidget(led_group)

        # Signals
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

    def disconnect_serial(self):
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread = None
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        self.btn_start_data.setEnabled(False)
        self.btn_stop_data.setEnabled(False)

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

        self.lbl_count.setText(f"PKT: {data['count']:06d}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())