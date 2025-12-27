import sys
import struct
import time
import serial
import serial.tools.list_ports
import csv
from datetime import datetime
from collections import deque
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QGroupBox, QLabel, QComboBox, 
                             QPushButton, QGridLayout, QSpinBox, 
                             QRadioButton, QButtonGroup, QCheckBox, QFrame)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QColor, QPainterPath, QFont

CMD_HEADER = 0xA5
TLM_HEADER = 0x55
BAUD_RATE = 460800
CMD_FMT = '<BBHBIIIIBBBBBHBBB' 
PACKET_SIZE = 68
FULL_TLM_FMT = '<BBBHHfIIIIBBBBIIIIBBBBBHHIIH'

def calc_crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000: crc = (crc << 1) ^ 0x1021
            else: crc <<= 1
        crc &= 0xFFFF
    return crc

class RealTimeGraph(QFrame):
    def __init__(self, max_val=20.0, line_color=QColor(0, 0, 0), title="", parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Box | QFrame.Plain)
        self.setStyleSheet("background: #FFFFFF; border: 3px solid #000000;")
        self.data = deque([0.0] * 300, maxlen=300) 
        self.max_val = max_val
        self.line_color = line_color
        self.title = title
        self.setMinimumHeight(150)

    def add_value(self, val):
        self.data.append(val)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        
        p.fillRect(10, 10, len(self.title)*10, 20, QColor("#FFEB3B"))
        
        p.setPen(QColor("#000000"))
        p.setFont(QFont("Consolas", 10, QFont.Bold))
        p.drawText(15, 25, self.title)
        
        p.setPen(QPen(QColor("#000000"), 1, Qt.DashLine))
        p.drawLine(0, int(h/2), w, int(h/2))

        path = QPainterPath()
        scale_x = w / (len(self.data) - 1) if len(self.data) > 1 else 1
        scale_y = h / self.max_val if self.max_val > 0 else 1

        path.moveTo(0, h - (self.data[0] * scale_y))
        for i, val in enumerate(self.data):
            x = i * scale_x
            y = h - (val * scale_y)
            path.lineTo(x, max(0, min(h, y)))

        p.setPen(QPen(self.line_color, 3))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        if self.data:
            val_str = f"{self.data[-1]:.1f}"
            p.fillRect(w - 70, 10, 60, 25, QColor("#000000"))
            p.setPen(QColor("#FFFFFF"))
            p.setFont(QFont("Consolas", 12, QFont.Bold))
            p.drawText(w - 65, 27, val_str)

class CommsThread(QThread):
    telemetry_signal = pyqtSignal(dict)
    connection_signal = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.port_name = ""
        self.running = False
        self.last_rx_time = 0
        self.cmd_enable = False
        self.cmd_safety = True
        self.cmd_load = False
        self.cmd_fire = False
        self.cmd_manual = 0
        self.cmd_bypass = False
        self.cmd_reset_cycle = False
        self.req_set_ammo = 0 
        self.mode = 0
        self.burst = 1
        self.timings = [35, 80, 450, 10000]
        self.seq = 0

    def start_comms(self, port):
        self.port_name = port
        self.running = True
        self.start()

    def stop_comms(self):
        self.running = False
        self.wait()

    def run(self):
        ser = None
        try:
            ser = serial.Serial(self.port_name, BAUD_RATE, timeout=0.002, write_timeout=0)
            self.connection_signal.emit(True)
        except Exception as e:
            self.connection_signal.emit(False)
            return

        rx_buffer = bytearray()
        last_tx_time = 0
        self.last_rx_time = time.time()

        while self.running:
            try:
                now = time.time()
                if now - self.last_rx_time > 1.0:
                    self.telemetry_signal.emit({'timeout': True})
                
                if now - last_tx_time >= 0.005:
                    self.seq = (self.seq + 1) & 0xFFFF
                    ammo_to_send = self.req_set_ammo
                    self.req_set_ammo = 0 

                    try:
                        pkt = struct.pack(CMD_FMT,
                            CMD_HEADER, 1, self.seq, self.mode,
                            self.timings[0], self.timings[1], self.timings[2], self.timings[3],
                            1 if self.cmd_safety else 0, 1 if self.cmd_load else 0, 1 if self.cmd_fire else 0,
                            self.cmd_manual, self.burst, ammo_to_send, 
                            1 if self.cmd_enable else 0, 1 if self.cmd_bypass else 0, 1 if self.cmd_reset_cycle else 0
                        )
                        crc = calc_crc16(pkt)
                        ser.write(pkt + struct.pack('<H', crc))
                        last_tx_time = now
                    except Exception:
                        pass

                if ser.in_waiting:
                    chunk = ser.read(ser.in_waiting)
                    rx_buffer.extend(chunk)
                    while len(rx_buffer) >= PACKET_SIZE:
                        try: idx = rx_buffer.index(TLM_HEADER)
                        except ValueError: rx_buffer = bytearray(); break
                        if idx > 0: del rx_buffer[:idx]; continue
                        if len(rx_buffer) < PACKET_SIZE: break
                        
                        raw_pkt = rx_buffer[:PACKET_SIZE]
                        payload = raw_pkt[:-2]
                        rcv_crc = struct.unpack('<H', raw_pkt[-2:])[0]
                        calc = calc_crc16(payload)

                        if calc == rcv_crc:
                            self.last_rx_time = time.time()
                            try:
                                data = self.parse_fast(payload)
                                self.telemetry_signal.emit(data)
                            except Exception: pass
                            del rx_buffer[:PACKET_SIZE]
                        else: del rx_buffer[0:1] 

            except Exception: pass
            self.usleep(100) 

        if ser and ser.is_open: ser.close()
        self.connection_signal.emit(False)

    def parse_fast(self, payload):
        val = struct.unpack(FULL_TLM_FMT, payload)
        return {
            'timeout': False,
            'header': val[0], 'state': val[1], 'err': val[2], 'mag_rem': val[3], 'burst_fired': val[4], 'curr': val[5],
            'cur_t1': val[6], 'cur_t2': val[7], 'cur_t3': val[8], 'cur_t4': val[9],
            'lvdt_header': val[10], 'mode_flags': val[11], 'b_cnt_lvdt': val[12], 'b_rem_lvdt': val[13],
            't_recv': val[14], 't_free': val[15], 't_chamb': val[16], 't_shock': val[17],
            'p1': val[18], 'p2': val[19], 'success': val[20], 'misfire': val[21], 'out': val[22], 'pos': val[23], 'lvdt_crc': val[24],
            'count_miss': val[25], 'timing_sum': val[26], 'ack_flags': val[27]
        }

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GCU CONTROL // NEO-BRUTAL")
        self.resize(1280, 950)
        
        self.thread = CommsThread()
        self.thread.telemetry_signal.connect(self.update_ui)
        self.thread.connection_signal.connect(self.on_conn)
        
        self.init_csv_logging()
        self.init_ui()
        self.apply_style()
        self.refresh_ports()

        self.tmr = QTimer()
        self.tmr.timeout.connect(self.sync_data)
        self.tmr.start(50) 
        
        self.last_draw_time = 0

    def init_csv_logging(self):
        filename = f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        self.csv_file = open(filename, 'w', newline='')
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_header_written = False

    def write_log(self, data):
        if not self.csv_file: return
        log_data = data.copy()
        log_data['pc_time'] = datetime.now().strftime('%H:%M:%S.%f')
        if not self.csv_header_written:
            self.csv_writer.writerow(log_data.keys())
            self.csv_header_written = True
        self.csv_writer.writerow(log_data.values())

    def apply_style(self):
        c_bg = "#FFFFFF"       
        c_fg = "#000000"       
        c_border = "#000000"   
        c_yellow = "#FFEB3B" 
        c_cyan = "#00E5FF" 
        c_pink = "#FF4081" 
        c_green = "#76FF03" 
        c_warn = "#FF3D00"     
        c_gray = "#F0F0F0"     

        self.setStyleSheet(f"""
            QMainWindow {{ background: {c_gray}; }}
            
            QGroupBox {{ 
                background: {c_bg}; 
                border: 3px solid {c_border}; 
                font-family: 'Consolas', monospace;
                font-size: 11pt;
                font-weight: bold; 
                margin-top: 30px; 
                padding-top: 15px; 
            }}
            
            QGroupBox::title {{ 
                subcontrol-origin: margin; 
                subcontrol-position: top left; 
                left: 15px;
                top: 5px;
                padding: 4px 8px;
                background: {c_yellow}; 
                color: {c_fg};
                border: 3px solid {c_border};
                border-bottom: 5px solid {c_border};
                border-right: 5px solid {c_border};
            }}
            
            QPushButton {{ 
                background: {c_bg}; 
                border: 3px solid {c_border};
                border-bottom: 6px solid {c_border};
                border-right: 6px solid {c_border};
                padding: 10px; 
                font-family: 'Consolas', monospace;
                font-weight: 900; 
                color: {c_fg}; 
                font-size: 11pt;
                margin: 2px;
            }}
            
            QPushButton:hover {{ background: {c_cyan}; }}
            
            QPushButton:pressed {{ 
                border-bottom: 3px solid {c_border};
                border-right: 3px solid {c_border};
                padding-top: 13px; 
                padding-left: 13px;
                background: {c_fg}; 
                color: {c_yellow};
            }}
            
            QPushButton:checked {{ 
                background: {c_green}; 
                color: {c_fg};
                border-bottom: 3px solid {c_border};
                border-right: 3px solid {c_border};
            }}

            QPushButton#btn_load {{ background: {c_cyan}; }}
            QPushButton#btn_fire {{ background: {c_warn}; color: white; }}
            QPushButton#btn_reset {{ background: {c_warn}; color: white; }}

            QLabel {{ 
                color: {c_fg}; 
                font-family: 'Consolas', monospace; 
                font-size: 10pt; 
                font-weight: bold;
            }}
            
            QComboBox, QSpinBox {{
                border: 3px solid {c_border};
                padding: 5px;
                background: {c_bg};
                font-weight: bold;
                font-family: 'Consolas', monospace;
                min-height: 25px;
            }}
            QComboBox::drop-down {{
                border-left: 3px solid {c_border};
                background: {c_yellow};
                width: 30px;
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                border-left: 2px solid {c_border};
                background: {c_gray};
                width: 20px;
            }}
            
            QCheckBox {{ 
                font-family: 'Consolas', monospace;
                font-weight: bold; 
                font-size: 11pt; 
                color: {c_fg}; 
                spacing: 10px;
                padding: 5px;
            }}
            
            QCheckBox::indicator {{
                width: 20px; height: 20px;
                border: 3px solid {c_border};
                background: {c_bg};
            }}
            QCheckBox::indicator:checked {{
                background: {c_fg}; 
                image: none;
                border: 3px solid {c_border};
            }}
            
            QRadioButton {{ 
                font-family: 'Consolas', monospace; 
                font-weight: bold; 
                spacing: 10px;
            }}
            QRadioButton::indicator {{
                width: 18px; height: 18px;
                border: 3px solid {c_border};
                border-radius: 12px;
                background: {c_bg};
            }}
            QRadioButton::indicator:checked {{
                background: {c_fg};
                border: 5px solid {c_bg};
                outline: 3px solid {c_border};
            }}
        """)

    def init_ui(self):
        w = QWidget(); self.setCentralWidget(w); layout = QHBoxLayout(w)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        left = QVBoxLayout(); right = QVBoxLayout()
        left.setSpacing(15); right.setSpacing(15)
        layout.addLayout(left, 3); layout.addLayout(right, 7)

        g_con = QGroupBox("CONNECTION"); l_con = QHBoxLayout()
        self.cb_port = QComboBox(); self.cb_port.setMinimumHeight(30)
        b_ref = QPushButton("R"); b_ref.setMaximumWidth(40); b_ref.clicked.connect(self.refresh_ports)
        self.b_con = QPushButton("CONNECT"); self.b_con.setCheckable(True); self.b_con.clicked.connect(self.toggle_con)
        l_con.addWidget(self.cb_port, 1); l_con.addWidget(b_ref); l_con.addWidget(self.b_con, 1)
        g_con.setLayout(l_con); left.addWidget(g_con)

        g_mst = QGroupBox("MASTER CONTROL"); l_mst = QVBoxLayout()
        self.ck_en = QCheckBox("SYSTEM ENABLE")
        self.ck_safe = QCheckBox("SAFETY ACTIVE"); self.ck_safe.setChecked(True)
        self.ck_bypass = QCheckBox("BYPASS LVDT")
        l_mst.addWidget(self.ck_en); l_mst.addWidget(self.ck_safe); l_mst.addWidget(self.ck_bypass)
        g_mst.setLayout(l_mst); left.addWidget(g_mst)

        g_cfg = QGroupBox("CONFIGURATION"); l_cfg = QGridLayout()
        self.bg_mode = QButtonGroup()
        modes = ["SINGLE", "SEMI-S", "SEMI-L", "AUTO"]
        for i, m in enumerate(modes):
            rb = QRadioButton(m); self.bg_mode.addButton(rb, i); l_cfg.addWidget(rb, i, 0)
        self.bg_mode.button(0).setChecked(True)
        
        self.sb_burst = QSpinBox(); self.sb_burst.setRange(1, 100); self.sb_burst.setValue(1)
        l_cfg.addWidget(QLabel("BURST:"), 4, 0); l_cfg.addWidget(self.sb_burst, 4, 1)
        
        self.sb_mag = QSpinBox(); self.sb_mag.setRange(0, 999); self.sb_mag.setValue(30)
        b_set_ammo = QPushButton("SET"); b_set_ammo.setMaximumWidth(50)
        b_set_ammo.clicked.connect(self.trigger_set_ammo)
        
        l_cfg.addWidget(QLabel("AMMO:"), 5, 0)
        h_ammo = QHBoxLayout(); h_ammo.addWidget(self.sb_mag); h_ammo.addWidget(b_set_ammo)
        l_cfg.addLayout(h_ammo, 5, 1)
        
        self.sb_times = []
        vals = [35, 80, 450, 10000] 
        lbls = ["T.SGL", "T.SM-S", "T.SM-L", "T.AUTO"]
        for i in range(4):
            l_cfg.addWidget(QLabel(lbls[i]), 6+i, 0)
            sb = QSpinBox(); sb.setRange(10, 10000); sb.setValue(vals[i]); self.sb_times.append(sb)
            l_cfg.addWidget(sb, 6+i, 1)
        g_cfg.setLayout(l_cfg); left.addWidget(g_cfg)

        g_man = QGroupBox("MANUAL OPS"); l_man = QGridLayout()
        b_ext = QPushButton("EXTEND"); b_ret = QPushButton("RETRACT")
        b_ext.pressed.connect(lambda: self.set_man(1)); b_ext.released.connect(lambda: self.set_man(0))
        b_ret.pressed.connect(lambda: self.set_man(2)); b_ret.released.connect(lambda: self.set_man(0))
        
        b_rst = QPushButton("RESET STATS"); b_rst.setObjectName("btn_reset")
        b_rst.pressed.connect(lambda: self.set_rst(True)); b_rst.released.connect(lambda: self.set_rst(False))
        
        l_man.addWidget(b_ext, 0, 0); l_man.addWidget(b_ret, 0, 1)
        l_man.addWidget(b_rst, 1, 0, 1, 2)
        g_man.setLayout(l_man); left.addWidget(g_man)
        left.addStretch()

        g_st = QGroupBox("STATUS MONITOR"); l_st = QHBoxLayout()
        self.lb_st = QLabel("OFFLINE"); self.lb_st.setAlignment(Qt.AlignCenter)
        self.lb_st.setStyleSheet("background: #F0F0F0; color: #000000; font-size: 24pt; font-weight: 900; border: 3px solid #000000;")
        
        self.ind_ack = QLabel("SYNC")
        self.ind_ack.setAlignment(Qt.AlignCenter)
        self.ind_ack.setFixedWidth(80)
        self.ind_ack.setStyleSheet("background: #F0F0F0; border: 3px solid #000000; font-weight: bold;")

        l_st.addWidget(self.lb_st, 8); l_st.addWidget(self.ind_ack, 2)
        g_st.setLayout(l_st); right.addWidget(g_st)

        g_gr = QGroupBox("VISUALIZATION"); l_gr = QGridLayout()
        self.graph_curr = RealTimeGraph(max_val=20.0, line_color=QColor("#00E5FF"), title="CURRENT (A)")
        self.graph_lvdt = RealTimeGraph(max_val=65535.0, line_color=QColor("#FF4081"), title="LVDT POS")
        self.graph_p1 = RealTimeGraph(max_val=2.0, line_color=QColor("#76FF03"), title="SENS P1")
        self.graph_p2 = RealTimeGraph(max_val=2.0, line_color=QColor("#9C27B0"), title="SENS P2")
        l_gr.addWidget(self.graph_curr, 0, 0); l_gr.addWidget(self.graph_lvdt, 0, 1)
        l_gr.addWidget(self.graph_p1, 1, 0); l_gr.addWidget(self.graph_p2, 1, 1)
        g_gr.setLayout(l_gr); right.addWidget(g_gr)

        g_tlm = QGroupBox("TELEMETRY"); l_tlm = QGridLayout()
        num_style = "font-size: 16pt; font-weight: 900; color: #000000; background: #FFFFFF; border: 2px solid black; padding: 2px;"
        
        self.lbl_curr = QLabel("0.00 A"); self.lbl_curr.setStyleSheet(num_style)
        self.lbl_mag_rem = QLabel("0"); self.lbl_mag_rem.setStyleSheet(num_style + "color: #FF4081;")
        self.lbl_burst_fired = QLabel("0"); self.lbl_burst_fired.setStyleSheet(num_style)
        self.lbl_miss = QLabel("0"); self.lbl_miss.setStyleSheet(num_style)
        self.lbl_time_sum = QLabel("0 ms"); self.lbl_time_sum.setStyleSheet(num_style)
        
        l_tlm.addWidget(QLabel("CURRENT:"), 0, 0); l_tlm.addWidget(self.lbl_curr, 0, 1)
        l_tlm.addWidget(QLabel("MAGAZINE:"), 0, 2); l_tlm.addWidget(self.lbl_mag_rem, 0, 3)
        l_tlm.addWidget(QLabel("BURST CNT:"), 1, 0); l_tlm.addWidget(self.lbl_burst_fired, 1, 1)
        l_tlm.addWidget(QLabel("MISS CNT:"), 1, 2); l_tlm.addWidget(self.lbl_miss, 1, 3)
        l_tlm.addWidget(QLabel("CYCLE T:"), 2, 0); l_tlm.addWidget(self.lbl_time_sum, 2, 1)
        g_tlm.setLayout(l_tlm); right.addWidget(g_tlm)

        g_sen = QGroupBox("FLAGS"); l_sen = QHBoxLayout()
        self.ind_p1 = QLabel("P1"); self.ind_p2 = QLabel("P2"); 
        self.ind_jam = QLabel("JAM"); self.ind_out = QLabel("EMPTY")
        self.ind_suc = QLabel("OK"); self.ind_mis = QLabel("FAIL")
        for l in [self.ind_p1, self.ind_p2, self.ind_jam, self.ind_out, self.ind_suc, self.ind_mis]:
            l.setAlignment(Qt.AlignCenter)
            l.setStyleSheet("background: #FFFFFF; border: 2px solid #000000; color: #F0F0F0; font-weight: bold; min-width: 50px; padding: 5px;")
            l_sen.addWidget(l)
        g_sen.setLayout(l_sen); right.addWidget(g_sen)

        g_act = QGroupBox("COMMAND"); l_act = QHBoxLayout()
        b_load = QPushButton("LOAD"); b_load.setObjectName("btn_load"); b_load.setMinimumHeight(60)
        b_fire = QPushButton("FIRE"); b_fire.setObjectName("btn_fire"); b_fire.setMinimumHeight(60)
        
        b_load.pressed.connect(lambda: self.set_cmd('load', True)); b_load.released.connect(lambda: self.set_cmd('load', False))
        b_fire.pressed.connect(lambda: self.set_cmd('fire', True)); b_fire.released.connect(lambda: self.set_cmd('fire', False))
        l_act.addWidget(b_load); l_act.addWidget(b_fire)
        g_act.setLayout(l_act); right.addWidget(g_act)

    def refresh_ports(self):
        self.cb_port.clear()
        for p in serial.tools.list_ports.comports(): self.cb_port.addItem(p.device)
    def toggle_con(self):
        if self.b_con.isChecked(): self.thread.start_comms(self.cb_port.currentText())
        else: self.thread.stop_comms()
    def on_conn(self, ok):
        if ok: 
            self.b_con.setText("DISCONNECT")
        else: 
            self.b_con.setChecked(False); self.b_con.setText("CONNECT"); 
            self.lb_st.setText("OFFLINE")
            self.lb_st.setStyleSheet("background: #F0F0F0; color: #000000; font-size: 24pt; font-weight: 900; border: 3px solid #000000;")
    
    def set_cmd(self, k, v):
        if k == 'load': self.thread.cmd_load = v
        if k == 'fire': self.thread.cmd_fire = v
    def set_man(self, v): self.thread.cmd_manual = v
    def set_rst(self, v): self.thread.cmd_reset_cycle = v
    
    def trigger_set_ammo(self):
        self.thread.req_set_ammo = self.sb_mag.value()
    
    def sync_data(self):
        self.thread.cmd_enable = self.ck_en.isChecked()
        self.thread.cmd_safety = self.ck_safe.isChecked()
        self.thread.cmd_bypass = self.ck_bypass.isChecked()
        self.thread.mode = self.bg_mode.checkedId()
        self.thread.burst = self.sb_burst.value()
        self.thread.timings = [sb.value() for sb in self.sb_times]

    def update_ui(self, d):
        if d.get('timeout', False):
            self.lb_st.setText("NO LINK"); 
            self.lb_st.setStyleSheet("background: #000000; color: #FF3D00; font-weight: 900; font-size: 24pt; border: 3px solid #FF3D00;")
            self.ind_ack.setStyleSheet("background: #F0F0F0; border: 3px solid #000000;")
            return

        self.write_log(d)

        now = time.time()
        if now - self.last_draw_time < 0.030: return 
        self.last_draw_time = now

        self.graph_curr.add_value(d['curr'])
        self.graph_p1.add_value(d['p1'])
        self.graph_p2.add_value(d['p2'])
        if not self.ck_bypass.isChecked(): self.graph_lvdt.add_value(d['pos'])
        else: self.graph_lvdt.add_value(0)

        st = d['state']
        txt = {0:"UNK", 1:"READY LOAD", 2:"READY FIRE", 3:"LOAD(EXT)", 4:"WAIT", 5:"LOAD(RET)", 6:"FIRING", 7:"MAN EXT", 8:"MAN RET", 10: "ERR: OVC", 11: "ERR: LVDT", 12:"JAMMED", 13:"EMPTY"}.get(st, f"STATE {st}")
        
        col = "#F0F0F0"
        if st in [1, 2]: col = "#76FF03" 
        elif st == 6: col = "#FFEB3B" 
        elif st >= 10: col = "#FF3D00" 
        elif st in [3,4,5]: col = "#00E5FF" 
        
        self.lb_st.setText(txt)
        self.lb_st.setStyleSheet(f"background: {col}; color: black; font-weight: 900; font-size: 24pt; border: 3px solid black;")
        
        ack = d['ack_flags']
        if ack > 0:
            self.ind_ack.setStyleSheet("background: #76FF03; color: black; font-weight: bold; border: 3px solid black;")
        else:
            self.ind_ack.setStyleSheet("background: #F0F0F0; border: 3px solid #000000;")

        self.lbl_curr.setText(f"{d['curr']:.2f} A")
        self.lbl_mag_rem.setText(f"{d['mag_rem']}")
        self.lbl_burst_fired.setText(f"{d['burst_fired']}")
        self.lbl_miss.setText(f"{d['count_miss']}")
        self.lbl_time_sum.setText(f"{d['timing_sum']} ms")
        
        def set_led(l, on, c="#76FF03"):
            bg = c if on else "#FFFFFF"
            fg = "black" if on else "#F0F0F0"
            l.setStyleSheet(f"background: {bg}; color: {fg}; font-weight: bold; border: 2px solid #000000; min-width: 50px; padding: 5px;")
        
        set_led(self.ind_p1, d['p1'] > 0)
        set_led(self.ind_p2, d['p2'] > 0)
        set_led(self.ind_jam, d['misfire'] or st==12, "#FF3D00")
        set_led(self.ind_out, d['out'] or st==13, "#FF3D00")
        set_led(self.ind_suc, d['success'], "#76FF03")
        set_led(self.ind_mis, d['misfire'], "#FF3D00")

    def closeEvent(self, event):
        self.thread.stop_comms()
        if hasattr(self, 'csv_file') and self.csv_file: self.csv_file.close()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    font = QFont("Consolas")
    font.setStyleHint(QFont.Monospace)
    app.setFont(font)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())