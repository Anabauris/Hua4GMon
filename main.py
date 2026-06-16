"""
Hua4GMon — Huawei 4G Monitor (portable, single-file).

Mērķis:
    Rīks antenu montieriem un Huawei rūteru (E3372, B315, B525, B535,
    B628, B818 un citi) lietotājiem LTE signāla kvalitātes monitoringam,
    antenas manuālai pielāgošanai un bāzes stacijas parametru fiksēšanai.

Šīs versijas īpašības:
    * Pilnībā portatīvs: NEKAS netiek saglabāts diskā
      (nav config.ini, nav paroļu failos, nav žurnālu diskā).
    * Viens izpildāmais fails.
    * Grafiks veidots ar tīru tk.Canvas — nav matplotlib (~30 MB
      ekonomijas .exe failā, ātrāka palaišana).
    * Automātiska pārslēgšanās, ja pazūd savienojums ar rūteri.
    * Virziena indikators (↑↓→) — parāda, vai signāls uzlabojas,
      pagriežot antenu.
    * LTE band un EARFCN noteikšana ar piesaisti frekvencei.
    * Sesijas eksports CSV formātā klienta atskaitei (pēc pieprasījuma).
    * CLI argumenti ātrai palaišanai (--ip, --password).

Palaišana:
    python main.py
    python main.py --ip 192.168.1.1 --password admin

Portatīvā .exe veidošana (Windows):
    pip install pyinstaller
    pyinstaller --onefile --windowed --name Hua4GMon main.py

Atkarības:
    huawei-lte-api>=1.10
"""

from __future__ import annotations

import argparse
import csv
import datetime
import logging
import re
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional, Tuple

from huawei_lte_api.Client import Client
from huawei_lte_api.Connection import Connection

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False


__version__ = "1.2"
APP_NAME = "Hua4GMon"

logger = logging.getLogger(APP_NAME)


# =========================================================
# KONSTANTES
# =========================================================

PLMN_MAP: Dict[str, str] = {
    # Latvia (MCC=247)
    '24701': 'LMT', '24702': 'Tele2 LV', '24705': 'Bite',
    # Russia (MCC=250)
    '25001': 'MTS', '25002': 'MegaFon', '25011': 'Yota',
    '25020': 'Tele2', '25027': 'Letai', '25035': 'Motiv',
    '25039': 'Rostelecom', '25099': 'Beeline',
    # Belarus (MCC=257)
    '25701': 'A1 BY', '25702': 'MTS BY', '25704': 'life:)',
    # Kazakhstan (MCC=401)
    '40101': 'Beeline KZ', '40102': 'Kcell', '40177': 'Tele2 KZ',
    # Ukraine (MCC=255)
    '25501': 'Vodafone UA', '25502': 'Kyivstar', '25506': 'lifecell',
    # Lithuania (MCC=246)
    '24601': 'Omnitel', '24602': 'Bite LT', '24603': 'Tele2 LT',
    # Estonia (MCC=248)
    '24801': 'Telia EE', '24802': 'Elisa', '24803': 'Tele2 EE',
}

# LTE bitmask values used by Huawei set_net_mode()
BANDS: Dict[str, int] = {
    'B1 (2100 MHz)':   0x1,
    'B3 (1800 MHz)':   0x4,
    'B7 (2600 MHz)':   0x40,
    'B8 (900 MHz)':    0x80,
    'B20 (800 MHz)':   0x80000,
    'B38 (TDD 2600)':  0x2000000000,
    'B40 (TDD 2300)':  0x8000000000,
}

ANTENNA_MODES: Dict[str, int] = {
    "Auto": 0,
    "Iekšējā": 1,
    "Ārējā": 2,
    "Jaukta": 3,
}

# LTE band atšifrējums: numurs → īsa frekvenču josla
BAND_FREQ_MAP: Dict[int, str] = {
    1: "2100", 2: "1900PCS", 3: "1800+", 4: "AWS-1", 5: "850",
    7: "2600", 8: "900", 12: "700a", 13: "700c", 17: "700b",
    18: "850Lower", 19: "850Upper", 20: "800DD", 25: "1900+",
    26: "850+", 28: "700APT", 32: "L-band",
    38: "TDD2600", 39: "TDD1900+", 40: "TDD2300", 41: "TDD2500",
    42: "TDD3500", 43: "TDD3700", 66: "AWS-3", 71: "600",
}

# EARFCN (downlink) diapazoni → band (3GPP TS 36.101). Galvenās izplatītās joslas.
EARFCN_RANGES: List[Tuple[int, int, int]] = [
    (0, 599, 1),       (600, 1199, 2),    (1200, 1949, 3),
    (1950, 2399, 4),   (2400, 2649, 5),   (2750, 3449, 7),
    (3450, 3799, 8),   (5010, 5179, 12),  (5180, 5279, 13),
    (5730, 5849, 17),  (5850, 5999, 18),  (6000, 6149, 19),
    (6150, 6449, 20),  (8040, 8689, 25),  (8690, 9039, 26),
    (9210, 9659, 28),  (37750, 38249, 38), (38250, 38649, 39),
    (38650, 39649, 40), (39650, 41589, 41),
    (41590, 43589, 42), (43590, 45589, 43),
    (66436, 67335, 66), (68586, 68935, 71),
]

# Network mode constants for set_net_mode
NETMODE_LTE_ONLY = '03'
NETMODE_AUTO = '00'
LTEBAND_AUTO_ALL = '7FFFFFFFFFFFFFFF'    # all LTE bands
NETBAND_AUTO_MASK = '3FFFFFFF'           # GSM/WCDMA/LTE auto

# Robežvērtības: [(min_vērtība, etiķete, krāsa, procentu_vērtējums), ...]
# Pēdējais ieraksts ar min_vērtība=None ir "noklusējuma" gadījums.
SIGNAL_THRESHOLDS: Dict[str, List[Tuple[Optional[float], str, str, int]]] = {
    'rsrp': [(-80,  "Izcils",         "#00b894", 100),
             (-90,  "Labs",           "#2ecc71", 80),
             (-100, "Vidējs",         "#fdcb6e", 50),
             (None, "Slikts",         "#d63031", 15)],
    'sinr': [(20,   "Ideāls",         "#00b894", 100),
             (13,   "Labs",           "#2ecc71", 75),
             (0,    "Trokšņains",     "#fdcb6e", 40),
             (None, "Kritisks",       "#d63031", 5)],
    'rssi': [(-65,  "Stiprs",         "#00b894", 100),
             (-75,  "Normāls",        "#2ecc71", 75),
             (-85,  "Vājš",           "#fdcb6e", 45),
             (None, "Ļoti vājš",      "#d63031", 10)],
    'rsrq': [(-6,   "Izcils",         "#00b894", 100),
             (-12,  "Stabils",        "#2ecc71", 70),
             (-15,  "Zudumi",         "#fdcb6e", 40),
             (None, "Lieli zudumi",   "#d63031", 10)],
}

PARAM_RANGES: Dict[str, Tuple[int, int]] = {
    'rsrp': (-120, -50),
    'rssi': (-110, -50),
    'rsrq': (-20, -3),
    'sinr': (-5, 30),
}

GRAPH_HISTORY = 100
JITTER_WINDOW = 5
SESSION_LOG_MAX = 10800        # ~3 stundas ar 1 s soli
RECONNECT_DELAY_INITIAL = 2.0
RECONNECT_DELAY_MAX = 30.0
DIRECTION_LOOKBACK = 3         # cik tikšķus salīdzināt bultas noteikšanai

IP_RE = re.compile(r'^\d{1,3}(\.\d{1,3}){3}$')


# =========================================================
# TĪRĀS FUNKCIJAS (vienkārši testējamas atsevišķi)
# =========================================================

def is_valid_ip(s: str) -> bool:
    """Vienkārša IPv4 validācija."""
    if not s or not IP_RE.match(s):
        return False
    return all(0 <= int(p) <= 255 for p in s.split('.'))


def evaluate_signal(param: str,
                    val: Optional[float]) -> Tuple[str, str, int]:
    """Atgriež (statusa_teksts, krāsa, kvalitātes_procenti)."""
    if val is None:
        return "Nav datu", "gray", 0
    rules = SIGNAL_THRESHOLDS.get(param)
    if not rules:
        return "N/D", "gray", 0
    for threshold, text, color, pct in rules:
        if threshold is None or val >= threshold:
            return text, color, pct
    return "N/D", "gray", 0


def calculate_overall_health(rsrp: Optional[float],
                              sinr: Optional[float]
                              ) -> Tuple[int, str, str]:
    """Vispārējs savienojuma kvalitātes vērtējums no RSRP un SINR."""
    if rsrp is None or sinr is None:
        return 0, "Nav datu", "gray"
    _, _, r_pct = evaluate_signal('rsrp', rsrp)
    _, _, s_pct = evaluate_signal('sinr', sinr)
    overall = int(min(r_pct, s_pct) * 0.7 + max(r_pct, s_pct) * 0.3)
    overall = max(0, min(100, overall))
    if overall >= 85:
        return overall, f"Ideāli ({overall}%) — 4K/tiešsaistes spēles", "#00b894"
    if overall >= 65:
        return overall, f"Labi ({overall}%) — stabils FullHD", "#2ecc71"
    if overall >= 35:
        return overall, f"Vidēji ({overall}%) — pagrieziet antenu", "#fdcb6e"
    return overall, f"Slikti ({overall}%) — savienojums rauties!", "#d63031"


def extract_number(val: Any) -> Optional[float]:
    """Stingra skaitļa izvilkšana. Nepieļauj 'timeout 0' tipa virknes."""
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s in ('-', 'None', 'N/A', 'NA'):
        return None
    # Pieļaujam zīmi, daļskaitļa daļu un opcionālu sufiksu (dBm, %, dB u.tml.)
    m = re.fullmatch(r'(-?\d+(?:\.\d+)?)\s*[a-zA-Z%/]*', s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def parse_cell_id(raw: Any) -> Tuple[Optional[int], Optional[int]]:
    """Parsē cell_id no Huawei API. Atgriež (eNodeB_id, sektors)."""
    if raw is None or raw == '':
        return None, None
    s = str(raw).strip()
    try:
        if s.lower().startswith('0x'):
            cid = int(s, 16)
        elif any(c in 'abcdefABCDEF' for c in s):
            cid = int(s, 16)
        else:
            cid = int(s)
    except (ValueError, TypeError):
        return None, None
    # Atmetam acīmredzami "nepareizas" vērtības
    if cid <= 0 or cid >= 0xFFFFFFFF:
        return None, None
    if cid > 0x0FFFFFFF:     # > 28 biti — nav LTE CID
        return None, None
    return cid // 256, cid % 256


def parse_antenna_value(label: str) -> Optional[int]:
    """Izvelk antenas režīma kodu no lokalizētas etiķetes."""
    base = label.split('(')[0].strip()
    if base in ANTENNA_MODES:
        return ANTENNA_MODES[base]
    m = re.search(r'\((\d+)\)', label)
    if m:
        return int(m.group(1))
    return None


def earfcn_to_band(earfcn: Any) -> Optional[int]:
    """EARFCN (DL channel) → LTE band numurs, vai None, ja nenoteikts."""
    try:
        e = int(earfcn)
    except (TypeError, ValueError):
        return None
    for lo, hi, band in EARFCN_RANGES:
        if lo <= e <= hi:
            return band
    return None


def format_band_label(band_raw: Any, earfcn: Any = None) -> str:
    """Cilvēkam saprotama LTE-band etiķete.

    Saprot formātus:
      "LTE BAND 7", "7", "B7", "B7+B20", "7+20", "0x40".
    Ja band nav pieejams — mēģina noteikt pēc EARFCN.
    """
    if band_raw not in (None, '', '-'):
        s = str(band_raw).strip()
        # Hex-maska, piem. 0x40
        if s.lower().startswith('0x'):
            try:
                mask = int(s, 16)
                # Pārbaudām zināmos viena bita laukus
                hits = [b for name, val in BANDS.items()
                        for b in [int(re.search(r'B(\d+)', name).group(1))]
                        if mask & val]
                if hits:
                    return _format_band_list(hits)
            except (ValueError, AttributeError):
                pass
        # Izvelkam visus numurus 1..100 (B1..B71, bez false-positives).
        # Bez \b — citādi nematčo "B3+B7" (B un 3 abi ir word-character).
        nums = [int(n) for n in re.findall(r'\d+', s)
                if 1 <= int(n) <= 100]
        if nums:
            return _format_band_list(nums)
        return s   # atgriežam kā ir
    # Fallback pēc EARFCN
    if earfcn not in (None, '', '-'):
        b = earfcn_to_band(earfcn)
        if b is not None:
            freq = BAND_FREQ_MAP.get(b, '')
            tail = f" ({freq} MHz)" if freq else ""
            return f"≈ B{b}{tail} [pēc EARFCN={earfcn}]"
    return "-"


def _format_band_list(bands: List[int]) -> str:
    """Formatē band numuru sarakstu virknē."""
    bands = list(dict.fromkeys(bands))   # dedup, saglabājot kārtību
    if len(bands) == 1:
        b = bands[0]
        freq = BAND_FREQ_MAP.get(b, '')
        return f"B{b}" + (f" ({freq} MHz)" if freq else "")
    parts = []
    for b in bands:
        freq = BAND_FREQ_MAP.get(b, '')
        parts.append(f"B{b}" + (f"/{freq}" if freq else ""))
    return "CA: " + " + ".join(parts)


def format_bytes_mb(b: Any) -> str:
    try:
        return f"{int(b) / 1048576:.1f} MB"
    except (TypeError, ValueError):
        return "-"


def format_rate_mbps(bps: Any) -> str:
    try:
        return f"{int(bps) * 8 / 1_000_000:.2f} Mbit/s"
    except (TypeError, ValueError):
        return "-"


# =========================================================
# GRAFIKS UZ tk.Canvas (matplotlib aizvietotājs)
# =========================================================

class CanvasGraph(tk.Canvas):
    """Vienkāršs līnijgrafiks uz tīra tk.Canvas (bez matplotlib).

    Atbalsta:
      * automātisku izmēra mainīšanu;
      * pielāgojamu Y ass diapazonu un etiķeti;
      * gludu punktu pievienošanu ar automātisku histories apgriešanu;
      * pēdējās vērtības marķieri ar skaitlisku etiķeti.
    """

    PADDING = (45, 12, 18, 22)   # left, right, top, bottom (px)

    def __init__(self, parent: tk.Misc, history: int = 100, **kw):
        super().__init__(parent, bg='white', highlightthickness=1,
                         highlightbackground='#cccccc', **kw)
        self.history = history
        self.values: List[float] = []
        self.y_min = -120.0
        self.y_max = -50.0
        self.unit = "dBm"
        self.title = "RSRP"
        self.bind("<Configure>", lambda e: self._redraw())

    def configure_axes(self, y_min: float, y_max: float,
                       unit: str, title: str) -> None:
        self.y_min, self.y_max = float(y_min), float(y_max)
        self.unit, self.title = unit, title
        self.values.clear()
        self._redraw()

    def push(self, val: float) -> None:
        self.values.append(float(val))
        if len(self.values) > self.history:
            self.values.pop(0)
        self._redraw()

    def clear(self) -> None:
        self.values.clear()
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 80 or h < 50:
            return
        pl, pr, pt, pb = self.PADDING
        plot_w, plot_h = w - pl - pr, h - pt - pb
        if plot_w <= 0 or plot_h <= 0:
            return

        # Virsraksts (augšā-pa kreisi)
        self.create_text(pl, 3, anchor='nw',
                         text=f"{self.title} ({self.unit})",
                         font=("Segoe UI", 9, "bold"), fill='#333')

        # Tīkls + Y ass etiķetes (5 līmeņi)
        for i in range(5):
            y = pt + plot_h * i / 4
            v = self.y_max - (self.y_max - self.y_min) * i / 4
            self.create_line(pl, y, w - pr, y, fill='#ececec')
            self.create_text(pl - 3, y, anchor='e', text=f"{v:g}",
                             font=("", 8), fill='#666')

        # X ass bāzes līnija
        self.create_line(pl, h - pb, w - pr, h - pb, fill='#888')
        self.create_text((pl + w - pr) / 2, h - 3, anchor='s',
                         text=f"pēdējie {self.history} punkti",
                         font=("", 8), fill='#888')

        if not self.values:
            return

        # Punkti
        span = max(self.history - 1, 1)
        rng = max(self.y_max - self.y_min, 1e-9)
        pts: List[float] = []
        for i, v in enumerate(self.values):
            x = pl + plot_w * i / span
            v_cl = max(self.y_min, min(self.y_max, v))
            y = (h - pb) - plot_h * (v_cl - self.y_min) / rng
            pts.extend([x, y])

        if len(pts) >= 4:
            self.create_line(*pts, fill='#0078D7', width=2)
        # Pēdējās vērtības marķieris
        lx, ly = pts[-2], pts[-1]
        self.create_oval(lx - 3, ly - 3, lx + 3, ly + 3,
                         fill='#0078D7', outline='')
        self.create_text(w - pr - 5, pt + 4, anchor='ne',
                         text=f"{self.values[-1]:g} {self.unit}",
                         font=("Segoe UI", 9, "bold"), fill='#0078D7')


# =========================================================
# GALVENĀ KLASE
# =========================================================

class Hua4GMon:
    def __init__(self, root: tk.Tk, default_ip: str = "192.168.8.1",
                 default_password: str = ""):
        self.root = root
        self.root.title(f"{APP_NAME} v{__version__}")
        self.root.geometry("900x720")
        self.root.minsize(820, 650)

        # ---- Thread sync primitives ----
        self._stop_event = threading.Event()
        self._data_lock = threading.Lock()
        self.monitor_thread: Optional[threading.Thread] = None
        self._interval_seconds: float = 1.0

        # ---- Connection state ----
        self.connected = False
        self.is_monitoring = False
        self.client: Optional[Client] = None
        self.last_data: Dict[str, Any] = {}
        self.device_info: Dict[str, Any] = {}
        self.start_time: Optional[float] = None
        self.roof_win: Optional[tk.Toplevel] = None

        # Cached credentials (live only in RAM, never written to disk)
        self._cached_ip: str = ""
        self._cached_pw: str = ""

        # ---- Monitoring buffers ----
        self.dynamic_params = ['rsrp', 'rssi', 'sinr', 'rsrq']
        self.peak_values: Dict[str, Any] = {p: '-' for p in self.dynamic_params}
        self.values: Dict[str, List[float]] = {p: [] for p in self.dynamic_params}
        self.session_log: List[Dict[str, Any]] = []
        self.dir_history: List[float] = []

        # ---- Reconnect ----
        self.auto_reconnect = True
        self.reconnect_delay = RECONNECT_DELAY_INITIAL

        # Defaults from CLI
        self.default_ip = default_ip
        self.default_password = default_password

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.setup_ui()

        if default_password:
            # CLI: automātiska pieslēgšanās
            self.root.after(200, self.start_connect)

    # =====================================================
    # UI BUILD
    # =====================================================

    def setup_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        # Augšējā statusa rinda
        self.top_bar = ttk.Frame(self.root)
        self.top_bar.pack(fill=tk.X, padx=5, pady=2)
        self.status_label = ttk.Label(
            self.top_bar, text="Atvienots", foreground='red',
            font=("Segoe UI", 10, "bold"))
        self.status_label.pack(side=tk.LEFT, padx=5)

        self.ontop_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.top_bar, text="Virsū logiem",
                        variable=self.ontop_var,
                        command=self.toggle_on_top).pack(side=tk.RIGHT, padx=5)

        # Cilnes
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.tab_settings = ttk.Frame(self.notebook)
        self.tab_monitor = ttk.Frame(self.notebook)
        self.tab_network = ttk.Frame(self.notebook)
        self.tab_tower = ttk.Frame(self.notebook)
        self.tab_status = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_settings, text="⚙️ Savienojums")
        self.notebook.add(self.tab_monitor, text="📈 Monitors")
        self.notebook.add(self.tab_network, text="🎛️ Tīkls")
        self.notebook.add(self.tab_tower, text="🗼 Tornis")
        self.notebook.add(self.tab_status, text="📊 Statuss")

        self.build_settings_tab()
        self.build_monitor_tab()
        self.build_network_tab()
        self.build_tower_tab()
        self.build_status_tab()

    def build_settings_tab(self) -> None:
        frame = ttk.LabelFrame(self.tab_settings,
                               text="Rūtera parametri", padding=10)
        frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(frame, text="IP adrese:").grid(
            row=0, column=0, sticky='e', padx=5, pady=5)
        self.ip_entry = ttk.Entry(frame, width=25)
        self.ip_entry.insert(0, self.default_ip)
        self.ip_entry.grid(row=0, column=1, sticky='w', padx=5)
        self.ip_entry.bind("<Return>", lambda e: self.password_entry.focus())

        ttk.Label(frame, text="Parole:").grid(
            row=1, column=0, sticky='e', padx=5, pady=5)
        self.password_entry = ttk.Entry(frame, show="*", width=25)
        if self.default_password:
            self.password_entry.insert(0, self.default_password)
        self.password_entry.grid(row=1, column=1, sticky='w', padx=5)
        # Enter paroles laukā — pieslēgties
        self.password_entry.bind("<Return>", lambda e: self.start_connect())

        ttk.Label(frame, text="Aptauja (sek):").grid(
            row=2, column=0, sticky='e', padx=5, pady=5)
        self.update_interval = tk.StringVar(value='1')
        self.update_interval.trace_add('write',
                                       lambda *a: self._sync_interval())
        ttk.Combobox(frame, textvariable=self.update_interval,
                     values=['0.5', '1', '2', '5'],
                     state='readonly', width=5).grid(
            row=2, column=1, sticky='w', padx=5)

        self.reconnect_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text="Automātiska pārslēgšanās, ja pazūd savienojums",
                        variable=self.reconnect_var).grid(
            row=3, column=0, columnspan=2, sticky='w', padx=5, pady=5)

        btn_frame = ttk.Frame(self.tab_settings)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        self.connect_button = ttk.Button(
            btn_frame, text="🚀 Pieslēgties", command=self.start_connect)
        self.connect_button.pack(side=tk.LEFT, padx=5)

        info = ttk.LabelFrame(self.tab_settings, text="Padoms", padding=10)
        info.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(info, wraplength=780, justify="left", text=(
            "• IP pēc noklusējuma vairumam Huawei: 192.168.8.1\n"
            "  (B315/B525 — 192.168.1.1 vai 192.168.3.1).\n"
            "• Lietotājvārds pēc noklusējuma: admin, parole norādīta uzlīmē.\n"
            "• 401 Unauthorized — pārstartējiet rūteri vai pārbaudiet paroli.\n"
            "• Dati diskā NETIEK saglabāti — programma ir pilnībā portatīva."
        )).pack(anchor='w')

    def build_monitor_tab(self) -> None:
        # Savienojuma kvalitāte — vienmēr redzama augšā
        self.health_frame = ttk.LabelFrame(
            self.tab_monitor, text="Vispārējā savienojuma kvalitāte", padding=10)
        self.health_frame.pack(fill=tk.X, padx=10, pady=5)
        self.health_progress = ttk.Progressbar(
            self.health_frame, orient="horizontal", mode="determinate")
        self.health_progress.pack(fill=tk.X, side=tk.TOP, pady=5)
        self.health_text_lbl = tk.Label(
            self.health_frame, text="Pieslēdzieties rūterim",
            font=("Segoe UI", 12, "bold"), fg="gray")
        self.health_text_lbl.pack(side=tk.TOP, pady=2)

        # 4 lieli rādītāji (ar maksimumu)
        self.digits_frame = ttk.Frame(self.tab_monitor)
        self.digits_frame.pack(fill=tk.X, padx=10, pady=5)
        self.lbl_vars: Dict[str, Dict[str, Any]] = {}
        for i, param in enumerate(self.dynamic_params):
            f = ttk.LabelFrame(self.digits_frame, text=param.upper(),
                               padding=5)
            f.grid(row=0, column=i, padx=5, sticky='nsew')
            self.digits_frame.columnconfigure(i, weight=1)
            val = tk.Label(f, text="-",
                           font=("Segoe UI", 20, "bold"), fg='gray')
            val.pack()
            status = tk.Label(f, text="Nav datu",
                              font=("Segoe UI", 9, "bold"), fg='gray')
            status.pack(pady=2)
            peak = tk.Label(f, text="Maks.: -",
                            font=("Segoe UI", 8), fg='gray')
            peak.pack(side=tk.BOTTOM)
            self.lbl_vars[param] = {
                'val': val, 'status': status, 'peak': peak, 'frame': f}

        # Virziena indikators (galvenais palīgs montāžai)
        self.dir_frame = ttk.LabelFrame(
            self.tab_monitor,
            text="RSRP tendence (pagrieziet antenu)", padding=8)
        self.dir_frame.pack(fill=tk.X, padx=10, pady=5)
        self.dir_label = tk.Label(
            self.dir_frame, text="—",
            font=("Segoe UI", 32, "bold"), fg='gray')
        self.dir_label.pack()
        self.dir_text = tk.Label(
            self.dir_frame, text="Tiek vākti dati...",
            font=("Segoe UI", 10), fg='gray')
        self.dir_text.pack()

        # Rīki: džiteris, audio palīgs, jumta režīms
        self.tools_frame = ttk.Frame(self.tab_monitor)
        self.tools_frame.pack(fill=tk.X, padx=15, pady=5)
        self.jitter_label = ttk.Label(
            self.tools_frame, text="Džiteris: -",
            font=("Segoe UI", 10, "bold"))
        self.geiger_var = tk.BooleanVar(value=False)
        self.geiger_cb = ttk.Checkbutton(
            self.tools_frame, text="🔊 Audio palīgs",
            variable=self.geiger_var)
        if not HAS_WINSOUND:
            self.geiger_cb.config(state='disabled',
                                  text="🔊 Audio (OS nav atbalstīta)")
        ttk.Button(self.tools_frame, text="🖥 Jumta režīms",
                   command=self.toggle_roof_mode).pack(side=tk.RIGHT, padx=5)
        self.geiger_cb.pack(side=tk.RIGHT, padx=5)
        self.jitter_label.pack(side=tk.LEFT)

        # Grafika vadība + eksports
        self.ctrl_frame = ttk.Frame(self.tab_monitor)
        self.ctrl_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(self.ctrl_frame, text="Grafiks:").pack(side=tk.LEFT)
        self.graph_param = tk.StringVar(value='rsrp')
        self.graph_cb = ttk.Combobox(
            self.ctrl_frame, textvariable=self.graph_param,
            values=self.dynamic_params, state='readonly', width=8)
        self.graph_cb.pack(side=tk.LEFT, padx=5)
        self.graph_cb.bind("<<ComboboxSelected>>", self.reset_graph)
        ttk.Button(self.ctrl_frame, text="Atiestatīt maksimumus",
                   command=self.reset_peaks).pack(side=tk.RIGHT, padx=5)
        ttk.Button(self.ctrl_frame, text="💾 Eksportēt CSV",
                   command=self.export_csv).pack(side=tk.RIGHT, padx=5)

        # Grafiks uz tīra tk.Canvas (bez matplotlib)
        self.signal_graph = CanvasGraph(
            self.tab_monitor, history=GRAPH_HISTORY, height=180)
        self.signal_graph.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.setup_graph()

    def build_network_tab(self) -> None:
        band_frame = ttk.LabelFrame(
            self.tab_network, text="Frekvenču fiksācija (Band Lock)", padding=10)
        band_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(band_frame, wraplength=800, justify='left', text=(
            "UZMANĪBU: diapazona fiksēšana var samazināt pārklājumu. "
            "Lietojiet, lai piesaistītos labākajai stacijai pēc "
            "analīzes Pro-režīmā.")).grid(
            row=0, column=0, columnspan=3, sticky='w', pady=(0, 8))

        self.band_checkboxes: Dict[str, tk.BooleanVar] = {}
        row, col = 1, 0
        for band_name in BANDS:
            var = tk.BooleanVar(value=False)
            ttk.Checkbutton(band_frame, text=band_name,
                            variable=var).grid(
                row=row, column=col, sticky='w', padx=10, pady=2)
            self.band_checkboxes[band_name] = var
            col += 1
            if col > 2:
                col = 0
                row += 1

        btn_frame = ttk.Frame(band_frame)
        btn_frame.grid(row=row + 1, column=0, columnspan=3, pady=10)
        ttk.Button(btn_frame, text="Pielietot Band Lock",
                   command=self.apply_bands).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Atiestatīt AUTO",
                   command=self.reset_bands).pack(side=tk.LEFT, padx=5)

        ant_frame = ttk.LabelFrame(self.tab_network,
                                   text="Antenu pārslēgšana", padding=10)
        ant_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(ant_frame, text="Režīms:").pack(side=tk.LEFT, padx=5)
        self.antenna_var = tk.StringVar(value="Auto")
        ttk.Combobox(ant_frame, textvariable=self.antenna_var,
                     values=list(ANTENNA_MODES.keys()),
                     state='readonly', width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(ant_frame, text="Pielietot",
                   command=self.apply_antenna).pack(side=tk.LEFT, padx=5)

        # Rūtera vadība
        mgmt_frame = ttk.LabelFrame(self.tab_network,
                                     text="Rūtera vadība", padding=10)
        mgmt_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(mgmt_frame, wraplength=820, justify='left', text=(
            "Pārstartēšana dažreiz nepieciešama pēc Band Lock, antenu "
            "pārslēgšanas vai, ja \"sastingst\" tīkla daļa. Pēc 1–2 "
            "minūtēm pieslēdzieties no jauna manuāli.")).pack(anchor='w', pady=(0, 6))
        ttk.Button(mgmt_frame, text="🔄 Pārstartēt rūteri",
                   command=self.reboot_router).pack(side=tk.LEFT, padx=5)

    def build_tower_tab(self) -> None:
        info_frame = ttk.LabelFrame(
            self.tab_tower, text="Informācija par stāciju", padding=10)
        info_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
        self.tower_labels: Dict[str, ttk.Label] = {}
        fields = [
            ('plmn', 'Operators (PLMN)'),
            ('band', 'Darba Band (LTE)'),
            ('earfcn', 'EARFCN (DL kanāls)'),
            ('aggregation', 'Agregācija (CA)'),
            ('dlbandwidth', 'Kanāla platums (DL)'),
            ('pci', 'Antenas sektors (PCI)'),
            ('enodeb', 'eNodeB (Tornis)'),
            ('sector', 'Cell (Lokālais sektors)'),
        ]
        for i, (key, name) in enumerate(fields):
            ttk.Label(info_frame, text=f"{name}:",
                      font=("", 10, "bold")).grid(
                row=i, column=0, sticky='e', pady=4, padx=5)
            lbl = ttk.Label(info_frame, text="-", font=("", 10))
            lbl.grid(row=i, column=1, sticky='w', pady=4, padx=5)
            self.tower_labels[key] = lbl

        # SIM / Ierīce — statiska info, aizpildīta pieslēgšanās brīdī
        sim_frame = ttk.LabelFrame(
            self.tab_tower, text="SIM / Ierīce", padding=10)
        sim_frame.pack(fill=tk.X, padx=10, pady=5)
        self.sim_labels: Dict[str, ttk.Label] = {}
        sim_fields = [
            ('Imei', 'IMEI (rūteris)'),
            ('Imsi', 'IMSI (SIM)'),
            ('Iccid', 'ICCID (SIM-karte)'),
            ('Msisdn', 'Tālruņa numurs'),
            ('SerialNumber', 'Sērijas numurs'),
            ('DeviceName', 'Modelis'),
            ('SoftwareVersion', 'Programmaparatūra'),
        ]
        for i, (key, name) in enumerate(sim_fields):
            ttk.Label(sim_frame, text=f"{name}:",
                      font=("", 10, "bold")).grid(
                row=i, column=0, sticky='e', pady=3, padx=5)
            lbl = ttk.Label(sim_frame, text="-",
                             font=("Consolas", 10))
            lbl.grid(row=i, column=1, sticky='w', pady=3, padx=5)
            self.sim_labels[key] = lbl

        btn_frame = ttk.Frame(self.tab_tower)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(btn_frame, text="🗺 Atvērt CellMapper",
                   command=self.open_cellmapper).pack(side=tk.LEFT, padx=5)

    def build_status_tab(self) -> None:
        stat_frame = ttk.LabelFrame(
            self.tab_status, text="Aparatūras un trafika monitorings",
            padding=10)
        stat_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.stat_labels: Dict[str, ttk.Label] = {}
        fields = [
            ('uptime', 'Sesijas laiks'),
            ('temp', 'Mikroshēmas temperatūra'),
            ('dl_rate', 'Ātrums (Download)'),
            ('ul_rate', 'Ātrums (Upload)'),
            ('total_dl', 'Lejupielādēts sesijā'),
            ('total_ul', 'Augšupielādēts sesijā'),
            ('rsrp_min', 'RSRP min / maks'),
            ('sinr_min', 'SINR min / maks'),
        ]
        for i, (key, name) in enumerate(fields):
            ttk.Label(stat_frame, text=f"{name}:",
                      font=("", 10, "bold")).grid(
                row=i, column=0, sticky='e', pady=6, padx=5)
            lbl = ttk.Label(stat_frame, text="-", font=("", 10))
            lbl.grid(row=i, column=1, sticky='w', pady=6, padx=5)
            self.stat_labels[key] = lbl

    # =====================================================
    # Misc helpers
    # =====================================================

    def toggle_on_top(self) -> None:
        self.root.attributes('-topmost', self.ontop_var.get())

    def _sync_interval(self) -> None:
        try:
            self._interval_seconds = float(self.update_interval.get())
        except (ValueError, tk.TclError):
            self._interval_seconds = 1.0

    # =====================================================
    # CONNECTION
    # =====================================================

    def start_connect(self) -> None:
        if self.connected:
            self.disconnect()
            return
        ip = self.ip_entry.get().strip()
        if not is_valid_ip(ip):
            messagebox.showerror("Kļūda",
                                 f"Nederīga IP adrese: {ip!r}\n"
                                 "Piemērs: 192.168.8.1")
            return
        self._cached_ip = ip
        self._cached_pw = self.password_entry.get()
        self._sync_interval()
        self.auto_reconnect = self.reconnect_var.get()
        self.reconnect_delay = RECONNECT_DELAY_INITIAL
        self.connect_button.config(state='disabled')
        self.status_label.config(text="Pieslēdzas...", foreground='orange')
        threading.Thread(target=self._connect_thread, daemon=True).start()

    def _connect_thread(self) -> None:
        url = f"http://{self._cached_ip}"
        try:
            client = Client(Connection(
                url, username='admin',
                password=self._cached_pw, timeout=4))
            info = client.device.information() or {}    # verifikācija + cache
            self.client = client
            self.device_info = info
            self.connected = True
            self.is_monitoring = True
            self.start_time = time.time()
            self._stop_event.clear()
            self.root.after(0, self._on_connected_success)
            self.monitor_thread = threading.Thread(
                target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()
        except Exception as e:
            logger.exception("Connect failed")
            self.root.after(0, lambda err=str(e): self._on_connected_fail(err))

    def _on_connected_success(self) -> None:
        self.connect_button.config(state='normal', text="⏹ Atvienoties")
        self.status_label.config(text="Pieslēgts", foreground='green')
        self.notebook.select(self.tab_monitor)
        self.reset_graph()
        self.session_log.clear()
        self.dir_history.clear()
        self.peak_values = {p: '-' for p in self.dynamic_params}
        # Aizpildām SIM/Device etiķetes no kešotā device.information()
        for key, lbl in self.sim_labels.items():
            raw = self.device_info.get(key, '')
            lbl.config(text=str(raw) if raw not in (None, '') else 'N/D')

    def _on_connected_fail(self, error: str) -> None:
        self.connect_button.config(state='normal', text="🚀 Pieslēgties")
        self.status_label.config(text="Kļūda", foreground='red')
        snippet = error if len(error) < 200 else error[:200] + "..."
        messagebox.showerror("Pieslēgšanas kļūda",
                             f"Nav iespējams sazināties ar rūteri:\n\n{snippet}")

    def disconnect(self) -> None:
        """Korekta apturēšana: vispirms apturam pavedienu, tad atbrīvojam klientu."""
        was_connected = self.connected
        self.is_monitoring = False
        self.connected = False
        self.auto_reconnect = False
        self._stop_event.set()
        if self.monitor_thread and self.monitor_thread.is_alive():
            wait = self._interval_seconds + 2.0
            self.monitor_thread.join(timeout=wait)
        self.monitor_thread = None
        if self.client is not None:
            try:
                self.client.user.logout()
            except Exception:
                logger.debug("Logout failed (ignored)", exc_info=True)
            self.client = None
        self.device_info = {}
        self.connect_button.config(text="🚀 Pieslēgties", state='normal')
        if was_connected:
            self.status_label.config(text="Atvienots", foreground='red')
            self.health_text_lbl.config(text="Pieslēdzieties rūterim",
                                        fg="gray")
            self.health_progress.config(value=0)
            self.dir_label.config(text="—", fg='gray')
            self.dir_text.config(text="Nav datu", fg='gray')
            for lbl in self.sim_labels.values():
                lbl.config(text="-")

    # =====================================================
    # MONITOR LOOP (fona pavediens)
    # =====================================================

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            client = self.client
            if client is None:
                break
            try:
                sig = client.device.signal()
                plmn = client.net.current_plmn()
                status = client.monitoring.status()
                traffic = client.monitoring.traffic_statistics()
                data = {**(sig or {}), **(plmn or {}),
                        **(status or {}), **(traffic or {})}
                data['plmn'] = (plmn or {}).get(
                    'Numeric', data.get('plmn', ''))

                enodeb, sector = parse_cell_id(data.get('cell_id'))
                if enodeb is not None:
                    data['enodeb'] = enodeb
                    data['sector'] = sector

                band_str = str(data.get('band', ''))
                data['aggregation'] = ("Aktīva"
                                       if ("+" in band_str
                                           or "CA" in band_str)
                                       else "Nav (Single)")

                with self._data_lock:
                    self.last_data = data
                self.root.after(0, self.refresh_ui)
                # Veiksmīgs tikšķis — atiestatām backoff
                self.reconnect_delay = RECONNECT_DELAY_INITIAL
            except Exception as e:
                logger.warning("Monitor tick failed: %s", e)
                self.root.after(0, lambda: self.status_label.config(
                    text="API taimauts...", foreground='orange'))
                if self.auto_reconnect and not self._stop_event.is_set():
                    self._try_reconnect()
                else:
                    break

            if self._stop_event.wait(self._interval_seconds):
                break

    def _try_reconnect(self) -> None:
        """Viens pārpieslēgšanās mēģinājums ar eksponenciālu backoff."""
        if self._stop_event.is_set():
            return
        delay = min(self.reconnect_delay, RECONNECT_DELAY_MAX)
        self.root.after(0, lambda d=delay: self.status_label.config(
            text=f"Pārpieslēdzas pēc {d:.0f}s...", foreground='orange'))
        if self._stop_event.wait(delay):
            return
        try:
            new_client = Client(Connection(
                f"http://{self._cached_ip}", username='admin',
                password=self._cached_pw, timeout=4))
            new_client.device.information()
            self.client = new_client
            self.reconnect_delay = RECONNECT_DELAY_INITIAL
            self.root.after(0, lambda: self.status_label.config(
                text="Pieslēgts", foreground='green'))
        except Exception as e:
            logger.warning("Reconnect failed: %s", e)
            self.reconnect_delay = min(self.reconnect_delay * 2,
                                       RECONNECT_DELAY_MAX)

    # =====================================================
    # UI REFRESH (galvenais pavediens, ar root.after)
    # =====================================================

    def refresh_ui(self) -> None:
        if not self.is_monitoring:
            return
        self.status_label.config(text="Pieslēgts", foreground='green')

        with self._data_lock:
            data = dict(self.last_data)

        current_vals: Dict[str, Optional[float]] = {
            p: extract_number(data.get(p)) for p in self.dynamic_params
        }

        for p in self.dynamic_params:
            val_num = current_vals[p]
            if val_num is None:
                continue
            status_text, color, _ = evaluate_signal(p, val_num)
            self.lbl_vars[p]['val'].config(
                text=f"{val_num:g} {self._unit(p)}", fg=color)
            self.lbl_vars[p]['status'].config(
                text=status_text.upper(), fg=color)
            if (self.peak_values[p] == '-' or val_num > self.peak_values[p]):
                self.peak_values[p] = val_num
            self.lbl_vars[p]['peak'].config(text=f"Maks.: {self.peak_values[p]}")
            self.values[p].append(val_num)
            if len(self.values[p]) > GRAPH_HISTORY:
                self.values[p].pop(0)

        # Virziena indikators (pēc RSRP)
        rsrp = current_vals.get('rsrp')
        if rsrp is not None:
            self.dir_history.append(rsrp)
            if len(self.dir_history) > DIRECTION_LOOKBACK * 2:
                self.dir_history.pop(0)
            self._update_direction()

        # Savienojuma kvalitāte — vienmēr tiek atjaunota
        score, summary, color = calculate_overall_health(
            rsrp, current_vals.get('sinr'))
        self.health_progress.config(value=score)
        self.health_text_lbl.config(text=summary, fg=color)

        # Džiteris — vienmēr tiek atjaunots
        if len(self.values['rsrp']) >= JITTER_WINDOW:
            recent = self.values['rsrp'][-JITTER_WINDOW:]
            jitter = max(recent) - min(recent)
            jcol = ('green' if jitter < 3
                    else 'orange' if jitter < 7 else 'red')
            self.jitter_label.config(
                text=f"Džiteris: {jitter:.1f} dB (signāla stabilitāte)",
                foreground=jcol)

        # Audio palīgs: frekvence atkarīga no tuvuma RSRP MAKSIMUMAM
        if HAS_WINSOUND and self.geiger_var.get() and rsrp is not None:
            best = self.peak_values['rsrp']
            if isinstance(best, (int, float)):
                # 0..30 dB zem maksimuma → 2500..300 Hz (tuvāk maksimumam — augstāks)
                delta = max(0.0, best - rsrp)
                freq = max(300, min(2500, int(2500 - delta * 70)))
                threading.Thread(target=winsound.Beep,
                                 args=(freq, 80), daemon=True).start()

        # Grafiks — pievienojam pēdējo vērtību vienmēr
        if self.start_time is not None:
            param = self.graph_param.get()
            val_now = current_vals.get(param)
            if val_now is not None:
                self.signal_graph.push(val_now)

        # Spogulis Jumta režīmā
        if self.roof_win is not None and self.roof_win.winfo_exists():
            r = rsrp
            s = current_vals.get('sinr')
            _, r_col, _ = evaluate_signal('rsrp', r)
            _, s_col, _ = evaluate_signal('sinr', s)
            self.r_lbl_rsrp.config(
                text=f"RSRP: {r if r is not None else '-'}", fg=r_col)
            self.r_lbl_sinr.config(
                text=f"SINR: {s if s is not None else '-'}", fg=s_col)
            arrow, color = self._direction_glyph()
            self.r_dir.config(text=arrow, fg=color)

        # Informācija par torni
        earfcn_raw = data.get('earfcn', data.get('Earfcn', '-'))
        for key, lbl in self.tower_labels.items():
            if key == 'plmn':
                val = str(data.get('plmn', '-'))
                if val != '-' and len(val) >= 5:
                    op = PLMN_MAP.get(val, 'Nezināms operators')
                    val = f"{val} ({op})"
            elif key == 'band':
                val = format_band_label(data.get('band'), earfcn_raw)
            elif key == 'earfcn':
                val = (str(earfcn_raw)
                       if earfcn_raw not in (None, '', '-') else '-')
            else:
                val = str(data.get(key, '-'))
            lbl.config(text=val)

        # Statistika
        self.stat_labels['dl_rate'].config(
            text=format_rate_mbps(data.get('CurrentDownloadRate', 0)))
        self.stat_labels['ul_rate'].config(
            text=format_rate_mbps(data.get('CurrentUploadRate', 0)))
        self.stat_labels['total_dl'].config(
            text=format_bytes_mb(data.get('TotalDownload', 0)))
        self.stat_labels['total_ul'].config(
            text=format_bytes_mb(data.get('TotalUpload', 0)))
        up_sec = data.get('CurrentConnectTime',
                          data.get('ConnectionTime', 0))
        try:
            up_sec_int = int(up_sec)
            uptime_str = (str(datetime.timedelta(seconds=up_sec_int))
                          if up_sec_int > 0 else "-")
        except (TypeError, ValueError):
            uptime_str = "-"
        self.stat_labels['uptime'].config(text=uptime_str)
        self.stat_labels['temp'].config(
            text=str(data.get('Temperature', 'N/D')))
        for p, lbl_key in (('rsrp', 'rsrp_min'), ('sinr', 'sinr_min')):
            vals = self.values[p]
            if vals:
                self.stat_labels[lbl_key].config(
                    text=f"{min(vals):g} / {max(vals):g} {self._unit(p)}")

        # Sesijas žurnāls (RAM, CSV eksportam)
        if len(self.session_log) < SESSION_LOG_MAX:
            self.session_log.append({
                'ts': datetime.datetime.now().isoformat(timespec='seconds'),
                **{p: current_vals.get(p) for p in self.dynamic_params},
                'plmn': data.get('plmn', ''),
                'enodeb': data.get('enodeb', ''),
                'sector': data.get('sector', ''),
                'band': data.get('band', ''),
                'pci': data.get('pci', ''),
            })

    def _update_direction(self) -> None:
        arrow, color = self._direction_glyph()
        text = {
            "↑": "Signāls uzlabojas — turpiniet tajā virzienā",
            "↓": "Signāls pasliktinās — pagrieziet pretējā virzienā",
            "→": "Signāls stabils — fiksējiet antenu",
            "—": "Tiek vākti dati...",
        }.get(arrow, "")
        self.dir_label.config(text=arrow, fg=color)
        self.dir_text.config(text=text, fg=color)

    def _direction_glyph(self) -> Tuple[str, str]:
        if len(self.dir_history) < DIRECTION_LOOKBACK * 2:
            return "—", "gray"
        recent = self.dir_history[-DIRECTION_LOOKBACK:]
        older = self.dir_history[-DIRECTION_LOOKBACK * 2:-DIRECTION_LOOKBACK]
        delta = (sum(recent) / len(recent)) - (sum(older) / len(older))
        if delta >= 1.0:
            return "↑", "#00b894"
        if delta <= -1.0:
            return "↓", "#d63031"
        return "→", "#fdcb6e"

    # =====================================================
    # NETWORK / ANTENNA
    # =====================================================

    def apply_bands(self) -> None:
        if self.client is None:
            messagebox.showwarning("Kļūda",
                                   "Vispirms pieslēdzieties rūterim.")
            return
        mask = sum(BANDS[n] for n, v in self.band_checkboxes.items()
                   if v.get())
        if mask == 0:
            messagebox.showwarning("Uzmanību",
                                   "Izvēlieties vismaz vienu diapazonu!")
            return
        hex_mask = format(mask, 'X')
        client = self.client

        def task():
            try:
                client.net.set_net_mode(hex_mask, NETBAND_AUTO_MASK,
                                        NETMODE_LTE_ONLY)
                self.root.after(0, lambda: messagebox.showinfo(
                    "Veiksmīgi", f"Band Lock pielietots (maska: {hex_mask})."))
            except Exception as e:
                logger.exception("Band lock failed")
                self.root.after(0, lambda err=str(e): messagebox.showerror(
                    "Kļūda", f"Rūteris atteicās izpildīt komandu:\n{err}"))
        threading.Thread(target=task, daemon=True).start()

    def reset_bands(self) -> None:
        if self.client is None:
            return
        client = self.client

        def task():
            try:
                client.net.set_net_mode(LTEBAND_AUTO_ALL,
                                        NETBAND_AUTO_MASK, NETMODE_AUTO)
                self.root.after(0, lambda: messagebox.showinfo(
                    "Veiksmīgi", "Tīkls atiestatīts uz AUTO."))
            except Exception as e:
                logger.exception("Reset bands failed")
                self.root.after(0, lambda err=str(e): messagebox.showerror(
                    "Kļūda", err))
        threading.Thread(target=task, daemon=True).start()

    def apply_antenna(self) -> None:
        if self.client is None:
            messagebox.showwarning("Kļūda",
                                   "Vispirms pieslēdzieties rūterim.")
            return
        ant_val = parse_antenna_value(self.antenna_var.get())
        if ant_val is None:
            messagebox.showerror("Kļūda", "Nezināms antenas režīms.")
            return
        client = self.client

        def task():
            try:
                # Vispirms mēģinam ar enum (jaunāks API)
                try:
                    from huawei_lte_api.enums.device import AntennaTypeEnum
                    client.device.set_antenna_settings(
                        AntennaTypeEnum(ant_val))
                except ImportError:
                    if hasattr(client.device, 'set_antenna_settings'):
                        client.device.set_antenna_settings(ant_val)
                    elif hasattr(client.device, 'set_antenna_type'):
                        client.device.set_antenna_type(ant_val)
                    else:
                        raise RuntimeError(
                            "Antenu vadības API nav atrasts "
                            "(rūtera modelis to varbūt neatbalsta)."
                        ) from None
                self.root.after(0, lambda: messagebox.showinfo(
                    "Veiksmīgi",
                    f"Antenas tips nomainīts: {self.antenna_var.get()}"))
            except Exception as e:
                logger.exception("Set antenna failed")
                self.root.after(0, lambda err=str(e): messagebox.showerror(
                    "Kļūda", err))
        threading.Thread(target=task, daemon=True).start()

    def reboot_router(self) -> None:
        if self.client is None:
            messagebox.showwarning("Kļūda",
                                   "Vispirms pieslēdzieties rūterim.")
            return
        if not messagebox.askyesno(
                "Apstiprinājums",
                "Pārstartēt rūteri?\n\n"
                "Interneta savienojums tiks pārtraukts uz 1–2 minūtēm. "
                "Pēc ielādes pieslēdzieties manuāli no jauna."):
            return
        client = self.client

        def task():
            try:
                client.device.reboot()
                # Rūteris tagad pazudīs — pārtraucam savienojumu UI pusē
                self.root.after(0, self.disconnect)
                self.root.after(100, lambda: messagebox.showinfo(
                    "Pārstartēšana",
                    "Komanda nosūtīta. Rūteris atgriezīsies pēc 1–2 minūtēm."))
            except Exception as e:
                logger.exception("Reboot failed")
                self.root.after(0, lambda err=str(e): messagebox.showerror(
                    "Kļūda", f"Nav iespējams pārstartēt:\n{err}"))
        threading.Thread(target=task, daemon=True).start()

    # =====================================================
    # EXTERNAL LOOKUPS
    # =====================================================

    def open_cellmapper(self) -> None:
        with self._data_lock:
            plmn = str(self.last_data.get('plmn', ''))
            enodeb = self.last_data.get('enodeb')
        if len(plmn) < 5 or enodeb is None:
            messagebox.showwarning(
                "Uzmanību",
                "Nepietiek datu par torni (nepieciešams PLMN un eNodeB).")
            return
        mcc, mnc = plmn[:3], plmn[3:]
        url = (f"https://www.cellmapper.net/map?MCC={mcc}&MNC={mnc}"
               f"&type=LTE&siteid={enodeb}")
        try:
            webbrowser.open(url)
        except Exception as e:
            messagebox.showerror("Kļūda", f"Nevar atvērt pārlūku: {e}")

    # =====================================================
    # ROOF MODE (pilnekrāna)
    # =====================================================

    def toggle_roof_mode(self) -> None:
        if self.roof_win is not None and self.roof_win.winfo_exists():
            self._close_roof()
            return
        self.roof_win = tk.Toplevel(self.root)
        self.roof_win.attributes('-fullscreen', True)
        self.roof_win.configure(bg='black')
        self.roof_win.bind("<Escape>", lambda e: self._close_roof())
        self.roof_win.protocol("WM_DELETE_WINDOW", self._close_roof)
        tk.Label(self.roof_win, text="[ESC] iziet",
                 font=("Arial", 14), fg='gray',
                 bg='black').pack(pady=12)
        self.r_lbl_rsrp = tk.Label(
            self.roof_win, text="RSRP: -",
            font=("Consolas", 90, "bold"), bg='black', fg='white')
        self.r_lbl_rsrp.pack(expand=True)
        self.r_dir = tk.Label(
            self.roof_win, text="—",
            font=("Consolas", 140, "bold"), bg='black', fg='gray')
        self.r_dir.pack(expand=True)
        self.r_lbl_sinr = tk.Label(
            self.roof_win, text="SINR: -",
            font=("Consolas", 90, "bold"), bg='black', fg='white')
        self.r_lbl_sinr.pack(expand=True)

    def _close_roof(self) -> None:
        if self.roof_win is not None and self.roof_win.winfo_exists():
            self.roof_win.destroy()
        self.roof_win = None

    # =====================================================
    # CSV EXPORT
    # =====================================================

    def export_csv(self) -> None:
        if not self.session_log:
            messagebox.showinfo(
                "Eksports",
                "Sesijas žurnāls ir tukšs. Pieslēdzieties un uzgaidiet, "
                "kamēr tiek savākti dati.")
            return
        default = f"hua4gmon-{datetime.datetime.now():%Y%m%d-%H%M%S}.csv"
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Visi", "*.*")],
            initialfile=default)
        if not path:
            return
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                fields = list(self.session_log[0].keys())
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerows(self.session_log)
            messagebox.showinfo(
                "Eksports",
                f"Saglabāti {len(self.session_log)} ieraksti:\n{path}")
        except OSError as e:
            messagebox.showerror("Kļūda", f"Nav iespējams ierakstīt failu: {e}")

    # =====================================================
    # MISC HELPERS
    # =====================================================

    def setup_graph(self) -> None:
        param = self.graph_param.get()
        y_min, y_max = PARAM_RANGES.get(param, (-120, 0))
        self.signal_graph.configure_axes(
            y_min=y_min, y_max=y_max,
            unit=self._unit(param), title=param.upper())

    def reset_graph(self, _event=None) -> None:
        self.values = {p: [] for p in self.dynamic_params}
        self.setup_graph()

    def reset_peaks(self) -> None:
        self.peak_values = {p: '-' for p in self.dynamic_params}
        for p in self.dynamic_params:
            self.lbl_vars[p]['peak'].config(text="Maks.: -")

    @staticmethod
    def _unit(param: str) -> str:
        return "dBm" if param in ('rsrp', 'rssi') else "dB"

    # =====================================================
    # SHUTDOWN
    # =====================================================

    def on_closing(self) -> None:
        logger.info("Shutting down")
        self.disconnect()
        self._close_roof()
        try:
            self.root.quit()
        finally:
            try:
                self.root.destroy()
            except tk.TclError:
                pass


# =========================================================
# IEEJA
# =========================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=f"{APP_NAME} — portatīvs Huawei LTE monitors.")
    p.add_argument('--ip', default='192.168.8.1',
                   help='Rūtera IP (pēc noklusējuma 192.168.8.1)')
    p.add_argument('--password', default='',
                   help='Parole (ja norādīta — automātiska pieslēgšanās)')
    p.add_argument('--verbose', '-v', action='store_true',
                   help='Detalizēts žurnāls stderr')
    p.add_argument('--version', action='version',
                   version=f'{APP_NAME} {__version__}')
    return p.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        stream=sys.stderr)
    root = tk.Tk()
    app = Hua4GMon(root,
                   default_ip=args.ip,
                   default_password=args.password)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        app.on_closing()


if __name__ == "__main__":
    main()
