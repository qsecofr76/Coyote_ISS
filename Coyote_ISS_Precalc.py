import sys
import os
import json
import time
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
        else:
            self.selected_pass_idx = None
            self.btn_generate.configure(state=tk.DISABLED)

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

# --- ENTRY POINT ---
if __name__ == "__main__":
    root = tk.Tk()
    app = CoyoteISSPrecalcApp(root)
    root.mainloop()
