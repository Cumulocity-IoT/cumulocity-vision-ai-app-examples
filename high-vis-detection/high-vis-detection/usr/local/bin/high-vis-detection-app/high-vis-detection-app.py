import time
import json
import os
import logging
import paho.mqtt.client as mqtt

# Define the log file path
LOG_DIR = "/var/log/tedge/vision-apps" # Or any other suitable directory
LOG_FILE = os.path.join(LOG_DIR, "high-vis-detection-app.log")

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

EXIT_THRESHOLD = 50

TRACKED_PEOPLE = []
TRACKED_VESTS = []

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
    global TRACKED_PEOPLE, TRACKED_VESTS, EXIT_CACHE, EXIT_THRESHOLD

    people = 0
    vests = 0

    people_in_pic = []
    vests_in_pic = []

    detections = data['detections']
    for detection in detections:
        if detection['tracker_id'] < 0:
            detections.remove(detection)

    for detection in detections:
        tracker_id = detection['tracker_id']
        class_id = detection['class_id']
        # Check if something entered
        # in case of person
        if class_id == 0:
            people_in_pic.append(tracker_id)
            if tracker_id not in TRACKED_PEOPLE:
                EXIT_CACHE[tracker_id] = 0
                TRACKED_PEOPLE.append(tracker_id)
                people += 1
        # in case of vest
        elif class_id == 1:
            vests_in_pic.append(tracker_id)
            if tracker_id not in TRACKED_VESTS:
                EXIT_CACHE[tracker_id] = 0
                TRACKED_VESTS.append(tracker_id)
                vests += 1

    logging.debug(f'people {people} vests {vests}')
    if people != 0 or vests != 0:
        send_measurement(client, people, vests, device_id)

    # Check if something left
    logging.debug(f't_p {TRACKED_PEOPLE}')
    logging.debug(f't_v {TRACKED_VESTS}')
    logging.debug(f'p {people_in_pic}')
    logging.debug(f'v {vests_in_pic}')
    for_deletion = []
    try:
        vanished_people = [t_people for t_people in TRACKED_PEOPLE if t_people not in people_in_pic]
        for key in vanished_people:
            EXIT_CACHE[key] += 1
        vanished_vests = [t_vests for t_vests in TRACKED_VESTS if t_vests not in vests_in_pic]
        for key in vanished_vests:
            EXIT_CACHE[key] += 1
    except KeyError:
        #sometimes might be already deleted
        logging.debug(f'key {key} already deleted')
    logging.debug(f'v_p {vanished_people}')
    logging.debug(f'v_v {vanished_vests}')
    for key, value in EXIT_CACHE.items():
        if value > EXIT_THRESHOLD:
            logging.info(f'mark for delection {key}')
            for_deletion.append(key)
    for key in for_deletion:
        del EXIT_CACHE[key]#
        if key in TRACKED_PEOPLE:
            TRACKED_PEOPLE.remove(key)
        else:
            TRACKED_VESTS.remove(key)
    logging.debug(f'exit {EXIT_CACHE}')

def send_measurement(client, people, vests, device_id):
    measurement = {
        "people": people,
        "vests": vests
    }
    client.publish(f"te/device/{device_id}///m/people_counter", json.dumps(measurement))

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
        logging.error("HighVis counter post-processor stopped.")
    except Exception as e:
        logging.error(f"An error occurred: {e}")
    finally:
        client.loop_stop() # Stop the loop
        client.disconnect()

if __name__ == "__main__":
    main()