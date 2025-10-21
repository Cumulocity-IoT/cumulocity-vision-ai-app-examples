import time
import json
import numpy as np
from collections import deque

import paho.mqtt.client as mqtt

# Configuration
DEVICE_ID = "ai_camera"
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
mqtt_client: mqtt.Client = None
ALARM_TYPE = 'person_down'
EVENT_TYPE = 'pose_change'
BUFFER_SIZE = 30  # Number of frames to keep in history
POSE_THRESHOLD = 0.8  # 80% of frames must be the pose to trigger any action
INACTIVE_THRESHOLD = 100  # Remove person from tracking after this many frames of inactivity
persons =  {}  # Will store: {tracker_id: {'buffer': deque, 'event_sent': str, 'last_frame': int}}

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
    """
    Check if a person should trigger a lying alarm based on pose history.
    Uses a sliding window buffer: if 80% of the last BUFFER_SIZE frames are "Lying", raise alarm.
    """
    global persons
    pose = classify_pose(keypoints)
    print(f'{tracker_id}@{frame_id}: {pose}', flush=True)

    # Initialize person tracking if new
    if tracker_id not in persons:
        persons[tracker_id] = {
            'buffer': deque(maxlen=BUFFER_SIZE),
            'event_sent': None,
            'last_frame': frame_id
        }

    person_data = persons[tracker_id]
    person_data['last_frame'] = frame_id

    # Add current pose to buffer (automatically removes oldest if buffer is full)
    person_data['buffer'].append(pose)

    # Calculate percentage of current pose in the buffer
    if len(person_data['buffer']) >= BUFFER_SIZE:
        pose_count = sum(1 for p in person_data['buffer'] if p == pose)
        pose_percentage = pose_count / len(person_data['buffer'])
        # Trigger alarm if 80% or more frames are "Lying" and alarm hasn't been sent yet
        if pose_percentage >= POSE_THRESHOLD and person_data['event_sent'] != pose:
            person_data['event_sent'] = pose
            print(f'EVENT: Person {tracker_id} detected {pose} in {pose_percentage*100:.1f}% of last {BUFFER_SIZE} frames', flush=True)
            return tracker_id, True, pose

    return tracker_id, False, None

def cleanup_inactive_persons(current_frame_id):
    """Remove persons who haven't been detected in INACTIVE_THRESHOLD frames."""
    global persons
    inactive_ids = [
        tracker_id for tracker_id, data in persons.items()
        if current_frame_id - data['last_frame'] > INACTIVE_THRESHOLD
    ]
    for tracker_id in inactive_ids:
        print(f'CLEANUP: Removing inactive person {tracker_id}', flush=True)
        del persons[tracker_id]

def evaluate_state(client, data):
    detections = data['detections']
    frame_id = data['frame_id']

    # Clean up inactive persons periodically
    cleanup_inactive_persons(frame_id)

    if len(detections) > 0:
        for detection in detections:
            keypoints = np.array([[kp[1], kp[2], kp[3]] for kp in detection.get('keypoints', [])])
            tracker_id = detection.get('tracker_id')
            if tracker_id < 0:
                return
            (alarm_tracker_id, need_raise_event, pose) = check_person_on_floor(keypoints, tracker_id, frame_id)
            if need_raise_event:
                if pose ==  'Lying':
                    alarm = {
                        "text": f"Person {alarm_tracker_id} on the ground",
                        "severity": "major",
                        "time": time.time()
                    }
                    client.publish(f"te/device/{DEVICE_ID}///a/{ALARM_TYPE}", json.dumps(alarm))
                else:
                    event = {
                        "text": f"Person {alarm_tracker_id} changed pose to {pose}",
                        "time": time.time()
                    }
                    client.publish(f"te/device/{DEVICE_ID}///e/{EVENT_TYPE}", json.dumps(event))


def main():
    """Main loop to generate and send measurements via MQTT."""
    client = mqtt.Client("pose-detection")
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
