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
    DialogResult, MessageBox, MessageBoxButtons, MessageBoxIcon
)
from System.Drawing import Size, Point, Color, Font, FontStyle
import System.Threading as Threading

# Try to import SharpCap API
try:
    import SharpCap
except ImportError:
    SharpCap = None

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
        self.Size = Size(520, 680)
        self.BackColor = Color.FromArgb(30, 30, 30)
        self.ForeColor = Color.White
        self.Font = Font("Segoe UI", 9)
        self.FormBorderStyle = 3  # Fixed3D
        self.MaximizeBox = False
        
        # Tracking variables
        self.trajectory_filepath = ""
        self.trajectory_data = {}
        self.is_altaz = False
        self.abort_requested = False
        self.tracking_active = False
        self.last_traj_idx = 0
        self.active_thread = None
        
        # Real-time state monitored by background thread
        self.status_text = "Nessuna traiettoria caricata"
        self.countdown_text = "Tempo all'Intercettazione: --"
        self.rates_text = "Velocità Asse 0: 0.00°/s | Asse 1: 0.00°/s"
        self.error_text = "Errore di Puntamento: --"
        
        self.create_widgets()
        self.update_gui_labels()
        
        # Start GUI status updater timer
        self.timer = Threading.Timer(self.timer_tick, None, 100, 100)
        
        # Attempt to auto-connect to SharpCap mount
        self.auto_connect_mount()
        
    def create_widgets(self):
        # Configuration File & Connect Mount
        lbl = Label()
        lbl.Text = "CONFIGURAZIONE HARDWARE & TRAIETTORIA"
        lbl.Location = Point(15, 15)
        lbl.Size = Size(480, 20)
        lbl.Font = Font("Segoe UI", 9, FontStyle.Bold)
        lbl.ForeColor = Color.FromArgb(10, 132, 255)
        self.Controls.Add(lbl)
        
        self.lbl_file = Label()
        self.lbl_file.Text = "File Traiettoria: Nessuno caricato"
        self.lbl_file.Location = Point(15, 40)
        self.lbl_file.Size = Size(360, 20)
        self.lbl_file.ForeColor = Color.LightGray
        self.Controls.Add(self.lbl_file)
        
        self.btn_load = Button()
        self.btn_load.Text = "Sfoglia..."
        self.btn_load.Location = Point(385, 36)
        self.btn_load.Size = Size(105, 26)
        self.btn_load.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_load.ForeColor = Color.White
        self.btn_load.FlatStyle = 0  # Flat
        self.btn_load.Click += self.on_load_trajectory
        self.Controls.Add(self.btn_load)
        
        self.lbl_mount = Label()
        self.lbl_mount.Text = "Montatura: Disconnessa"
        self.lbl_mount.Location = Point(15, 70)
        self.lbl_mount.Size = Size(360, 20)
        self.lbl_mount.ForeColor = Color.LightGray
        self.Controls.Add(self.lbl_mount)
        
        self.btn_connect = Button()
        self.btn_connect.Text = "Connetti"
        self.btn_connect.Location = Point(385, 66)
        self.btn_connect.Size = Size(105, 26)
        self.btn_connect.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_connect.ForeColor = Color.White
        self.btn_connect.FlatStyle = 0
        self.btn_connect.Click += self.on_connect_mount
        self.Controls.Add(self.btn_connect)
        
        self.chk_altaz = CheckBox()
        self.chk_altaz.Text = "Montatura Alt/Az (Auto-rilevata)"
        self.chk_altaz.Location = Point(15, 95)
        self.chk_altaz.Size = Size(300, 20)
        self.chk_altaz.ForeColor = Color.LightGray
        self.Controls.Add(self.chk_altaz)
        
        # Target Info Panel
        self.lbl_info_title = Label()
        self.lbl_info_title.Text = "DETTAGLI PASSAGGIO ISS CARICATO"
        self.lbl_info_title.Location = Point(15, 130)
        self.lbl_info_title.Size = Size(480, 20)
        self.lbl_info_title.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.lbl_info_title.ForeColor = Color.FromArgb(10, 132, 255)
        self.Controls.Add(self.lbl_info_title)
        
        self.lbl_info_time = Label()
        self.lbl_info_time.Text = "Ora Intercettazione (Locale): --"
        self.lbl_info_time.Location = Point(15, 155)
        self.lbl_info_time.Size = Size(480, 20)
        self.Controls.Add(self.lbl_info_time)
        
        self.lbl_info_coords = Label()
        self.lbl_info_coords.Text = "Coordinate Celesti (JNow): RA: -- | Dec: --"
        self.lbl_info_coords.Location = Point(15, 175)
        self.lbl_info_coords.Size = Size(480, 20)
        self.Controls.Add(self.lbl_info_coords)
        
        self.lbl_info_maxalt = Label()
        self.lbl_info_maxalt.Text = "Altitudine / Azimuth Intercettazione: Alt: -- | Az: --"
        self.lbl_info_maxalt.Location = Point(15, 195)
        self.lbl_info_maxalt.Size = Size(480, 20)
        self.Controls.Add(self.lbl_info_maxalt)
        
        # Slew & Calibrate
        lbl_slew = Label()
        lbl_slew.Text = "1. POSIZIONAMENTO & CALIBRAZIONE"
        lbl_slew.Location = Point(15, 230)
        lbl_slew.Size = Size(480, 20)
        lbl_slew.Font = Font("Segoe UI", 9, FontStyle.Bold)
        lbl_slew.ForeColor = Color.FromArgb(10, 132, 255)
        self.Controls.Add(lbl_slew)
        
        self.btn_goto_solve = Button()
        self.btn_goto_solve.Text = "GOTO & Plate Solve (Consigliato)"
        self.btn_goto_solve.Location = Point(15, 255)
        self.btn_goto_solve.Size = Size(235, 30)
        self.btn_goto_solve.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_goto_solve.ForeColor = Color.White
        self.btn_goto_solve.FlatStyle = 0
        self.btn_goto_solve.Click += self.on_goto_solve
        self.Controls.Add(self.btn_goto_solve)
        
        self.btn_goto_only = Button()
        self.btn_goto_only.Text = "GOTO Semplice (Senza Solve)"
        self.btn_goto_only.Location = Point(260, 255)
        self.btn_goto_only.Size = Size(230, 30)
        self.btn_goto_only.BackColor = Color.FromArgb(58, 58, 60)
        self.btn_goto_only.ForeColor = Color.White
        self.btn_goto_only.FlatStyle = 0
        self.btn_goto_only.Click += self.on_goto_only
        self.Controls.Add(self.btn_goto_only)
        
        # Settings Panel
        lbl_set = Label()
        lbl_set.Text = "2. IMPOSTAZIONI CAMERA & INSEGUIMENTO"
        lbl_set.Location = Point(15, 300)
        lbl_set.Size = Size(480, 20)
        lbl_set.Font = Font("Segoe UI", 9, FontStyle.Bold)
        lbl_set.ForeColor = Color.FromArgb(10, 132, 255)
        self.Controls.Add(lbl_set)
        
        lbl_se = Label()
        lbl_se.Text = "Esposizione Stelle (ms):"
        lbl_se.Location = Point(15, 325)
        lbl_se.Size = Size(140, 20)
        self.Controls.Add(lbl_se)
        
        self.txt_star_exp = TextBox()
        self.txt_star_exp.Text = "3000"
        self.txt_star_exp.Location = Point(160, 322)
        self.txt_star_exp.Size = Size(65, 20)
        self.txt_star_exp.BackColor = Color.FromArgb(44, 44, 46)
        self.txt_star_exp.ForeColor = Color.White
        self.Controls.Add(self.txt_star_exp)
        
        lbl_sg = Label()
        lbl_sg.Text = "Gain Stelle:"
        lbl_sg.Location = Point(260, 325)
        lbl_sg.Size = Size(140, 20)
        self.Controls.Add(lbl_sg)
        
        self.txt_star_gain = TextBox()
        self.txt_star_gain.Text = "350"
        self.txt_star_gain.Location = Point(425, 322)
        self.txt_star_gain.Size = Size(65, 20)
        self.txt_star_gain.BackColor = Color.FromArgb(44, 44, 46)
        self.txt_star_gain.ForeColor = Color.White
        self.Controls.Add(self.txt_star_gain)
        
        lbl_ie = Label()
        lbl_ie.Text = "Esposizione ISS (ms):"
        lbl_ie.Location = Point(15, 355)
        lbl_ie.Size = Size(140, 20)
        self.Controls.Add(lbl_ie)
        
        self.txt_iss_exp = TextBox()
        self.txt_iss_exp.Text = "1.5"
        self.txt_iss_exp.Location = Point(160, 352)
        self.txt_iss_exp.Size = Size(65, 20)
        self.txt_iss_exp.BackColor = Color.FromArgb(44, 44, 46)
        self.txt_iss_exp.ForeColor = Color.White
        self.Controls.Add(self.txt_iss_exp)
        
        lbl_ig = Label()
        lbl_ig.Text = "Gain ISS:"
        lbl_ig.Location = Point(260, 355)
        lbl_ig.Size = Size(140, 20)
        self.Controls.Add(lbl_ig)
        
        self.txt_iss_gain = TextBox()
        self.txt_iss_gain.Text = "250"
        self.txt_iss_gain.Location = Point(425, 352)
        self.txt_iss_gain.Size = Size(65, 20)
        self.txt_iss_gain.BackColor = Color.FromArgb(44, 44, 46)
        self.txt_iss_gain.ForeColor = Color.White
        self.Controls.Add(self.txt_iss_gain)
        
        lbl_k = Label()
        lbl_k.Text = "Guadagno Prop. Kp:"
        lbl_k.Location = Point(15, 385)
        lbl_k.Size = Size(140, 20)
        self.Controls.Add(lbl_k)
        
        self.txt_kp = TextBox()
        self.txt_kp.Text = "1.0"
        self.txt_kp.Location = Point(160, 382)
        self.txt_kp.Size = Size(65, 20)
        self.txt_kp.BackColor = Color.FromArgb(44, 44, 46)
        self.txt_kp.ForeColor = Color.White
        self.Controls.Add(self.txt_kp)
        
        lbl_lt = Label()
        lbl_lt.Text = "Lead Time (sec):"
        lbl_lt.Location = Point(260, 385)
        lbl_lt.Size = Size(140, 20)
        self.Controls.Add(lbl_lt)
        
        self.txt_lead = TextBox()
        self.txt_lead.Text = "2.0"
        self.txt_lead.Location = Point(425, 382)
        self.txt_lead.Size = Size(65, 20)
        self.txt_lead.BackColor = Color.FromArgb(44, 44, 46)
        self.txt_lead.ForeColor = Color.White
        self.Controls.Add(self.txt_lead)
        
        # Control Buttons
        self.btn_arm = Button()
        self.btn_arm.Text = "ARM PER INSEGUIMENTO"
        self.btn_arm.Location = Point(15, 420)
        self.btn_arm.Size = Size(155, 38)
        self.btn_arm.BackColor = Color.FromArgb(48, 209, 88)
        self.btn_arm.ForeColor = Color.White
        self.btn_arm.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.btn_arm.FlatStyle = 0
        self.btn_arm.Click += self.on_arm_intercept
        self.Controls.Add(self.btn_arm)
        
        self.btn_sim = Button()
        self.btn_sim.Text = "SIMULA INSEGUIMENTO"
        self.btn_sim.Location = Point(180, 420)
        self.btn_sim.Size = Size(155, 38)
        self.btn_sim.BackColor = Color.FromArgb(10, 132, 255)
        self.btn_sim.ForeColor = Color.White
        self.btn_sim.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.btn_sim.FlatStyle = 0
        self.btn_sim.Click += self.on_run_simulation
        self.Controls.Add(self.btn_sim)
        
        self.btn_abort = Button()
        self.btn_abort.Text = "ABORT / ARRESTA"
        self.btn_abort.Location = Point(345, 420)
        self.btn_abort.Size = Size(145, 38)
        self.btn_abort.BackColor = Color.FromArgb(255, 69, 58)
        self.btn_abort.ForeColor = Color.White
        self.btn_abort.Font = Font("Segoe UI", 9, FontStyle.Bold)
        self.btn_abort.FlatStyle = 0
        self.btn_abort.Click += self.on_abort
        self.Controls.Add(self.btn_abort)
        
        # Live Monitor Panel
        lbl_mon = Label()
        lbl_mon.Text = "STATO IN REALE-TEMPO"
        lbl_mon.Location = Point(15, 475)
        lbl_mon.Size = Size(480, 20)
        lbl_mon.Font = Font("Segoe UI", 9, FontStyle.Bold)
        lbl_mon.ForeColor = Color.FromArgb(10, 132, 255)
        self.Controls.Add(lbl_mon)
        
        # Box container for state
        state_panel = Label()
        state_panel.Location = Point(15, 500)
        state_panel.Size = Size(475, 120)
        state_panel.BackColor = Color.FromArgb(44, 44, 46)
        self.Controls.Add(state_panel)
        
        self.lbl_state = Label()
        self.lbl_state.Location = Point(25, 510)
        self.lbl_state.Size = Size(455, 20)
        self.lbl_state.BackColor = Color.FromArgb(44, 44, 46)
        self.lbl_state.ForeColor = Color.White
        self.lbl_state.Font = Font("Segoe UI", 10, FontStyle.Bold)
        self.Controls.Add(self.lbl_state)
        self.lbl_state.BringToFront()
        
        self.lbl_countdown = Label()
        self.lbl_countdown.Location = Point(25, 532)
        self.lbl_countdown.Size = Size(455, 20)
        self.lbl_countdown.BackColor = Color.FromArgb(44, 44, 46)
        self.lbl_countdown.ForeColor = Color.FromArgb(255, 214, 10)  # Warning yellow
        self.lbl_countdown.Font = Font("Segoe UI", 10, FontStyle.Bold)
        self.Controls.Add(self.lbl_countdown)
        self.lbl_countdown.BringToFront()
        
        self.lbl_rates = Label()
        self.lbl_rates.Location = Point(25, 557)
        self.lbl_rates.Size = Size(455, 18)
        self.lbl_rates.BackColor = Color.FromArgb(44, 44, 46)
        self.lbl_rates.ForeColor = Color.LightGray
        self.Controls.Add(self.lbl_rates)
        self.lbl_rates.BringToFront()
        
        self.lbl_error = Label()
        self.lbl_error.Location = Point(25, 577)
        self.lbl_error.Size = Size(455, 18)
        self.lbl_error.BackColor = Color.FromArgb(44, 44, 46)
        self.lbl_error.ForeColor = Color.LightGray
        self.Controls.Add(self.lbl_error)
        self.lbl_error.BringToFront()

    # --- UI UPDATER TICK ---
    def timer_tick(self, state):
        try:
            # We call BeginInvoke to update GUI thread safely
            self.BeginInvoke(clr.Action(self.update_gui_labels))
        except Exception:
            pass
            
    def update_gui_labels(self):
        self.lbl_state.Text = "Stato: " + self.status_text
        self.lbl_countdown.Text = self.countdown_text
        self.lbl_rates.Text = self.rates_text
        self.lbl_error.Text = self.error_text
        
        # Check tracking status to toggle buttons
        if self.tracking_active:
            self.btn_load.Enabled = False
            self.btn_connect.Enabled = False
            self.btn_goto_solve.Enabled = False
            self.btn_goto_only.Enabled = False
            self.btn_arm.Enabled = False
            self.btn_sim.Enabled = False
        else:
            self.btn_load.Enabled = True
            self.btn_connect.Enabled = True
            has_data = len(self.trajectory_data) > 0
            self.btn_goto_solve.Enabled = has_data
            self.btn_goto_only.Enabled = has_data
            self.btn_arm.Enabled = has_data
            self.btn_sim.Enabled = has_data

    def set_state(self, status, countdown="--", rates="--", error="--"):
        self.status_text = status
        self.countdown_text = "Tempo all'Intercettazione: " + str(countdown)
        self.rates_text = rates
        self.error_text = error

    # --- HARDWARE CONNECT CORE ---
    def auto_connect_mount(self):
        if SharpCap is None:
            self.lbl_mount.Text = "Montatura: Esecuzione fuori da SharpCap"
            return
            
        mount = SharpCap.Mounts.SelectedMount
        if mount is not None and mount.Connected:
            try:
                ascom_mount = mount.AscomMount
                # Check alignment mode
                try:
                    mode = ascom_mount.AlignmentMode
                    self.is_altaz = (mode == 0)
                except Exception:
                    # Some mounts do not support alignment mode reading, check defaults
                    self.is_altaz = False
                
                self.chk_altaz.Checked = self.is_altaz
                
                # Check axis rate support
                if ascom_mount.CanMoveAxis(0) and ascom_mount.CanMoveAxis(1):
                    self.lbl_mount.Text = "Montatura: Connessa (" + ("Alt/Az" if self.is_altaz else "Equatoriale") + ")"
                    self.lbl_mount.ForeColor = Color.FromArgb(48, 209, 88)
                else:
                    self.lbl_mount.Text = "Montatura: ASCOM MoveAxis NON supportato!"
                    self.lbl_mount.ForeColor = Color.FromArgb(255, 69, 58)
                    MessageBox.Show(
                        "Attenzione: il driver ASCOM di questa montatura dichiara di non supportare "
                        "il comando MoveAxis. L'inseguimento orbitale non sarà possibile.",
                        "Supporto MoveAxis Mancante", MessageBoxButtons.OK, MessageBoxIcon.Warning
                    )
            except Exception as e:
                self.lbl_mount.Text = "Montatura: Errore: " + str(e)
                self.lbl_mount.ForeColor = Color.FromArgb(255, 69, 58)
        else:
            self.lbl_mount.Text = "Montatura: Non connessa in SharpCap"
            self.lbl_mount.ForeColor = Color.FromArgb(255, 69, 58)

    def on_connect_mount(self, sender, event):
        self.auto_connect_mount()
        if SharpCap is not None and SharpCap.Mounts.SelectedMount is not None:
            if not SharpCap.Mounts.SelectedMount.Connected:
                MessageBox.Show(
                    "Connetti prima la montatura tramite l'interfaccia di SharpCap "
                    "(Hardware -> Telescope/Mount).", 
                    "Connessione richiesta", MessageBoxButtons.OK, MessageBoxIcon.Information
                )

    # --- CAMERA CONFIG CORE ---
    def configure_camera(self, exp_ms, gain):
        if SharpCap is None or SharpCap.SelectedCamera is None:
            print("Configure camera skipped (SharpCap not running or no camera selected)")
            return True
            
        try:
            cam = SharpCap.SelectedCamera
            # Exposure setting
            exp_ctrl = getattr(cam.Controls, "Exposure", None)
            if exp_ctrl is not None:
                exp_ctrl.Value = float(exp_ms)
            else:
                # Search list
                for ctrl in cam.Controls:
                    if ctrl.Name.lower() == "exposure":
                        ctrl.Value = float(exp_ms)
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
            return True
        except Exception as e:
            print("Error configuring camera controls:", e)
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
                
                # Populate Info labels
                self.lbl_info_time.Text = "Ora Intercettazione (Locale): " + str(data["INTERCEPT_LOCAL_TIME"])
                self.lbl_info_coords.Text = "Coordinate Celesti (JNow): RA: %.4fh | Dec: %.3f°" % (data["INTERCEPT_RA"], data["INTERCEPT_DEC"])
                self.lbl_info_maxalt.Text = "Altitudine / Azimuth Intercettazione: Alt: %.1f° | Az: %.1f°" % (data["INTERCEPT_ALT"], data["INTERCEPT_AZ"])
                
                self.set_state("Traiettoria caricata con successo")
            except Exception as e:
                self.lbl_file.Text = "File: Caricamento fallito"
                self.lbl_file.ForeColor = Color.FromArgb(255, 69, 58)
                MessageBox.Show(
                    "Errore caricamento traiettoria:\n" + str(e),
                    "Errore File", MessageBoxButtons.OK, MessageBoxIcon.Error
                )

    # --- SLEW & CALIBRATE (GOTO) ROUTINES ---
    def on_goto_solve(self, sender, event):
        if not self.trajectory_data:
            return
        self.abort_requested = False
        Threading.ThreadPool.QueueUserWorkItem(self.run_goto_and_solve_thread, True)
        
    def on_goto_only(self, sender, event):
        if not self.trajectory_data:
            return
        self.abort_requested = False
        Threading.ThreadPool.QueueUserWorkItem(self.run_goto_and_solve_thread, False)

    def run_goto_and_solve_thread(self, run_solve):
        if SharpCap is None or SharpCap.Mounts.SelectedMount is None:
            self.status_text = "Errore: Montatura disconnessa"
            return
            
        mount = SharpCap.Mounts.SelectedMount
        ascom = mount.AscomMount
        
        try:
            self.tracking_active = True
            self.set_state("Puntamento in corso...")
            
            ra = self.trajectory_data["INTERCEPT_RA"]
            dec = self.trajectory_data["INTERCEPT_DEC"]
            
            # Initiate Slew
            ascom.SlewToCoordinatesAsync(ra, dec)
            
            # Wait for Slew
            while ascom.Slewing:
                Threading.Thread.Sleep(200)
                if self.abort_requested:
                    ascom.AbortSlew()
                    self.set_state("GOTO interrotto")
                    self.tracking_active = False
                    return
            
            # Double check tracking is on (MoveAxis requires it)
            try:
                if not ascom.Tracking:
                    ascom.Tracking = True
            except Exception:
                pass
                
            if run_solve:
                # Setup stars exposure
                self.set_state("Puntato. Impostazione camera per stelle...")
                star_exp = float(self.txt_star_exp.Text)
                star_gain = float(self.txt_star_gain.Text)
                self.configure_camera(star_exp, star_gain)
                
                # Sleep to let sensor clear and stabilize
                Threading.Thread.Sleep(2000)
                if self.abort_requested:
                    self.tracking_active = False
                    return
                
                self.set_state("Avvio Plate Solving & Sync...")
                # Trigger SharpCap Plate Solve
                SharpCap.Transforms.PlateSolveAndSync()
                
                # Plate solving takes a few seconds. We count down 12 seconds.
                for s in range(12, 0, -1):
                    self.set_state("Risoluzione del campo... Attendere %ds" % s)
                    Threading.Thread.Sleep(1000)
                    if self.abort_requested:
                        self.tracking_active = False
                        return
                
                self.set_state("Calibrazione eseguita. Impostazione camera per ISS...")
            else:
                self.set_state("Puntato. Impostazione camera per ISS...")
                
            # Configure ISS camera settings
            iss_exp = float(self.txt_iss_exp.Text)
            iss_gain = float(self.txt_iss_gain.Text)
            self.configure_camera(iss_exp, iss_gain)
            
            # Ready for tracking
            self.set_state("Posizionato e Pronto per l'Inseguimento")
            
        except Exception as e:
            self.set_state("Errore GOTO: " + str(e))
            print(traceback.format_exc())
        finally:
            self.tracking_active = False

    # --- ACTIVE TRACKING TIMELINE ---
    def on_arm_intercept(self, sender, event):
        if not self.trajectory_data:
            return
            
        # Check current time
        t_now = time.time()
        t_intercept = self.trajectory_data["INTERCEPT_TIME"]
        lead_time = float(self.txt_lead.Text)
        t_start = t_intercept - lead_time
        
        if t_now >= t_intercept + 20.0:
            MessageBox.Show(
                "Errore: Il passaggio della ISS è già terminato o si trova troppo avanti nel tempo.\n"
                "Usa 'SIMULA INSEGUIMENTO' per effettuare un test immediato.",
                "Passaggio Scaduto", MessageBoxButtons.OK, MessageBoxIcon.Error
            )
            return
            
        self.abort_requested = False
        self.active_thread = Threading.Thread(Threading.ThreadStart(lambda: self.tracking_worker(is_simulation=False)))
        self.active_thread.IsBackground = True
        self.active_thread.Start()

    def on_run_simulation(self, sender, event):
        if not self.trajectory_data:
            return
            
        self.abort_requested = False
        self.active_thread = Threading.Thread(Threading.ThreadStart(lambda: self.tracking_worker(is_simulation=True)))
        self.active_thread.IsBackground = True
        self.active_thread.Start()

    def on_abort(self, sender, event):
        self.abort_requested = True
        self.set_state("Interruzione manuale richiesta...")
        self.stop_hardware()

    def stop_hardware(self):
        # Stop mount
        try:
            if SharpCap is not None and SharpCap.Mounts.SelectedMount is not None:
                ascom = SharpCap.Mounts.SelectedMount.AscomMount
                ascom.MoveAxis(0, 0.0)
                ascom.MoveAxis(1, 0.0)
        except Exception as e:
            print("Error stopping mount axis rates:", e)
            
        # Stop capturing
        try:
            if SharpCap is not None and SharpCap.SelectedCamera is not None:
                SharpCap.SelectedCamera.StopCapture()
        except Exception as e:
            print("Error stopping capture:", e)

    # --- TRACKING LOOP WORKER ---
    def tracking_worker(self, is_simulation):
        if SharpCap is None or SharpCap.Mounts.SelectedMount is None:
            self.status_text = "Errore: Montatura disconnessa"
            return
            
        self.tracking_active = True
        self.last_traj_idx = 0
        ascom = SharpCap.Mounts.SelectedMount.AscomMount
        self.is_altaz = self.chk_altaz.Checked
        
        t_intercept = self.trajectory_data["INTERCEPT_TIME"]
        lead_time = float(self.txt_lead.Text)
        t_start = t_intercept - lead_time
        t_capture = t_intercept - 1.0  # Camera starts recording 1 second before intercept
        
        # Calculate simulation offset
        if is_simulation:
            # Shift timeline so that t_start occurs exactly 2 seconds from now
            sim_offset = time.time() - t_start + 2.0
            print("Simulation started. Time offset shifted by:", sim_offset)
        else:
            sim_offset = 0.0
            
        def get_simulated_time():
            return time.time() - sim_offset
            
        # Retrieve trajectory array
        trajectory = self.trajectory_data["TRAJECTORY"]
        t_end = trajectory[-1][0]
        
        kp = float(self.txt_kp.Text)
        
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
                self.set_state(
                    "IN ATTESA DI INTERCETTAZIONE" + (" (SIMULATO)" if is_simulation else ""),
                    countdown="%.1fs" % time_left
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
                
            # Main high-frequency loop (20 Hz)
            dt = 0.05
            
            while get_simulated_time() < t_end:
                if self.abort_requested:
                    self.set_state("Inseguimento Interrotto")
                    return
                    
                t_now = get_simulated_time()
                
                # Check for camera trigger (1 second before intercept)
                if t_now >= t_capture and not capture_started:
                    try:
                        self.set_state("AVVIO REGISTRAZIONE VIDEO...", countdown="%.1fs" % (t_intercept - t_now))
                        if SharpCap is not None and SharpCap.SelectedCamera is not None:
                            SharpCap.SelectedCamera.StartCapture()
                        capture_started = True
                    except Exception as e:
                        print("Error starting capture:", e)
                        capture_started = True  # don't retry repeatedly
                
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
                
                # Read current mount coordinates
                real_ra = ascom.RightAscension
                real_dec = ascom.Declination
                real_alt = ascom.Altitude
                real_az = ascom.Azimuth
                
                # Calculate position error
                if self.is_altaz:
                    err_axis_0 = angle_diff(target_az, real_az)  # degrees
                    err_axis_1 = target_alt - real_alt  # degrees
                    ff_0 = ff_az_rate
                    ff_1 = ff_alt_rate
                else:
                    err_axis_0 = angle_diff(target_ra * 15.0, real_ra * 15.0)  # degrees
                    err_axis_1 = target_dec - real_dec  # degrees
                    ff_0 = ff_ra_rate
                    ff_1 = ff_dec_rate
                    
                # Position Error in arcminutes for UI reporting
                error_magnitude_arcmin = math.sqrt(err_axis_0**2 + err_axis_1**2) * 60.0
                
                # Command rates (Proportional feedback + Feedforward)
                # Keep correction clamped to +/- 1.0 deg/s to prevent jerks
                corr_0 = kp * err_axis_0
                corr_1 = kp * err_axis_1
                
                max_corr = 1.0
                corr_0 = max(-max_corr, min(max_corr, corr_0))
                corr_1 = max(-max_corr, min(max_corr, corr_1))
                
                cmd_rate_0 = ff_0 + corr_0
                cmd_rate_1 = ff_1 + corr_1
                
                # Set axis rates
                ascom.MoveAxis(0, cmd_rate_0)
                ascom.MoveAxis(1, cmd_rate_1)
                
                # Update UI
                countdown_val = t_intercept - t_now
                countdown_str = ("+%.1fs" % abs(countdown_val)) if countdown_val < 0 else ("-%.1fs" % countdown_val)
                
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
            
        except Exception as e:
            self.set_state("Errore in Loop: " + str(e))
            print(traceback.format_exc())
        finally:
            self.stop_hardware()
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

# --- ENTRY POINT ---
if __name__ == "__main__":
    form = SharpISSFollowerForm()
    # If in SharpCap, show form modelessly so console remains free
    form.Show()
