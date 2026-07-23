# -*- coding: utf-8 -*-
# SharpISS Follower - SharpCap IronPython Script
# Controls ASCOM Mount and Camera for active ISS tracking

import sys
import os
import time
import math
import traceback

# Import .NET namespaces
import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
from System.Windows.Forms import (
    Form, Label, TextBox, Button, CheckBox, OpenFileDialog,
    DialogResult, MessageBox, MessageBoxButtons, MessageBoxIcon, FormBorderStyle,
    ListBox, SelectionMode, PictureBox, MouseButtons, Panel, AnchorStyles, PictureBoxSizeMode,
    LinkLabel
)
from System.Drawing import Size, Point, Color, Font, FontStyle, Pen, SolidBrush, PointF, ContentAlignment
import System.Drawing.Drawing2D as Drawing2D
import System.Threading as Threading
from System import Action

# Try to detect if we are running inside SharpCap (global 'SharpCap' variable should exist)
try:
    # Verify if 'SharpCap' is defined globally.
    # In SharpCap's IronPython console, 'SharpCap' is a pre-defined global.
    # Outside SharpCap (like in standard Python), this will raise NameError.
    _ = SharpCap
except NameError:
    SharpCap = None

# Try to resolve ASCOM TelescopeAxes/TelescopeAxis enum type for CanMoveAxis/MoveAxis calls
telescope_axes_type = None

# 1. Try to load ASCOM assemblies
for ref in ["ASCOM.DeviceInterfaces", "ASCOM.DeviceInterface", "ASCOM.Common"]:
    try:
        clr.AddReference(ref)
    except Exception:
        pass

# 2. Try to import from various namespaces
for ns in ["ASCOM.DeviceInterface", "ASCOM.DeviceInterfaces", "ASCOM.Common", "ASCOM.Common.DeviceInterfaces"]:
    try:
        mod = __import__(ns, globals(), locals(), ["TelescopeAxes", "TelescopeAxis"])
        for name in ["TelescopeAxes", "TelescopeAxis"]:
            if hasattr(mod, name):
                telescope_axes_type = getattr(mod, name)
                break
        if telescope_axes_type is not None:
            break
    except Exception:
        pass

# 3. Fallback: Search all loaded assemblies in the AppDomain
if telescope_axes_type is None:
    try:
        import System
        for assembly in System.AppDomain.CurrentDomain.GetAssemblies():
            for fullname in ["ASCOM.DeviceInterface.TelescopeAxes", "ASCOM.Common.DeviceInterfaces.TelescopeAxis"]:
                t = assembly.GetType(fullname)
                if t is not None:
                    telescope_axes_type = t
                    break
            if telescope_axes_type is not None:
                break
    except Exception:
        pass

def to_axis(val):
    if telescope_axes_type is not None:
        import System
        return System.Enum.ToObject(telescope_axes_type, val)
    return val

# --- HELPER FUNCTIONS ---
def angle_diff(target, current):
    diff = (target - current) % 360.0
    if diff > 180.0:
        diff -= 360.0
    return diff

# --- MAIN FORM CLASS ---
class SharpISSFollowerForm(Form):
    def __init__(self):
        self.Text = "SharpISS Follower"
        
        # Load form icon from coyote_iss_icon.png if present
        self.icon_bitmap = None
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            script_dir = os.getcwd()
            
        icon_path = os.path.join(script_dir, "coyote_iss_icon.png")
        fallback_path = r"C:\ProgettiPy\Coyote_ISS\coyote_iss_icon.png"
        
        if not os.path.exists(icon_path) and os.path.exists(fallback_path):
            icon_path = fallback_path
            
        print("[DEBUG] Tentativo caricamento icona da: " + str(icon_path))
        if os.path.exists(icon_path):
            try:
                from System.Drawing import Bitmap, Icon
                self.icon_bitmap = Bitmap(icon_path)
                hicon = self.icon_bitmap.GetHicon()
                self.Icon = Icon.FromHandle(hicon)
                print("[DEBUG] Icona caricata con successo.")
            except Exception as e:
                print("[DEBUG] Errore caricamento icona: " + str(e))
        else:
            print("[DEBUG] File icona coyote_iss_icon.png non trovato in: " + str(icon_path))
                
        self.Size = Size(1432, 800)
        self.MinimumSize = Size(1432, 800)
        self.BackColor = Color.FromArgb(30, 30, 30)
        self.ForeColor = Color.White
        self.Font = Font("Segoe UI", 9)
        self.FormBorderStyle = FormBorderStyle.Sizable
        
        # Tracking variables
        self.trajectory_filepath = ""
        self.current_countdown_sec = 0.0
        self.trajectory_data = {}
        self.is_altaz = False
        self.abort_requested = False
        self.tracking_active = False
        self.last_traj_idx = 0
        self.block_ascom_until = 0.0
        
        # Manual trajectory offsets during tracking (degrees)
        self.manual_offset_axis0 = 0.0
        self.manual_offset_axis1 = 0.0
        
        # PI controller integral terms
        self.track_integral_0 = 0.0
        self.track_integral_1 = 0.0
        
        # Cached mount coordinates for visual bar and position checking
        self.cached_mount_ra = None
        self.cached_mount_dec = None
        self.cached_mount_alt = None
        self.cached_mount_az = None
        
        # Trajectory adjustment limits (indices in the loaded trajectory)
        self.track_start_idx = 0
        self.track_end_idx = 0
        self.default_start_idx = 0
        self.default_end_idx = 0
        self.culm_idx = 0
        self.flip_idx = None
        self.ha_1h_idx = None
        self.ha_2h_idx = None
        self.ha_minus1h_idx = None
        self.ha_minus2h_idx = None
        self.pic_sky_map = None
        self.active_thread = None
        
        # Pointing model / Calibration variables
        self.has_calib_start = False
        self.has_calib_inter = False
        self.has_calib_end = False
        self.calib_delta_ra_x = 0.0
        self.calib_delta_dec_x = 0.0
        self.calib_delta_az_x = 0.0
        self.calib_delta_alt_x = 0.0
        self.calib_delta_ra_y = 0.0
        self.calib_delta_dec_y = 0.0
        self.calib_delta_az_y = 0.0
        self.calib_delta_alt_y = 0.0
        self.calib_delta_ra_z = 0.0
        self.calib_delta_dec_z = 0.0
        self.calib_delta_az_z = 0.0
        self.calib_delta_alt_z = 0.0
        self.calib_active = False
        
        # Coordinates for manual GOTO & corrections
        self.coords_start = None
        self.coords_inter = None
        self.coords_end = None
        self.last_goto_point = None  # "start", "intermediate", "end", or None
        self.last_goto_coords = None # (ra, dec) or None
        self.check_pos_counter = 0
        
        # Real-time state monitored by background thread
        self.status_text = "Nessuna traiettoria caricata"
        self.countdown_text = "Tempo all'Intercettazione: --"
        self.rates_text = "Velocità Asse 0: 0.00°/s | Asse 1: 0.00°/s"
        self.error_text = "Errore di Puntamento: --"
        
        self.create_widgets()
        self.update_gui_labels()
        
        # Keyboard Shortcuts for Real-Time Exposure/Gain control
        self.KeyPreview = True
        self.KeyDown += self.on_key_down
        self.FormClosing += self.on_form_closing
        
        self.last_applied_exp = None
        self.last_applied_gain = None
        
        # Start GUI status updater timer
        self.timer = Threading.Timer(self.timer_tick, None, 100, 100)
        
        self.log("SharpISS Follower avviato.")
        if telescope_axes_type is not None:
            self.log("Risolto tipo enum ASCOM: %s" % str(telescope_axes_type))
        else:
            self.log("ATTENZIONE: Impossibile risolvere tipo enum ASCOM TelescopeAxes!")
            
        # Attempt to auto-connect to SharpCap mount
        self.auto_connect_mount()
        self.recalculate_default_step()
        self.FormClosing += self.on_form_closing

    def on_form_closing(self, sender, event):
        print("[DEBUG] Form in chiusura: arresto hardware e thread di tracciamento.")
        self.abort_requested = True
        try:
            self.stop_hardware()
        except Exception as e:
            print("[ERRORE] stop_hardware durante chiusura form: " + str(e))

    def recalculate_default_step(self):
        try:
            f_str = self.txt_focal.Text
            f = float(f_str) if f_str else 1000.0
            if f <= 0:
                f = 1000.0
        except Exception:
            f = 1000.0
            
        try:
            global SharpCap
            if SharpCap is not None and SharpCap.SelectedCamera is not None:
                cam = SharpCap.SelectedCamera
                # Get resolution
                img_size = cam.GetImageSize()
                h = float(img_size.Height)
                # Get pixel size in microns
                pix_h = float(cam.PixelSize.Height)
                # Formula: FOV_h = (h * pix_h / 1000) / f * (180 / pi)
                # Step (1/3 FOV) = FOV_h / 3
                step_default = (h * pix_h * 0.01909859) / f
                
                # Format to 4 decimal places
                self.txt_step_corr.Text = "%.4f" % step_default
                self.log("Ricalcolato step di correzione di default (1/3 FOV): %.4f°" % step_default)
        except Exception as e:
            pass
            
    def update_calib_status_label(self):
        try:
            def update():
                self.lbl_calib_status.Text = "Calibrazioni: Inizio: %s | Culmine: %s | Fine: %s" % (
                    "✔️" if self.has_calib_start else "❌",
                    "✔️" if self.has_calib_inter else "❌",
                    "✔️" if self.has_calib_end else "❌"
                )
                if self.has_calib_start and self.has_calib_inter and self.has_calib_end:
                    self.lbl_calib_status.ForeColor = Color.FromArgb(48, 209, 88)
                else:
                    self.lbl_calib_status.ForeColor = Color.LightGray
            if self.InvokeRequired:
                self.BeginInvoke(Action(update))
            else:
                update()
        except Exception:
            pass
            
    def log(self, text):
        timestamp = time.strftime("%H:%M:%S")
        lines = str(text).replace("\r\n", "\n").split("\n")
        print("[%s] %s" % (timestamp, text))
        try:
            formatted_lines = []
            for i, line in enumerate(lines):
                if i == 0:
                    formatted_lines.append("[%s] %s" % (timestamp, line))
                else:
                    formatted_lines.append("           %s" % line)
            
            if self.InvokeRequired:
                self.BeginInvoke(Action(lambda: self.add_log_lines(formatted_lines)))
            else:
                self.add_log_lines(formatted_lines)
        except Exception:
            pass

    def add_log_lines(self, lines):
        self.lst_log.BeginUpdate()
        for line in lines:
            self.lst_log.Items.Add(line)
        self.lst_log.EndUpdate()
        self.lst_log.TopIndex = self.lst_log.Items.Count - 1

    def on_log_key_down(self, sender, event):
        from System.Windows.Forms import Keys, Clipboard
        if event.Control and event.KeyCode == Keys.C:
            lines = []
            for item in self.lst_log.SelectedItems:
                lines.append(str(item))
            if lines:
                Clipboard.SetText("\r\n".join(lines))
                event.Handled = True
        elif event.Control and event.KeyCode == Keys.A:
            self.lst_log.BeginUpdate()
            for i in range(self.lst_log.Items.Count):
                self.lst_log.SetSelected(i, True)
            self.lst_log.EndUpdate()
            event.Handled = True
        
    def load_follower_config(self):
        import os
        import json
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "follower_config.json")
        default_config = {
            "lead_time": "2.0",
            "kp": "1.0",
            "star_exp": "3000.0",
            "star_gain": "350.0",
            "iss_exp": "1.5",
            "iss_gain": "250.0",
            "is_altaz": True,
            "inv_axis0": False,
            "inv_axis1": False,
            "focal_length": "1000.0",
            "step_corr": "0.05"
        }
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    loaded = json.load(f)
                    for k, v in loaded.items():
                        if k in default_config:
                            # Support converting types correctly
                            if isinstance(default_config[k], bool):
                                default_config[k] = bool(v)
                            else:
                                default_config[k] = str(v)
            except Exception as e:
                self.log("Errore caricamento configurazione follower: " + str(e))
        return default_config

    def save_follower_config(self):
        import os
        import json
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "follower_config.json")
        try:
            config = {
                "lead_time": self.txt_lead.Text,
                "kp": self.txt_kp.Text,
                "star_exp": self.txt_star_exp.Text,
                "star_gain": self.txt_star_gain.Text,
                "iss_exp": self.txt_iss_exp.Text,
                "iss_gain": self.txt_iss_gain.Text,
                "is_altaz": self.chk_altaz.Checked,
                "inv_axis0": self.chk_inv_axis0.Checked,
                "inv_axis1": self.chk_inv_axis1.Checked,
                "focal_length": self.txt_focal.Text,
                "step_corr": self.txt_step_corr.Text
            }
            with open(config_path, "w") as f:
                json.dump(config, f, indent=4)
            self.log("Configurazione follower salvata.")
        except Exception as e:
            self.log("Errore salvataggio configurazione follower: " + str(e))

    def on_form_closing(self, sender, event):
        self.save_follower_config()

    def create_widgets(self):
        # === COLONNA 1: SINISTRA (CONFIGURAZIONE & CONTROLLI) ===
        # Form Header & Mascot Logo (100x100px) & Credits Link
        if self.icon_bitmap is not None:
            try:
                self.logo_pb = PictureBox()
                self.logo_pb.Location = Point(10, 10)
                self.logo_pb.Size = Size(100, 100)
                self.logo_pb.Image = self.icon_bitmap
                self.logo_pb.SizeMode = PictureBoxSizeMode.Zoom
                self.Controls.Add(self.logo_pb)
            except Exception:
                pass
                
        lbl_credits_name = Label()
        lbl_credits_name.Text = "Roberto De Marchi"
        lbl_credits_name.Location = Point(120, 20)
        lbl_credits_name.Size = Size(270, 18)
        lbl_credits_name.Font = Font("Segoe UI", 9, FontStyle.Bold)
        lbl_credits_name.ForeColor = Color.LightGray
        self.Controls.Add(lbl_credits_name)
        
        lbl_app_name = Label()
        lbl_app_name.Text = "Coyote ISS Follower"
        lbl_app_name.Location = Point(120, 40)
        lbl_app_name.Size = Size(270, 18)
        lbl_app_name.Font = Font("Segoe UI", 9, FontStyle.Bold)
        lbl_app_name.ForeColor = Color.LightGray
        self.Controls.Add(lbl_app_name)
        
        lnk_credits_url = LinkLabel()
        lnk_credits_url.Text = "www.astrofilipontedipiave.it"
        lnk_credits_url.Location = Point(120, 60)
        lnk_credits_url.Size = Size(270, 18)
        lnk_credits_url.Font = Font("Segoe UI", 9)
        lnk_credits_url.LinkColor = Color.FromArgb(10, 132, 255)
        lnk_credits_url.ActiveLinkColor = Color.White
        lnk_credits_url.VisitedLinkColor = Color.FromArgb(10, 132, 255)
        
        def on_link_clicked(sender, event):
            try:
                import System.Diagnostics as Diagnostics
                Diagnostics.Process.Start("http://www.astrofilipontedipiave.it")
            except Exception:
                pass
        lnk_credits_url.LinkClicked += on_link_clicked
        self.Controls.Add(lnk_credits_url)
        
        # Configuration File & Connect Mount (shifted down by 105px from original, 50px from previous)
        lbl = Label()
        lbl.Text = "CARICAMENTO TRAIETTORIA"
        lbl.Location = Point(10, 125)
        lbl.Size = Size(380, 20)
        lbl.Font = Font("Segoe UI", 9, FontStyle.Bold)
        lbl.ForeColor = Color.FromArgb(10, 132, 255)
        self.Controls.Add(lbl)
        
        self.lbl_file = Label()
        self.lbl_file.Text = "File Traiettoria: Nessuno caricato"
        self.lbl_file.Location = Point(10, 150)
        self.lbl_file.Size = Size(280, 20)
        self.lbl_file.ForeColor = Color.LightGray
        self.Controls.Add(self.lbl_file)
        
        self.btn_load = Button()
        self.btn_load.Text = "Sfoglia..."
        self.btn_load.Location = Point(300, 146)
        self.btn_load.Size = Size(95, 24)
        self.btn_load.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_load.ForeColor = Color.White
        self.btn_load.FlatStyle = 0  # Flat
        self.btn_load.Click += self.on_load_trajectory
        self.Controls.Add(self.btn_load)
        
        self.lbl_mount = Label()
        self.lbl_mount.Text = "Montatura: Disconnessa"
        self.lbl_mount.Location = Point(10, 180)
        self.lbl_mount.Size = Size(448, 20)
        self.lbl_mount.ForeColor = Color.LightGray
        self.Controls.Add(self.lbl_mount)
        
        cfg = self.load_follower_config()
        
        self.chk_altaz = CheckBox()
        self.chk_altaz.Text = "Montatura Alt/Az (Auto-rilevata)"
        self.chk_altaz.Location = Point(10, 205)
        self.chk_altaz.Size = Size(300, 20)
        self.chk_altaz.ForeColor = Color.LightGray
        self.chk_altaz.Checked = cfg["is_altaz"]
        self.Controls.Add(self.chk_altaz)
        
        # Settings Panel (shifted down by 105px from original, 50px from previous)
        lbl_set = Label()
        lbl_set.Text = "IMPOSTAZIONI CAMERA & INSEGUIMENTO"
        lbl_set.Location = Point(10, 245)
        lbl_set.Size = Size(380, 20)
        lbl_set.Font = Font("Segoe UI", 9, FontStyle.Bold)
        lbl_set.ForeColor = Color.FromArgb(10, 132, 255)
        self.Controls.Add(lbl_set)
        
        # Col 1A
        lbl_se = Label()
        lbl_se.Text = "Esp. Stelle (ms):"
        lbl_se.Location = Point(10, 270)
        lbl_se.Size = Size(100, 20)
        self.Controls.Add(lbl_se)
        
        self.txt_star_exp = TextBox()
        self.txt_star_exp.Text = cfg["star_exp"]
        self.txt_star_exp.Location = Point(115, 267)
        self.txt_star_exp.Size = Size(65, 20)
        self.txt_star_exp.BackColor = Color.FromArgb(44, 44, 46)
        self.txt_star_exp.ForeColor = Color.White
        self.Controls.Add(self.txt_star_exp)
        
        lbl_ie = Label()
        lbl_ie.Text = "Esp. ISS (ms):"
        lbl_ie.Location = Point(10, 295)
        lbl_ie.Size = Size(100, 20)
        self.Controls.Add(lbl_ie)
        
        self.txt_iss_exp = TextBox()
        self.txt_iss_exp.Text = cfg["iss_exp"]
        self.txt_iss_exp.Location = Point(115, 292)
        self.txt_iss_exp.Size = Size(65, 20)
        self.txt_iss_exp.BackColor = Color.FromArgb(44, 44, 46)
        self.txt_iss_exp.ForeColor = Color.White
        self.Controls.Add(self.txt_iss_exp)
        
        lbl_k = Label()
        lbl_k.Text = "Aggress.\r\ncorrez.:"
        lbl_k.Location = Point(10, 320)
        lbl_k.Size = Size(100, 36)
        self.Controls.Add(lbl_k)
        
        self.txt_kp = TextBox()
        self.txt_kp.Text = cfg["kp"]
        self.txt_kp.Location = Point(115, 328)
        self.txt_kp.Size = Size(65, 20)
        self.txt_kp.BackColor = Color.FromArgb(44, 44, 46)
        self.txt_kp.ForeColor = Color.White
        self.Controls.Add(self.txt_kp)
        
        # Col 1B
        lbl_sg = Label()
        lbl_sg.Text = "Gain Stelle:"
        lbl_sg.Location = Point(210, 270)
        lbl_sg.Size = Size(100, 20)
        self.Controls.Add(lbl_sg)
        
        self.txt_star_gain = TextBox()
        self.txt_star_gain.Text = cfg["star_gain"]
        self.txt_star_gain.Location = Point(320, 267)
        self.txt_star_gain.Size = Size(65, 20)
        self.txt_star_gain.BackColor = Color.FromArgb(44, 44, 46)
        self.txt_star_gain.ForeColor = Color.White
        self.Controls.Add(self.txt_star_gain)
        
        lbl_ig = Label()
        lbl_ig.Text = "Gain ISS:"
        lbl_ig.Location = Point(210, 295)
        lbl_ig.Size = Size(100, 20)
        self.Controls.Add(lbl_ig)
        
        self.txt_iss_gain = TextBox()
        self.txt_iss_gain.Text = cfg["iss_gain"]
        self.txt_iss_gain.Location = Point(320, 292)
        self.txt_iss_gain.Size = Size(65, 20)
        self.txt_iss_gain.BackColor = Color.FromArgb(44, 44, 46)
        self.txt_iss_gain.ForeColor = Color.White
        self.Controls.Add(self.txt_iss_gain)
        
        lbl_lt = Label()
        lbl_lt.Text = "Tempo\r\nanticipo (s):"
        lbl_lt.Location = Point(210, 320)
        lbl_lt.Size = Size(100, 36)
        self.Controls.Add(lbl_lt)
        
        self.txt_lead = TextBox()
        self.txt_lead.Text = cfg["lead_time"]
        self.txt_lead.Location = Point(320, 328)
        self.txt_lead.Size = Size(65, 20)
        self.txt_lead.BackColor = Color.FromArgb(44, 44, 46)
        self.txt_lead.ForeColor = Color.White
        self.Controls.Add(self.txt_lead)
        # Row 4: Focal length
        lbl_foc = Label()
        lbl_foc.Text = "Focale (mm):"
        lbl_foc.Location = Point(10, 362)
        lbl_foc.Size = Size(100, 20)
        self.Controls.Add(lbl_foc)
        
        self.txt_focal = TextBox()
        self.txt_focal.Text = cfg.get("focal_length", "1000.0")
        self.txt_focal.Location = Point(115, 359)
        self.txt_focal.Size = Size(65, 20)
        self.txt_focal.BackColor = Color.FromArgb(44, 44, 46)
        self.txt_focal.ForeColor = Color.White
        self.txt_focal.TextChanged += lambda s, e: self.recalculate_default_step()
        self.Controls.Add(self.txt_focal)

        # Axis Inversion Options (Row 5 - shifted down from 362 to 398)
        self.chk_inv_axis0 = CheckBox()
        self.chk_inv_axis0.Text = "Inverti Asse 0 (Az/RA)"
        self.chk_inv_axis0.Location = Point(10, 398)
        self.chk_inv_axis0.Size = Size(230, 20)
        self.chk_inv_axis0.ForeColor = Color.LightGray
        self.chk_inv_axis0.Font = Font("Segoe UI", 9)
        self.chk_inv_axis0.Checked = cfg["inv_axis0"]
        self.Controls.Add(self.chk_inv_axis0)
        
        self.chk_inv_axis1 = CheckBox()
        self.chk_inv_axis1.Text = "Inverti Asse 1 (Alt/Dec)"
        self.chk_inv_axis1.Location = Point(250, 398)
        self.chk_inv_axis1.Size = Size(230, 20)
        self.chk_inv_axis1.ForeColor = Color.LightGray
        self.chk_inv_axis1.Font = Font("Segoe UI", 9)
        self.chk_inv_axis1.Checked = cfg["inv_axis1"]
        self.Controls.Add(self.chk_inv_axis1)
        
        # Slew & Calibrate (shifted down to accommodate new settings)
        lbl_slew = Label()
        lbl_slew.Text = "POSIZIONAMENTO & CALIBRAZIONE"
        lbl_slew.Location = Point(10, 425)
        lbl_slew.Size = Size(380, 20)
        lbl_slew.Font = Font("Segoe UI", 9, FontStyle.Bold)
        lbl_slew.ForeColor = Color.FromArgb(10, 132, 255)
        self.Controls.Add(lbl_slew)
        
        # Row 1: GOTO Buttons (shifted from 410 to 450)
        self.btn_goto_start = Button()
        self.btn_goto_start.Text = "GOTO Inizio"
        self.btn_goto_start.Location = Point(10, 450)
        self.btn_goto_start.Size = Size(124, 28)
        self.btn_goto_start.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_goto_start.ForeColor = Color.White
        self.btn_goto_start.FlatStyle = 0
        self.btn_goto_start.Click += lambda s, e: Threading.ThreadPool.QueueUserWorkItem(lambda state: self.run_manual_goto("start", self.coords_start))
        self.Controls.Add(self.btn_goto_start)
        
        self.btn_goto_inter = Button()
        self.btn_goto_inter.Text = "GOTO Culmine"
        self.btn_goto_inter.Location = Point(140, 450)
        self.btn_goto_inter.Size = Size(124, 28)
        self.btn_goto_inter.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_goto_inter.ForeColor = Color.White
        self.btn_goto_inter.FlatStyle = 0
        self.btn_goto_inter.Click += lambda s, e: Threading.ThreadPool.QueueUserWorkItem(lambda state: self.run_manual_goto("intermediate", self.coords_inter))
        self.Controls.Add(self.btn_goto_inter)
        
        self.btn_goto_end = Button()
        self.btn_goto_end.Text = "GOTO Fine"
        self.btn_goto_end.Location = Point(270, 450)
        self.btn_goto_end.Size = Size(124, 28)
        self.btn_goto_end.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_goto_end.ForeColor = Color.White
        self.btn_goto_end.FlatStyle = 0
        self.btn_goto_end.Click += lambda s, e: Threading.ThreadPool.QueueUserWorkItem(lambda state: self.run_manual_goto("end", self.coords_end))
        self.Controls.Add(self.btn_goto_end)
        
        # Row 2: Plate Solve & Sync Button and Test Directions Button (shifted from 445 to 485)
        self.btn_solve_sync = Button()
        self.btn_solve_sync.Text = "Plate Solve & Sync"
        self.btn_solve_sync.Location = Point(10, 485)
        self.btn_solve_sync.Size = Size(244, 28)
        self.btn_solve_sync.BackColor = Color.FromArgb(0, 122, 255)
        self.btn_solve_sync.ForeColor = Color.White
        self.btn_solve_sync.FlatStyle = 0
        self.btn_solve_sync.Click += lambda s, e: Threading.ThreadPool.QueueUserWorkItem(lambda state: self.run_manual_solve_sync())
        self.Controls.Add(self.btn_solve_sync)
        
        self.btn_test_dir = Button()
        self.btn_test_dir.Text = "Rileva Direzioni"
        self.btn_test_dir.Location = Point(260, 485)
        self.btn_test_dir.Size = Size(134, 28)
        self.btn_test_dir.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_test_dir.ForeColor = Color.White
        self.btn_test_dir.FlatStyle = 0
        self.btn_test_dir.Click += lambda s, e: Threading.ThreadPool.QueueUserWorkItem(lambda state: self.run_auto_direction_calibration())
        self.Controls.Add(self.btn_test_dir)
        
        # Row 3: Set Correction Buttons (shifted from 480 to 520)
        self.btn_set_start = Button()
        self.btn_set_start.Text = "Set Corr. Iniz."
        self.btn_set_start.Location = Point(10, 520)
        self.btn_set_start.Size = Size(124, 28)
        self.btn_set_start.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_set_start.ForeColor = Color.White
        self.btn_set_start.FlatStyle = 0
        self.btn_set_start.Click += lambda s, e: Threading.ThreadPool.QueueUserWorkItem(lambda state: self.run_set_correction("start"))
        self.Controls.Add(self.btn_set_start)
        
        self.btn_set_inter = Button()
        self.btn_set_inter.Text = "Set Corr. Culm."
        self.btn_set_inter.Location = Point(140, 520)
        self.btn_set_inter.Size = Size(124, 28)
        self.btn_set_inter.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_set_inter.ForeColor = Color.White
        self.btn_set_inter.FlatStyle = 0
        self.btn_set_inter.Click += lambda s, e: Threading.ThreadPool.QueueUserWorkItem(lambda state: self.run_set_correction("intermediate"))
        self.Controls.Add(self.btn_set_inter)
        
        self.btn_set_end = Button()
        self.btn_set_end.Text = "Set Corr. Fine"
        self.btn_set_end.Location = Point(270, 520)
        self.btn_set_end.Size = Size(124, 28)
        self.btn_set_end.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_set_end.ForeColor = Color.White
        self.btn_set_end.FlatStyle = 0
        self.btn_set_end.Click += lambda s, e: Threading.ThreadPool.QueueUserWorkItem(lambda state: self.run_set_correction("end"))
        self.Controls.Add(self.btn_set_end)
        
        # Control Buttons (shifted from 530 to 560)
        self.btn_arm = Button()
        self.btn_arm.Text = "ARMA"
        self.btn_arm.Location = Point(10, 560)
        self.btn_arm.Size = Size(150, 36)
        self.btn_arm.BackColor = Color.FromArgb(48, 209, 88)
        self.btn_arm.ForeColor = Color.White
        self.btn_arm.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.btn_arm.FlatStyle = 0
        def _on_arm_click(s, e):
            print("[DEBUG CLICK] ARMA premuto!")
            try:
                self.on_arm_intercept(s, e)
            except Exception as ex:
                print("[ERRORE] on_arm_intercept: " + str(ex))
        self.btn_arm.Click += _on_arm_click
        self.Controls.Add(self.btn_arm)
        
        self.btn_sim = Button()
        self.btn_sim.Text = "SIMULA"
        self.btn_sim.Location = Point(170, 560)
        self.btn_sim.Size = Size(150, 36)
        self.btn_sim.BackColor = Color.FromArgb(10, 132, 255)
        self.btn_sim.ForeColor = Color.White
        self.btn_sim.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.btn_sim.FlatStyle = 0
        def _on_sim_click(s, e):
            print("[DEBUG CLICK] SIMULA premuto!")
            try:
                self.on_run_simulation(s, e)
            except Exception as ex:
                print("[ERRORE] on_run_simulation: " + str(ex))
        self.btn_sim.Click += _on_sim_click
        self.Controls.Add(self.btn_sim)
        
        self.btn_abort = Button()
        self.btn_abort.Text = "ABORT"
        self.btn_abort.Location = Point(330, 560)
        self.btn_abort.Size = Size(150, 36)
        self.btn_abort.BackColor = Color.FromArgb(255, 69, 58)
        self.btn_abort.ForeColor = Color.White
        self.btn_abort.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.btn_abort.FlatStyle = 0
        def _on_abort_click(s, e):
            print("[DEBUG CLICK] ABORT premuto!")
            try:
                self.on_abort(s, e)
            except Exception as ex:
                print("[ERRORE] on_abort: " + str(ex))
        self.btn_abort.Click += _on_abort_click
        self.Controls.Add(self.btn_abort)

        # Calibration Status Label (shows which of the 3 points have valid plate solved corrections)
        self.lbl_calib_status = Label()
        self.lbl_calib_status.Text = "Calibrazioni: Inizio: ❌ | Culmine: ❌ | Fine: ❌"
        self.lbl_calib_status.Location = Point(10, 605)
        self.lbl_calib_status.Size = Size(380, 20)
        self.lbl_calib_status.Font = Font("Segoe UI", 9, FontStyle.Regular)
        self.lbl_calib_status.ForeColor = Color.LightGray
        self.Controls.Add(self.lbl_calib_status)

        # Manual Offset D-pad (Row under Arm/Sim/Abort, shifted down to y=635 with 3x3 layout)
        # Row 1, Col 1: Step Correction Speed input
        lbl_sc = Label()
        lbl_sc.Text = "Step (°):"
        lbl_sc.Location = Point(55, 638)
        lbl_sc.Size = Size(55, 20)
        lbl_sc.ForeColor = Color.LightGray
        self.Controls.Add(lbl_sc)
        
        self.txt_step_corr = TextBox()
        self.txt_step_corr.Text = cfg.get("step_corr", "0.05")
        self.txt_step_corr.Location = Point(112, 635)
        self.txt_step_corr.Size = Size(55, 20)
        self.txt_step_corr.BackColor = Color.FromArgb(44, 44, 46)
        self.txt_step_corr.ForeColor = Color.White
        self.Controls.Add(self.txt_step_corr)

        # Row 1, Col 2: Up (▲ Alt/Dec +)
        self.btn_off_ax1_pls = Button()
        self.btn_off_ax1_pls.Text = "▲ Alt/Dec +"
        self.btn_off_ax1_pls.Location = Point(185, 635)
        self.btn_off_ax1_pls.Size = Size(112, 36)
        self.btn_off_ax1_pls.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_off_ax1_pls.ForeColor = Color.White
        self.btn_off_ax1_pls.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.btn_off_ax1_pls.FlatStyle = 0
        def _offset_axis1_plus(s, e):
            try:
                val = float(self.txt_step_corr.Text)
                self.manual_offset_axis1 += val
                self.track_integral_0 = 0.0
                self.track_integral_1 = 0.0
                self.log("Offset manual: Asse 1 (Alt/Dec) = %.4f°" % self.manual_offset_axis1)
            except Exception:
                pass
        self.btn_off_ax1_pls.Click += _offset_axis1_plus
        self.Controls.Add(self.btn_off_ax1_pls)

        # Row 2, Col 1: Left (◀ Az/RA -)
        self.btn_off_ax0_min = Button()
        self.btn_off_ax0_min.Text = "◀ Az/RA -"
        self.btn_off_ax0_min.Location = Point(55, 675)
        self.btn_off_ax0_min.Size = Size(112, 36)
        self.btn_off_ax0_min.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_off_ax0_min.ForeColor = Color.White
        self.btn_off_ax0_min.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.btn_off_ax0_min.FlatStyle = 0
        def _offset_axis0_minus(s, e):
            try:
                val = float(self.txt_step_corr.Text)
                self.manual_offset_axis0 -= val
                self.track_integral_0 = 0.0
                self.track_integral_1 = 0.0
                self.log("Offset manual: Asse 0 (Az/RA) = %.4f°" % self.manual_offset_axis0)
            except Exception:
                pass
        self.btn_off_ax0_min.Click += _offset_axis0_minus
        self.Controls.Add(self.btn_off_ax0_min)

        # Row 2, Col 3: Right (▶ Az/RA +)
        self.btn_off_ax0_pls = Button()
        self.btn_off_ax0_pls.Text = "▶ Az/RA +"
        self.btn_off_ax0_pls.Location = Point(315, 675)
        self.btn_off_ax0_pls.Size = Size(112, 36)
        self.btn_off_ax0_pls.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_off_ax0_pls.ForeColor = Color.White
        self.btn_off_ax0_pls.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.btn_off_ax0_pls.FlatStyle = 0
        def _offset_axis0_plus(s, e):
            try:
                val = float(self.txt_step_corr.Text)
                self.manual_offset_axis0 += val
                self.track_integral_0 = 0.0
                self.track_integral_1 = 0.0
                self.log("Offset manual: Asse 0 (Az/RA) = %.4f°" % self.manual_offset_axis0)
            except Exception:
                pass
        self.btn_off_ax0_pls.Click += _offset_axis0_plus
        self.Controls.Add(self.btn_off_ax0_pls)

        # Row 3, Col 2: Down (▼ Alt/Dec -)
        self.btn_off_ax1_min = Button()
        self.btn_off_ax1_min.Text = "▼ Alt/Dec -"
        self.btn_off_ax1_min.Location = Point(185, 715)
        self.btn_off_ax1_min.Size = Size(112, 36)
        self.btn_off_ax1_min.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_off_ax1_min.ForeColor = Color.White
        self.btn_off_ax1_min.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.btn_off_ax1_min.FlatStyle = 0
        def _offset_axis1_minus(s, e):
            try:
                val = float(self.txt_step_corr.Text)
                self.manual_offset_axis1 -= val
                self.track_integral_0 = 0.0
                self.track_integral_1 = 0.0
                self.log("Offset manual: Asse 1 (Alt/Dec) = %.4f°" % self.manual_offset_axis1)
            except Exception:
                pass
        self.btn_off_ax1_min.Click += _offset_axis1_minus
        self.Controls.Add(self.btn_off_ax1_min)
        
        # Row 1, Col 3: Swap/Invert Axis 1 (Alt/Dec) direction
        self.btn_swap_axis1 = Button()
        self.btn_swap_axis1.Text = "🔄 Inv Y"
        self.btn_swap_axis1.Location = Point(315, 635)
        self.btn_swap_axis1.Size = Size(112, 36)
        self.btn_swap_axis1.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_swap_axis1.ForeColor = Color.White
        self.btn_swap_axis1.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.btn_swap_axis1.FlatStyle = 0
        def _toggle_inv_axis1(s, e):
            self.chk_inv_axis1.Checked = not self.chk_inv_axis1.Checked
            self.log("Direzione Asse 1 (Alt/Dec) invertita: %s" % ("SI" if self.chk_inv_axis1.Checked else "NO"))
        self.btn_swap_axis1.Click += _toggle_inv_axis1
        self.Controls.Add(self.btn_swap_axis1)

        # Row 3, Col 3: Swap/Invert Axis 0 (Az/RA) direction
        self.btn_swap_axis0 = Button()
        self.btn_swap_axis0.Text = "🔄 Inv X"
        self.btn_swap_axis0.Location = Point(315, 715)
        self.btn_swap_axis0.Size = Size(112, 36)
        self.btn_swap_axis0.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_swap_axis0.ForeColor = Color.White
        self.btn_swap_axis0.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.btn_swap_axis0.FlatStyle = 0
        def _toggle_inv_axis0(s, e):
            self.chk_inv_axis0.Checked = not self.chk_inv_axis0.Checked
            self.log("Direzione Asse 0 (Az/RA) invertita: %s" % ("SI" if self.chk_inv_axis0.Checked else "NO"))
        self.btn_swap_axis0.Click += _toggle_inv_axis0
        self.Controls.Add(self.btn_swap_axis0)
        
        # === COLONNA 2: DESTRA (STATO, TELEMETRIA & LOG) ===
        # Target Info Panel (resized widths to 590 to fit the sky map on the right without overlapping)
        self.lbl_info_title = Label()
        self.lbl_info_title.Text = "DETTAGLI PASSAGGIO ISS CARICATO"
        self.lbl_info_title.Location = Point(510, 15)
        self.lbl_info_title.Size = Size(590, 20)
        self.lbl_info_title.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.lbl_info_title.ForeColor = Color.FromArgb(10, 132, 255)
        self.Controls.Add(self.lbl_info_title)
        
        self.lbl_info_time = Label()
        self.lbl_info_time.Text = "Orario Intercettazione: --"
        self.lbl_info_time.Location = Point(510, 40)
        self.lbl_info_time.Size = Size(590, 20)
        self.lbl_info_time.ForeColor = Color.LightGray
        self.Controls.Add(self.lbl_info_time)
        
        self.lbl_info_coords = Label()
        self.lbl_info_coords.Text = "Coordinate RA/Dec: --"
        self.lbl_info_coords.Location = Point(510, 60)
        self.lbl_info_coords.Size = Size(590, 20)
        self.lbl_info_coords.ForeColor = Color.LightGray
        self.Controls.Add(self.lbl_info_coords)
        
        self.lbl_info_maxalt = Label()
        self.lbl_info_maxalt.Text = "Altezza Massima Passaggio: --"
        self.lbl_info_maxalt.Location = Point(510, 80)
        self.lbl_info_maxalt.Size = Size(590, 20)
        self.lbl_info_maxalt.ForeColor = Color.LightGray
        self.Controls.Add(self.lbl_info_maxalt)
        
        self.lbl_info_start_altaz = Label()
        self.lbl_info_start_altaz.Text = "Coordinate Start Alt/Az: --"
        self.lbl_info_start_altaz.Location = Point(510, 100)
        self.lbl_info_start_altaz.Size = Size(590, 20)
        self.lbl_info_start_altaz.ForeColor = Color.LightGray
        self.Controls.Add(self.lbl_info_start_altaz)
        
        # Polar coordinate sky map PictureBox (placed next to details, to the left of the Ripristina button)
        self.pic_sky_map = PictureBox()
        self.pic_sky_map.Location = Point(1110, 5)
        self.pic_sky_map.Size = Size(140, 140)
        self.pic_sky_map.BackColor = Color.FromArgb(44, 44, 46)
        self.pic_sky_map.Paint += self.on_sky_map_paint
        self.pic_sky_map.Anchor = AnchorStyles.Top | AnchorStyles.Right
        self.Controls.Add(self.pic_sky_map)
        
        # Trajectory adjustment Panel
        lbl_adjust = Label()
        lbl_adjust.Text = "REGOLAZIONE FINESTRA D'INSEGUIMENTO"
        lbl_adjust.Location = Point(510, 130)
        lbl_adjust.Size = Size(380, 20)
        lbl_adjust.Font = Font("Segoe UI", 9, FontStyle.Bold)
        lbl_adjust.ForeColor = Color.FromArgb(10, 132, 255)
        self.Controls.Add(lbl_adjust)
        
        self.btn_reset_limits = Button()
        self.btn_reset_limits.Text = "Ripristina Limiti"
        self.btn_reset_limits.Location = Point(1270, 123)
        self.btn_reset_limits.Size = Size(120, 28)
        self.btn_reset_limits.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_reset_limits.ForeColor = Color.White
        self.btn_reset_limits.FlatStyle = 0
        self.btn_reset_limits.Font = Font("Segoe UI", 8.5)
        self.btn_reset_limits.Click += self.on_reset_limits_click
        self.btn_reset_limits.Anchor = AnchorStyles.Top | AnchorStyles.Right
        self.Controls.Add(self.btn_reset_limits)
        
        self.pic_bar = PictureBox()
        self.pic_bar.Location = Point(510, 155)
        self.pic_bar.Size = Size(880, 60)
        self.pic_bar.BackColor = Color.FromArgb(44, 44, 46)
        self.pic_bar.Paint += self.on_bar_paint
        self.pic_bar.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right
        self.Controls.Add(self.pic_bar)
        
        self.btn_shift_start_dec = Button()
        self.btn_shift_start_dec.Text = "Iniz -5°"
        self.btn_shift_start_dec.Location = Point(510, 225)
        self.btn_shift_start_dec.Size = Size(100, 28)
        self.btn_shift_start_dec.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_shift_start_dec.ForeColor = Color.White
        self.btn_shift_start_dec.FlatStyle = 0
        self.btn_shift_start_dec.Font = Font("Segoe UI", 8.5)
        self.btn_shift_start_dec.Click += lambda s, e: self.shift_trajectory_limit("start", -5.0)
        self.btn_shift_start_dec.Anchor = AnchorStyles.Top | AnchorStyles.Left
        self.Controls.Add(self.btn_shift_start_dec)
        
        self.btn_shift_start_inc = Button()
        self.btn_shift_start_inc.Text = "Iniz +5°"
        self.btn_shift_start_inc.Location = Point(615, 225)
        self.btn_shift_start_inc.Size = Size(100, 28)
        self.btn_shift_start_inc.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_shift_start_inc.ForeColor = Color.White
        self.btn_shift_start_inc.FlatStyle = 0
        self.btn_shift_start_inc.Font = Font("Segoe UI", 8.5)
        self.btn_shift_start_inc.Click += lambda s, e: self.shift_trajectory_limit("start", 5.0)
        self.btn_shift_start_inc.Anchor = AnchorStyles.Top | AnchorStyles.Left
        self.Controls.Add(self.btn_shift_start_inc)
        
        self.lbl_shift_info = Label()
        self.lbl_shift_info.Text = "Inizio: +0.0° | Fine: -0.0°"
        self.lbl_shift_info.Location = Point(720, 229)
        self.lbl_shift_info.Size = Size(460, 20)
        self.lbl_shift_info.ForeColor = Color.LightGray
        self.lbl_shift_info.TextAlign = ContentAlignment.MiddleCenter
        self.lbl_shift_info.Font = Font("Segoe UI", 8.5)
        self.lbl_shift_info.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right
        self.Controls.Add(self.lbl_shift_info)
        
        self.btn_shift_end_dec = Button()
        self.btn_shift_end_dec.Text = "Fine -5°"
        self.btn_shift_end_dec.Location = Point(1185, 225)
        self.btn_shift_end_dec.Size = Size(100, 28)
        self.btn_shift_end_dec.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_shift_end_dec.ForeColor = Color.White
        self.btn_shift_end_dec.FlatStyle = 0
        self.btn_shift_end_dec.Font = Font("Segoe UI", 8.5)
        self.btn_shift_end_dec.Click += lambda s, e: self.shift_trajectory_limit("end", -5.0)
        self.btn_shift_end_dec.Anchor = AnchorStyles.Top | AnchorStyles.Right
        self.Controls.Add(self.btn_shift_end_dec)
        
        self.btn_shift_end_inc = Button()
        self.btn_shift_end_inc.Text = "Fine +5°"
        self.btn_shift_end_inc.Location = Point(1290, 225)
        self.btn_shift_end_inc.Size = Size(100, 28)
        self.btn_shift_end_inc.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_shift_end_inc.ForeColor = Color.White
        self.btn_shift_end_inc.FlatStyle = 0
        self.btn_shift_end_inc.Font = Font("Segoe UI", 8.5)
        self.btn_shift_end_inc.Click += lambda s, e: self.shift_trajectory_limit("end", 5.0)
        self.btn_shift_end_inc.Anchor = AnchorStyles.Top | AnchorStyles.Right
        self.Controls.Add(self.btn_shift_end_inc)
        
        # Live Monitor Panel
        lbl_mon = Label()
        lbl_mon.Text = "STATO IN TEMPO REALE"
        lbl_mon.Location = Point(510, 270)
        lbl_mon.Size = Size(880, 20)
        lbl_mon.Font = Font("Segoe UI", 9, FontStyle.Bold)
        lbl_mon.ForeColor = Color.FromArgb(10, 132, 255)
        lbl_mon.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right
        self.Controls.Add(lbl_mon)
        
        self.state_panel = Panel()
        self.state_panel.Location = Point(510, 290)
        self.state_panel.Size = Size(880, 130)
        self.state_panel.BackColor = Color.FromArgb(44, 44, 46)
        self.state_panel.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right
        self.Controls.Add(self.state_panel)
        
        self.lbl_state = Label()
        self.lbl_state.Location = Point(10, 5)
        self.lbl_state.Size = Size(860, 22)
        self.lbl_state.BackColor = Color.Transparent
        self.lbl_state.ForeColor = Color.White
        self.lbl_state.Font = Font("Segoe UI", 10, FontStyle.Bold)
        self.lbl_state.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right
        self.state_panel.Controls.Add(self.lbl_state)
        
        self.lbl_trip_info = Label()
        self.lbl_trip_info.Location = Point(10, 29)
        self.lbl_trip_info.BackColor = Color.Transparent
        self.lbl_trip_info.ForeColor = Color.LightGray
        self.lbl_trip_info.Font = Font("Segoe UI", 9)
        self.lbl_trip_info.AutoSize = True
        self.lbl_trip_info.Anchor = AnchorStyles.Top | AnchorStyles.Left
        self.state_panel.Controls.Add(self.lbl_trip_info)
        
        self.lbl_countdown = Label()
        self.lbl_countdown.Location = Point(10, 50)
        self.lbl_countdown.Size = Size(860, 22)
        self.lbl_countdown.BackColor = Color.Transparent
        self.lbl_countdown.ForeColor = Color.FromArgb(255, 214, 10)
        self.lbl_countdown.Font = Font("Segoe UI", 10, FontStyle.Bold)
        self.lbl_countdown.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right
        self.state_panel.Controls.Add(self.lbl_countdown)
        
        self.lbl_rates = Label()
        self.lbl_rates.Location = Point(10, 74)
        self.lbl_rates.Size = Size(860, 20)
        self.lbl_rates.BackColor = Color.Transparent
        self.lbl_rates.ForeColor = Color.LightGray
        self.lbl_rates.Font = Font("Segoe UI", 8.5)
        self.lbl_rates.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right
        self.state_panel.Controls.Add(self.lbl_rates)
        
        self.lbl_error = Label()
        self.lbl_error.Location = Point(10, 96)
        self.lbl_error.Size = Size(860, 20)
        self.lbl_error.BackColor = Color.Transparent
        self.lbl_error.ForeColor = Color.LightGray
        self.lbl_error.Font = Font("Segoe UI", 8.5)
        self.lbl_error.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right
        self.state_panel.Controls.Add(self.lbl_error)
        
        # Debug Log ListBox
        lbl_log = Label()
        lbl_log.Text = "LOG DI SISTEMA & DEBUG"
        lbl_log.Location = Point(510, 435)
        lbl_log.Size = Size(880, 20)
        lbl_log.Font = Font("Segoe UI", 9, FontStyle.Bold)
        lbl_log.ForeColor = Color.FromArgb(10, 132, 255)
        lbl_log.Anchor = AnchorStyles.Top | AnchorStyles.Left
        self.Controls.Add(lbl_log)
        
        self.lst_log = ListBox()
        self.lst_log.Location = Point(510, 455)
        self.lst_log.Size = Size(880, 145)
        self.lst_log.BackColor = Color.FromArgb(20, 20, 20)
        self.lst_log.ForeColor = Color.FromArgb(48, 209, 88)
        self.lst_log.Font = Font("Consolas", 8.5)
        self.lst_log.HorizontalScrollbar = True
        self.lst_log.SelectionMode = SelectionMode.MultiExtended
        self.lst_log.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right
        self.lst_log.KeyDown += self.on_log_key_down
        self.Controls.Add(self.lst_log)

    def _get_ui_value(self, control):
        """Safely read a TextBox/control .Text from any thread via Invoke."""
        result = [None]
        def _read():
            result[0] = control.Text
        self.Invoke(Action(_read))
        return result[0]

    # --- UI UPDATER TICK ---
    def timer_tick(self, state):
        try:
            # We call BeginInvoke to update GUI thread safely
            self.BeginInvoke(Action(self.update_gui_labels))
        except Exception:
            pass
            
    def update_gui_labels(self):
        # Cache current mount coordinates for high-performance visual bar drawing and safety checks
        is_connected = False
        if SharpCap is not None and SharpCap.Mounts.SelectedMount is not None:
            try:
                is_connected = SharpCap.Mounts.SelectedMount.Connected
                if not is_connected:
                    self.cached_mount_alt = None
                    self.cached_mount_az = None
                    self.cached_mount_ra = None
                    self.cached_mount_dec = None
                
                # ONLY query ASCOM directly when NOT tracking, NOT blocked, and rate limit it to 1 Hz (once every 10 ticks)
                if is_connected and not self.tracking_active and time.time() >= self.block_ascom_until:
                    self.gui_com_tick_counter += 1
                    if self.gui_com_tick_counter >= 10:
                        self.gui_com_tick_counter = 0
                        ascom = SharpCap.Mounts.SelectedMount.AscomMount
                        if ascom:
                            self.cached_mount_ra = ascom.RightAscension
                            self.cached_mount_dec = ascom.Declination
                            self.cached_mount_alt = ascom.Altitude
                            self.cached_mount_az = ascom.Azimuth
            except Exception:
                pass
                
        self.lbl_state.Text = "Stato: " + self.status_text
        self.lbl_countdown.Text = self.countdown_text
        self.lbl_rates.Text = self.rates_text
        self.lbl_error.Text = self.error_text
        
        # Update mount live status and coordinates
        if is_connected:
            mount_desc = "Connessa"
            if SharpCap.Mounts.SelectedMount is not None:
                mount_desc = SharpCap.Mounts.SelectedMount.Name
            if self.cached_mount_alt is not None and self.cached_mount_az is not None:
                self.lbl_mount.Text = "Montatura: %s | Alt: %.1f° | Az: %.1f°" % (mount_desc, self.cached_mount_alt, self.cached_mount_az)
            else:
                self.lbl_mount.Text = "Montatura: %s" % mount_desc
            self.lbl_mount.ForeColor = Color.FromArgb(48, 209, 88)
        else:
            self.lbl_mount.Text = "Montatura: Disconnessa"
            self.lbl_mount.ForeColor = Color.FromArgb(255, 69, 58)
        
        # Calculate and display trip start/intercept local times
        if self.trajectory_data:
            t_intercept = self.trajectory_data["INTERCEPT_TIME"]
            try:
                lead_time = float(self.txt_lead.Text)
            except ValueError:
                lead_time = 2.0
            trajectory = self.trajectory_data["TRAJECTORY"]
            t_track_start = trajectory[self.track_start_idx][0]
            t_start_epoch = t_track_start - lead_time
            t_start_str = time.strftime("%H:%M:%S", time.localtime(t_start_epoch))
            
            # Format intercept time without milliseconds to prevent clipping
            time_str = str(self.trajectory_data.get("INTERCEPT_LOCAL_TIME", "--"))
            if "." in time_str:
                time_str = time_str.split(".")[0]
            self.lbl_trip_info.Text = "Avvio Inseguimento: %s | Intercettazione: %s" % (t_start_str, time_str)
            
            # Real-time countdown updates when idle (not actively tracking)
            if not self.tracking_active:
                time_left = t_start_epoch - time.time()
                if time_left > 0:
                    self.countdown_text = "Tempo all'Intercettazione: Inizio tra " + self.format_duration(time_left)
                else:
                    self.countdown_text = "Tempo all'Intercettazione: Scaduto da " + self.format_duration(abs(time_left))
                self.lbl_countdown.Text = self.countdown_text
        else:
            self.lbl_trip_info.Text = "Avvio Inseguimento: -- | Intercettazione: --"
            if not self.tracking_active:
                self.countdown_text = "Tempo all'Intercettazione: --"
                self.lbl_countdown.Text = self.countdown_text
            
        # Determine background and text style based on state and update Arm button countdown
        state_upper = self.status_text.upper()
        if self.tracking_active:
            if "ATTESA" in state_upper:
                if self.current_countdown_sec > 0:
                    self.btn_arm.Text = "ARMED (%s)" % self.format_duration(self.current_countdown_sec)
                else:
                    self.btn_arm.Text = "ARMED..."
            else:
                self.btn_arm.Text = "IN CORSO..."
        else:
            self.btn_arm.Text = "ARMA"
            
        if "INSEGUIMENTO ATTIVO" in state_upper or "AVVIO INSEGUIMENTO" in state_upper or "REGISTRAZIONE" in state_upper:
            # Tracking active: Dark Red
            bg_color = Color.FromArgb(80, 10, 10)
            text_color = Color.FromArgb(255, 180, 180)
        elif "ATTESA" in state_upper or "ARM" in state_upper:
            # Armed/Waiting: Dark Green
            bg_color = Color.FromArgb(16, 68, 16)
            text_color = Color.FromArgb(180, 255, 180)
        elif "ERRORE" in state_upper:
            # Error state: Dark Grey with Red text
            bg_color = Color.FromArgb(44, 44, 46)
            text_color = Color.FromArgb(255, 69, 58)
        else:
            # Normal Idle/Ready: Dark Grey
            bg_color = Color.FromArgb(44, 44, 46)
            text_color = Color.White
            
        self.state_panel.BackColor = bg_color
        self.lbl_state.BackColor = bg_color
        self.lbl_trip_info.BackColor = bg_color
        self.lbl_countdown.BackColor = bg_color
        self.lbl_rates.BackColor = bg_color
        self.lbl_error.BackColor = bg_color
        
        self.lbl_state.ForeColor = text_color
        
        if self.tracking_active and hasattr(self, 'pic_bar'):
            self.pic_bar.Invalidate()
            if hasattr(self, 'pic_sky_map') and self.pic_sky_map is not None:
                self.pic_sky_map.Invalidate()
        
        # 1 Hz position check rate limiting
        self.check_pos_counter += 1
        if self.check_pos_counter >= 10:
            self.check_pos_counter = 0
            self.check_mount_position()
            if hasattr(self, 'pic_bar'):
                self.pic_bar.Invalidate()
                if hasattr(self, 'pic_sky_map') and self.pic_sky_map is not None:
                    self.pic_sky_map.Invalidate()
                
            # If mount is not connected, try to auto-detect/connect it once every 3 seconds
            if not is_connected:
                self.auto_connect_mount()
            
        # Check tracking status to toggle buttons
        has_data = (self.coords_start is not None)
        if self.tracking_active:
            self.btn_load.Enabled = False
            
            self.btn_goto_start.Enabled = False
            self.btn_goto_inter.Enabled = False
            self.btn_goto_end.Enabled = False
            self.btn_solve_sync.Enabled = False
            self.btn_test_dir.Enabled = False
            self.btn_set_start.Enabled = False
            self.btn_set_inter.Enabled = False
            self.btn_set_end.Enabled = False
            
            self.btn_arm.Enabled = False
            self.btn_sim.Enabled = False
            
            self.btn_reset_limits.Enabled = False
            self.btn_shift_start_dec.Enabled = False
            self.btn_shift_start_inc.Enabled = False
            self.btn_shift_end_dec.Enabled = False
            self.btn_shift_end_inc.Enabled = False
        else:
            self.btn_load.Enabled = True
            
            self.btn_goto_start.Enabled = has_data
            self.btn_goto_inter.Enabled = has_data
            self.btn_goto_end.Enabled = has_data
            self.btn_solve_sync.Enabled = has_data
            self.btn_test_dir.Enabled = True
            
            self.btn_arm.Enabled = has_data
            self.btn_sim.Enabled = has_data
            
            self.btn_set_start.Enabled = (self.last_goto_point == "start")
            self.btn_set_inter.Enabled = (self.last_goto_point == "intermediate")
            self.btn_set_end.Enabled = (self.last_goto_point == "end")
            
            self.btn_reset_limits.Enabled = has_data
            self.btn_shift_start_dec.Enabled = has_data
            self.btn_shift_start_inc.Enabled = has_data
            self.btn_shift_end_dec.Enabled = has_data
            self.btn_shift_end_inc.Enabled = has_data

    def set_state(self, status, countdown="--", rates="--", error="--"):
        self.status_text = status
        self.countdown_text = "Tempo all'Intercettazione: " + str(countdown)
        self.rates_text = rates
        self.error_text = error

    # --- HARDWARE CONNECT CORE ---
    def auto_connect_mount(self):
        global SharpCap
        if SharpCap is None:
            self.lbl_mount.Text = "Montatura: Esecuzione fuori da SharpCap"
            self.log("Rilevamento SharpCap fallito: esecuzione all'esterno.")
            return
            
        mount = SharpCap.Mounts.SelectedMount
        if mount is not None:
            try:
                    cam = SharpCap.SelectedCamera
                    try:
                        self.log("DEBUG CAM SENSOR VALUE: PixelSize=%s, ImageSize=%s" % (str(cam.PixelSize), str(cam.GetImageSize())))
                    except Exception as val_ex:
                        self.log("DEBUG CAM SENSOR VALUE err: %s" % str(val_ex))
                    # Also log TelescopeFocalLength if it exists
                    if hasattr(SharpCap, "TelescopeFocalLength"):
                        self.log("DEBUG FOCAL LENGTH: %s" % str(SharpCap.TelescopeFocalLength))
            except Exception as e:
                self.log("DEBUG CAM ATTRS err: %s" % str(e))
        if mount is not None and mount.Connected:
            self.log("Rilevata montatura connessa in SharpCap: %s" % mount.Name)
            try:
                ascom_mount = mount.AscomMount
                # Check alignment mode
                try:
                    mode = ascom_mount.AlignmentMode
                    mode_val = -1
                    try:
                        mode_val = int(mode)
                    except Exception:
                        pass
                    mode_str = str(mode).lower()
                    self.is_altaz = (mode_val == 0 or "altaz" in mode_str)
                    self.log("Modalità allineamento montatura (letta): %s -> %s" % (
                        str(mode), "Alt/Az" if self.is_altaz else "Equatoriale"
                    ))
                except Exception as ex:
                    self.is_altaz = False
                    self.log("Impossibile leggere AlignmentMode (errore: %s). Default: Equatoriale." % str(ex))
                
                # Unconditional override check based on driver name or description
                desc = ""
                try:
                    desc = str(ascom_mount.Description)
                except Exception:
                    pass
                name_full = (str(mount.Name) + " " + desc).lower()
                if "cpc" in name_full or "nexstar" in name_full or "altaz" in name_full or "alt-az" in name_full:
                    self.is_altaz = True
                    self.log("Forzato allineamento Alt/Az basato sul nome/descrizione: '%s'" % name_full)
                
                self.chk_altaz.Checked = self.is_altaz
                
                # Check axis rate support
                self.log("Verifica supporto CanMoveAxis...")
                can_move_0 = ascom_mount.CanMoveAxis(to_axis(0))
                can_move_1 = ascom_mount.CanMoveAxis(to_axis(1))
                self.log("CanMoveAxis(0): %s, CanMoveAxis(1): %s" % (can_move_0, can_move_1))
                
                if can_move_0 and can_move_1:
                    self.lbl_mount.Text = "Montatura: Connessa (" + ("Alt/Az" if self.is_altaz else "Equatoriale") + ")"
                    self.lbl_mount.ForeColor = Color.FromArgb(48, 209, 88)
                    self.log("Montatura ASCOM agganciata correttamente con supporto MoveAxis.")
                else:
                    self.lbl_mount.Text = "Montatura: ASCOM MoveAxis NON supportato!"
                    self.lbl_mount.ForeColor = Color.FromArgb(255, 69, 58)
                    self.log("Errore: la montatura ASCOM non supporta MoveAxis su entrambi gli assi!")
                    MessageBox.Show(
                        "Attenzione: il driver ASCOM di questa montatura dichiara di non supportare "
                        "il comando MoveAxis. L'inseguimento orbitale non sarà possibile.",
                        "Supporto MoveAxis Mancante", MessageBoxButtons.OK, MessageBoxIcon.Warning
                    )
            except Exception as e:
                self.lbl_mount.Text = "Montatura: Errore: " + str(e)
                self.lbl_mount.ForeColor = Color.FromArgb(255, 69, 58)
                self.log("Errore durante l'inizializzazione della montatura: " + str(e))
        else:
            self.lbl_mount.Text = "Montatura: Non connessa in SharpCap"
            self.lbl_mount.ForeColor = Color.FromArgb(255, 69, 58)
            if mount is None:
                self.log("Nessuna montatura selezionata in SharpCap.")
            else:
                self.log("Montatura selezionata in SharpCap ma non connessa.")

    def on_reset_limits_click(self, sender, event):
        if not self.trajectory_data:
            return
        trajectory = self.trajectory_data["TRAJECTORY"]
        self.track_start_idx = self.default_start_idx
        self.track_end_idx = self.default_end_idx
        
        # Update calibration coordinates
        self.coords_start = (trajectory[self.track_start_idx][1], trajectory[self.track_start_idx][2])
        self.coords_end = (trajectory[self.track_end_idx][1], trajectory[self.track_end_idx][2])
        
        self.lbl_shift_info.Text = "Inizio: +0.0° | Fine: -0.0°"
        self.has_calib_start = False
        self.has_calib_inter = False
        self.has_calib_end = False
        self.update_calib_status_label()
        self.pic_bar.Invalidate()
        if hasattr(self, 'pic_sky_map') and self.pic_sky_map is not None:
            self.pic_sky_map.Invalidate()
        self.update_start_altaz_label()
        self.log("Limiti di inseguimento ripristinati ai valori originali.")

    def format_duration(self, seconds):
        sec = int(math.ceil(seconds))
        if sec < 0:
            return "--"
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        if h > 0:
            return "%dh %dm %ds" % (h, m, s)
        elif m > 0:
            return "%dm %ds" % (m, s)
        else:
            return "%ds" % s

    # --- CAMERA CONFIG CORE ---
    def configure_camera(self, exp_ms, gain, force_raw8=False):
        if SharpCap is None or SharpCap.SelectedCamera is None:
            self.log("Configurazione camera ignorata (SharpCap non attivo o nessuna camera selezionata)")
            return True
            
        try:
            cam = SharpCap.SelectedCamera
            # Exposure setting (convert milliseconds to seconds for SharpCap)
            exp_seconds = float(exp_ms) / 1000.0
            exp_ctrl = getattr(cam.Controls, "Exposure", None)
            if exp_ctrl is not None:
                exp_ctrl.Value = exp_seconds
            else:
                for ctrl in cam.Controls:
                    if ctrl.Name.lower() == "exposure":
                        ctrl.Value = exp_seconds
                        break
            
            # Gain setting
            gain_ctrl = getattr(cam.Controls, "Gain", None)
            if gain_ctrl is not None:
                gain_ctrl.Value = float(gain)
            else:
                for ctrl in cam.Controls:
                    if ctrl.Name.lower() == "gain":
                        ctrl.Value = float(gain)
                        break

            # Force 8-bit RAW and Max Resolution (disable binning) if requested
            if force_raw8:
                # 1. Output Format / Colour Space
                for ctrl in cam.Controls:
                    name_lower = ctrl.Name.lower()
                    if "colour space" in name_lower or "colourspace" in name_lower or "output format" in name_lower:
                        try:
                            allowed = list(ctrl.AvailableValues)
                            for val in ["RAW8", "Mono8", "RGB8"]:
                                if val in allowed:
                                    ctrl.Value = val
                                    break
                        except Exception:
                            pass
                
                # 2. Reset Binning to 1
                for ctrl in cam.Controls:
                    if ctrl.Name.lower() == "binning":
                        try:
                            allowed = list(ctrl.AvailableValues)
                            if "1" in allowed:
                                ctrl.Value = "1"
                            elif 1 in allowed:
                                ctrl.Value = 1
                        except Exception:
                            pass
            return True
        except Exception as e:
            self.log("Errore nella configurazione dei controlli camera: " + str(e))
            return False

    # --- LOAD TRAJECTORY ---
    def on_load_trajectory(self, sender, event):
        dialog = OpenFileDialog()
        dialog.Filter = "JSON files (*.json)|*.json"
        dialog.Title = "Seleziona File Traiettoria Coyote ISS"
        
        if dialog.ShowDialog() == DialogResult.OK:
            self.trajectory_filepath = dialog.FileName
            try:
                import json
                with open(self.trajectory_filepath, "r") as f:
                    data = json.load(f)
                
                # Verify required data
                required_vars = [
                    "INTERCEPT_TIME", "INTERCEPT_RA", "INTERCEPT_DEC", 
                    "INTERCEPT_ALT", "INTERCEPT_AZ", "TRAJECTORY", 
                    "INTERCEPT_LOCAL_TIME"
                ]
                missing = [v for v in required_vars if v not in data]
                if missing:
                    raise ValueError("Variabili mancanti nel file traiettoria: " + ", ".join(missing))
                
                self.trajectory_data = data
                self.lbl_file.Text = "File: " + os.path.basename(self.trajectory_filepath)
                self.lbl_file.ForeColor = Color.FromArgb(48, 209, 88)
                
                # Populate Info labels (concise text format to prevent overlapping the sky map)
                self.lbl_info_title.Size = Size(590, 20)
                self.lbl_info_time.Size = Size(590, 20)
                self.lbl_info_coords.Size = Size(590, 20)
                self.lbl_info_maxalt.Size = Size(590, 20)
                self.lbl_info_start_altaz.Size = Size(590, 20)
                
                time_str = str(data["INTERCEPT_LOCAL_TIME"])
                if "." in time_str:
                    time_str = time_str.split(".")[0]
                self.lbl_info_time.Text = "Intercettazione (Locale): " + time_str
                self.lbl_info_coords.Text = "JNow RA/Dec: %.4fh / %.3f°" % (data["INTERCEPT_RA"], data["INTERCEPT_DEC"])
                self.lbl_info_maxalt.Text = "Intercept Alt/Az: Alt: %.1f° | Az: %.1f°" % (data["INTERCEPT_ALT"], data["INTERCEPT_AZ"])
                
                # Extract 3-point calibration/GOTO coordinates
                trajectory = data["TRAJECTORY"]
                
                # Point Y: Intermediate (Culmination point)
                max_alt_idx = 0
                max_alt_val = -90.0
                for idx, pt in enumerate(trajectory):
                    if pt[3] > max_alt_val:
                        max_alt_val = pt[3]
                        max_alt_idx = idx
                self.coords_inter = (trajectory[max_alt_idx][1], trajectory[max_alt_idx][2])
                
                # Find the index in the trajectory closest to the intercept time
                intercept_time = data["INTERCEPT_TIME"]
                intercept_idx = 0
                min_diff = float('inf')
                for idx, pt in enumerate(trajectory):
                    diff = abs(pt[0] - intercept_time)
                    if diff < min_diff:
                        min_diff = diff
                        intercept_idx = idx
                
                # Initialize tracking adjustment limits
                self.track_start_idx = intercept_idx
                self.track_end_idx = len(trajectory) - 1
                self.default_start_idx = intercept_idx
                self.default_end_idx = len(trajectory) - 1
                self.culm_idx = max_alt_idx
                self.flip_idx = data.get("MERIDIAN_FLIP_INDEX", None)
                self.ha_1h_idx = data.get("HA_1H_INDEX", None)
                self.ha_2h_idx = data.get("HA_2H_INDEX", None)
                self.ha_minus1h_idx = data.get("HA_MINUS1H_INDEX", None)
                self.ha_minus2h_idx = data.get("HA_MINUS2H_INDEX", None)
                self.has_calib_start = False
                self.has_calib_inter = False
                self.has_calib_end = False
                self.update_calib_status_label()
                self.lbl_shift_info.Text = "Inizio: +0.0° | Fine: -0.0°"
                # Debug logging of radar geometry
                alt_c = trajectory[max_alt_idx][3]
                az_c = trajectory[max_alt_idx][4]
                self.log("INFO RADAR: Culmine Alt: %.1f°, Az: %.1f°" % (alt_c, az_c))
                self.pic_bar.Invalidate()
                if hasattr(self, 'pic_sky_map') and self.pic_sky_map is not None:
                    self.pic_sky_map.Invalidate()
                
                # Point X: Start (Adjusted for lead_time to match the actual tracking start coordinates)
                lead_time = float(self.txt_lead.Text) if self.txt_lead.Text else 2.0
                start_time = intercept_time - lead_time
                start_idx = 0
                min_start_diff = float('inf')
                for idx, pt in enumerate(trajectory):
                    diff = abs(pt[0] - start_time)
                    if diff < min_start_diff:
                        min_start_diff = diff
                        start_idx = idx
                self.coords_start = (trajectory[start_idx][1], trajectory[start_idx][2])
                
                # Point Z: End (Descent/last point in trajectory, dynamically aligns to track_end_idx)
                self.coords_end = (trajectory[self.track_end_idx][1], trajectory[self.track_end_idx][2])
                
                self.last_goto_point = None
                self.last_goto_coords = None
                
                self.set_state("Traiettoria caricata con successo")
                self.log("Variabili caricate con successo. Intercettazione locale: " + str(data["INTERCEPT_LOCAL_TIME"]))
                
                # Check for meridian flip key
                requires_flip = data.get("REQUIRES_MERIDIAN_FLIP", False)
                if requires_flip:
                    self.log("⚠️ ATTENZIONE: Questa traiettoria RICHIEDE un MERIDIAN FLIP sulla montatura equatoriale!")
                else:
                    self.log("Nessun meridian flip richiesto per questo passaggio.")
                    
                self.log("Coordinate Partenza (Start): RA=%.4fh, Dec=%.3f° | Culmine (Intermedio): RA=%.4fh, Dec=%.3f° | Fine (Arrivo): RA=%.4fh, Dec=%.3f°" % 
                         (self.coords_start[0], self.coords_start[1], self.coords_inter[0], self.coords_inter[1], self.coords_end[0], self.coords_end[1]))
                self.update_start_altaz_label()
            except Exception as e:
                self.lbl_file.Text = "File: Caricamento fallito"
                self.lbl_file.ForeColor = Color.FromArgb(255, 69, 58)
                self.log("Errore durante il caricamento del file traiettoria: " + str(e))
                MessageBox.Show(
                    "Errore caricamento traiettoria:\n" + str(e),
                    "Errore File", MessageBoxButtons.OK, MessageBoxIcon.Error
                )

    # --- POSITION CHECKER ---
    def check_mount_position(self):
        if self.tracking_active:
            return
        if self.last_goto_point is None or self.last_goto_coords is None:
            return
        if self.cached_mount_ra is None or self.cached_mount_dec is None:
            return
        try:
            current_ra = self.cached_mount_ra
            current_dec = self.cached_mount_dec
            target_ra, target_dec = self.last_goto_coords
            diff_ra = abs(current_ra - target_ra)
            if diff_ra > 12.0:
                diff_ra = 24.0 - diff_ra
            diff_dec = abs(current_dec - target_dec)
            
            # Threshold: 0.067h RA (1.0 degree) and 1.0 deg Dec to avoid false triggers
            if diff_ra > 0.067 or diff_dec > 1.0:
                self.log("Rilevato spostamento manuale della montatura. Pulsanti 'Set Correction' disabilitati.")
                self.last_goto_point = None
                self.last_goto_coords = None
        except Exception:
            pass

    def get_interpolated_correction(self, t_current):
        t_x = self.trajectory_data["INTERCEPT_TIME"]
        trajectory = self.trajectory_data["TRAJECTORY"]
        t_z = trajectory[-1][0]
        
        # Find Y point timestamp (culmination)
        max_alt_idx = 0
        max_alt_val = -90.0
        for idx, pt in enumerate(trajectory):
            if pt[3] > max_alt_val:
                max_alt_val = pt[3]
                max_alt_idx = idx
        t_y = trajectory[max_alt_idx][0]
        
        # Select active parameters based on mode
        if self.is_altaz:
            x_val = (self.calib_delta_az_x, self.calib_delta_alt_x)
            y_val = (self.calib_delta_az_y, self.calib_delta_alt_y)
            z_val = (self.calib_delta_az_z, self.calib_delta_alt_z)
        else:
            x_val = (self.calib_delta_ra_x, self.calib_delta_dec_x)
            y_val = (self.calib_delta_ra_y, self.calib_delta_dec_y)
            z_val = (self.calib_delta_ra_z, self.calib_delta_dec_z)
            
        if t_current <= t_x:
            return x_val[0], x_val[1]
        elif t_current >= t_z:
            return z_val[0], z_val[1]
        elif t_current < t_y:
            w = (t_current - t_x) / (t_y - t_x)
            d0 = (1.0 - w) * x_val[0] + w * y_val[0]
            d1 = (1.0 - w) * x_val[1] + w * y_val[1]
            return d0, d1
        else:
            w = (t_current - t_y) / (t_z - t_y)
            d0 = (1.0 - w) * y_val[0] + w * z_val[0]
            d1 = (1.0 - w) * y_val[1] + w * z_val[1]
            return d0, d1

    # --- SLEW & CALIBRATE (GOTO) ROUTINES ---
    # --- MANUAL SLEW & CALIBRATE (GOTO) ROUTINES ---
    def run_manual_goto(self, name, coords):
        if coords is None:
            return
        if SharpCap is None or SharpCap.Mounts.SelectedMount is None:
            self.status_text = "Errore: Montatura disconnessa"
            return
            
        mount = SharpCap.Mounts.SelectedMount
        ascom = mount.AscomMount
        
        try:
            self.abort_requested = False
            self.tracking_active = True
            self.set_state("GOTO %s in corso..." % name)
            self.log("Avvio GOTO manuale al punto %s..." % name)
            
            # Enable mount tracking if it's off (required by some ASCOM mounts for slews/MoveAxis)
            try:
                if not ascom.Tracking:
                    ascom.Tracking = True
                    self.log("Tracking della montatura attivato per GOTO.")
            except Exception as ex:
                self.log("Impossibile impostare Tracking=True: %s" % str(ex))
                
            # If going to start, dynamically recalculate target coordinates including current lead_time
            if name == "start" and self.trajectory_data:
                try:
                    lead_time = float(self._get_ui_value(self.txt_lead))
                    intercept_time = self.trajectory_data["INTERCEPT_TIME"]
                    trajectory = self.trajectory_data["TRAJECTORY"]
                    start_time = intercept_time - lead_time
                    
                    start_idx = 0
                    min_start_diff = float('inf')
                    for idx, pt in enumerate(trajectory):
                        diff = abs(pt[0] - start_time)
                        if diff < min_start_diff:
                            min_start_diff = diff
                            start_idx = idx
                            
                    coords = (trajectory[start_idx][1], trajectory[start_idx][2])
                    self.log("Coordinate GOTO start ricalcolate per anticipo di %.1fs: RA=%.5fh, Dec=%.4f°" % (lead_time, coords[0], coords[1]))
                except Exception as ex:
                    self.log("Errore ricalcolo coordinate start per lead_time: %s" % str(ex))
                    
            ra, dec = coords
            ascom.SlewToCoordinatesAsync(ra, dec)
            
            # Wait for Slew
            while ascom.Slewing:
                Threading.Thread.Sleep(200)
                if self.abort_requested:
                    ascom.AbortSlew()
                    self.set_state("GOTO manuale abortito")
                    self.log("GOTO manuale interrotto dall'utente.")
                    return
            
            # Setup stars exposure — use Invoke to safely read GUI from this background thread
            star_exp = float(self._get_ui_value(self.txt_star_exp))
            star_gain = float(self._get_ui_value(self.txt_star_gain))
            self.configure_camera(star_exp, star_gain)
            
            # Wait for camera to settle
            Threading.Thread.Sleep(2000)
            
            self.last_goto_point = name
            self.last_goto_coords = coords
            self.set_state("Puntato su %s" % name)
            self.log("Montatura posizionata su %s. Camera impostata per le stelle." % name)
        except Exception as e:
            self.set_state("Errore GOTO: " + str(e))
            self.log("Errore GOTO %s: %s" % (name, str(e)))
        finally:
            try:
                if mount is not None and mount.Connected and ascom is not None:
                    self.cached_mount_ra = ascom.RightAscension
                    self.cached_mount_dec = ascom.Declination
                    self.cached_mount_alt = ascom.Altitude
                    self.cached_mount_az = ascom.Azimuth
            except Exception:
                pass
            self.tracking_active = False

    def run_manual_solve_sync(self):
        if SharpCap is None or SharpCap.Mounts.SelectedMount is None:
            self.log("Errore: Montatura disconnessa o esecuzione fuori da SharpCap")
            return
            
        mount = SharpCap.Mounts.SelectedMount
        
        try:
            self.abort_requested = False
            self.tracking_active = True
            self.set_state("Plate Solving & Sync...")
            self.log("Avvio Plate Solving & Sync...")
            
            # Configure camera for stars before plate solve — use Invoke to safely read GUI
            star_exp = float(self._get_ui_value(self.txt_star_exp))
            star_gain = float(self._get_ui_value(self.txt_star_gain))
            self.configure_camera(star_exp, star_gain)
            
            # Dynamic sleep based on star exposure to let the camera apply settings and capture a frame
            sleep_ms = int(max(2000.0, star_exp + 1000.0))
            self.log("Attesa di %d ms per applicazione esposizione stellare..." % sleep_ms)
            Threading.Thread.Sleep(sleep_ms)
            
            task = mount.SolveAndSync()
            
            # Poll task status at 5 Hz (every 200 ms) up to 30 seconds
            max_wait = 30.0
            dt = 0.2
            elapsed = 0.0
            while not task.IsCompleted:
                if self.abort_requested:
                    self.set_state("Sync Abortito")
                    return
                time_left = max(0.0, max_wait - elapsed)
                self.set_state("Sync in corso... Attendi %.1fs" % time_left)
                Threading.Thread.Sleep(int(dt * 1000.0))
                elapsed += dt
                if elapsed >= max_wait:
                    break
                    
            if not task.IsCompleted:
                self.set_state("Sync Timeout")
                self.log("ATTENZIONE: Timeout durante il Plate Solving.")
            else:
                try:
                    success = task.Result
                except Exception as ex:
                    success = False
                    self.log("Errore nel task di Plate Solve: %s" % str(ex))
                    
                if success:
                    self.set_state("Sync completato")
                    self.log("Plate Solving & Sync completato con successo (montatura sincronizzata).")
                else:
                    self.set_state("Sync Fallito")
                    self.log("ATTENZIONE: Plate Solving fallito (risoluzione non riuscita).")
        except Exception as e:
            self.set_state("Sync Fallito: " + str(e))
            self.log("Errore durante Plate Solving: " + str(e))
        finally:
            self.tracking_active = False

    def run_auto_direction_calibration(self):
        if SharpCap is None or SharpCap.Mounts.SelectedMount is None:
            MessageBox.Show("Errore: montatura non connessa.", "Errore", MessageBoxButtons.OK, MessageBoxIcon.Error)
            return
            
        mount = SharpCap.Mounts.SelectedMount
        ascom = mount.AscomMount
        
        self.set_state("Calibrazione...")
        self.log("Inizio calibrazione automatica direzione assi...")
        
        try:
            self.tracking_active = True
            
            # Read alignment mode from GUI check
            is_altaz_box = [False]
            def _get_altaz():
                is_altaz_box[0] = self.chk_altaz.Checked
            self.Invoke(Action(_get_altaz))
            is_altaz = is_altaz_box[0]
            
            # --- AXIS 0 TEST ---
            pos0_start = ascom.Azimuth if is_altaz else ascom.RightAscension * 15.0
            self.log("Asse 0: Posizione iniziale = %.3f°" % pos0_start)
            
            # Command positive rate of 1.0 deg/s for 1.5 seconds
            ascom.MoveAxis(to_axis(0), 1.0)
            Threading.Thread.Sleep(1500)
            ascom.MoveAxis(to_axis(0), 0.0)
            Threading.Thread.Sleep(500)
            
            pos0_end = ascom.Azimuth if is_altaz else ascom.RightAscension * 15.0
            diff0 = angle_diff(pos0_end, pos0_start)
            self.log("Asse 0: Posizione finale = %.3f° | Differenza = %.3f°" % (pos0_end, diff0))
            
            # If difference is negative, standard positive command moved coordinate down -> needs inversion
            needs_inv0 = (diff0 < 0.0)
            def _update_chk0():
                self.chk_inv_axis0.Checked = needs_inv0
            self.Invoke(Action(_update_chk0))
            self.log("Asse 0: Inversione impostata su %s" % needs_inv0)
            
            # Slew back to original position
            ascom.MoveAxis(to_axis(0), -1.0)
            Threading.Thread.Sleep(1500)
            ascom.MoveAxis(to_axis(0), 0.0)
            
            # --- AXIS 1 TEST ---
            pos1_start = ascom.Altitude if is_altaz else ascom.Declination
            self.log("Asse 1: Posizione iniziale = %.3f°" % pos1_start)
            
            # Command positive rate of 1.0 deg/s for 1.5 seconds
            ascom.MoveAxis(to_axis(1), 1.0)
            Threading.Thread.Sleep(1500)
            ascom.MoveAxis(to_axis(1), 0.0)
            Threading.Thread.Sleep(500)
            
            pos1_end = ascom.Altitude if is_altaz else ascom.Declination
            diff1 = pos1_end - pos1_start
            self.log("Asse 1: Posizione finale = %.3f° | Differenza = %.3f°" % (pos1_end, diff1))
            
            needs_inv1 = (diff1 < 0.0)
            def _update_chk1():
                self.chk_inv_axis1.Checked = needs_inv1
            self.Invoke(Action(_update_chk1))
            self.log("Asse 1: Inversione impostata su %s" % needs_inv1)
            
            # Slew back to original position
            ascom.MoveAxis(to_axis(1), -1.0)
            Threading.Thread.Sleep(1500)
            ascom.MoveAxis(to_axis(1), 0.0)
            
            self.set_state("Rilevamento OK")
            self.log("Calibrazione direzione completata con successo.")
            
        except Exception as e:
            self.set_state("Calibrazione Fallita")
            self.log("Errore durante calibrazione direzione: " + str(e))
        finally:
            self.tracking_active = False

    def run_set_correction(self, name):
        if SharpCap is None or SharpCap.Mounts.SelectedMount is None:
            self.log("Errore: Montatura disconnessa")
            return
            
        mount = SharpCap.Mounts.SelectedMount
        ascom = mount.AscomMount
        
        try:
            self.abort_requested = False
            self.tracking_active = True
            self.set_state("Calcolo Correzione %s..." % name)
            self.log("Avvio Plate Solve per correzione punto %s..." % name)
            
            # Configure camera for stars before plate solve — use Invoke to safely read GUI
            star_exp = float(self._get_ui_value(self.txt_star_exp))
            star_gain = float(self._get_ui_value(self.txt_star_gain))
            self.configure_camera(star_exp, star_gain)
            
            # Dynamic sleep based on star exposure to let the camera apply settings and capture a frame
            sleep_ms = int(max(2000.0, star_exp + 1000.0))
            self.log("Attesa di %d ms per applicazione esposizione stellare..." % sleep_ms)
            Threading.Thread.Sleep(sleep_ms)
            
            # Read coordinates before solve
            ra_before = ascom.RightAscension
            dec_before = ascom.Declination
            az_before = ascom.Azimuth
            alt_before = ascom.Altitude
            
            # Invoke Plate Solve using SharpCap.BlindSolver (which does not sync the mount!)
            import System
            plate_solve_purpose_type = None
            radec_position_type = None
            epoch_type = None
            for assembly in System.AppDomain.CurrentDomain.GetAssemblies():
                try:
                    if plate_solve_purpose_type is None:
                        plate_solve_purpose_type = assembly.GetType("SharpCap.Interfaces.PlateSolvePurpose")
                    if radec_position_type is None:
                        radec_position_type = assembly.GetType("SharpCap.Base.RADecPosition")
                    if epoch_type is None:
                        epoch_type = assembly.GetType("SharpCap.Base.Epoch")
                except Exception:
                    pass
            
            if plate_solve_purpose_type is None or radec_position_type is None or epoch_type is None:
                raise Exception("Tipi .NET PlateSolvePurpose, RADecPosition o Epoch non trovati.")
                
            purpose = System.Enum.Parse(plate_solve_purpose_type, "MountSync")
            cancellation_token = getattr(System.Threading.CancellationToken, "None")
            radius = 15.0
            
            # Epoch JNow or fallback to J2000
            try:
                epoch_val = System.Enum.Parse(epoch_type, "JNow")
            except Exception:
                epoch_val = System.Enum.Parse(epoch_type, "J2000")
                
            # Construct hint position: Void .ctor(Double, Double, SharpCap.Base.Epoch, Boolean)
            hint_pos = System.Activator.CreateInstance(radec_position_type, ra_before, dec_before, epoch_val, False)
            set_pixel_pos = False
            
            self.set_state("Solving %s..." % name)
            self.log("Avvio Plate Solve (Solve Only) per punto %s..." % name)
            
            # Solve is a synchronous method on IPlateSolveOnly, which returns a RADecPosition if successful
            resolved_pos = SharpCap.BlindSolver.Solve(purpose, cancellation_token, radius, hint_pos, set_pixel_pos)
            
            if resolved_pos is None:
                raise Exception("Il plate solver ha restituito None (soluzione fallita)")
                
            ra_val = resolved_pos.RightAscension
            dec_val = resolved_pos.Declination
            
            # Extract double/float values safely from properties or wrapped objects
            if hasattr(ra_val, "Hours"):
                ra_after = ra_val.Hours
            elif hasattr(ra_val, "Value"):
                ra_after = ra_val.Value
            else:
                ra_after = float(ra_val)
                
            if hasattr(dec_val, "Degrees"):
                dec_after = dec_val.Degrees
            elif hasattr(dec_val, "Value"):
                dec_after = dec_val.Value
            else:
                dec_after = float(dec_val)
            
            # Calculate corresponding Alt/Az solved coordinates mathematically using mount's SiderealTime and site Latitude
            try:
                lat = 45.0
                if self.trajectory_data is not None:
                    lat = self.trajectory_data.get("OBSERVER_LAT", 45.0)
                lst = ascom.SiderealTime
                
                ra_rad = ra_after * 15.0 * math.pi / 180.0
                dec_rad = dec_after * math.pi / 180.0
                lat_rad = lat * math.pi / 180.0
                lst_rad = lst * 15.0 * math.pi / 180.0
                
                ha_rad = lst_rad - ra_rad
                
                sin_alt = math.sin(dec_rad) * math.sin(lat_rad) + math.cos(dec_rad) * math.cos(lat_rad) * math.cos(ha_rad)
                sin_alt = max(-1.0, min(1.0, sin_alt))
                alt_rad = math.asin(sin_alt)
                alt_after = alt_rad * 180.0 / math.pi
                
                y = -math.sin(ha_rad) * math.cos(dec_rad)
                x = math.sin(dec_rad) * math.cos(lat_rad) - math.cos(dec_rad) * math.sin(lat_rad) * math.cos(ha_rad)
                az_rad = math.atan2(y, x)
                az_after = az_rad * 180.0 / math.pi
                if az_after < 0.0:
                    az_after += 360.0
            except Exception as conv_ex:
                self.log("ATTENZIONE: Impossibile calcolare Alt/Az risolti: %s. Uso valori prima del solve." % str(conv_ex))
                alt_after = alt_before
                az_after = az_before
            
            # Helper function for coordinate differences with wrap-around
            def diff_hours(h1, h2):
                diff = h1 - h2
                while diff > 12.0: diff -= 24.0
                while diff < -12.0: diff += 24.0
                return diff
                
            def diff_degrees(d1, d2):
                diff = d1 - d2
                while diff > 180.0: diff -= 360.0
                while diff < -180.0: diff += 360.0
                return diff
            
            # Calculate local shift
            shift_ra = diff_hours(ra_after, ra_before)
            shift_dec = diff_degrees(dec_after, dec_before)
            shift_az = diff_degrees(az_after, az_before)
            shift_alt = alt_after - alt_before
            
            # No mount Sync or Sync-restore is performed!
            self.log("Correzione punto %s calcolata: dRA=%.4fh, dDec=%.3f° | dAz=%.3f°, dAlt=%.3f°" % (name, shift_ra, shift_dec, shift_az, shift_alt))
            
            # Save correction
            if name == "start":
                self.calib_delta_ra_x = shift_ra
                self.calib_delta_dec_x = shift_dec
                self.calib_delta_az_x = shift_az
                self.calib_delta_alt_x = shift_alt
                self.has_calib_start = True
            elif name == "intermediate":
                self.calib_delta_ra_y = shift_ra
                self.calib_delta_dec_y = shift_dec
                self.calib_delta_az_y = shift_az
                self.calib_delta_alt_y = shift_alt
                self.has_calib_inter = True
            elif name == "end":
                self.calib_delta_ra_z = shift_ra
                self.calib_delta_dec_z = shift_dec
                self.calib_delta_az_z = shift_az
                self.calib_delta_alt_z = shift_alt
                self.has_calib_end = True
            
            self.calib_active = True
            self.update_calib_status_label()
            self.log("Correzione '%s' impostata: Delta RA=%.5fh, Delta Dec=%.4f°" % (name, shift_ra, shift_dec))
            self.set_state("Correzione %s Impostata" % name)
            
            # Reset last_goto_point to disable the button
            self.last_goto_point = None
            self.last_goto_coords = None
        except Exception as e:
            self.set_state("Errore Correction: " + str(e))
            self.log("Errore durante il calcolo della correzione: " + str(e))
        finally:
            self.tracking_active = False

    # --- ACTIVE TRACKING TIMELINE ---
    def on_arm_intercept(self, sender, event):
        print("[DEBUG] ARMA premuto")
        if not self.trajectory_data:
            MessageBox.Show("Carica prima una traiettoria per abilitare l'inseguimento!", "Attenzione", MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return
            
        if self.tracking_active:
            MessageBox.Show("Inseguimento già in corso. Premi ABORT per fermarlo.", "Attenzione", MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return

        # Reset manual offsets for the new tracking run
        self.manual_offset_axis0 = 0.0
        self.manual_offset_axis1 = 0.0

        # Check current time
        t_now = time.time()
        t_intercept = self.trajectory_data["INTERCEPT_TIME"]
        lead_time = float(self.txt_lead.Text)
        
        if t_now >= t_intercept + 20.0:
            MessageBox.Show(
                "Errore: Il passaggio della ISS è già terminato o si trova troppo avanti nel tempo.\n"
                "Usa 'SIMULA' per effettuare un test immediato.",
                "Passaggio Scaduto", MessageBoxButtons.OK, MessageBoxIcon.Error
            )
            return
        
        print("[DEBUG] Avvio thread ARMA (inseguimento reale)")
        self.abort_requested = False
        # Read all GUI values HERE in the GUI thread — worker thread cannot access WinForms controls
        is_altaz = self.chk_altaz.Checked
        lead_time = float(self.txt_lead.Text)
        kp = float(self.txt_kp.Text)
        star_gain = float(self.txt_star_gain.Text) if self.txt_star_gain.Text else 350.0
        iss_gain = float(self.txt_iss_gain.Text) if self.txt_iss_gain.Text else 250.0
        iss_exp = float(self.txt_iss_exp.Text) if self.txt_iss_exp.Text else 3.0
        inv_axis0 = self.chk_inv_axis0.Checked
        inv_axis1 = self.chk_inv_axis1.Checked
        def _start_real():
            try:
                self.tracking_worker(is_simulation=False, is_altaz=is_altaz, lead_time=lead_time, kp=kp,
                                     star_gain=star_gain, iss_gain=iss_gain, iss_exp=iss_exp,
                                     inv_axis0=inv_axis0, inv_axis1=inv_axis1)
            except Exception as ex:
                self.log("[ERRORE CRITICO] Thread ARMA: " + traceback.format_exc())
                print("[ERRORE CRITICO] Thread ARMA: " + str(ex))
        self.active_thread = Threading.Thread(Threading.ThreadStart(_start_real))
        self.active_thread.IsBackground = True
        self.active_thread.Start()

    def on_run_simulation(self, sender, event):
        print("[DEBUG] SIMULA premuto")
        if not self.trajectory_data:
            MessageBox.Show("Carica prima una traiettoria per avviare la simulazione!", "Attenzione", MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return
            
        if self.tracking_active:
            MessageBox.Show("Inseguimento già in corso. Premi ABORT per fermarlo.", "Attenzione", MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return
        
        # Reset manual offsets for the new simulation run
        self.manual_offset_axis0 = 0.0
        self.manual_offset_axis1 = 0.0

        print("[DEBUG] Avvio thread SIMULA")
        self.abort_requested = False
        # Read all GUI values HERE in the GUI thread — worker thread cannot access WinForms controls
        is_altaz = self.chk_altaz.Checked
        lead_time = float(self.txt_lead.Text)
        kp = float(self.txt_kp.Text)
        star_gain = float(self.txt_star_gain.Text) if self.txt_star_gain.Text else 350.0
        iss_gain = float(self.txt_iss_gain.Text) if self.txt_iss_gain.Text else 250.0
        iss_exp = float(self.txt_iss_exp.Text) if self.txt_iss_exp.Text else 3.0
        inv_axis0 = self.chk_inv_axis0.Checked
        inv_axis1 = self.chk_inv_axis1.Checked
        def _start_sim():
            try:
                self.tracking_worker(is_simulation=True, is_altaz=is_altaz, lead_time=lead_time, kp=kp,
                                     star_gain=star_gain, iss_gain=iss_gain, iss_exp=iss_exp,
                                     inv_axis0=inv_axis0, inv_axis1=inv_axis1)
            except Exception as ex:
                self.log("[ERRORE CRITICO] Thread SIMULA: " + traceback.format_exc())
                print("[ERRORE CRITICO] Thread SIMULA: " + str(ex))
        self.active_thread = Threading.Thread(Threading.ThreadStart(_start_sim))
        self.active_thread.IsBackground = True
        self.active_thread.Start()

    def on_abort(self, sender, event):
        self.abort_requested = True
        self.set_state("Interruzione manuale richiesta...")
        self.log("Pulsante ABORT premuto. Richiesto arresto immediato di montatura e camera.")
        self.stop_hardware()
    def stop_hardware(self):
        # Set block for all ASCOM/mount queries for 30 seconds to let SharpCap dump frames to disk at max speed
        self.block_ascom_until = time.time() + 30.0
        
        # Stop mount axes immediately (synchronous)
        try:
            if SharpCap is not None and SharpCap.Mounts.SelectedMount is not None:
                ascom = SharpCap.Mounts.SelectedMount.AscomMount
                ascom.MoveAxis(to_axis(0), 0.0)
                ascom.MoveAxis(to_axis(1), 0.0)
                self.log("Assi della montatura fermati (velocità impostata a 0).")
        except Exception as e:
            self.log("Errore durante l'arresto degli assi: " + str(e))
            
        # Stop capturing in background thread — StopCapture() can block while
        # flushing the video buffer to disk; running async prevents ABORT freezing the UI.
        def _stop_capture():
            try:
                if SharpCap is not None and SharpCap.SelectedCamera is not None:
                    SharpCap.SelectedCamera.StopCapture()
                    self.log("Registrazione SharpCap interrotta.")
            except Exception as e:
                self.log("Errore arresto registrazione: " + str(e))
        Threading.ThreadPool.QueueUserWorkItem(lambda state: _stop_capture())

    def clamp_axis_rate(self, axis_idx, rate):
        if abs(rate) < 1e-5:
            return 0.0
            
        try:
            if SharpCap is not None and SharpCap.Mounts.SelectedMount is not None:
                ascom = SharpCap.Mounts.SelectedMount.AscomMount
                axis_rates = ascom.AxisRates(to_axis(axis_idx))
                
                if axis_rates is not None and len(axis_rates) > 0:
                    abs_rate = abs(rate)
                    min_allowed = None
                    max_allowed = None
                    
                    rates_str = []
                    for r in axis_rates:
                        r_min = float(r.Minimum)
                        r_max = float(r.Maximum)
                        rates_str.append("[%.5f, %.5f]" % (r_min, r_max))
                        if min_allowed is None or r_min < min_allowed:
                            min_allowed = r_min
                        if max_allowed is None or r_max > max_allowed:
                            max_allowed = r_max
                            
                    self.log("[DEBUG] Asse %d AxisRates: %s" % (axis_idx, ", ".join(rates_str)))
                    
                    if min_allowed is not None and abs_rate < min_allowed:
                        if abs_rate < min_allowed * 0.5:
                            return 0.0
                        else:
                            return math.copysign(min_allowed, rate)
                            
                    if max_allowed is not None and abs_rate > max_allowed:
                        self.log("[DEBUG] Rate %.5f supera max_allowed %.5f per Asse %d. Clamping." % (rate, max_allowed, axis_idx))
                        return math.copysign(max_allowed, rate)
        except Exception as e:
            self.log("[DEBUG] Fallito recupero AxisRates Asse %d: %s" % (axis_idx, str(e)))
            
        # Hardcoded fallback limits: clamp to +/- 1.0 deg/s to prevent driver crashes
        abs_rate = abs(rate)
        if abs_rate < 0.002: # Deadband for very small corrections
            return 0.0
        if abs_rate > 1.0:
            return math.copysign(1.0, rate)
            
        return rate


    # --- TRACKING LOOP WORKER ---
    def tracking_worker(self, is_simulation, is_altaz, lead_time, kp, star_gain, iss_gain, iss_exp, inv_axis0, inv_axis1):
        print("[DEBUG] tracking_worker avviato, is_simulation=%s" % is_simulation)
        self.last_applied_exp = None
        self.last_applied_gain = None
        if SharpCap is None or SharpCap.Mounts.SelectedMount is None:
            self.set_state("Errore: Montatura disconnessa")
            self.log("[ERRORE] Montatura non connessa in SharpCap.")
            print("[ERRORE] Montatura non connessa.")
            self.tracking_active = False
            return
            
        self.tracking_active = True
        self.last_traj_idx = self.track_start_idx
        ascom = SharpCap.Mounts.SelectedMount.AscomMount
        self.is_altaz = is_altaz
        print("[DEBUG] ASCOM agganciato, is_altaz=%s" % is_altaz)
        
        # Retrieve trajectory array
        trajectory = self.trajectory_data["TRAJECTORY"]
        t_track_start = trajectory[self.track_start_idx][0]
        t_track_end = trajectory[self.track_end_idx][0]
        t_intercept = self.trajectory_data["INTERCEPT_TIME"]
        print("[DEBUG] Traiettoria: start_idx=%d, end_idx=%d" % (self.track_start_idx, self.track_end_idx))
        
        t_start = t_track_start - lead_time
        t_capture = t_track_start - 1.0
        
        # Calculate simulation offset
        if is_simulation:
            # Shift timeline so that t_start occurs exactly 2 seconds from now
            sim_offset = time.time() - t_start + 2.0
            self.log("Simulazione avviata. Offset temporale applicato: %.3fs" % sim_offset)
            print("[DEBUG] Simulazione: sim_offset=%.3f" % sim_offset)
        else:
            sim_offset = 0.0
            self.log("Inseguimento reale avviato. In attesa del punto di inizio...")
            print("[DEBUG] Modalità reale: attesa di t_start=%.1f (ora=%.1f)" % (t_start, time.time()))
            
        def get_simulated_time():
            return time.time() - sim_offset
            
        # Retrieve trajectory array end time
        t_end = t_track_end
        
        prev_time = get_simulated_time()
        prev_err_0 = 0.0
        prev_err_1 = 0.0
        capture_started = False
        
        try:
            # 1. WAITING FOR START PHASE
            while get_simulated_time() < t_start:
                if self.abort_requested:
                    self.set_state("Inseguimento Annullato")
                    return
                    
                time_left = t_start - get_simulated_time()
                self.current_countdown_sec = time_left
                self.set_state(
                    "IN ATTESA DI INTERCETTAZIONE" + (" (SIMULATO)" if is_simulation else ""),
                    countdown="Inizio tra: " + self.format_duration(time_left)
                )
                Threading.Thread.Sleep(100)
                
            # 2. RUNNING PASS TRACKING LOOP
            self.set_state("AVVIO INSEGUIMENTO", countdown="0.0s")
            
            # Double check tracking is active (required for MoveAxis)
            try:
                if not ascom.Tracking:
                    ascom.Tracking = True
            except Exception:
                pass
                
            # Main high-frequency loop (5 Hz)
            dt = 0.20
            loop_counter = 0
            
            # Cached error values
            err_axis_0 = 0.0
            err_axis_1 = 0.0
            error_magnitude_arcmin = 0.0
            
            # Rate command filters to prevent COM hammering
            last_sent_rate_0 = None
            last_sent_rate_1 = None
            
            # Integral terms for PI controller
            self.track_integral_0 = 0.0
            self.track_integral_1 = 0.0
            
            while get_simulated_time() < t_end:
                if self.abort_requested:
                    self.set_state("Inseguimento Interrotto")
                    return
                    
                t_now = get_simulated_time()
                
                # Apply camera settings (values captured at startup from GUI thread)
                if iss_exp != self.last_applied_exp or iss_gain != self.last_applied_gain:
                    try:
                        self.configure_camera(iss_exp, iss_gain, force_raw8=False)
                        self.last_applied_exp = iss_exp
                        self.last_applied_gain = iss_gain
                    except Exception:
                        pass
                
                # Check for camera trigger (1 second before intercept)
                if t_now >= t_capture and not capture_started:
                    try:
                        self.current_countdown_sec = t_intercept - t_now
                        self.set_state("AVVIO REGISTRAZIONE VIDEO...", countdown="Inizio tra: " + self.format_duration(t_intercept - t_now))
                        if SharpCap is not None and SharpCap.SelectedCamera is not None:
                            SharpCap.SelectedCamera.PrepareToCapture()
                            SharpCap.SelectedCamera.RunCapture()
                            self.log("Registrazione video avviata in SharpCap.")
                        capture_started = True
                    except Exception as e:
                        self.log("Errore durante l'avvio della registrazione video: " + str(e))
                        capture_started = True  # don't retry repeatedly
                
                # Target coordinates & velocities (clamp to start coordinates during lead time wait)
                if t_now < t_track_start:
                    target_dec = trajectory[self.track_start_idx][2]
                    target_alt = trajectory[self.track_start_idx][3]
                    target_az = trajectory[self.track_start_idx][4]
                    target_ra = trajectory[self.track_start_idx][1]
                    
                    ff_ra_rate = 0.0
                    ff_dec_rate = 0.0
                    ff_alt_rate = 0.0
                    ff_az_rate = 0.0
                else:
                    # Interpolate trajectory point
                    pt_pair = self.get_trajectory_points(t_now, trajectory)
                    if pt_pair is None:
                        break
                        
                    p0, p1 = pt_pair
                    t0, ra0, dec0, alt0, az0, ra_rate0, dec_rate0, alt_rate0, az_rate0 = p0
                    t1, ra1, dec1, alt1, az1, ra_rate1, dec_rate1, alt_rate1, az_rate1 = p1
                    
                    # Interpolation fraction
                    frac = (t_now - t0) / (t1 - t0) if t1 > t0 else 0.0
                    
                    # Target coordinates & velocities
                    target_dec = dec0 + frac * (dec1 - dec0)
                    target_alt = alt0 + frac * (alt1 - alt0)
                    target_az = az0 + frac * angle_diff(az1, az0)
                    
                    target_ra_deg = ra0 * 15.0 + frac * angle_diff(ra1 * 15.0, ra0 * 15.0)
                    target_ra = target_ra_deg / 15.0
                    
                    # Feedforward speeds (deg/s)
                    ff_ra_rate = ra_rate0 + frac * (ra_rate1 - ra_rate0)
                    ff_dec_rate = dec_rate0 + frac * (dec_rate1 - dec_rate0)
                    ff_alt_rate = alt_rate0 + frac * (alt_rate1 - alt_rate0)
                    ff_az_rate = az_rate0 + frac * (az_rate1 - az_rate0)
                
                # Apply dynamic pointing calibration if active
                if self.calib_active:
                    t_corr_query = max(t_track_start, t_now)
                    d0, d1 = self.get_interpolated_correction(t_corr_query)
                    if self.is_altaz:
                        target_az = target_az + d0 - self.calib_delta_az_z
                        target_alt = target_alt + d1 - self.calib_delta_alt_z
                    else:
                        target_ra = target_ra + d0 - self.calib_delta_ra_z
                        target_dec = target_dec + d1 - self.calib_delta_dec_z
                        
                # Apply manual offsets (Step Correction buttons)
                if self.is_altaz:
                    target_az = target_az + self.manual_offset_axis0
                    target_alt = target_alt + self.manual_offset_axis1
                else:
                    target_ra = target_ra + (self.manual_offset_axis0 / 15.0)
                    target_dec = target_dec + self.manual_offset_axis1

                
                # Read current mount coordinates and calculate errors (at 5 Hz loop frequency)
                try:
                    real_ra = ascom.RightAscension
                    real_dec = ascom.Declination
                    
                    if self.is_altaz:
                        # Calculate simulated Sidereal Time (LST) for the current simulated time
                        lat = 45.0
                        if self.trajectory_data is not None:
                            lat = self.trajectory_data.get("OBSERVER_LAT", 45.0)
                        
                        # Real LST
                        real_lst = ascom.SiderealTime
                        # Adjusted LST for simulated time offset
                        lst_sim = real_lst - (sim_offset * 1.002737909 / 3600.0)
                        while lst_sim < 0.0: lst_sim += 24.0
                        while lst_sim >= 24.0: lst_sim -= 24.0
                        
                        # Convert real_ra and real_dec to Alt/Az at simulated LST
                        ra_rad = real_ra * 15.0 * math.pi / 180.0
                        dec_rad = real_dec * math.pi / 180.0
                        lat_rad = lat * math.pi / 180.0
                        lst_rad = lst_sim * 15.0 * math.pi / 180.0
                        
                        ha_rad = lst_rad - ra_rad
                        
                        sin_alt = math.sin(dec_rad) * math.sin(lat_rad) + math.cos(dec_rad) * math.cos(lat_rad) * math.cos(ha_rad)
                        sin_alt = max(-1.0, min(1.0, sin_alt))
                        real_alt = math.asin(sin_alt) * 180.0 / math.pi
                        
                        y = -math.sin(ha_rad) * math.cos(dec_rad)
                        x = math.sin(dec_rad) * math.cos(lat_rad) - math.cos(dec_rad) * math.sin(lat_rad) * math.cos(ha_rad)
                        real_az = math.atan2(y, x) * 180.0 / math.pi
                        if real_az < 0.0:
                            real_az += 360.0
                            
                        self.cached_mount_alt = real_alt
                        self.cached_mount_az = real_az
                    else:
                        real_alt = ascom.Altitude
                        real_az = ascom.Azimuth
                        self.cached_mount_alt = real_alt
                        self.cached_mount_az = real_az
                        
                    # Cache these values so the GUI thread can display them without querying ASCOM
                    self.cached_mount_ra = real_ra
                    self.cached_mount_dec = real_dec
                    
                    # Calculate position error
                    if self.is_altaz:
                        err_axis_0 = angle_diff(target_az, real_az)  # degrees
                        err_axis_1 = target_alt - real_alt  # degrees
                    else:
                        err_axis_0 = angle_diff(target_ra * 15.0, real_ra * 15.0)  # degrees
                        err_axis_1 = target_dec - real_dec  # degrees
                        
                    # Position Error in arcminutes for UI reporting
                    error_magnitude_arcmin = math.sqrt(err_axis_0**2 + err_axis_1**2) * 60.0
                except Exception as e:
                    # Continue using last valid coordinates
                    pass
                
                # Increment tracking iteration counter
                loop_counter += 1
                
                if self.is_altaz:
                    ff_0 = ff_az_rate
                    ff_1 = ff_alt_rate
                else:
                    ff_0 = ff_ra_rate
                    ff_1 = ff_dec_rate
                
                # Command rates (PI feedback + Feedforward)
                # Proportional terms
                corr_0 = kp * err_axis_0
                corr_1 = kp * err_axis_1
                
                # Integral terms
                ki = 0.15 * kp  # Integral gain (15% of Proportional gain)
                self.track_integral_0 += err_axis_0 * dt
                self.track_integral_1 += err_axis_1 * dt
                
                # Anti-windup (clamp integral contribution to +/- 0.3 deg/s equivalent)
                max_i_contrib = 0.3
                if ki > 0.0:
                    max_i = max_i_contrib / ki
                    self.track_integral_0 = max(-max_i, min(max_i, self.track_integral_0))
                    self.track_integral_1 = max(-max_i, min(max_i, self.track_integral_1))
                    
                corr_0 += ki * self.track_integral_0
                corr_1 += ki * self.track_integral_1
                
                # Keep correction clamped to +/- 1.0 deg/s to prevent jerks
                max_corr = 1.0
                corr_0 = max(-max_corr, min(max_corr, corr_0))
                corr_1 = max(-max_corr, min(max_corr, corr_1))
                
                cmd_rate_0 = ff_0 + corr_0
                cmd_rate_1 = ff_1 + corr_1
                
                # Set axis rates with optional direction inversion
                rate_raw_0 = -cmd_rate_0 if inv_axis0 else cmd_rate_0
                rate_raw_1 = -cmd_rate_1 if inv_axis1 else cmd_rate_1
                
                # Apply dynamic ASCOM rate limits and deadband clamping
                rate_0 = self.clamp_axis_rate(0, rate_raw_0)
                rate_1 = self.clamp_axis_rate(1, rate_raw_1)
                
                # Filter small variations and command axes safely with try-except to avoid thread crashes
                if last_sent_rate_0 is None or abs(rate_0 - last_sent_rate_0) >= 0.01:
                    try:
                        ascom.MoveAxis(to_axis(0), rate_0)
                        last_sent_rate_0 = rate_0
                    except Exception as ex:
                        self.log("Errore ASCOM MoveAxis Asse 0 (rate=%.5f): %s" % (rate_0, str(ex)))
                        try:
                            ascom.MoveAxis(to_axis(0), 0.0)
                        except:
                            pass
                        last_sent_rate_0 = 0.0
                        
                if last_sent_rate_1 is None or abs(rate_1 - last_sent_rate_1) >= 0.01:
                    try:
                        ascom.MoveAxis(to_axis(1), rate_1)
                        last_sent_rate_1 = rate_1
                    except Exception as ex:
                        self.log("Errore ASCOM MoveAxis Asse 1 (rate=%.5f): %s" % (rate_1, str(ex)))
                        try:
                            ascom.MoveAxis(to_axis(1), 0.0)
                        except:
                            pass
                        last_sent_rate_1 = 0.0
                
                # Update UI
                countdown_str = "Tempo trascorso: " + self.format_duration(t_now - t_start)
                
                self.set_state(
                    "INSEGUIMENTO ATTIVO" + (" (SIMULATO)" if is_simulation else ""),
                    countdown=countdown_str,
                    rates="Velocità Asse 0: %.3f°/s | Asse 1: %.3f°/s" % (cmd_rate_0, cmd_rate_1),
                    error="Errore: %.2f' (Asse 0: %.2f' | Asse 1: %.2f')" % (
                        error_magnitude_arcmin, err_axis_0 * 60.0, err_axis_1 * 60.0
                    )
                )
                
                # Loop execution period
                loop_elapsed = time.time() - (t_now + sim_offset)
                sleep_time = int(max(5, (dt - loop_elapsed) * 1000.0))
                Threading.Thread.Sleep(sleep_time)
                
            # 3. COMPLETED PASS
            self.set_state("INSEGUIMENTO COMPLETATO", countdown="Finito")
            self.log("Inseguimento orbitale completato con successo.")
            
        except Exception as e:
            self.set_state("Errore in Loop: " + str(e))
            self.log("Errore critico nel loop di inseguimento:\n" + traceback.format_exc())
        finally:
            self.stop_hardware()
            self.manual_offset_axis0 = 0.0
            self.manual_offset_axis1 = 0.0
            self.tracking_active = False

    def get_trajectory_points(self, t_now, trajectory):
        if t_now < trajectory[0][0] or t_now >= trajectory[-1][0]:
            return None
            
        idx = self.last_traj_idx
        if idx >= len(trajectory) - 1:
            idx = 0
            
        while idx < len(trajectory) - 1 and trajectory[idx+1][0] <= t_now:
            idx += 1
            
        self.last_traj_idx = idx
        return trajectory[idx], trajectory[idx+1]

    def on_key_down(self, sender, event):
        if not self.tracking_active:
            return
            
        from System.Windows.Forms import Keys
        try:
            # Up/Down Arrows: Adjust exposure by +/- 0.1 ms (min 0.1ms)
            if event.KeyCode == Keys.Up:
                val = float(self.txt_iss_exp.Text) + 0.1
                self.txt_iss_exp.Text = "%.1f" % val
                event.Handled = True
            elif event.KeyCode == Keys.Down:
                val = max(0.1, float(self.txt_iss_exp.Text) - 0.1)
                self.txt_iss_exp.Text = "%.1f" % val
                event.Handled = True
            # Right/Left Arrows: Adjust gain by +/- 5 (min 0)
            elif event.KeyCode == Keys.Right:
                val = float(self.txt_iss_gain.Text) + 5
                self.txt_iss_gain.Text = "%d" % int(val)
                event.Handled = True
            elif event.KeyCode == Keys.Left:
                val = max(0, float(self.txt_iss_gain.Text) - 5)
                self.txt_iss_gain.Text = "%d" % int(val)
                event.Handled = True
        except ValueError:
            pass

    def get_closest_trajectory_index(self):
        if not self.trajectory_data:
            return None
        if self.cached_mount_ra is None or self.cached_mount_dec is None:
            return None
            
        try:
            trajectory = self.trajectory_data["TRAJECTORY"]
            min_dist = float('inf')
            closest_idx = None
            
            import math
            curr_ra_rad = math.radians(self.cached_mount_ra * 15.0)
            curr_dec_rad = math.radians(self.cached_mount_dec)
            
            for idx, pt in enumerate(trajectory):
                pt_ra_rad = math.radians(pt[1] * 15.0)
                pt_dec_rad = math.radians(pt[2])
                
                cos_dist = math.sin(curr_dec_rad)*math.sin(pt_dec_rad) + math.cos(curr_dec_rad)*math.cos(pt_dec_rad)*math.cos(curr_ra_rad - pt_ra_rad)
                dist = 1.0 - cos_dist
                if dist < min_dist:
                    min_dist = dist
                    closest_idx = idx
            
            if min_dist < 0.035: # within 15 degrees
                return closest_idx
        except Exception:
            pass
        return None

    def on_sky_map_paint(self, sender, event):
        g = event.Graphics
        # Anti-aliasing for smooth circles and lines
        g.SmoothingMode = Drawing2D.SmoothingMode.AntiAlias
        
        width = self.pic_sky_map.Width
        height = self.pic_sky_map.Height
        center_x = width / 2
        center_y = height / 2
        R = min(width, height) / 2 - 15  # leave margin for labels
        
        # Draw background circle
        bg_brush = SolidBrush(Color.FromArgb(30, 30, 30))
        g.FillEllipse(bg_brush, center_x - R, center_y - R, R * 2, R * 2)
        
        # Draw circle border
        circle_pen = Pen(Color.FromArgb(100, 100, 100), 1)
        g.DrawEllipse(circle_pen, center_x - R, center_y - R, R * 2, R * 2)
        
        # Draw central Zenit point
        zenit_pen = Pen(Color.FromArgb(80, 80, 80), 1)
        g.DrawLine(zenit_pen, center_x - 3, center_y, center_x + 3, center_y)
        g.DrawLine(zenit_pen, center_x, center_y - 3, center_x, center_y + 3)
        
        # Draw cardinal cross lines
        cross_pen = Pen(Color.FromArgb(60, 60, 60), 1)
        g.DrawLine(cross_pen, center_x, center_y - R, center_x, center_y + R)
        g.DrawLine(cross_pen, center_x - R, center_y, center_x + R, center_y)
        
        # Draw Cardinal Labels (Standard compass rose format: North top, South bottom, East right, West left)
        font_lbl = Font("Segoe UI", 7.0, FontStyle.Bold)
        gray_brush = SolidBrush(Color.DarkGray)
        g.DrawString("N", font_lbl, gray_brush, PointF(center_x - 4, center_y - R - 13))
        g.DrawString("S", font_lbl, gray_brush, PointF(center_x - 4, center_y + R + 2))
        g.DrawString("E", font_lbl, gray_brush, PointF(center_x + R + 2, center_y - 6))
        g.DrawString("W", font_lbl, gray_brush, PointF(center_x - R - 11, center_y - 6))
        
        if not self.trajectory_data:
            return
            
        trajectory = self.trajectory_data["TRAJECTORY"]
        if len(trajectory) < 2:
            return
            
        # Map points
        points = []
        for pt in trajectory:
            alt = pt[3]
            az = pt[4]
            if alt < 0:
                continue
            rad = (az - 90.0) * math.pi / 180.0
            dist = R * (90.0 - alt) / 90.0
            px = center_x + dist * math.cos(rad) # Standard X coordinate projection
            py = center_y + dist * math.sin(rad)
            points.append(PointF(px, py))
            
        # Draw full trajectory path in semi-transparent green
        if len(points) >= 2:
            path_pen = Pen(Color.FromArgb(100, 48, 209, 88), 1.5)
            for i in range(len(points) - 1):
                g.DrawLine(path_pen, points[i], points[i+1])
                
        # Draw active selection segment in bright green
        active_points = []
        for idx in range(self.track_start_idx, self.track_end_idx + 1):
            if idx >= len(trajectory):
                continue
            pt = trajectory[idx]
            alt = pt[3]
            az = pt[4]
            if alt < 0:
                continue
            rad = (az - 90.0) * math.pi / 180.0
            dist = R * (90.0 - alt) / 90.0
            px = center_x + dist * math.cos(rad) # Standard X coordinate projection
            py = center_y + dist * math.sin(rad)
            active_points.append(PointF(px, py))
            
        if len(active_points) >= 2:
            active_pen = Pen(Color.FromArgb(48, 209, 88), 2.5)
            for i in range(len(active_points) - 1):
                g.DrawLine(active_pen, active_points[i], active_points[i+1])
                
        # Draw start point (Green dot)
        if len(active_points) > 0:
            g.FillEllipse(SolidBrush(Color.FromArgb(48, 209, 88)), active_points[0].X - 3.5, active_points[0].Y - 3.5, 7, 7)
            
        # Draw end point (Red dot)
        if len(active_points) > 1:
            g.FillEllipse(SolidBrush(Color.FromArgb(255, 69, 58)), active_points[-1].X - 3.5, active_points[-1].Y - 3.5, 7, 7)
            
        # Draw culmination point (Yellow dot)
        if self.culm_idx < len(trajectory):
            pt_culm = trajectory[self.culm_idx]
            alt_c = pt_culm[3]
            az_c = pt_culm[4]
            rad_c = (az_c - 90.0) * math.pi / 180.0
            dist_c = R * (90.0 - alt_c) / 90.0
            px_c = center_x + dist_c * math.cos(rad_c) # Standard X
            py_c = center_y + dist_c * math.sin(rad_c)
            g.FillEllipse(SolidBrush(Color.Yellow), px_c - 3, py_c - 3, 6, 6)
            
        # Draw current position indicator
        closest_idx = None
        is_tracking_now = self.tracking_active and "INSEGUIMENTO" in self.status_text.upper()
        if is_tracking_now and hasattr(self, 'last_traj_idx'):
            closest_idx = self.last_traj_idx
        else:
            closest_idx = self.get_closest_trajectory_index()
            
        if closest_idx is not None and closest_idx < len(trajectory):
            pt_curr = trajectory[closest_idx]
            alt_curr = pt_curr[3]
            az_curr = pt_curr[4]
            rad_curr = (az_curr - 90.0) * math.pi / 180.0
            dist_curr = R * (90.0 - alt_curr) / 90.0
            px_curr = center_x + dist_curr * math.cos(rad_curr) # Standard X
            py_curr = center_y + dist_curr * math.sin(rad_curr)
            
            color_brush = Color.FromArgb(10, 132, 255) if is_tracking_now else Color.FromArgb(255, 149, 0)
            g.FillEllipse(SolidBrush(color_brush), px_curr - 4.5, py_curr - 4.5, 9, 9)

    def on_bar_paint(self, sender, event):
        g = event.Graphics
        width = self.pic_bar.Width
        height = self.pic_bar.Height
        
        # Draw background bar border
        rect_pen = Pen(Color.FromArgb(100, 100, 100), 1)
        g.DrawRectangle(rect_pen, 0, 0, width - 1, height - 1)
        
        if not self.trajectory_data:
            # Draw placeholder text
            font = Font("Segoe UI", 9, FontStyle.Italic)
            brush = SolidBrush(Color.Gray)
            g.DrawString("Nessuna traiettoria caricata", font, brush, PointF(10, 12))
            return
            
        trajectory = self.trajectory_data["TRAJECTORY"]
        N = len(trajectory)
        if N <= 1:
            return
            
        # Draw the main bar line in the middle (Adjusted for 60px height)
        bar_y = 26
        bar_height = 12
        
        # 1. Draw entire bar as inactive/gray
        bg_brush = SolidBrush(Color.FromArgb(70, 70, 70))
        g.FillRectangle(bg_brush, 10, bar_y, width - 20, bar_height)
        
        # 2. Draw active (selected) tracking range in green
        start_x = 10 + int(float(self.track_start_idx) / (N - 1) * (width - 20))
        end_x = 10 + int(float(self.track_end_idx) / (N - 1) * (width - 20))
        active_brush = SolidBrush(Color.FromArgb(48, 209, 88))
        g.FillRectangle(active_brush, start_x, bar_y, max(1, end_x - start_x), bar_height)
        
        # 3. Draw culmination point
        culm_x = 10 + int(float(self.culm_idx) / (N - 1) * (width - 20))
        culm_pen = Pen(Color.Yellow, 2)
        g.DrawLine(culm_pen, culm_x, bar_y - 4, culm_x, bar_y + bar_height + 4)
        
        # Draw Culmination label
        text_font = Font("Segoe UI", 7.5, FontStyle.Bold)
        yellow_brush = SolidBrush(Color.Yellow)
        g.DrawString("CULM", text_font, yellow_brush, PointF(culm_x - 12, bar_y - 15))
        
        # 4. Draw meridian flip point if any
        if self.flip_idx is not None:
            flip_x = 10 + int(float(self.flip_idx) / (N - 1) * (width - 20))
            flip_pen = Pen(Color.FromArgb(255, 69, 58), 2)
            g.DrawLine(flip_pen, flip_x, bar_y - 4, flip_x, bar_y + bar_height + 4)
            
            # Draw Meridian Flip label
            red_brush = SolidBrush(Color.FromArgb(255, 69, 58))
            g.DrawString("FLIP", text_font, red_brush, PointF(flip_x - 10, bar_y + bar_height + 5))
            
        # 4b. Draw HA +1h and +2h lines if any
        orange_brush = SolidBrush(Color.FromArgb(255, 149, 0))
        text_font_small = Font("Segoe UI", 7.0, FontStyle.Regular)
        margin_pen = Pen(Color.FromArgb(255, 149, 0), 1)
        
        if hasattr(self, 'ha_minus2h_idx') and self.ha_minus2h_idx is not None:
            ha_m2_x = 10 + int(float(self.ha_minus2h_idx) / (N - 1) * (width - 20))
            g.DrawLine(margin_pen, ha_m2_x, bar_y, ha_m2_x, bar_y + bar_height)
            g.DrawString("-2h", text_font_small, orange_brush, PointF(ha_m2_x - 6, bar_y - 12))

        if hasattr(self, 'ha_minus1h_idx') and self.ha_minus1h_idx is not None:
            ha_m1_x = 10 + int(float(self.ha_minus1h_idx) / (N - 1) * (width - 20))
            g.DrawLine(margin_pen, ha_m1_x, bar_y, ha_m1_x, bar_y + bar_height)
            g.DrawString("-1h", text_font_small, orange_brush, PointF(ha_m1_x - 6, bar_y - 12))

        if hasattr(self, 'ha_1h_idx') and self.ha_1h_idx is not None:
            ha1_x = 10 + int(float(self.ha_1h_idx) / (N - 1) * (width - 20))
            g.DrawLine(margin_pen, ha1_x, bar_y, ha1_x, bar_y + bar_height)
            g.DrawString("+1h", text_font_small, orange_brush, PointF(ha1_x - 6, bar_y - 12))
            
        if hasattr(self, 'ha_2h_idx') and self.ha_2h_idx is not None:
            ha2_x = 10 + int(float(self.ha_2h_idx) / (N - 1) * (width - 20))
            g.DrawLine(margin_pen, ha2_x, bar_y, ha2_x, bar_y + bar_height)
            g.DrawString("+2h", text_font_small, orange_brush, PointF(ha2_x - 6, bar_y - 12))
            
        # 5. Draw current telescope position indicator
        closest_idx = None
        is_tracking_now = self.tracking_active and "INSEGUIMENTO" in self.status_text.upper()
        if is_tracking_now and hasattr(self, 'last_traj_idx'):
            closest_idx = self.last_traj_idx
        else:
            closest_idx = self.get_closest_trajectory_index()
            
        if closest_idx is not None:
            current_x = 10 + int(float(closest_idx) / (N - 1) * (width - 20))
            current_x = max(10, min(width - 10, current_x))
            color_brush = Color.FromArgb(10, 132, 255) if is_tracking_now else Color.FromArgb(255, 149, 0)
            current_brush = SolidBrush(color_brush)
            g.FillEllipse(current_brush, current_x - 4, bar_y + 2, 8, 8)

    def shift_trajectory_limit(self, limit_name, direction_deg):
        if not self.trajectory_data:
            return
        trajectory = self.trajectory_data["TRAJECTORY"]
        N = len(trajectory)
        
        if limit_name == "start":
            curr_idx = self.track_start_idx
        else:
            curr_idx = self.track_end_idx
            
        import math
        step = 1 if direction_deg > 0 else -1
        target_idx = curr_idx
        
        def get_dist(idx1, idx2):
            p1 = trajectory[idx1]
            p2 = trajectory[idx2]
            r1 = math.radians(p1[1] * 15.0)
            d1 = math.radians(p1[2])
            r2 = math.radians(p2[1] * 15.0)
            d2 = math.radians(p2[2])
            
            cos_dist = math.sin(d1)*math.sin(d2) + math.cos(d1)*math.cos(d2)*math.cos(r1 - r2)
            cos_dist = max(-1.0, min(1.0, cos_dist))
            return math.degrees(math.acos(cos_dist))
            
        dist = 0.0
        while 0 <= target_idx + step < N:
            target_idx += step
            dist = get_dist(curr_idx, target_idx)
            if dist >= abs(direction_deg):
                break
                
        if limit_name == "start":
            if target_idx < self.track_end_idx:
                self.track_start_idx = target_idx
        else:
            if target_idx > self.track_start_idx:
                self.track_end_idx = target_idx
                
        # Update calibration coordinates
        self.coords_start = (trajectory[self.track_start_idx][1], trajectory[self.track_start_idx][2])
        self.coords_end = (trajectory[self.track_end_idx][1], trajectory[self.track_end_idx][2])
        
        # Calculate shifts in degrees relative to default limits
        default_start_ra = trajectory[self.default_start_idx][1] * 15.0
        default_start_dec = trajectory[self.default_start_idx][2]
        curr_start_ra = trajectory[self.track_start_idx][1] * 15.0
        curr_start_dec = trajectory[self.track_start_idx][2]
        
        def get_dist_direct(ra1, dec1, ra2, dec2):
            r1, d1 = math.radians(ra1), math.radians(dec1)
            r2, d2 = math.radians(ra2), math.radians(dec2)
            cos_d = math.sin(d1)*math.sin(d2) + math.cos(d1)*math.cos(d2)*math.cos(r1 - r2)
            cos_d = max(-1.0, min(1.0, cos_d))
            return math.degrees(math.acos(cos_d))
            
        shift_start = get_dist_direct(default_start_ra, default_start_dec, curr_start_ra, curr_start_dec)
        
        default_end_ra = trajectory[self.default_end_idx][1] * 15.0
        default_end_dec = trajectory[self.default_end_idx][2]
        curr_end_ra = trajectory[self.track_end_idx][1] * 15.0
        curr_end_dec = trajectory[self.track_end_idx][2]
        shift_end = get_dist_direct(default_end_ra, default_end_dec, curr_end_ra, curr_end_dec)
        
        sign_start = "+" if self.track_start_idx >= self.default_start_idx else "-"
        sign_end = "+" if self.track_end_idx >= self.default_end_idx else "-"
        self.lbl_shift_info.Text = "Inizio: %s%.1f° | Fine: %s%.1f°" % (sign_start, shift_start, sign_end, shift_end)
        self.pic_bar.Invalidate()
        if hasattr(self, 'pic_sky_map') and self.pic_sky_map is not None:
            self.pic_sky_map.Invalidate()
        self.update_start_altaz_label()

    def update_start_altaz_label(self):
        if self.trajectory_data:
            trajectory = self.trajectory_data["TRAJECTORY"]
            pt = trajectory[self.track_start_idx]
            self.lbl_info_start_altaz.Text = "Partenza Effettiva: Alt: %.1f° | Az: %.1f°" % (pt[3], pt[4])
        else:
            self.lbl_info_start_altaz.Text = "Partenza Effettiva: Alt: -- | Az: --"

# --- ENTRY POINT ---
if __name__ == "__main__":
    form = SharpISSFollowerForm()
    # If in SharpCap, show form modelessly so console remains free
    form.Show()
    form.Activate()
    form.Focus()
    form.BringToFront()
    # Temporarily set TopMost to force Windows to bring the form to the absolute foreground
    form.TopMost = True
    form.TopMost = False
