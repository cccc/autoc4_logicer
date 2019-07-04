#!/usr/bin/python3
import logging
from threading import Thread
from paho.mqtt import client as mqtt_client
import time

from flask import Flask, jsonify
app = Flask(__name__)

class MQTT_bridge(Thread):
    def __init__(self, clientId=None, keepalive=None, willQos=0,
                 willTopic=None, willMessage=None, willRetain=False, *args, **kwargs):
        super(MQTT_bridge, self).__init__(*args, **kwargs)

        if clientId is not None:
            self.clientId = clientId
        else:
            self.clientId = 'webserver'

        if keepalive is not None:
            self.keepalive = keepalive
        else:
            self.keepalive = 60

        self.willQos = willQos
        self.willTopic = willTopic
        self.willMessage = willMessage
        self.willRetain = willRetain

    def run(self):
        self.mqtt_client = mqtt_client.Client(self.clientId)
        self.mqtt_client.on_message = self.publishReceived
        self.mqtt_client.on_connect = self.on_connect
        #self.mqtt_client.on_publish = on_publish
        #self.mqtt_client.on_subscribe = self.on_subscribe
        # Uncomment to enable debug messages
        #self.mqtt_client.on_log = on_log
        logging.info('connecting')
        self.mqtt_client.connect('127.0.0.1', 1883, self.keepalive)
        self.mqtt_client.loop_forever()
        logging.info('leaving program loop')

    def on_connect(self, mosq, obj, rc):
        if rc != 0:
            logging.info('could not connect, bad return code')
        else:
            logging.info('connected, subscribing')
            self.mqtt_client.subscribe('test', 0)

    def publishReceived(self, mosq, obj, msg):
        print(msg)
        d['test'] = msg

d = {
        'api': '0.13,',
        'space': 'CCC Cologne',
        'logo': 'http://w8n.koeln.ccc.de/media/images/hexogen-platine.svg',
        'url': 'http://koeln.ccc.de/',
        'ext_ccc': "erfa",
        'location': {
                'address': 'Chaos Computer Club Cologne (c4) e.V., Heliosstr. 6a, 50825 Koeln, Germany', #XXX unicode
                'lat': 50.9504142,
                'lon': -6.9129647,
            },
        'state': {
                'open': False,
                'lastchange': 0,
#                'icon': {'open':'url','closed':'url'},
            },
        'contact': {
                'irc': 'irc://freenode.org/#cccc',
                'email': 'mail@koeln.ccc.de',
                'twitter': '@ccc_koeln',
                'phone': '+49 221-49 24 119',
            },
        'issue_report_channels': ['twitter'], #XXX
        'feeds': {
#                'blog': { 'type': '', 'url': '' },
#                'wiki': { 'type': '', 'url': '' },
#                'calendar': { 'type': '', 'url': '' },
            },
        'projects': [
                'http://github.com/cccc',
            ],
    }

@app.route("/")
def hello():
    return jsonify(d)


def set_log_level(loglevel):
    # assuming loglevel is bound to the string value obtained from the
    # command line argument. Convert to upper case to allow the user to
    # specify --log=DEBUG or --log=debug
    numeric_level = getattr(logging, loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % loglevel)
    logging.basicConfig(filename='/var/log/mqtt-mpd-transport.log', format='%(asctime)s [%(levelname)s]: %(message)s', level=numeric_level)
    #logging.basicConfig(format='%(asctime)s [%(levelname)s]: %(message)s', level=numeric_level)

def main():
    set_log_level('DEBUG')
    logging.info('starting')

    logging.info('starting mqtt thread')
    mqtt_thread = MQTT_bridge()
    mqtt_thread.start()

    # wait for mqtt thread to start, connect, ...
    time.sleep(1)

    # start flask app
    app.run(debug=True, host='0.0.0.0')

    mqtt_thread.join()
    logging.info('mqtt-mpd transport joined')

    logging.info('stopping')


if __name__ == '__main__':
    main()
