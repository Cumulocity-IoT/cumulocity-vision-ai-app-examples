import time
import json
import os
import logging
from datetime import datetime
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

EXIT_THRESHOLD = 30

DURATION_THRESHOLD = 1.0

TRACKED_PEOPLE = {}

EXIT_CACHE = {}

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
    evaluate_state(client, data, message.topic.split('/')[1])
    
def evaluate_state(client, data, device_id):
    global TRACKED_PEOPLE, EXIT_CACHE, EXIT_THRESHOLD

    people_in_pic = []
    logging.info('exit ' + str(EXIT_CACHE))
    logging.info('tracked ' + str(TRACKED_PEOPLE))
    detections = data['detections']
    for detection in detections:
        if detection['tracker_id'] < 0:
            detections.remove(detection)
    
    if len(detections) == 0 and len(TRACKED_PEOPLE) == 0:
        return
    
    for detection in detections:
        tracker_id = detection['tracker_id']
        class_id = detection['class_id']
        # Check if a person entered
        # in case of person
        if class_id == 0:
            if tracker_id not in TRACKED_PEOPLE.keys():
                TRACKED_PEOPLE[tracker_id] = { 'enter': data['timestamp']}
            people_in_pic.append(tracker_id)
            EXIT_CACHE[tracker_id] = 0

    # Check if someone left
    for_deletion = []
    for t_people in TRACKED_PEOPLE.keys():
        if t_people not in people_in_pic:
            if EXIT_CACHE[t_people] == 0:
                TRACKED_PEOPLE[t_people]['leave'] = data['timestamp']
            EXIT_CACHE[t_people] += 1
    for key, value in EXIT_CACHE.items():
        if value > EXIT_THRESHOLD:
            send_measurement(client, TRACKED_PEOPLE[key]['enter'], TRACKED_PEOPLE[key]['leave'], device_id)
            del TRACKED_PEOPLE[key]
            for_deletion.append(key)
    for key in for_deletion:
        del EXIT_CACHE[key]

def send_measurement(client, enter, leave, device_id):
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