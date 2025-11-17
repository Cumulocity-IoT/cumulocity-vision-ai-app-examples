import time
import json
import os
import logging
from datetime import datetime
from threading import Lock
import paho.mqtt.client as mqtt

# Define the log file path
LOG_DIR = "/var/log/tedge/post-processor" # Or any other suitable directory
LOG_FILE = os.path.join(LOG_DIR, "time-in-fov-processor.log")

# Ensure the log directory exists
os.makedirs(LOG_DIR, exist_ok=True)

# Configure the logging
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,  # Set the minimum level of messages to log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Configuration
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

PERSON_CLASS = 0

EXIT_THRESHOLD = 30

DURATION_THRESHOLD = 1.0

TRACKED_PEOPLE = {}

previous_count = 0

lock = Lock()

def on_connect(client, userdata, flags, rc):
    """Callback function for when the MQTT client connects."""
    if rc == 0:
        logging.info("Connected to MQTT broker")
        client.subscribe("imx500/+/detection/highvis")
    else:
        logging.error(f"Connection to MQTT broker failed with code {rc}")

def on_message(client, userdata, message):
    """Callback function for when a message is received via MQTT."""
    data = json.loads(message.payload.decode())
    parts = message.topic.split("/")
    device_id = parts[1] if len(parts) > 1 else "unknown"

    with lock:
        evaluate_state(client, data, device_id)
    
def evaluate_state(client, data, device_id):
    global TRACKED_PEOPLE, EXIT_THRESHOLD, previous_count

    logging.info('tracked ' + str(TRACKED_PEOPLE))

    detections = data['detections']
    detected_people = [d for d in detections if d.get('class_id') == PERSON_CLASS]
    tracker_ids = [d.get("tracker_id") for d in detected_people if isinstance(d.get("tracker_id"), int) and d.get("tracker_id") >= 0]

    if len(tracker_ids) == 0 and len(TRACKED_PEOPLE) == 0:
        return

    # Check for persons who entered
    for tracker_id in tracker_ids:
        if tracker_id not in TRACKED_PEOPLE.keys():
            TRACKED_PEOPLE[tracker_id] = { 'enter': data['timestamp'] }
        TRACKED_PEOPLE[tracker_id]['timeout'] = 0

    # Check who left and report it
    for_deletion = []
    for tracker_id in TRACKED_PEOPLE.keys():
        if tracker_id not in tracker_ids:
            if TRACKED_PEOPLE[tracker_id]['timeout'] == 0:
                TRACKED_PEOPLE[tracker_id]['leave'] = data['timestamp']
            TRACKED_PEOPLE[tracker_id]['timeout'] += 1
    for tracker_id, person in TRACKED_PEOPLE.items():
        if person['timeout'] > EXIT_THRESHOLD:
            publish_duration(client, person['enter'], person['leave'], device_id)
            for_deletion.append(tracker_id)
    for tracker_id in for_deletion:
        del TRACKED_PEOPLE[tracker_id]

    # Report counted people (if changed)
    count = len(TRACKED_PEOPLE)
    if count != previous_count:
            previous_count = count
            publish_count(client, device_id, count, data.get("timestamp"))

def publish_duration(client, enter, leave, device_id):
    dt_enter = datetime.fromisoformat(enter)
    dt_leave = datetime.fromisoformat(leave)
    duration = round(dt_leave.timestamp() - dt_enter.timestamp(), 3)
    if duration < DURATION_THRESHOLD:
        logging.info(f'Only {duration}s. Do not report')
        return
    measurement = {
        "duration": duration
    }
    client.publish(f"te/device/{device_id}///m/duration", json.dumps(measurement))

def publish_count(client, device_id: str, count: int, ts: str | None):
    measurement = {
        "count": int(count)
    }
    client.publish(f"te/device/{device_id}///m/people_count", json.dumps(measurement))

def main():
    """Main loop to generate and send measurements via MQTT."""
    client = mqtt.Client()
    client.on_connect = on_connect

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)  # Connect to the broker
        client.on_message = on_message
        client.loop_start() # Start the loop

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logging.error("Duration post-processor stopped.")
    except Exception as e:
        logging.error(f"An error occurred: {e}")
    finally:
        client.loop_stop() # Stop the loop
        client.disconnect()

if __name__ == "__main__":
    main()