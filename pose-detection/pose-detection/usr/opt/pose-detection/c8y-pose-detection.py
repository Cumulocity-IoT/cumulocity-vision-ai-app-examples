import time
import json
import numpy as np

import paho.mqtt.client as mqtt
import threading

# Configuration
DEVICE_ID = "sony_imx500"
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
mqtt_client: mqtt.Client = None
ALARM_TYPE = 'person_down'
MIN_FRAMES = 30
persons =  {}

def _pt(kp, idx, conf_th=0.2):
    """Return (x,y) if keypoint idx has sufficient confidence, else (nan, nan)."""
    if idx >= kp.shape[0]:
        return np.nan, np.nan
    x, y, c = kp[idx]
    return (x, y) if c >= conf_th else (np.nan, np.nan)

def _avg_point(p1, p2):
    x1, y1 = p1; x2, y2 = p2
    return (np.nanmean([x1, x2]), np.nanmean([y1, y2]))

def classify_pose(kp, conf_th=0.2):
    """
    Heuristic classification: 'Lying', 'Sitting', 'Standing', 'Walking/Other'
    Uses bbox aspect ratio + relative vertical distances. Works per-frame (no tracking needed).
    """
    # Mid joints (averaged L/R when available)
    sh = _avg_point(_pt(kp, 5, conf_th), _pt(kp, 6, conf_th))   # shoulders mid
    hip = _avg_point(_pt(kp, 11, conf_th), _pt(kp, 12, conf_th))# hips mid
    knee = _avg_point(_pt(kp, 13, conf_th), _pt(kp, 14, conf_th))# knees mid
    ank = _avg_point(_pt(kp, 15, conf_th), _pt(kp, 16, conf_th))# ankles mid

    xs = kp[:,0]; ys = kp[:,1]; cs = kp[:,2]
    valid = cs >= conf_th
    if valid.sum() < 4:
        return "Unknown"

    # Bounding box over confident keypoints
    x_min, x_max = np.nanmin(xs[valid]), np.nanmax(xs[valid])
    y_min, y_max = np.nanmin(ys[valid]), np.nanmax(ys[valid])
    bw = max(.0001, x_max - x_min)
    bh = max(.0001, y_max - y_min)
    aspect = bw / bh  # horizontal if >>1

    # Vertical distances (ignore nan safely)
    def _dy(p_top, p_bot):
        return 0.0 if (np.isnan(p_top[1]) or np.isnan(p_bot[1])) else (p_bot[1] - p_top[1])

    sh_hip = _dy(sh, hip)
    hip_knee = _dy(hip, knee)
    knee_ank = _dy(knee, ank)
    sh_ank  = _dy(sh, ank)

    # Normalize by overall body height (shoulder→ankle), fallback to bbox height
    ref_h = sh_ank if sh_ank > 1 else bh
    r_sh_hip  = sh_hip / ref_h
    r_hip_knee= hip_knee / ref_h

    #print(f'a: {aspect}, r_sh_hip: {r_sh_hip}, r_hip_knee: {r_hip_knee}')
    # Heuristics (tune thresholds as needed)
    if aspect > 1.0 and r_sh_hip < 0.4:
        return "Lying"
    if r_hip_knee < 0.25 and r_sh_hip >= 0.4:
        return "Sitting"

    
    # "Walking" proxy: ankles spread wide relative to bbox width
    lx, _ = _pt(kp, 15, conf_th); rx, _ = _pt(kp, 16, conf_th)
    if not np.isnan(lx) and not np.isnan(rx):
        ankle_sep = abs(lx - rx) / bw
        if ankle_sep > 0.30:  # feet apart → likely stride
            return "Walking/Other"

    return "Standing"

def on_connect(client, userdata, flags, rc):
    global mqtt_client
    """Callback function for when the MQTT client connects."""
    if rc == 0:
        print("Connected to MQTT broker")
        mqtt_client = client
        client.subscribe(f"imx500/{DEVICE_ID}/detection/#")
    else:
        print(f"Connection to MQTT broker failed with code {rc}")

def on_message(client, userdata, message):
    """Callback function for when a message is received via MQTT."""
    data = json.loads(message.payload.decode())
    evaluate_state(client, data)

def check_person_on_floor(keypoints, tracker_id, frame_id):
    global persons
    pose = classify_pose(keypoints)
    print(f'{tracker_id}@{frame_id}: {pose}',flush=True) 
    if tracker_id not in persons:
        persons[tracker_id] = (pose, frame_id, False)
    else:
        prev_pose, prev_frame, alarm_sent = persons[tracker_id]
        
        if prev_pose != pose:
            # Pose changed - reset tracking
            persons[tracker_id] = (pose, frame_id, False)
        elif pose == 'Lying' and not alarm_sent and frame_id > prev_frame + MIN_FRAMES:
            # Person lying for MIN_FRAMES and no alarm sent yet
            persons[tracker_id] = (pose, prev_frame, True)  # Mark alarm as sent
            return tracker_id, True
    
    return None, False

def evaluate_state(client, data):
    detections = data['detections']
    frame_id = data['frame_id']
    if len(detections) > 0:
        
        for detection in detections:
            keypoints = np.array([[kp[1], kp[2], kp[3]] for kp in detection.get('keypoints', [])])
            tracker_id = detection.get('tracker_id')
            if tracker_id < 0:
                return
            (alarm_tracker_id, need_raise_event) = check_person_on_floor(keypoints, tracker_id, frame_id)
            if need_raise_event:
                alarm = {
                    "text": "Person on the ground",
                    "severity": "major",
                    "time": time.time()
                }
                client.publish(f"te/device/{DEVICE_ID}///a/{ALARM_TYPE}", json.dumps(alarm))

def main():
    """Main loop to generate and send measurements via MQTT."""
    client = mqtt.Client("object-counter")
    client.on_connect = on_connect

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)  # Connect to the broker
        client.on_message = on_message
        client.loop_start() # Start the loop

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("customer application stopped.")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        client.loop_stop() # Stop the loop
        client.disconnect()

if __name__ == "__main__":
    main()
