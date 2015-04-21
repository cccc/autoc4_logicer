#!/usr/bin/python3

"""
Implements logic for the MQTT-based home automation. This includes:

    * light switches:       Toggle lights for rooms
    * club status:          Call irc_topicer.py when club status changes
    * club status switch:   Forward to club status
    * club shutdown:        Turn off lights, music
    * dmx channels:         Set the etherrape dmx output
    * room master:          Forwards commands to all lights in a room
"""

import logging
import sys
sys.path.append('/home/autoc4/.pyenv/versions/3.4.0/lib/python3.4/site-packages/')
from subprocess import call
from paho.mqtt import client as mqtt_client
import re


class MQTTLogicer(object):
    """
    Last received messages for topics are stored in `last_state`.
    """

    fnordcenter_lichter = [
        'licht/fnord/links',
        'licht/fnord/rechts',
    ]
    keller_lichter = [
        'licht/keller/aussen',
        'licht/keller/innen',
    ]
    wohnzimmer_lichter = [
        'licht/wohnzimmer/kueche',
        'licht/wohnzimmer/mitte',
        'licht/wohnzimmer/tuer',
        'licht/wohnzimmer/gang',
    ]
    plenarsaal_lichter = [
        'licht/plenar/vornefenster',
        'licht/plenar/vornewand',
        'licht/plenar/hintenfenster',
        'licht/plenar/hintenwand',
    ]
    powers = [
        'power/wohnzimmer/kitchenlight',
    ]
    alle_lichter = fnordcenter_lichter + keller_lichter + wohnzimmer_lichter + plenarsaal_lichter + powers
    exit_light = 'licht/wohnzimmer/tuer'

    fenster_to_licht = {
        'fenster/plenar/vornerechts': 'licht/plenar/vornefenster',
        'fenster/plenar/vornelinks': 'licht/plenar/vornefenster',
        'fenster/plenar/hintenrechts': 'licht/plenar/hintenfenster',
        'fenster/plenar/hintenlinks': 'licht/plenar/hintenfenster',
        'fenster/wohnzimmer/kuecherechts': 'licht/wohnzimmer/kueche',
        'fenster/wohnzimmer/kuechelinks': 'licht/wohnzimmer/kueche',
        'fenster/fnord/links': 'licht/fnord/links',
        'fenster/fnord/rechts': 'licht/fnord/rechts',
    }

    musiken = [
        'mpd/plenar',
        'mpd/fnord',
        'mpd/baellebad',
    ]

    dmx_channels_fnordcenter = [
        'dmx/fnord/fairyfenster',
        'dmx/fnord/schranklinks',
        'dmx/fnord/schrankrechts',
        'dmx/fnord/scummfenster',
    ]
    dmx_channels_wohnzimmer = [
        'dmx/wohnzimmer/mitte1',
        'dmx/wohnzimmer/mitte2',
        'dmx/wohnzimmer/mitte3',
        'dmx/wohnzimmer/tuer1',
        'dmx/wohnzimmer/tuer2',
        'dmx/wohnzimmer/tuer3',
        'dmx/wohnzimmer/gang',
        'dmx/wohnzimmer/baellebad',
    ]
    dmx_channels_plenarsaal = [
        'dmx/plenar/vorne1',
        'dmx/plenar/vorne2',
        'dmx/plenar/vorne3',
        'dmx/plenar/hinten1',
        'dmx/plenar/hinten2',
        'dmx/plenar/hinten3',
        'dmx/plenar/hinten4',
    ]
    dmx_channels = dmx_channels_fnordcenter + dmx_channels_wohnzimmer + dmx_channels_plenarsaal

    last_state = None

    def __init__(self, clientId=None, keepalive=None, willQos=0,
                 willTopic=None, willMessage=None, willRetain=False):

        if clientId is not None:
            self.clientId = clientId
        else:
            self.clientId = 'Logicer'

        if keepalive is not None:
            self.keepalive = keepalive
        else:
            self.keepalive = 60

        self.willQos = willQos
        self.willTopic = willTopic
        self.willMessage = willMessage
        self.willRetain = willRetain

        self.last_state = {}
        #self.last_state = { s: None for s in self.plenarsaal_lichter + self.wohnzimmer_lichter + self.keller_licht }

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
                    ('schalter/+/+',  0),
                    ('licht/+/+',     0),
                    ('licht/+',       0),
                    ('fenster/+/+',   0),
                    ('dmx/+/+',       0),
                    ('dmx/+',         0),
                    ('preset/+/+',    0),
                    ('club/status',   0),
                    ('club/shutdown', 0),
                    ('club/gate',     0),
                    #('temp/+/+',     0),
                ]:
                self.mqtt_client.subscribe(*t)

    def publishReceived(self, mosq, obj, msg):
        #if msg.topic.startswith('temp/kuehlschrank/'):
        #    import struct
        #    logging.debug('%s, %f' % (msg.topic, struct.unpack('<f', msg.payload[:4])[0]))

        if not msg.topic in self.last_state:
            self.initial_value(msg.topic, msg.payload)
        else:
            if msg.payload != self.last_state[msg.topic]:
                self.value_changed(msg.topic, msg.payload)
        self.got_publish(msg.topic, msg.payload, msg.retain)

        self.last_state[msg.topic] = msg.payload
        #logging.debug('setstate {} = {}'.format(msg.topic, repr(msg.payload)))


    # FROM HERE ON: actual logic

    def initial_value(self, topic, value):
        """
        Called when a topic receives a message for the first time. (There is no
        entry in `last_state`)
        """

        if topic == 'schalter/wohnzimmer/rechts':
            logging.debug('setting club status')
            self.mqtt_client.publish('club/status', value, retain=True)

        if topic == 'club/status':
            logging.debug('setting irc topic')
            # publish to irc topic ?

            if value != b'\x00':
                status = 'open'
            else:
                status = 'closed'

            #endpoint = TCP4ClientEndpoint(reactor, 'chat.freenode.net', 6667)
            #d = endpoint.connect(BotFactory('c4status', status))
            call(['/usr/bin/python2.7', '/home/autoc4/logicer/irc_topicer.py', status])


    def value_changed(self, topic, new_value):
        """
        Called when a topic receives a message which differs from the one
        stored in `last_state`.
        """

        if topic == 'schalter/wohnzimmer/rechts':
            logging.debug('toggling club status')
            self.mqtt_client.publish('club/status', new_value, retain=True)

        if topic == 'schalter/wohnzimmer/links':
            logging.debug('toggling wohnzimmer')
            self.toggle_room_lights(self.wohnzimmer_lichter)

        if topic == 'schalter/wohnzimmer/gang':
            logging.debug('toggling wohnzimmer')
            self.toggle_room_lights(['licht/wohnzimmer/gang'])

        if topic == 'schalter/plenar/vorne':
            logging.debug('toggling plenarsaal')
            self.toggle_room_lights(self.plenarsaal_lichter)

        if topic == 'schalter/fnord/vorne':
            logging.debug('toggling fnordcenter')
            self.toggle_room_lights(self.fnordcenter_lichter)

        if topic == 'club/status':
            logging.debug('toggling irc topic')
            # publish to irc topic ?

            if new_value != b'\x00':
                status = 'open'
            else:
                status = 'closed'

            #endpoint = TCP4ClientEndpoint(reactor, 'chat.freenode.net', 6667)
            #d = endpoint.connect(BotFactory('c4status', status))
            call(['/usr/bin/python2.7', '/home/autoc4/logicer/irc_topicer.py', status])


    def got_publish(self, topic, payload, retain):
        """
        Called for each message received.
        """

        match = re.match(r'^licht/(fnord|wohnzimmer|plenar|keller)$', topic)
        if match:
            if retain:
                return

            # if payload is 0x00 or 0x01 relay to all light channels of the room
            # else toggle the room
            room = match.group(1)
            if room == 'fnord':
                lights = self.fnordcenter_lichter
            elif room == 'wohnzimmer':
                lights = self.wohnzimmer_lichter
            elif room == 'plenar':
                lights = self.plenarsaal_lichter
            elif room == 'keller':
                lights = self.keller_lichter
            else:
                logging.warning('This should not happen')
                return

            if payload in (b'\x00', b'\x01'):
                logging.debug('switching ' + room)
                for t in lights:
                    self.mqtt_client.publish(t, payload, retain=True)
            else:
                logging.debug('toggling ' + room)
                self.toggle_room_lights(lights)


        match = re.match(r'^dmx/(fnord|wohnzimmer|plenar|keller)/master$', topic)
        if match:
            if retain:
                return

            # relay message to all dmx channels of the room
            room = match.group(1)
            for t in [s for s in self.dmx_channels if s.startswith('dmx/' + room)]:
                self.mqtt_client.publish(t, payload, retain=True)


        if topic.startswith('preset/'):
            if retain:
                return

            self.preset(topic, payload)


        if topic == 'club/shutdown':
            if retain:
                return

            logging.debug('shutdown')
            # turn off music
            for t in self.musiken:
                self.mqtt_client.publish(t+'/control', 'stop')
            # turn off dmx lights
            for t in self.dmx_channels:
                self.mqtt_client.publish(t, b'\x00'*8, retain=True)

            to_switch = { t: b'\x00' for t in self.alle_lichter }

            if payload != b'\x44': # shutdown is not forced
                # turn on lights corresponding to open windows
                for fenster, licht in self.fenster_to_licht.items():
                    if not fenster in self.last_state:
                        pass # TODO: edge case
                    elif self.last_state[fenster] != b'\x00':
                        to_switch[licht] = b'\x01'
                        to_switch[self.exit_light] = b'\x01'

            # publish licht messages
            for t, p in to_switch.items():
                self.mqtt_client.publish(t, p, retain=True)


    def preset(self, topic, payload):

        match = re.match(r'^preset/(fnord|wohnzimmer|plenar|keller)/(on|off)$', topic)
        if match:
            room = match.group(1)
            if match.group(2) == 'on':
                p = b'\x01'
            else:
                p = b'\x00'
            self.mqtt_client.publish('licht/' + room, p)
            self.mqtt_client.publish('dmx/' + room + '/master', b'\x00'*8)


        match = re.match(r'^preset/(wohnzimmer|plenar)/fade$', topic)
        if match:
            room = match.group(1)
            self.mqtt_client.publish('licht/' + room, b'\x00')
            self.mqtt_client.publish('dmx/' + room + '/master', b'\x00\x00\x00\x00\x00\x81\xff')


    def toggle_room_lights(self, room_lights):
        """
        Toggle all lights in a room:
            * If any one is on, turn all lights off.
            * If no light is on, turn all on.
        """

        for t in room_lights:
            if not t in self.last_state:
                return # strange edge case - i don't know what to do

        some_light_on = False
        for t in room_lights:
            if self.last_state[t] != b'\x00':
                some_light_on = True
                break

        if some_light_on:
            logging.debug('turning lights off')
            for t in room_lights:
                self.mqtt_client.publish(t, b'\x00', retain=True)
        else:
            logging.debug('turning lights on')
            for t in room_lights:
                self.mqtt_client.publish(t, b'\x01', retain=True)


def set_log_level(loglevel):
    # assuming loglevel is bound to the string value obtained from the
    # command line argument. Convert to upper case to allow the user to
    # specify --log=DEBUG or --log=debug
    numeric_level = getattr(logging, loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % loglevel)
    logging.basicConfig(filename='/var/log/mqtt-logicer.log', format='%(asctime)s [%(levelname)s]: %(message)s', level=numeric_level)
    #logging.basicConfig(format='%(asctime)s [%(levelname)s]: %(message)s', level=numeric_level)

def main():
    set_log_level('DEBUG')
    logging.info('starting')
    l = MQTTLogicer()
    l.run()
    logging.info('stopping')

if __name__ == '__main__':
    main()

# vim:set sw=4 sts=4 et ts=4 autoindent:
