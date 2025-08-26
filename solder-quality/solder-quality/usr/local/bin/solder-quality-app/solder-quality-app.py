import time
import json
import os
import logging
import paho.mqtt.client as mqtt

# Define the log file path
LOG_DIR = "/var/log/tedge/post-processor" # Or any other suitable directory
LOG_FILE = os.path.join(LOG_DIR, "solder-quality-app.log")

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
DEVICE_ID = "machine_1"
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
SCORE_THRESHOLD = 0.5

CURRENT_STATE = None
COUNTER = 0
STATE_THRESHOLD = 10

IDENTIFIED_STATE = "BOARD"

def on_connect(client, userdata, flags, rc):
    """Callback function for when the MQTT client connects."""
    if rc == 0:
        logging.info("Connected to MQTT broker")
        client.subscribe("imx500/+/classification/solder")
    else:
        logging.error(f"Connection to MQTT broker failed with code {rc}")

def on_message(client, userdata, message):
    """Callback function for when a message is received via MQTT."""
    data = json.loads(message.payload.decode())
    evaluate_state(client, data)

def state_label(state):
    if state == "BAD":
        return state
    elif state == "GOOD":
        return state
    else:
        return "BOARD"
    
def evaluate_state(client, data):
    global IDENTIFIED_STATE, COUNTER, CURRENT_STATE
    classifications = []
    for item in data['detections']:
        classification = {}
        if "label" in item.keys():
            classification["label"] = item["label"]
        else:
            classification["label"] = item["idx"]
        classification["score"] = item["confidence"]
        classifications.append(classification)
    classifications = sorted(classifications, key=lambda obj: obj["score"], reverse=True)
    if len(classifications) == 0:
        logging.info("No inference")
        return
    logging.debug(classifications[0])
    if classifications[0]["score"] < SCORE_THRESHOLD:
        # ignore
        return
    current_state = state_label(classifications[0]["label"])
    if current_state == CURRENT_STATE and COUNTER != STATE_THRESHOLD:
        # still in state
        COUNTER += 1
        #print(f"same state: {current_state}")
        return
    elif current_state != CURRENT_STATE:
        # change in state
        CURRENT_STATE = current_state
        COUNTER = 0
        #print(f"reset state: {current_state}")
        return
    elif current_state == CURRENT_STATE and current_state != IDENTIFIED_STATE and COUNTER == STATE_THRESHOLD:
        # identified a state
        COUNTER += 1
        logging.info(f"New state: {current_state}")
        if IDENTIFIED_STATE == "BOARD" and (current_state == "GOOD" or current_state == "BAD"):
            IDENTIFIED_STATE = current_state
        elif current_state == "BOARD" and (IDENTIFIED_STATE == "GOOD" or IDENTIFIED_STATE == "BAD"):
            IDENTIFIED_STATE = current_state
        else:
            logging.warn("Incorrect state change")
            return
        logging.info(f"Identified state: {IDENTIFIED_STATE}")
        if IDENTIFIED_STATE == "GOOD" or IDENTIFIED_STATE == "BAD":
            send_event(client, IDENTIFIED_STATE)

def send_event(client, board_state):
    event = {
        "text": f"Board produced. Quality: {board_state}",
        "quality": board_state
    }
    client.publish(f"te/device/{DEVICE_ID}///e/production_event_{board_state}", json.dumps(event))

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
        logging.error("\Solder post-processor stopped.")
    except Exception as e:
        logging.error(f"An error occurred: {e}")
    finally:
        client.loop_stop() # Stop the loop
        client.disconnect()

if __name__ == "__main__":
    main()