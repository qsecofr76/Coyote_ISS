import time
import sys
import math
import __main__

# Force remove SharpCap module from sys.modules
if 'SharpCap' in sys.modules:
    del sys.modules['SharpCap']

def run_test(frequency_hz=5.0):
    print(f"=== SHARPCAP + ASCOM TEST AT {frequency_hz} HZ ===")
    
    sc = getattr(__main__, 'SharpCap', None)
    if sc is None:
        try: sc = SharpCap
        except NameError:
            print("[ERRORE] Esegui questo script INSIDE SharpCap!")
            return
            
    camera = sc.SelectedCamera
    if camera is None:
        print("[ERRORE] Seleziona prima una fotocamera.")
        return
        
    mount = sc.Mounts.SelectedMount
    if mount is None or mount.AscomMount is None:
        print("[ERRORE] Connetti prima la montatura in SharpCap.")
        return
    ascom = mount.AscomMount
    
    # Configure camera to RAW8, 10ms
    for ctrl in camera.Controls:
        name = ctrl.Name.lower()
        if "colour space" in name or "colourspace" in name or "output format" in name:
            try:
                allowed = list(ctrl.AvailableValues)
                for val in ["RAW8", "Mono8", "RGB8"]:
                    if val in allowed:
                        ctrl.Value = val
                        break
            except Exception: pass
            
    exposure_seconds = 0.010
    exp_ctrl = getattr(camera.Controls, "Exposure", None)
    if exp_ctrl is not None:
        exp_ctrl.Value = exposure_seconds
    else:
        for ctrl in camera.Controls:
            if ctrl.Name.lower() == "exposure":
                ctrl.Value = exposure_seconds
                break
                
    print("Camera configurata per RAW8, 10ms.")
    
    try:
        if not ascom.Tracking:
            ascom.Tracking = True
    except Exception: pass
    
    print("Avvio cattura di 20 secondi...")
    camera.PrepareToCapture()
    camera.RunCapture()
    
    t_start = time.time()
    duration = 20.0
    dt = 1.0 / frequency_hz
    
    print(f"Avvio loop comandi a {frequency_hz} Hz (intervallo {dt*1000:.0f}ms)...")
    
    last_rate = None
    call_count = 0
    
    while time.time() - t_start < duration:
        t_elapsed = time.time() - t_start
        
        # Calculate target rate (sine wave with 10s period: 5s forward, 5s backward)
        target_rate = 1.0 * math.sin(2.0 * math.pi * t_elapsed / 10.0)
        
        # Threshold: only write if rate changed by more than 0.1 deg/s
        if last_rate is None or abs(target_rate - last_rate) >= 0.1:
            try:
                ascom.MoveAxis(0, target_rate)
                last_rate = target_rate
                call_count += 1
            except Exception as ex:
                print(f"Errore MoveAxis: {ex}")
                break
                
        time.sleep(dt)
        
    print("Stop montatura...")
    try:
        ascom.MoveAxis(0, 0.0)
    except Exception: pass
    
    print("Arresto registrazione...")
    camera.StopCapture()
    print(f"Test concluso. Chiamate COM totali: {call_count}")
    print("=== FINE TEST ===")

# Eseguiamo il test a 5 Hz
run_test(5.0)
