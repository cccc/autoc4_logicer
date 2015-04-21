#!/usr/bin/python3

"""
A MQTT <-> MPD bridge.

Runs an idling thread waiting for events for every configured MPD server and
another thread subscribed to the MQTT server, listening for commands.
"""

import logging
import sys
sys.path.append('/home/autoc4/.pyenv/versions/3.4.0/lib/python3.4/site-packages/')
from subprocess import Popen
from paho.mqtt import client as mqtt_client
from mpd import MPDClient
import mpd
#from thread import Lock
from threading import Thread
import re
import time
import socket

CHANNEL_TO_SERVER = {
    # topic_part: (mpd_server_name, mpd_server_port, mpd_topic_prefix)
    'plenar': ('eeetop', 6600, 'mpd/plenar'),
    'fnord': ('trillian', 6600, 'mpd/fnord'),
    'baellebad': ('autoc4', 6600, 'mpd/baellebad'),
}

ALLOWED_COMMANDS = {
    'next': lambda c: c.next(),
    'pause': lambda c: c.pause(1),
    'play': lambda c: c.play(),
    'prev': lambda c: c.previous(),
    #'random',
    #'repeat',
    #'single',
    #'consume',
    'shuffle': lambda c: c.shuffle(),
    'stop': lambda c: c.stop(),
    'toggle': lambda c: c.pause(),
    'update': lambda c: c.update(),
}

class MQTT_mpd_transport(Thread):
    """
    MQTT client.

    When an MPD command is received, connects to the appropriate server and
    relays the command. Mapping of mqtt command to MPD command is done with
    `ALLOWED_COMMANDS`, wich holds, for every implemented command, a (lamda)
    function. These functions get passed an MPD client instance and should
    execute the appropriate commands.

    Also the MPD idler threads will use this mqtt connection to publish their
    status updates.
    """

    def __init__(self, clientId=None, keepalive=None, willQos=0,
                 willTopic=None, willMessage=None, willRetain=False, *args, **kwargs):
        super(MQTT_mpd_transport, self).__init__(*args, **kwargs)

        if clientId is not None:
            self.clientId = clientId
        else:
            self.clientId = 'mpd-transport'

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
            for t in [
                    ('mpd/+/control', 0),
                ]:
                self.mqtt_client.subscribe(*t)

    def publishReceived(self, mosq, obj, msg):
        match = re.match(r'mpd/(\w+)/control', msg.topic)
        
        if match and match.group(1) in CHANNEL_TO_SERVER:
            command = msg.payload.decode('utf-8')
            if command in ALLOWED_COMMANDS:
                logging.debug('mpd command: {}'.format(command))
                try:
                    server, port, mqtt_prefix = CHANNEL_TO_SERVER[match.group(1)]
                    c = MPDClient()
                    c.timeout = 10
                    c.idletimeout = None
                    c.connect(server, port)
                    ALLOWED_COMMANDS[command](c)
                    c.close()
                    c.disconnect()
                except:
                    logging.error('error while sending mpd command ({server}:{port} {command})'.format(server=server, port=port, command=command))


class MPD_idler(Thread):
    """
    Connects to an MPD server and idles, waiting for events. Publishes new
    status when an event occurs.
    """

    should_stop = False

    current_song = None
    current_state = None

    def __init__(self, server_name, server_port, mqtt_topic_prefix, mqtt_thread, *args, **kwargs):
        super(MPD_idler, self).__init__(*args, **kwargs)

        self.server_name = server_name
        self.server_port = server_port
        self.mqtt_topic_prefix = mqtt_topic_prefix
        self.mqtt_thread = mqtt_thread
        self.retry_timeout = 5
    
    def request_stop(self):
        self.should_stop = True

    def run(self):
        self.client = MPDClient()
        self.client.timeout = 10
        self.client.idletimeout = None
        self.connect()
        #print(self.client.mpd_version)
        while not self.should_stop:
            try:
                logging.debug('idle_return ({server}:{port}): {ret}'.format(
                        server=self.server_name,
                        port=self.server_port,
                        ret=str(self.client.idle('mixer', 'player')))
                    )
                self.got_event()
            except (mpd.ConnectionError, TimeoutError, ConnectionResetError):
                logging.info('Connection lost ({}), reconnecting ...'.format(self.mqtt_topic_prefix))
                self.connect()
        self.client.close()
        self.client.disconnect()

    def connect(self):
        while True:
            try:
                self.client.connect(self.server_name, self.server_port)
                self.retry_timeout = 5
                logging.info('Connected to ({})'.format(self.mqtt_topic_prefix))
                self.publish_new_state()
                return
            except (ConnectionRefusedError, socket.timeout, mpd.ConnectionError, OSError):
                logging.info('Connecting failed ({}), retrying in {} ...'.format(self.mqtt_topic_prefix, self.retry_timeout))
                try:
                    self.client.disconnect() # got ConnectionError("Already connected") once...
                except mpd.ConnectionError:
                    pass
                time.sleep(self.retry_timeout)
                if self.retry_timeout < 3600: # max 1 hour
                    self.retry_timeout *= 2

    def got_event(self):
        self.publish_new_state()

    def publish_new_state(self):
        state = self.client.status()['state']
        song_obj = { 'artist': 'unknown', 'title': 'unknown', 'album': 'unknown', 'file': '' } # set default values
        song_obj.update(self.client.currentsong())
        if song_obj['artist'] == song_obj['title'] == song_obj['album'] == 'unknown':
            song = song_obj['file']
        else:
            song = '{artist} - {album} - {title}'.format(**song_obj)
        song = song.encode('utf-8') # ARGH!!!!!!!!!!!!!!!!!!!!!!! Isn't this python3?
        if self.current_song != song:
            self.current_song = song
            self.mqtt_thread.mqtt_client.publish(self.mqtt_topic_prefix + '/song', song, retain=True, qos=0)
            #with publish_lock:
            #    publish_queue.append((self.mqtt_topic_prefix + '/song', song))
        if self.current_state != state:
            self.current_state = state
            self.mqtt_thread.mqtt_client.publish(self.mqtt_topic_prefix + '/state', state, retain=True, qos=0)


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

    logging.info('starting mqtt-mpd transport')
    mqtt_thread = MQTT_mpd_transport()
    mqtt_thread.start()
    mpd_threads = []

    for channel, (server, port, mqtt_prefix) in CHANNEL_TO_SERVER.items():
        logging.info('starting mpd idler for {server}:{port}'.format(server=server, port=port))
        t = MPD_idler(server, port, mqtt_prefix, mqtt_thread)
        t.start()
        mpd_threads.append(t)

    mqtt_thread.join()
    logging.info('mqtt-mpd transport joined')

    for t in mpd_threads:
        t.join()
        logging.info('mpd idler for {server}:{port} joined'.format(server=t.server_name, port=t.server_port))

    logging.info('stopping')


if __name__ == '__main__':
    main()


# example mpd library output - "the reference" :/
# In [5]: c.status()
# Out[5]: 
# {'audio': '44100:24:2',
#  'nextsongid': '47',
#  'mixrampdb': '0.000000',
#  'elapsed': '111.282',
#  'single': '0',
#  'bitrate': '320',
#  'random': '1',
#  'state': 'play',
#  'songid': '46',
#  'volume': '35',
#  'nextsong': '1',
#  'mixrampdelay': 'nan',
#  'repeat': '1',
#  'time': '111:3614',
#  'playlistlength': '2',
#  'xfade': '0',
#  'playlist': '97',
#  'consume': '0',
#  'song': '0'}
# 
# In [6]: c.currentsong()
# Out[6]: 
# {'artist': 'Ostbahnhof',
#  'album': 'Ostbahnhof / Techno Mix',
#  'pos': '0',
#  'id': '46',
#  'time': '3614',
#  'last-modified': '2013-05-09T18:32:33Z',
#  'title': 'Vierundzwanzig',
#  'composer': 'Ostbahnhof',
#  'genre': 'Podcast',
#  'file': 'Ostbahnhof _ Techno Mix/ostbahnhof_2011-11-11T22_00_00-08_00.mp3'}


# vim:set sw=4 sts=4 et ts=4 autoindent:
