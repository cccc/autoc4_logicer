#!/usr/bin/python3

"""
For manual MQTT testing.

Usage:
    python -i mqtt-test.py
"""

import sys
sys.path.append('/home/autoc4/.pyenv/versions/3.4.0/lib/python3.4/site-packages/')
from paho.mqtt import client as mqtt_client

def pr(mosq, obj, msg):
 print(msg.topic, repr(msg.payload))

mqtt_client = mqtt_client.Client("testid")
mqtt_client.on_message = pr
mqtt_client.connect('127.0.0.1', 1883, 6000)
#mqtt_client.subscribe('heartbeat/#', 2)
#mqtt_client.publish('heartbeat/test', b'', retain=True)
#mqtt_client.loop_forever()

#mqtt_client.subscribe('dmx/fnord/#', 2)
#mqtt_client.loop_forever()

print("Connected client in `mqtt_client`")
