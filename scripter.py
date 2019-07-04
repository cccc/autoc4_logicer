import logging
import sys
sys.path.append('/home/autoc4/.pyenv/versions/3.4.0/lib/python3.4/site-packages/')
from paho.mqtt import client as mqtt_client
from threading import Thread
import re
import time
import socket
import random

channel2lock = {
    'dmx/plenar/vorne1': ['dmx/plenar/master'],
    # ...
}

from logicer import MQTTLogicer
channel_whitelist = MQTTLogicer.alle_lichter + MQTTLogicer.dmx_channels # + ['dmx/plenar/master']


# do loop? then be able to set call frequency
# or threads with manual sleep's?
class Script(Thread):
    name = None

    #last_values = None
    #unlocked_channels = None

    def __init__(self, mqtt_client, *args, **kwargs):
        super(Script, self).__init__(*args, **kwargs)

        self.mqtt_client = mqtt_client
        self.unlocked_channels = set()
        self.last_values = {}

    def run(self):
        self.on_starting()
        while True:
            self.loop()
            time.sleep(0.01)

    def lock_channel(self, channel):
        if channel in channel2lock:
            for c in channel2lock[channel]:
                self.lock_channel(c)

        if channel in self.unlocked_channels:
            self.unlocked_channels.remove(channel)

    def unlock_channel(self, channel):
        self.unlocked_channels.add(channel)

    def publish(self, channel, payload):
        if not channel in channel_whitelist:
            raise Exception('channel not allowed: ' + channel)
        if not channel in self.unlocked_channels:
            #print("channel locked: " + channel)
            return
        if channel.startswith('dmx'):
            while len(payload) in (4,7,8):
                payload += b'\x00'
        self.mqtt_client.publish(channel, payload)

    # overwrite these:

    def on_starting(self):
        pass
    def on_stopping(self):
        pass
    def on_channel_locked(self, channel):
        pass
    # a publish in `script/id`
    def on_message(self, payload):
        pass
    def loop(self):
        pass

def interpolate(v1,v2,t,max_t):
    if t >= max_t:
        return v2
    return t/max_t * v2 + (1.-t/max_t) * v1

class Fader():
    last_color = (0,0,0)
    target_color = (0,0,0)
    last_time = None
    fade_time = None
    fading = False

    def start_fading(self, target_color, fade_time):
        self.last_color = self.get_current_color()
        self.target_color = target_color
        self.last_time = time.time()
        self.fade_time = float(fade_time)
        self.fading = True
    def get_current_color(self):
        if not self.fading:
            return self.target_color
        return tuple(map(
                lambda a,b: int(interpolate(a, b, time.time()-self.last_time, self.fade_time)),
                self.last_color, self.target_color
            ))
    def poll_fading(self):
        if self.fading:
            if self.get_current_color() == self.target_color:
                self.fading = False
            return self.get_current_color()
        return None

class Test(Script):
    faders = None

    colors = (
        (255,255,255),
        (0,255,255),
        (255,0,255),
        (255,255,0),
        (255,0,0),
        (0,255,0),
        (0,0,255),
    )
    channel_groups = (MQTTLogicer.dmx_channels_fnordcenter, MQTTLogicer.dmx_channels_wohnzimmer, MQTTLogicer.dmx_channels_plenarsaal)

    color_time = None

    def __init__(self, *args, **kwargs):
        super(Test, self).__init__(*args, **kwargs)

        self.faders = [Fader() for i in range(3)]

    def on_starting(self):
        self.unlock_channel('dmx/wohnzimmer/mitte1')
        self.unlock_channel('dmx/wohnzimmer/mitte2')
        self.unlock_channel('dmx/wohnzimmer/mitte3')
        self.unlock_channel('dmx/plenar/vorne1')
        self.unlock_channel('dmx/plenar/vorne2')
        self.unlock_channel('dmx/plenar/vorne3')
        self.unlock_channel('dmx/plenar/hinten1')
        self.unlock_channel('dmx/plenar/hinten2')
        self.unlock_channel('dmx/plenar/hinten3')
        self.unlock_channel('dmx/plenar/hinten4')
        self.new_color()
    def broadcast_color(self, color, channels):
        for channel in channels:
            self.publish(channel, bytes(color)+b'\x00\x00\x00\xff')
    def new_color(self):
        self.color_time = time.time()
        for fader in self.faders:
            i = random.randint(0,len(self.colors)-1)
            fader.start_fading(self.colors[i], 5)
    def loop(self):
        if time.time() - self.color_time > 60:
            self.new_color()
        for fader,channels in zip(self.faders, (self.channel_groups)):
            color = fader.poll_fading()
            if color:
                self.broadcast_color(color, channels)


class MQTT_thread(Thread):
    """
    MQTT client.
    """

    def __init__(self, clientId=None, keepalive=None, willQos=0,
                 willTopic=None, willMessage=None, willRetain=False, *args, **kwargs):
        super(MQTT_thread, self).__init__(*args, **kwargs)

        if clientId is not None:
            self.clientId = clientId
        else:
            self.clientId = 'scripter'

        if keepalive is not None:
            self.keepalive = keepalive
        else:
            self.keepalive = 60

        self.willQos = willQos
        self.willTopic = willTopic
        self.willMessage = willMessage
        self.willRetain = willRetain

        self.scripts = []

    def start_script(self, cls, *args, **kwargs):
        s = cls(self.mqtt_client, *args, **kwargs)
        s.start()
        self.scripts.append(s)

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
                    ('script/#', 0),
                    ('dmx/+/+', 0),
                ]:
                self.mqtt_client.subscribe(*t)

    def publishReceived(self, mosq, obj, msg):
        match = re.match(r'^script/(\w+)(?:/(.*))?$', msg.topic)
        if match:
            for s in self.scripts:
                if s.name == match.group(1):
                    s.on_message(topic, msg.payload)
            return

        if msg.topic in MQTTLogicer.dmx_channels and len(msg.payload) in (4,7,8):
            for s in self.scripts:
                s.lock_channel(msg.topic)


def set_log_level(loglevel):
    # assuming loglevel is bound to the string value obtained from the
    # command line argument. Convert to upper case to allow the user to
    # specify --log=DEBUG or --log=debug
    numeric_level = getattr(logging, loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % loglevel)
    #logging.basicConfig(filename='/var/log/mqtt-scripter.log', format='%(asctime)s [%(levelname)s]: %(message)s', level=numeric_level)
    logging.basicConfig(format='%(asctime)s [%(levelname)s]: %(message)s', level=numeric_level)
    #logging.basicConfig(format='%(asctime)s [%(levelname)s]: %(message)s', level=numeric_level)

def main():
    set_log_level('DEBUG')
    logging.info('starting')

    logging.info('starting mqtt thread')
    mqtt_thread = MQTT_thread()
    mqtt_thread.start()

    # wait for mqtt thread to start, connect, ...
    time.sleep(1)

    mqtt_thread.start_script(Test)

    mqtt_thread.join()
    logging.info('mqtt thread joined')

    logging.info('stopping')


if __name__ == '__main__':
    main()
