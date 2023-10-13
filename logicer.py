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

import argparse
import logging
import re
import struct
import threading
import time
import requests
import sys
from collections import namedtuple
from datetime import datetime
from subprocess import Popen

import config
import helpers


_LastStateEntry = namedtuple('_LastStateEntry', ['value', 'time'])

class MQTTLogicer(helpers.MQTT_Client):
    """
    Last received messages for topics are stored in `last_state`.
    """

    fnordcenter_lichter = [
        'licht/fnord/links',
        'licht/fnord/rechts',
    ]
    keller_lichter = [
        'licht/keller/loet',
        'licht/keller/mitte',
        'licht/keller/vorne',
    ]
    leds_keller = [
        'led/keller/werkbankwarm',
        'led/keller/werkbankkalt',
        'led/keller/hintenwarm',
        'led/keller/hintenkalt',
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
    sockets = [
        'socket/wohnzimmer/screen/a',
        'socket/wohnzimmer/screen/b',
        'relais/plenar/amp',
        'relais/plenar/dmx',
        'relais/fnord/dmx',
        'relais/fnord/audio',
    ]
    screens = [
        'screen/wohnzimmer/infoscreen'
    ]
    alle_lichter = fnordcenter_lichter + keller_lichter + wohnzimmer_lichter + plenarsaal_lichter + powers + sockets + leds_keller + screens
    exit_light = 'licht/wohnzimmer/tuer'

    fenster_to_licht = {
        'fenster/plenar/vornerechts': 'licht/plenar/vornefenster',
        'fenster/plenar/vornelinks': 'licht/plenar/vornefenster',
        'fenster/plenar/hintenrechts': 'licht/plenar/hintenfenster',
        'fenster/plenar/hintenlinks': 'licht/plenar/hintenfenster',
        'fenster/wohnzimmer/rechts': 'licht/wohnzimmer/kueche',
        'fenster/wohnzimmer/links': 'licht/wohnzimmer/kueche',
        'fenster/fnord/links': 'licht/fnord/links',
        'fenster/fnord/rechts': 'licht/fnord/rechts',
    }

    musiken = [
        'mpd/plenar',
        'mpd/fnord',
        'mpd/baellebad',
        'mpd/keller',
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
        'dmx/wohnzimmer/spuele1',
        'dmx/wohnzimmer/spuele2',
        'dmx/wohnzimmer/chaosknoten',
        'dmx/wohnzimmer/tresen',
        'dmx/wohnzimmer/tresen2',
    ]
    leds_wohnzimmer = [
        'led/kitchen/sink',
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
    dmx_channels = dmx_channels_fnordcenter + dmx_channels_wohnzimmer + dmx_channels_plenarsaal + leds_wohnzimmer

    last_state = None
    last_event = None

    subscribe_topics = [
            ('schalter/+/+',        0),
            ('licht/+/+',           0),
            ('relais/+/+',          0),
            ('led/+/+',             0),
            ('licht/+',             0),
            ('screen/+/+',          0),
            ('fenster/+/+',         0),
            ('dmx/+/+',             0),
            ('dmx/+',               0),
            ('preset/+/+',          0),
            ('club/status',         0),
            ('club/status/message', 0),
            ('club/shutdown',       0),
            ('club/gate',           0),
            ('club/bell',           0),
            ('heartbeat/+',         0),
            #('temp/+/+',     0),
        ]

    def __init__(self, clientId='logicer', keepalive=60, heartbeat=True):
        super(MQTTLogicer, self).__init__(clientId, keepalive=keepalive, heartbeat=heartbeat, daemon=True)

        self.last_state = {}
        self.last_event = {}

    def on_message(self, client, userdata, msg):

        if not msg.topic in self.last_state:
            self.initial_value(msg.topic, msg.payload)

        else:
            if msg.payload != self.last_state[msg.topic].value:
                self.value_changed(msg.topic, msg.payload)

        self.got_publish(msg.topic, msg.payload, msg.retain)

        self.last_state[msg.topic] = _LastStateEntry(msg.payload, time.time())


    # FROM HERE ON: actual logic

    def initial_value(self, topic, value):
        """
        Called when a topic receives a message for the first time. (There is no
        entry in `last_state`)
        """

        if topic == 'schalter/wohnzimmer/rechts':
            logging.debug('setting club status')
            self.mqtt_client.publish('club/status', value, retain=True)


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

        if topic == 'schalter/keller/1' and new_value == b'\x00':
            logging.debug('toggling keller')
            self.toggle_room_lights(self.keller_lichter)

        if topic in self.dmx_channels_plenarsaal and any(b for b in new_value):
            if self.last_state['relais/plenar/dmx'].value != b'\x01':
                logging.debug('non zero dmx code, switching on plenarsaal dmx socket {}'.format(self.last_state['relais/plenar/dmx'].value))
                self.mqtt_client.publish('relais/plenar/dmx', b'\x01', retain=True)

        if topic in self.dmx_channels_fnordcenter and any(b for b in new_value):
            if self.last_state['relais/fnord/dmx'].value != b'\x01':
                logging.debug('non zero dmx code, switching on fnordcenter dmx socket {}'.format(self.last_state['relais/fnord/dmx'].value))
                self.mqtt_client.publish('relais/fnord/dmx', b'\x01', retain=True)
            
        cycle_topics = {
                'schalter/keller/hinten2':[
                        'led/keller/hintenwarm',
                        'led/keller/hintenkalt'
                    ],
                'schalter/keller/3':[
                        'led/keller/werkbankwarm',
                        'led/keller/werkbankkalt'
                    ],
            }

        if (topic == 'schalter/keller/hinten2' or topic == 'schalter/keller/3') and new_value == b'\x00':
            t = self.last_event.get(topic, 0)
            now = time.time()
            timeout = now - t
            self.last_event[topic] = now

            if timeout > 10:
                logging.debug('toggling {}'.format(topic))
                self.toggle_room_lights(cycle_topics[topic])
            else:
                logging.debug('cycling {}'.format(topic))
                self.cycle_topic_states(
                        cycle_topics[topic],
                        [
                            (b'\x00', b'\x00'),
                            (b'\x01', b'\x01'),
                            (b'\x01', b'\x00'),
                            (b'\x00', b'\x01'),
                        ]
                    )

        if topic == 'club/bell' and new_value == b'\x00':

            if self.last_state['club/status'].value == b'\x01':
                logging.debug('bell received, opening door')
                self.mqtt_client.publish('club/gate', b'')

            else:
                logging.debug('bell off')


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


        match = re.match(r'^heartbeat/(.*)$', topic)
        if match:
            logging.debug('heartbeat ' + match.group(1) + ": " + str(payload))

        if topic.startswith('schalter/test/1'):
            logging.debug('test: ' + str(payload))


        if topic == 'club/shutdown':
            if retain:
                return

            logging.debug('shutdown')

            # turn off beamer
            self.mqtt_client.publish('beamer/plenar/control', 'power off')

            # turn off music and reset outputs
            for t in self.musiken:
                self.mqtt_client.publish(t+'/control', 'stop')
                self.mqtt_client.publish(t+'/control', 'resetoutputs')

            # turn off dmx lights
            for t in self.dmx_channels:
                self.mqtt_client.publish(t, b'\x00'*8, retain=True)

            to_switch = { t: b'\x00' for t in self.alle_lichter }

            if payload != b'\x44': # shutdown is not forced
                # turn on lights corresponding to open windows
                for fenster, licht in self.fenster_to_licht.items():
                    if not fenster in self.last_state:
                        pass # TODO: edge case
                    elif self.last_state[fenster].value != b'\x00':
                        to_switch[licht] = b'\x01'
                        to_switch[self.exit_light] = b'\x01'

            # publish licht messages
            for t, p in to_switch.items():
                self.mqtt_client.publish(t, p, retain=True)

        if topic == 'club/status':
            self.set_club_status(payload, self.last_state.get('club/status/message', ''))
        if topic == 'club/status/message':
            self.set_club_status(self.last_state.get('club/status', b'\x00'), payload)


    def preset(self, topic, payload):

        match = re.match(r'^preset/(fnord|wohnzimmer|plenar|keller)/(on|off)$', topic)
        if match:
            logging.debug('preset ' + topic)
            room = match.group(1)
            if match.group(2) == 'on':
                p = b'\x01'
            else:
                p = b'\x00'
            self.mqtt_client.publish('licht/' + room, p)
            self.mqtt_client.publish('dmx/' + room + '/master', b'\x00'*8)
            return


        match = re.match(r'^preset/(wohnzimmer|plenar)/fade$', topic)
        if match:
            logging.debug('preset ' + topic)
            room = match.group(1)
            self.mqtt_client.publish('licht/' + room, b'\x00')
            self.mqtt_client.publish('dmx/' + room + '/master', b'\x00\x00\x00\x00\x00\x81\xff')
            return

        logging.info('unknown preset')


    def toggle_room_lights(self, room_lights):
        """
        Toggle all lights in a room:
            * If any one is on, turn all lights off.
            * If no light is on, turn all on.
        """

        for t in room_lights:
            if not t in self.last_state:
                # strange edge case - i don't know what to do
                logging.warning('Toggling light without known last state, ignoring. ({})'.format(repr(t)))
                return

        some_light_on = any(self.last_state[t].value != b'\x00' for t in room_lights)

        if some_light_on:
            logging.debug('turning lights off')
            for t in room_lights:
                self.mqtt_client.publish(t, b'\x00', retain=True)

        else:
            logging.debug('turning lights on')
            for t in room_lights:
                self.mqtt_client.publish(t, b'\x01', retain=True)

    def cycle_topic_states(self, topics, states, force_index=None):
        """
        Takes a list of topics and a corresponding list of tuples of values.
            * If the current values of the given topics is in the states list,
              set them to the next entry
            * Otherwise set them to the first entry in the states list
        """

        current_values = []

        for topic in topics:
            if topic in self.last_state:
                current_values.append(self.last_state[topic].value)
            else:
                logging.warning('Cycling topics without known last state, ignoring. ({})'.format(topic))
                return

        current_values = tuple(current_values)
        logging.debug('current values: {}'.format(current_values))

        try:
            index = states.index(current_values)
            new_index = (index + 1) % len(states)
        except ValueError:
            new_index = 0

        for topic, value in zip(topics, states[new_index]):
            logging.debug('setting: {} = {}'.format(repr(topic), repr(value)))
            self.mqtt_client.publish(topic, value, retain=True)

    def set_club_status(self, state, message):
            logging.debug('set club status')
            # publish to irc topic ?

            if state != b'\x00':
                self.mqtt_client.publish('rgb/bell', b'\x00\xff\x00' * 4, retain=True)
                status = 'open'
            else:
                self.mqtt_client.publish('rgb/bell', b'\xff\x00\x00' * 4, retain=True)
                status = 'closed'

            #logging.debug('setting irc topic')
            #Popen(['/usr/bin/python2.7', '/home/autoc4/logicer/irc_topicer.py', status])

            # forward to webserver (for spaceapi)
            logging.debug('setting spaceapi open status')
            try:
                requests.post(
                        'https://api.koeln.ccc.de/newstate',
                        timeout=5,
                        data={
                            "password"  : config.spaceapi_password,
                            "state"     : status,
                            "message"   : ( message.decode("utf-8") if isinstance(message, bytes) else message )
                        }
                    )
            except Exception as e:
                logging.warning('connection to webserver/spaceapi failed: {}'.format(repr(e)))


class MQTT_Time_Thread(threading.Thread):
    """
    Publishes the current time in regular intervals.
    """

    interval = 60
    topic = 'time'

    def __init__(self, logicer, *args, **kwargs):
        super(MQTT_Time_Thread, self).__init__(*args, daemon=True, **kwargs)
        self.logicer = logicer

    def run(self):

        try:
            self.main_loop()

        except:
            logging.exception('Thimethread exception, exiting.')

    def main_loop(self):

        while not self.logicer.connection_established:
            time.sleep(0.1)

        logging.info('timethread started')

        while True:
            self.publish_time()
            time.sleep(self.interval)

    def publish_time(self):

        t = datetime.now()
        data = struct.pack('<BBBBBBBB',
            t.hour,
            t.minute,
            t.second,
            0,
            t.weekday() + 1,
            t.month,
            t.day,
            t.year % 100,
            )
        self.logicer.mqtt_client.publish(self.topic, data)


def main():
    parser = argparse.ArgumentParser(
            description='MQTT Logicer',
            parents=[helpers.get_default_parser()],
        )
    args = parser.parse_args()
    helpers.configure_logging(args.logging_type, args.loglevel, args.logfile)

    logging.info('starting')

    logicer = MQTTLogicer()
    logicer.start()

    timethread = MQTT_Time_Thread(logicer)
    timethread.start()

    while logicer.is_alive() and timethread.is_alive():
        time.sleep(1)

    logging.info('exiting')
    sys.stdout.flush()
    sys.stderr.flush()
    sys.exit(1)

if __name__ == '__main__':
    main()

# vim:set sw=4 sts=4 et ts=4 autoindent:
