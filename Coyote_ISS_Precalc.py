import sys
import os
import json
import time
import math
import socket
import struct
import datetime
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# --- AUTO-INSTALL DEPENDENCIES ---
def install_dependencies():
    required = {"skyfield": "skyfield", "numpy": "numpy", "sgp4": "sgp4"}
    missing = []
    for pkg, name in required.items():
        try:
            __import__(pkg)
        except ImportError:
            missing.append(name)
    if missing:
        print("Installing missing dependencies:", missing)
        try:
            # Try installing silently
            subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
        except Exception as e:
            # If it fails, we will show a messagebox inside the GUI initialization
            pass

# Install dependencies before importing
install_dependencies()

try:
    from skyfield.api import load, wgs84, EarthSatellite
    import numpy as np
except ImportError:
    # We will handle the error in the GUI by notifying the user
    pass

# --- CONSTANTS & CONFIGURATION ---
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "latitude": 45.4642,    # Default Milano
    "longitude": 9.1900,
    "elevation": 120.0,
    "intercept_alt": 10.0
}

# --- HELPERS ---
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return DEFAULT_CONFIG
    return DEFAULT_CONFIG

def save_config(config):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print("Failed to save config:", e)

def angle_diff(target, current):
    diff = (target - current) % 360.0
    if diff > 180.0:
        diff -= 360.0
    return diff

# --- NTP SYNC CORE ---
def get_ntp_time(server="pool.ntp.org"):
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.settimeout(3.0)
    data = b'\x1b' + 47 * b'\0'
    try:
        client.sendto(data, (server, 123))
        data, _ = client.recvfrom(1024)
        if data:
            t = struct.unpack('!12I', data)[10]
            t -= 2208988800  # Convert to Unix epoch
            return t
    except Exception as e:
        print("NTP Error:", e)
    return None

def set_system_time(epoch_time):
    # Sets Windows system time
    import ctypes
    dt = datetime.datetime.fromtimestamp(epoch_time, tz=datetime.timezone.utc)
    
    class SYSTEMTIME(ctypes.Structure):
        _fields_ = [
            ("wYear", ctypes.c_ushort),
            ("wMonth", ctypes.c_ushort),
            ("wDayOfWeek", ctypes.c_ushort),
            ("wDay", ctypes.c_ushort),
            ("wHour", ctypes.c_ushort),
            ("wMinute", ctypes.c_ushort),
            ("wSecond", ctypes.c_ushort),
            ("wMilliseconds", ctypes.c_ushort)
        ]
        
    systime = SYSTEMTIME(
        dt.year, dt.month, dt.isoweekday() % 7, dt.day,
        dt.hour, dt.minute, dt.second, int(dt.microsecond / 1000)
    )
    ret = ctypes.windll.kernel32.SetSystemTime(ctypes.byref(systime))
    return ret != 0

def fetch_tle_from_celestrak():
    import requests
    url = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=tle"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        lines = [l.strip() for l in response.text.strip().split("\n") if l.strip()]
        if len(lines) >= 3:
            # Cache locally
            with open("iss_tle.txt", "w") as f:
                f.write("\n".join(lines[:3]))
            return lines[:3]
    except Exception as e:
        print("Failed to download TLE:", e)
    
    # Try reading from cache
    if os.path.exists("iss_tle.txt"):
        try:
            with open("iss_tle.txt", "r") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
                if len(lines) >= 3:
                    return lines[:3]
        except Exception:
            pass
    return None

# --- MAIN APP CLASS ---
class CoyoteISSPrecalcApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Coyote ISS - Offline Precalculator")
        self.root.geometry("820x640")
        self.root.configure(bg="#1c1c1e")
        
        # Check if libraries are loaded
        if 'skyfield' not in sys.modules or 'numpy' not in sys.modules:
            messagebox.showerror(
                "Errore Dipendenze", 
                "Le librerie richieste (skyfield, numpy, sgp4) non sono installate.\n"
                "Riapri il programma per tentare nuovamente l'installazione automatica."
            )
            self.root.destroy()
            return
            
        self.config = load_config()
        self.passes_data = []
        self.selected_pass_idx = None
        self.tle_lines = None
        
        # Load icon image if it exists in the same directory
        self.icon_image = None
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coyote_iss_icon.png")
        if os.path.exists(icon_path):
            try:
                # Subsample to make it half the size (32x32 if source is 512x512)
                self.icon_image = tk.PhotoImage(file=icon_path).subsample(16, 16)
            except Exception as e:
                print("Failed to load icon image:", e)
        
        self.setup_styles()
        self.create_widgets()
        self.load_inputs_from_config()
        
        self.log_message("Sistema pronto. Inserisci le coordinate e premi 'Aggiorna Passaggi'.")
        
    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use('default')
        
        # Dark Theme configurations
        self.style.configure('.', background='#1c1c1e', foreground='#ffffff')
        self.style.configure('TFrame', background='#1c1c1e')
        self.style.configure('TLabel', background='#1c1c1e', foreground='#ffffff', font=('Segoe UI', 10))
        self.style.configure('TEntry', fieldbackground='#2c2c2e', foreground='#ffffff', insertcolor='#ffffff', font=('Segoe UI', 10))
        
        # Treeview styling
        self.style.configure('Treeview', 
                             background='#2c2c2e', 
                             fieldbackground='#2c2c2e', 
                             foreground='#ffffff',
                             rowheight=26,
                             font=('Segoe UI', 9))
        self.style.configure('Treeview.Heading', 
                             background='#3a3a3c', 
                             foreground='#ffffff', 
                             font=('Segoe UI Semibold', 9),
                             relief='flat')
        self.style.map('Treeview.Heading', background=[('active', '#48484a')])
        self.style.map('Treeview', background=[('selected', '#0a84ff')], foreground=[('selected', '#ffffff')])
        
        # Custom button styles
        self.style.configure('Primary.TButton', 
                             background='#0a84ff', 
                             foreground='#ffffff', 
                             font=('Segoe UI Bold', 10),
                             borderwidth=0)
        self.style.map('Primary.TButton', background=[('active', '#0070e0')])
        
        self.style.configure('Secondary.TButton', 
                             background='#3a3a3c', 
                             foreground='#ffffff', 
                             font=('Segoe UI', 10),
                             borderwidth=0)
        self.style.map('Secondary.TButton', background=[('active', '#48484a')])

        self.style.configure('Green.TButton', 
                             background='#30d158', 
                             foreground='#ffffff', 
                             font=('Segoe UI Bold', 10),
                             borderwidth=0)
        self.style.map('Green.TButton', background=[('active', '#24b045')])

    def create_widgets(self):
        # Master Frame
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title Header Frame with Icon
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 15))
        
        if self.icon_image:
            lbl_icon = tk.Label(header_frame, image=self.icon_image, bg="#1c1c1e")
            lbl_icon.pack(side=tk.LEFT, padx=(0, 10))
            
        title_label = ttk.Label(header_frame, text="Coyote ISS - Offline Precalculation", font=('Segoe UI Semibold', 16, 'bold'), foreground='#0a84ff')
        title_label.pack(side=tk.LEFT, anchor=tk.CENTER)
        
        # Input & Control Row Frame
        control_frame = ttk.LabelFrame(main_frame, text=" Configurazione Località & Intercettazione ", padding="10")
        control_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Form grid
        # Col 0: Lat
        ttk.Label(control_frame, text="Latitudine (Deg):").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.entry_lat = ttk.Entry(control_frame, width=12)
        self.entry_lat.grid(row=0, column=1, padx=5, pady=5)
        
        # Col 2: Lon
        ttk.Label(control_frame, text="Longitudine (Deg):").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        self.entry_lon = ttk.Entry(control_frame, width=12)
        self.entry_lon.grid(row=0, column=3, padx=5, pady=5)
        
        # Col 4: Elev
        ttk.Label(control_frame, text="Elevazione (m):").grid(row=0, column=4, padx=5, pady=5, sticky=tk.W)
        self.entry_elev = ttk.Entry(control_frame, width=10)
        self.entry_elev.grid(row=0, column=5, padx=5, pady=5)
        
        # Col 6: Intercept Alt
        ttk.Label(control_frame, text="Alt. Intercettazione (°):").grid(row=0, column=6, padx=5, pady=5, sticky=tk.W)
        self.entry_intercept_alt = ttk.Entry(control_frame, width=8)
        self.entry_intercept_alt.grid(row=0, column=7, padx=5, pady=5)
        
        # Button container in the control frame
        btn_frame = ttk.Frame(control_frame)
        btn_frame.grid(row=1, column=0, columnspan=8, pady=(10, 0), sticky=tk.EW)
        
        self.btn_save_config = ttk.Button(btn_frame, text="Salva Config", style="Secondary.TButton", command=self.save_inputs)
        self.btn_save_config.pack(side=tk.LEFT, padx=5)
        
        self.btn_detect_gps = ttk.Button(btn_frame, text="Rileva Posizione da IP", style="Secondary.TButton", command=self.detect_gps)
        self.btn_detect_gps.pack(side=tk.LEFT, padx=5)
        
        self.btn_sync_clock = ttk.Button(btn_frame, text="Sincronizza Orologio PC", style="Secondary.TButton", command=self.sync_clock)
        self.btn_sync_clock.pack(side=tk.LEFT, padx=5)
        
        self.btn_update_passes = ttk.Button(btn_frame, text="Aggiorna Passaggi ISS", style="Primary.TButton", command=self.update_passes)
        self.btn_update_passes.pack(side=tk.RIGHT, padx=5)
        
        # Table of visible passes
        table_frame = ttk.LabelFrame(main_frame, text=" Passaggi ISS Selezionabili (Prossimi 3 Giorni) ", padding="10")
        table_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        columns = ("index", "date", "time", "duration", "max_alt", "direction")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        
        self.tree.heading("index", text="#")
        self.tree.heading("date", text="Data")
        self.tree.heading("time", text="Ora Inizio")
        self.tree.heading("duration", text="Durata")
        self.tree.heading("max_alt", text="Alt Max")
        self.tree.heading("direction", text="Traiettoria (Salita -> Culmine -> Discesa)")
        
        self.tree.column("index", width=30, anchor=tk.CENTER)
        self.tree.column("date", width=90, anchor=tk.CENTER)
        self.tree.column("time", width=80, anchor=tk.CENTER)
        self.tree.column("duration", width=70, anchor=tk.CENTER)
        self.tree.column("max_alt", width=70, anchor=tk.CENTER)
        self.tree.column("direction", width=350, anchor=tk.W)
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tree.bind("<<TreeviewSelect>>", self.on_pass_select)
        
        # Generate Row
        generate_frame = ttk.Frame(main_frame)
        generate_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.btn_generate = ttk.Button(generate_frame, text="Genera Traiettoria e Salva con Nome (Save As)", style="Green.TButton", state=tk.DISABLED, command=self.generate_and_save)
        self.btn_generate.pack(side=tk.RIGHT, padx=5)
        
        self.btn_map = ttk.Button(generate_frame, text="Visualizza Mappa del Cielo", style="Primary.TButton", state=tk.DISABLED, command=self.show_sky_map)
        self.btn_map.pack(side=tk.RIGHT, padx=5)
        
        # Log Box
        log_frame = ttk.Frame(main_frame)
        log_frame.pack(fill=tk.X)
        self.lbl_status = ttk.Label(log_frame, text="Status: Inizializzazione...", anchor=tk.W, font=('Segoe UI Italic', 9), foreground='#a2a2a7')
        self.lbl_status.pack(fill=tk.X)

    def load_inputs_from_config(self):
        self.entry_lat.insert(0, str(self.config.get("latitude", DEFAULT_CONFIG["latitude"])))
        self.entry_lon.insert(0, str(self.config.get("longitude", DEFAULT_CONFIG["longitude"])))
        self.entry_elev.insert(0, str(self.config.get("elevation", DEFAULT_CONFIG["elevation"])))
        self.entry_intercept_alt.insert(0, str(self.config.get("intercept_alt", DEFAULT_CONFIG["intercept_alt"])))

    def get_inputs(self):
        try:
            lat = float(self.entry_lat.get())
            lon = float(self.entry_lon.get())
            elev = float(self.entry_elev.get())
            intercept_alt = float(self.entry_intercept_alt.get())
            
            if not (-90 <= lat <= 90):
                raise ValueError("La latitudine deve essere tra -90 e 90 gradi.")
            if not (-180 <= lon <= 180):
                raise ValueError("La longitudine deve essere tra -180 e 180 gradi.")
            if elev < -100 or elev > 9000:
                raise ValueError("Elevazione non realistica.")
            if not (0 < intercept_alt < 90):
                raise ValueError("L'altezza di intercettazione deve essere compresa tra 0 e 90 gradi.")
                
            return lat, lon, elev, intercept_alt
        except ValueError as e:
            messagebox.showerror("Errore Input", f"Controlla i dati inseriti:\n{e}")
            return None

    def save_inputs(self):
        inputs = self.get_inputs()
        if inputs:
            lat, lon, elev, intercept_alt = inputs
            self.config["latitude"] = lat
            self.config["longitude"] = lon
            self.config["elevation"] = elev
            self.config["intercept_alt"] = intercept_alt
            save_config(self.config)
            self.log_message("Configurazione salvata con successo.")
            messagebox.showinfo("Configurazione", "Configurazione salvata correttamente.")

    def detect_gps(self):
        self.btn_detect_gps.configure(state=tk.DISABLED)
        self.log_message("Rilevamento posizione tramite IP in corso...")
        
        def run_detection():
            import requests
            try:
                # 1. IP Geolocation
                geo_url = "http://ip-api.com/json/"
                response = requests.get(geo_url, timeout=5)
                response.raise_for_status()
                geo_data = response.json()
                
                if geo_data.get("status") == "success":
                    lat = geo_data.get("lat")
                    lon = geo_data.get("lon")
                    
                    # 2. Elevation Geolocation
                    elev = 100.0  # Fallback
                    try:
                        elev_url = "https://api.open-meteo.com/v1/elevation?latitude=%s&longitude=%s" % (lat, lon)
                        elev_response = requests.get(elev_url, timeout=5)
                        elev_response.raise_for_status()
                        elev_data = elev_response.json()
                        elevations = elev_data.get("elevation", [])
                        if elevations:
                            elev = float(elevations[0])
                    except Exception as e:
                        print("Failed to get elevation:", e)
                        
                    # Update GUI safely in main thread
                    def update_gui():
                        self.entry_lat.delete(0, tk.END)
                        self.entry_lat.insert(0, "%.6f" % lat)
                        self.entry_lon.delete(0, tk.END)
                        self.entry_lon.insert(0, "%.6f" % lon)
                        self.entry_elev.delete(0, tk.END)
                        self.entry_elev.insert(0, "%.1f" % elev)
                        
                        self.log_message("Posizione rilevata con successo da IP.")
                        messagebox.showinfo("Posizione Rilevata", 
                            "Posizione rilevata con successo!\n\n"
                            "Latitudine: %.6f°\n"
                            "Longitudine: %.6f°\n"
                            "Elevazione: %.1f m\n\n"
                            "Controlla i valori e premi 'Salva Config' per memorizzarli." % (lat, lon, elev)
                        )
                    
                    self.root.after(0, update_gui)
                else:
                    raise ValueError("Il servizio IP Geolocation ha ritornato errore.")
            except Exception as e:
                self.root.after(0, lambda: self.log_message("Errore durante il rilevamento: %s" % e))
                self.root.after(0, lambda: messagebox.showerror("Errore Rilevamento", 
                    "Impossibile rilevare la posizione automaticamente.\n"
                    "Verifica la connessione internet o inserisci i dati manualmente.\n\n"
                    "Dettaglio errore: %s" % e
                ))
            finally:
                self.root.after(0, lambda: self.btn_detect_gps.configure(state=tk.NORMAL))
                
        threading.Thread(target=run_detection, daemon=True).start()

    def log_message(self, msg):
        self.lbl_status.configure(text=f"Status: {msg}")
        self.root.update_idletasks()

    def sync_clock(self):
        self.btn_sync_clock.configure(state=tk.DISABLED)
        self.log_message("Sincronizzazione orologio in corso...")
        
        def run_sync():
            ntp_time = get_ntp_time()
            if ntp_time is None:
                self.root.after(0, lambda: self.log_message("Errore: Impossibile contattare il server NTP."))
                self.root.after(0, lambda: messagebox.showerror("Errore Sincronizzazione", "Impossibile ottenere l'ora dal server NTP pool.ntp.org. Controlla la connessione internet."))
                self.root.after(0, lambda: self.btn_sync_clock.configure(state=tk.NORMAL))
                return
            
            local_now = time.time()
            offset = ntp_time - local_now
            
            # Try to set clock
            success = False
            try:
                success = set_system_time(ntp_time)
            except Exception as e:
                print("Set System Time Exception:", e)
                
            if success:
                self.root.after(0, lambda: self.log_message(f"Orologio sincronizzato con successo. Offset: {offset:+.3f}s"))
                self.root.after(0, lambda: messagebox.showinfo("Orologio Sincronizzato", f"L'orologio di sistema è stato sincronizzato con successo.\nOffset corretto: {offset:+.3f} secondi."))
            else:
                self.root.after(0, lambda: self.log_message(f"Fallito (Offset rilevato: {offset:+.3f}s). Esegui come Amministratore!"))
                self.root.after(0, lambda: messagebox.showwarning("Permesso Negato", 
                    f"Rilevato offset di {offset:+.3f} secondi.\n\n"
                    "Impossibile impostare l'ora di sistema per mancanza di autorizzazioni.\n"
                    "Avvia questo programma come AMMINISTRATORE (tasto destro -> Esegui come Amministratore) "
                    "per sincronizzare l'orologio automaticamente, oppure installa un client NTP come Meinberg NTP."))
            
            self.root.after(0, lambda: self.btn_sync_clock.configure(state=tk.NORMAL))
            
        threading.Thread(target=run_sync, daemon=True).start()

    def update_passes(self):
        inputs = self.get_inputs()
        if not inputs:
            return
        
        lat, lon, elev, _ = inputs
        self.btn_update_passes.configure(state=tk.DISABLED)
        self.btn_generate.configure(state=tk.DISABLED)
        self.log_message("Scaricamento TLE e calcolo passaggi in corso...")
        
        def run_calc():
            tle = fetch_tle_from_celestrak()
            if not tle:
                self.root.after(0, lambda: messagebox.showerror("Errore TLE", "Impossibile scaricare o caricare i TLE per la ISS (NORAD 25544). Verificare la connessione internet."))
                self.root.after(0, lambda: self.btn_update_passes.configure(state=tk.NORMAL))
                self.root.after(0, lambda: self.log_message("Calcolo fallito per mancanza dati TLE."))
                return
            
            self.tle_lines = tle
            
            # Skyfield computations
            try:
                ts = load.timescale()
                iss = EarthSatellite(tle[1], tle[2], tle[0], ts)
                observer = wgs84.latlon(lat, lon, elev)
                
                t0 = ts.now()
                # 3 days search range
                t1 = ts.from_datetime(t0.utc_datetime() + datetime.timedelta(days=3))
                
                # We search events rising above 10 degrees
                t_events, events = iss.find_events(observer, t0, t1, altitude_degrees=10.0)
                
                # Group events into passes
                passes = []
                current_pass = {}
                for ti, event in zip(t_events, events):
                    if event == 0:  # Rise
                        current_pass = {'rise': ti}
                    elif event == 1:  # Culmination
                        if 'rise' in current_pass:
                            current_pass['culmination'] = ti
                    elif event == 2:  # Set
                        if 'rise' in current_pass:
                            current_pass['set'] = ti
                            
                            # Fetch properties
                            pos_culm = (iss - observer).at(current_pass['culmination'])
                            alt_culm, az_culm, _ = pos_culm.altaz()
                            current_pass['max_alt'] = alt_culm.degrees
                            current_pass['culmination_az'] = az_culm.degrees
                            
                            pos_rise = (iss - observer).at(current_pass['rise'])
                            _, az_rise, _ = pos_rise.altaz()
                            current_pass['rise_az'] = az_rise.degrees
                            
                            pos_set = (iss - observer).at(current_pass['set'])
                            _, az_set, _ = pos_set.altaz()
                            current_pass['set_az'] = az_set.degrees
                            
                            current_pass['duration'] = (current_pass['set'] - current_pass['rise']) * 86400.0
                            
                            passes.append(current_pass)
                            current_pass = {}
                
                # Sort passes by rise time
                passes.sort(key=lambda x: x['rise'].tt)
                self.passes_data = passes
                
                # Populate UI
                self.root.after(0, self.populate_tree)
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Errore Calcolo", f"Errore durante il calcolo dell'orbita:\n{e}"))
                self.root.after(0, lambda: self.btn_update_passes.configure(state=tk.NORMAL))
                
        threading.Thread(target=run_calc, daemon=True).start()

    def populate_tree(self):
        # Clear existing
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        local_tz = datetime.datetime.now().astimezone().tzinfo
        
        for idx, p in enumerate(self.passes_data):
            dt_rise = p['rise'].utc_datetime().replace(tzinfo=datetime.timezone.utc).astimezone(local_tz)
            date_str = dt_rise.strftime("%d/%m/%Y")
            time_str = dt_rise.strftime("%H:%M:%S")
            duration_str = f"{int(p['duration'])}s"
            max_alt_str = f"{p['max_alt']:.1f}°"
            
            # Format trajectory details
            dir_str = f"{p['rise_az']:.0f}° -> {p['culmination_az']:.0f}° -> {p['set_az']:.0f}°"
            
            self.tree.insert("", tk.END, values=(idx + 1, date_str, time_str, duration_str, max_alt_str, dir_str))
            
        self.btn_update_passes.configure(state=tk.NORMAL)
        self.log_message(f"Trovati {len(self.passes_data)} passaggi nei prossimi 3 giorni.")

    def on_pass_select(self, event):
        selected = self.tree.selection()
        if selected:
            item = self.tree.item(selected[0])
            idx = int(item['values'][0]) - 1
            self.selected_pass_idx = idx
            self.btn_generate.configure(state=tk.NORMAL)
            self.btn_map.configure(state=tk.NORMAL)
        else:
            self.selected_pass_idx = None
            self.btn_generate.configure(state=tk.DISABLED)
            self.btn_map.configure(state=tk.DISABLED)

    def generate_and_save(self):
        if self.selected_pass_idx is None or not self.passes_data or not self.tle_lines:
            return
            
        inputs = self.get_inputs()
        if not inputs:
            return
            
        lat, lon, elev, intercept_alt = inputs
        selected_pass = self.passes_data[self.selected_pass_idx]
        
        # Validation: check if max altitude of selected pass is higher than intercept altitude
        if selected_pass['max_alt'] < intercept_alt:
            messagebox.showerror(
                "Errore Calcolo", 
                f"Il passaggio selezionato ha un'altezza massima ({selected_pass['max_alt']:.1f}°) "
                f"inferiore all'altezza di intercettazione desiderata ({intercept_alt:.1f}°).\n"
                "Seleziona un passaggio più alto o diminuisci l'altezza di intercettazione."
            )
            return

        # Calculate t_intercept quickly on the main thread to generate the filename
        try:
            ts = load.timescale()
            iss = EarthSatellite(self.tle_lines[1], self.tle_lines[2], self.tle_lines[0], ts)
            observer = wgs84.latlon(lat, lon, elev)
            
            t_rise = selected_pass['rise']
            t_culm = selected_pass['culmination']
            
            low = t_rise.tt
            high = t_culm.tt
            for _ in range(24):
                mid = (low + high) / 2.0
                pos = (iss - observer).at(ts.tt_jd(mid))
                alt, _, _ = pos.altaz()
                if alt.degrees < intercept_alt:
                    low = mid
                else:
                    high = mid
            t_intercept = ts.tt_jd(low)
            
            # Format time for filename: yyyyMMdd_hhmmss
            local_tz = datetime.datetime.now().astimezone().tzinfo
            dt_int_local = t_intercept.utc_datetime().replace(tzinfo=datetime.timezone.utc).astimezone(local_tz)
            time_prefix = dt_int_local.strftime("%Y%m%d_%H%M%S")
            initial_file = "%s_Coyote_ISS.json" % time_prefix
        except Exception as e:
            initial_file = "Coyote_ISS.json"

        # Open File Dialog to Save As
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json")],
            initialfile=initial_file,
            title="Salva Dati Traiettoria ISS"
        )
        
        if not file_path:
            return # Cancelled by user
            
        self.btn_generate.configure(state=tk.DISABLED)
        self.log_message("Generazione traiettoria in corso...")
        
        def run_generation():
            try:
                ts = load.timescale()
                iss = EarthSatellite(self.tle_lines[1], self.tle_lines[2], self.tle_lines[0], ts)
                observer = wgs84.latlon(lat, lon, elev)
                
                # Binary search for interception time (rising phase)
                t_rise = selected_pass['rise']
                t_culm = selected_pass['culmination']
                t_set = selected_pass['set']
                
                # Find intercept time
                low = t_rise.tt
                high = t_culm.tt
                
                for _ in range(24):
                    mid = (low + high) / 2.0
                    pos = (iss - observer).at(ts.tt_jd(mid))
                    alt, _, _ = pos.altaz()
                    if alt.degrees < intercept_alt:
                        low = mid
                    else:
                        high = mid
                t_intercept_tt = low
                t_intercept = ts.tt_jd(t_intercept_tt)
                
                # Binary search for descent altitude crossing (when it goes below intercept_alt after culmination)
                low_desc = t_culm.tt
                high_desc = t_set.tt
                for _ in range(24):
                    mid = (low_desc + high_desc) / 2.0
                    pos = (iss - observer).at(ts.tt_jd(mid))
                    alt, _, _ = pos.altaz()
                    if alt.degrees >= intercept_alt:
                        low_desc = mid
                    else:
                        high_desc = mid
                t_descent_tt = low_desc
                t_descent = ts.tt_jd(t_descent_tt)
                
                # Trajectory range: start 10 seconds before intercept, end 5 seconds after descent crossing
                t_start_val = t_intercept.utc_datetime() - datetime.timedelta(seconds=10)
                t_end_val = t_descent.utc_datetime() + datetime.timedelta(seconds=5)
                
                t_start_epoch = t_start_val.replace(tzinfo=datetime.timezone.utc).timestamp()
                t_end_epoch = t_end_val.replace(tzinfo=datetime.timezone.utc).timestamp()
                
                dt = 0.1 # 10 Hz
                num_steps = int((t_end_epoch - t_start_epoch) / dt) + 1
                epochs = [t_start_epoch + i * dt for i in range(num_steps)]
                
                # Bulk calculate positions
                dts = [datetime.datetime.fromtimestamp(ep, tz=datetime.timezone.utc) for ep in epochs]
                times_sf = ts.from_datetimes(dts)
                
                positions = (iss - observer).at(times_sf)
                
                # Coordinates
                alts, azs, _ = positions.altaz(temperature_C=15.0, pressure_mbar=1013.25)
                alt_deg = alts.degrees
                az_deg = azs.degrees
                
                ras, decs, _ = positions.radec(epoch='date')
                ra_hours = ras.hours
                dec_deg = decs.degrees
                
                # Compute Interception coordinate values
                pos_int = (iss - observer).at(t_intercept)
                alt_int, az_int, _ = pos_int.altaz(temperature_C=15.0, pressure_mbar=1013.25)
                ra_int, dec_int, _ = pos_int.radec(epoch='date')
                
                local_tz = datetime.datetime.now().astimezone().tzinfo
                dt_int_local = t_intercept.utc_datetime().replace(tzinfo=datetime.timezone.utc).astimezone(local_tz)
                local_time_str = dt_int_local.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                
                # Rates calculations via finite differences
                trajectory_data = []
                for i in range(num_steps):
                    epoch = epochs[i]
                    ra = ra_hours[i]
                    dec = dec_deg[i]
                    alt = alt_deg[i]
                    az = az_deg[i]
                    
                    if i < num_steps - 1:
                        # Forward difference
                        diff_alt = alt_deg[i+1] - alt
                        diff_dec = dec_deg[i+1] - dec
                        diff_az = angle_diff(az_deg[i+1], az)
                        diff_ra = angle_diff(ra_hours[i+1] * 15.0, ra * 15.0)
                        
                        alt_rate = diff_alt / dt
                        dec_rate = diff_dec / dt
                        az_rate = diff_az / dt
                        ra_rate = diff_ra / dt # in degrees per second
                    else:
                        # Copy rates from previous step at the boundary
                        alt_rate = trajectory_data[-1][5]
                        dec_rate = trajectory_data[-1][6]
                        az_rate = trajectory_data[-1][7]
                        ra_rate = trajectory_data[-1][8]
                        
                    trajectory_data.append((
                        epoch, ra, dec, alt, az,
                        ra_rate, dec_rate, alt_rate, az_rate
                    ))
                
                # Write to JSON data file
                output_data = {
                    "OBSERVER_LAT": lat,
                    "OBSERVER_LON": lon,
                    "OBSERVER_HEIGHT": elev,
                    "INTERCEPT_ALT_TARGET": intercept_alt,
                    "INTERCEPT_TIME": t_intercept.utc_datetime().replace(tzinfo=datetime.timezone.utc).timestamp(),
                    "INTERCEPT_LOCAL_TIME": local_time_str,
                    "INTERCEPT_RA": ra_int.hours,
                    "INTERCEPT_DEC": dec_int.degrees,
                    "INTERCEPT_ALT": alt_int.degrees,
                    "INTERCEPT_AZ": az_int.degrees,
                    "TRAJECTORY": trajectory_data
                }
                
                with open(file_path, "w") as f:
                    json.dump(output_data, f, indent=4)
                
                self.root.after(0, lambda: self.log_message(f"File salvato con successo: {os.path.basename(file_path)}"))
                self.root.after(0, lambda: messagebox.showinfo("Generazione Completata", f"Traiettoria generata con successo ({num_steps} punti a 10 Hz).\nFile salvato in:\n{file_path}"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Errore Generazione", f"Errore durante la generazione della traiettoria:\n{e}"))
                self.root.after(0, lambda: self.log_message("Generazione fallita."))
                
            self.root.after(0, lambda: self.btn_generate.configure(state=tk.NORMAL))
            
        threading.Thread(target=run_generation, daemon=True).start()

    def show_sky_map(self):
        if self.selected_pass_idx is None or not self.passes_data or not self.tle_lines:
            return
            
        inputs = self.get_inputs()
        if not inputs:
            return
            
        lat, lon, elev, intercept_alt = inputs
        selected_pass = self.passes_data[self.selected_pass_idx]
        
        # Calculate t_intercept and trajectory on the fly
        try:
            ts = load.timescale()
            iss = EarthSatellite(self.tle_lines[1], self.tle_lines[2], self.tle_lines[0], ts)
            observer = wgs84.latlon(lat, lon, elev)
            
            t_rise = selected_pass['rise']
            t_culm = selected_pass['culmination']
            t_set = selected_pass['set']
            
            # Find intercept time
            low = t_rise.tt
            high = t_culm.tt
            for _ in range(24):
                mid = (low + high) / 2.0
                pos = (iss - observer).at(ts.tt_jd(mid))
                alt, _, _ = pos.altaz()
                if alt.degrees < intercept_alt:
                    low = mid
                else:
                    high = mid
            t_intercept = ts.tt_jd(low)
            
            # Find descent time
            low_desc = t_culm.tt
            high_desc = t_set.tt
            for _ in range(24):
                mid = (low_desc + high_desc) / 2.0
                pos = (iss - observer).at(ts.tt_jd(mid))
                alt, _, _ = pos.altaz()
                if alt.degrees >= intercept_alt:
                    low_desc = mid
                else:
                    high_desc = mid
            t_descent = ts.tt_jd(low_desc)
            
            # Trajectory range: 10 seconds before intercept, 5 seconds after descent crossing
            t_start_val = t_intercept.utc_datetime() - datetime.timedelta(seconds=10)
            t_end_val = t_descent.utc_datetime() + datetime.timedelta(seconds=5)
            
            t_start_epoch = t_start_val.replace(tzinfo=datetime.timezone.utc).timestamp()
            t_end_epoch = t_end_val.replace(tzinfo=datetime.timezone.utc).timestamp()
            
            dt = 0.5  # 2 Hz is enough for drawing
            num_steps = int((t_end_epoch - t_start_epoch) / dt) + 1
            epochs = [t_start_epoch + i * dt for i in range(num_steps)]
            
            dts = [datetime.datetime.fromtimestamp(ep, tz=datetime.timezone.utc) for ep in epochs]
            times_sf = ts.from_datetimes(dts)
            
            positions = (iss - observer).at(times_sf)
            
            # Trajectory coordinates in RA/Dec JNow
            ras_traj, decs_traj, _ = positions.radec(epoch='date')
            traj_points = list(zip(ras_traj.hours, decs_traj.degrees))
            
            # Center coordinates (intercept point)
            pos_int = (iss - observer).at(t_intercept)
            ra_int, dec_int, _ = pos_int.radec(epoch='date')
            ra_center_hours = ra_int.hours
            dec_center_deg = dec_int.degrees
            
        except Exception as e:
            messagebox.showerror("Errore Mappa", "Errore nel calcolo del passaggio per la mappa:\n" + str(e))
            return

        # Load stars of mag <= 4.5
        stars = []
        if os.path.exists("hip_main.dat"):
            try:
                with open("hip_main.dat", "r", errors="ignore") as f:
                    for line in f:
                        if line.startswith("H|"):
                            parts = line.split("|")
                            if len(parts) >= 10:
                                try:
                                    mag_str = parts[5].strip()
                                    if mag_str:
                                        mag = float(mag_str)
                                        if mag <= 4.5:
                                            hip_id = int(parts[1].strip())
                                            ra_deg = float(parts[8].strip())
                                            dec_deg = float(parts[9].strip())
                                            stars.append({
                                                "hip": hip_id,
                                                "mag": mag,
                                                "ra": ra_deg,
                                                "dec": dec_deg
                                            })
                                except ValueError:
                                    pass
            except Exception as e:
                print("Error loading stars catalog:", e)
        else:
            messagebox.showwarning("Catalogo Stelle Mancante", 
                "Il file 'hip_main.dat' non è presente nella cartella.\n"
                "La mappa mostrerà solo la traiettoria della ISS senza le stelle dello sfondo.\n"
                "Riavvia il precalcolatore per scaricare il catalogo.")

        # Display Toplevel Sky Map Window
        map_win = tk.Toplevel(self.root)
        map_win.title("Simulazione Passaggio & Stelle di Campo - Coyote ISS")
        map_win.geometry("900x650")
        map_win.configure(bg="#1c1c1e")
        
        # Left Panel (Canvas)
        canvas_frame = tk.Frame(map_win, bg="#1c1c1e")
        canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        canvas_size = 550
        canvas = tk.Canvas(canvas_frame, width=canvas_size, height=canvas_size, bg="#0b0b0d", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)
        
        # Right Panel (Settings & Stars List)
        right_frame = tk.Frame(map_win, bg="#2c2c2e", width=300)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=15, pady=15)
        right_frame.pack_propagate(False)
        
        lbl_right_title = tk.Label(right_frame, text="INFO INTERCETTAZIONE", font=('Segoe UI Semibold', 10, 'bold'), fg="#0a84ff", bg="#2c2c2e")
        lbl_right_title.pack(anchor=tk.W, padx=10, pady=(10, 5))
        
        # Print info
        local_tz = datetime.datetime.now().astimezone().tzinfo
        dt_int_local = t_intercept.utc_datetime().replace(tzinfo=datetime.timezone.utc).astimezone(local_tz)
        info_txt = (
            "Centro Mappa (Intercettazione):\n"
            "A.R.: %.4fh\n"
            "Dec: %.3f°\n"
            "Ora Intercettazione: %s\n"
            "Alt: %.1f° | Az: %.1f°\n"
        ) % (ra_center_hours, dec_center_deg, dt_int_local.strftime('%H:%M:%S'), selected_pass['max_alt'], selected_pass['culmination_az'])
        
        lbl_info = tk.Label(right_frame, text=info_txt, font=('Segoe UI', 9), fg="#ffffff", bg="#2c2c2e", justify=tk.LEFT, anchor=tk.W)
        lbl_info.pack(anchor=tk.W, fill=tk.X, padx=10, pady=(0, 10))
        
        # Zoom / FOV Slider
        lbl_zoom = tk.Label(right_frame, text="Campo Inquadrato (FOV):", font=('Segoe UI Semibold', 9, 'bold'), fg="#ffffff", bg="#2c2c2e")
        lbl_zoom.pack(anchor=tk.W, padx=10)
        
        fov_var = tk.DoubleVar()
        fov_var.set(20.0) # default 20 degrees
        
        def update_fov(val):
            redraw()
            
        slider_fov = tk.Scale(right_frame, from_=5.0, to_=40.0, resolution=1.0, orient=tk.HORIZONTAL, variable=fov_var, command=update_fov, bg="#2c2c2e", fg="#ffffff", highlightthickness=0)
        slider_fov.pack(fill=tk.X, padx=10, pady=(0, 15))
        
        # Nearby Stars List
        lbl_stars_list = tk.Label(right_frame, text="Stelle Vicine (Mag < 4.0):", font=('Segoe UI Semibold', 9, 'bold'), fg="#ffffff", bg="#2c2c2e")
        lbl_stars_list.pack(anchor=tk.W, padx=10, pady=(5, 5))
        
        list_box = tk.Listbox(right_frame, bg="#1c1c1e", fg="#ffffff", selectbackground="#0a84ff", font=('Segoe UI', 8), borderwidth=0, highlightthickness=0)
        list_box.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        # Common Stars Names mapping
        COMMON_STARS = {
            32349: "Sirio", 30438: "Canopo", 69673: "Arturo", 91262: "Vega",
            24608: "Capella", 24436: "Rigel", 37279: "Procione", 27989: "Betelgeuse",
            97649: "Altair", 21421: "Aldebaran", 65474: "Spica", 80763: "Antares",
            37826: "Polluce", 113368: "Fomalhaut", 102098: "Deneb", 49669: "Regolo",
            11767: "Stella Polare", 36850: "Castore", 71683: "Rigil Kent.",
            25428: "Bellatrix", 27366: "Elnath", 81065: "Shaula", 26311: "Alnilam",
            84012: "Kaus Austr.", 68702: "Hadar", 61084: "Mimosa", 60718: "Acrux",
            49583: "Alioth", 67301: "Mizar", 54061: "Merak", 53910: "Dubhe",
            58001: "Phecda", 62956: "Alkaid", 109268: "Alnair", 15863: "Mirfak",
            76267: "Ras Alhague", 9884: "Hamal", 86032: "Sabik", 34444: "Adhara",
            112440: "Markab", 113136: "Scheat", 113963: "Algenib", 5447: "Alpheratz",
            98298: "Peacock", 109074: "Altais", 14354: "Algol", 95853: "Tarazed"
        }
        
        def redraw():
            canvas.delete("all")
            list_box.delete(0, tk.END)
            
            fov = fov_var.get()
            center_x = canvas_size / 2.0
            center_y = canvas_size / 2.0
            scale = (canvas_size / 2.0) / (fov / 2.0)  # pixels per degree
            
            c_dec = math.radians(dec_center_deg)
            c_ra = math.radians(ra_center_hours * 15.0)
            
            # 1. Draw grid circles
            # Draw FOV boundary circle
            canvas.create_oval(10, 10, canvas_size - 10, canvas_size - 10, outline="#2c2c2e", width=1)
            # Center target crosshair
            canvas.create_oval(center_x - 12, center_y - 12, center_x + 12, center_y + 12, outline="#ff453a", width=1.5)
            canvas.create_line(center_x - 20, center_y, center_x + 20, center_y, fill="#ff453a", width=1.5)
            canvas.create_line(center_x, center_y - 20, center_x, center_y + 20, fill="#ff453a", width=1.5)
            
            # 2. Draw Cardinal Points
            canvas.create_text(center_x, 25, text="N", fill="#3a3a3c", font=('Segoe UI Bold', 12))
            canvas.create_text(center_x, canvas_size - 25, text="S", fill="#3a3a3c", font=('Segoe UI Bold', 12))
            canvas.create_text(25, center_y, text="E", fill="#3a3a3c", font=('Segoe UI Bold', 12))
            canvas.create_text(canvas_size - 25, center_y, text="W", fill="#3a3a3c", font=('Segoe UI Bold', 12))
            
            # 3. Project and draw stars
            nearby_stars = []
            for s in stars:
                s_ra = math.radians(s['ra'])
                s_dec = math.radians(s['dec'])
                
                # Orthographic projection
                ra_diff = s_ra - c_ra
                x = -math.sin(ra_diff) * math.cos(s_dec)
                y = math.sin(s_dec) * math.cos(c_dec) - math.cos(s_dec) * math.sin(c_dec) * math.cos(ra_diff)
                
                # Convert to degrees
                x_deg = math.degrees(x)
                y_deg = math.degrees(y)
                
                # Distance from center in degrees
                dist_deg = math.sqrt(x_deg**2 + y_deg**2)
                
                if dist_deg <= fov / 2.0:
                    cx = center_x + x_deg * scale
                    cy = center_y - y_deg * scale
                    
                    # Draw star circle
                    r = max(1, int(5.5 - s['mag']))
                    color = "#ffffff"
                    if s['mag'] < 1.5:
                        color = "#ffcc00"  # Bright yellow stars
                    
                    canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline=color)
                    
                    # Label stars of mag <= 3.0 or common name
                    name = COMMON_STARS.get(s['hip'], "")
                    if name or s['mag'] <= 3.0:
                        lbl_text = name if name else "HIP %d" % s['hip']
                        lbl_text += " (%.1f)" % s['mag']
                        canvas.create_text(cx + r + 4, cy - 4, text=lbl_text, fill="#a2a2a7", font=('Segoe UI', 7), anchor=tk.W)
                    
                    if s['mag'] <= 4.0:
                        nearby_stars.append({
                            "name": name if name else "HIP %d" % s['hip'],
                            "mag": s['mag'],
                            "dist": dist_deg
                        })
            
            # Sort nearby stars by distance from center
            nearby_stars.sort(key=lambda s: s['dist'])
            for s in nearby_stars:
                list_box.insert(tk.END, "%s | Mag: %.2f | Dist: %.2f°" % (s['name'], s['mag'], s['dist']))
                
            # 4. Project and draw ISS trajectory
            traj_pixels = []
            for ra_val, dec_val in traj_points:
                s_ra = math.radians(ra_val * 15.0)
                s_dec = math.radians(dec_val)
                
                ra_diff = s_ra - c_ra
                x = -math.sin(ra_diff) * math.cos(s_dec)
                y = math.sin(s_dec) * math.cos(c_dec) - math.cos(s_dec) * math.sin(c_dec) * math.cos(ra_diff)
                
                x_deg = math.degrees(x)
                y_deg = math.degrees(y)
                
                cx = center_x + x_deg * scale
                cy = center_y - y_deg * scale
                
                # Draw lines only within FOV boundary
                dist_deg = math.sqrt(x_deg**2 + y_deg**2)
                if dist_deg <= fov / 2.0:
                    traj_pixels.append((cx, cy))
            
            # Draw path line
            if len(traj_pixels) >= 2:
                for i in range(len(traj_pixels) - 1):
                    canvas.create_line(traj_pixels[i][0], traj_pixels[i][1], traj_pixels[i+1][0], traj_pixels[i+1][1], fill="#30d158", width=2)
                    
        # Initial draw
        redraw()

# --- ENTRY POINT ---
if __name__ == "__main__":
    root = tk.Tk()
    app = CoyoteISSPrecalcApp(root)
    root.mainloop()
