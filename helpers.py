import argparse
import logging
from systemd.journal import JournalHandler
import threading
from paho.mqtt import client as mqtt_client


class MQTT_Client(threading.Thread):

    heartbeat_topic_prefix = 'heartbeat/'
    subscribe_topics = []

    def __init__(self, clientId=None, mqtt_host='127.0.0.1', mqtt_port=1883, keepalive=60, heartbeat=False, *args, **kwargs):
        super(MQTT_Client, self).__init__(*args, **kwargs)

        self.clientId = clientId
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.keepalive = keepalive

        self.heartbeat = heartbeat
        self.heartbeat_topic = self.heartbeat_topic_prefix + self.clientId

        if heartbeat:
            self.willQos = 2
            self.willTopic = self.heartbeat_topic
            self.willMessage = b'\x00'
            self.willRetain = True
        else:
            self.willQos = None
            self.willTopic = None
            self.willMessage = None
            self.willRetain = None

        self.mqtt_client = None

        #self.connection_established = threading.Event()
        self.connection_established = False

    def run(self):

        try:
            self.main_loop()

        except:
            logging.exception('MQTT Client Thread exception, exiting.')

    def main_loop(self):

        self.mqtt_client = mqtt_client.Client(self.clientId)

        self.mqtt_client.on_message = self.on_message
        self.mqtt_client.on_connect = self.on_connect
        #self.mqtt_client.on_publish = on_publish
        #self.mqtt_client.on_subscribe = self.on_subscribe

        if self.willTopic is not None:
            self.mqtt_client.will_set(self.willTopic, bytearray(self.willMessage), self.willQos, self.willRetain)

        # Uncomment to enable debug messages
        #self.mqtt_client.on_log = on_log

        logging.info('connecting')
        self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, self.keepalive)

        logging.info('looping')
        self.mqtt_client.loop_forever()

        logging.info('leaving program loop')

    def on_connect(self, client, userdata, flags, rc):

        try:
            if rc != 0:
                logging.info('could not connect, bad return code')

            else:
                logging.info('connected, subscribing')
                if self.subscribe_topics:
                    self.mqtt_client.subscribe(self.subscribe_topics)

                if self.heartbeat:
                    logging.info('sending heartbeat')
                    self.mqtt_client.publish(self.heartbeat_topic, b'\x01', retain=True)

                self.connection_established = True

        except Exception as e:
            logging.exception(e)
            raise

    def on_message(self, client, userdata, msg):
        pass


def get_default_parser():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--logging-type', default='stdout', choices=['stdout', 'file', 'journald'])
    parser.add_argument('--logfile', default='/var/log/mqtt-mpd-transport.log', help='Only used for logging-type=file')
    parser.add_argument('--loglevel', default='debug', help='Standard python logging levels error,warning,info,debug')
    return parser


def configure_logging(logging_type, loglevel, logfile=None):
    # assuming loglevel is bound to the string value obtained from the
    # command line argument. Convert to upper case to allow the user to
    # specify --log=DEBUG or --log=debug

    numeric_level = getattr(logging, loglevel.upper(), None)

    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % loglevel)

    if logging_type == 'stdout':
        logging.basicConfig(
                format='%(asctime)s [%(levelname)s]: %(message)s',
                level=numeric_level
            )
    elif logging_type == 'file':
        assert logfile is not None
        logging.basicConfig(
                filename=logfile,
                format='%(asctime)s [%(levelname)s]: %(message)s',
                level=numeric_level
            )
    elif logging_type == 'journald':
        logging.basicConfig(
                handlers=[JournalHandler()],
                format='%(message)s',
                level=numeric_level
            )
    else:
        assert False
