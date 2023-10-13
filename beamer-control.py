#!/usr/bin/python3

"""
A control script for our H6510BD Acer projector.
"""

import argparse
import logging
import queue
import re
import serial
import sys
import threading
import time

import helpers

ALLOWED_COMMANDS = {
        'power on': '* 0 IR 001',
        'power off': '* 0 IR 002',
        'keystone': '* 0 IR 004',
        'mute': '* 0 IR 006',
        'freeze': '* 0 IR 007',
        'menu': '* 0 IR 008',
        'up': '* 0 IR 009',
        'down': '* 0 IR 010',
        'right': '* 0 IR 011',
        'left': '* 0 IR 012',
        'resync': '* 0 IR 014',
        'source analog rgb': '* 0 IR 015',
        'source pbpr': '* 0 IR 017',
        'source svideo': '* 0 IR 018',
        'source composite': '* 0 IR 019',
        'source component': '* 0 IR 020',
        'aspect 16:9': '* 0 IR 021',
        'aspect 4:3': '* 0 IR 022',
        'volume+': '* 0 IR 023',
        'volume-': '* 0 IR 024',
        'birghtness': '* 0 IR 025',
        'contrast': '* 0 IR 026',
        'color temperature': '* 0 IR 027',
        'hide': '* 0 IR 030',
        'source': '* 0 IR 031',
        'color saturation': '* 0 IR 032',
        'hue': '* 0 IR 033',
        'sharpness': '* 0 IR 034',
        'keystone up': '* 0 IR 042',
        'keystone down': '* 0 IR 043',
        'zoom': '* 0 IR 046',
        'e': '* 0 IR 047',
        'color rgb': '* 0 IR 048',
        'language': '* 0 IR 049',
        'source hdmi': '* 0 IR 050',
    }

QUERY_COMMANDS = {
        'model name': '* 0 IR 035',
        'company name': '* 0 IR 037',
        'lamp status': '* 0 Lamp ?',
        'lamp hours': '* 0 Lamp',
        'source type': '* 0 Src ?',
    }


class MQTT_beamer_controller(helpers.MQTT_Client):

    subscribe_topics = [
            ('beamer/plenar/control', 0),
        ]

    def __init__(self, serial_thread, clientId='beamer-control', mqtt_host='autoc4', keepalive=60, heartbeat=True):
        super().__init__(clientId, mqtt_host=mqtt_host, keepalive=keepalive, heartbeat=heartbeat, daemon=True)
        self.serial_thread = serial_thread

    def on_message(self, client, userdata, msg):
        if msg.retain: # ignore retained messages
            return

        if not msg.topic == 'beamer/plenar/control':
            return

        command = msg.payload.decode('utf-8')

        if not command in ALLOWED_COMMANDS:
            logging.info('command not allowed: {}'.format(command))

        else:
            logging.debug('beamer command: {}'.format(command))

            try:
                self.serial_thread.queue_command(ALLOWED_COMMANDS[command])
            except queue.Full:
                logging.warning('command queue full, dropped command {}'.format(command))

    def on_connect(self, mosq, obj, flags, rc):
        super().on_connect(mosq, obj, rc)
        self.serial_thread.mqtt_thread = self
        self.serial_thread.queue_command(QUERY_COMMANDS['lamp status'])

class SerialThread(threading.Thread):
    should_stop = False

    current_song = None
    current_state = None

    def __init__(self, serial_device, baudrate, *args, **kwargs):
        super().__init__(*args, daemon=True, **kwargs)

        self.serial_device = serial_device
        self.baudrate = baudrate
        self.mqtt_thread = None
        self.command_queue = queue.Queue(10)
        self.current_command = None
        self.current_lamp_status = None

        self.last_lamp_query = time.time()
        self.deferred_commands = []

    def request_stop(self):
        self.should_stop = True

    def run(self):

        try:
            self.main_loop()

        except:
            logging.exception('Serial Thread exception, exiting.')

    def queue_command(self, cmd):
        self.command_queue.put(cmd, block=False)

    def on_line_received(self, line):
        logging.debug('line received {} for command {}'.format(repr(line), repr(self.current_command)))

        if not self.current_command in QUERY_COMMANDS.values():
            self.current_command = None
            if not line in (b'*000', b'*001'):
                logging.warning('unknown response')
            return

        else:
            if line == b'*001': # error
                logging.info('query command returned error {}'.format(self.current_command))
                self.current_command = None
            elif line == b'*000':
                # success, wait for next line (result)
                return
            else:
                # process response

                if self.current_command == QUERY_COMMANDS['lamp status']:
                    if line == b'Lamp 0':
                        self.on_lamp_status(False)
                    elif line == b'Lamp 1':
                        self.on_lamp_status(True)
                    else:
                        logging.warning('unknown lamp status response')

                elif self.current_command == QUERY_COMMANDS['lamp hours']:
                    try:
                        res = int(line.decode())
                        self.on_lamp_hours(res)
                    except:
                        logging.warning('unknown lamp hours response')

                elif self.current_command == QUERY_COMMANDS['source type']:
                    m = re.match(rb'^Src (\d+)$', line)
                    if m:
                        self.on_source_type(int(m.group(1).decode()))
                    else:
                        logging.warning('unknown source type response')

                elif self.current_command == QUERY_COMMANDS['model name']:
                    m = re.match(rb'^Model (.+)$', line)
                    if m:
                        self.on_model_name(m.group(1).decode())
                    else:
                        logging.warning('unknown model name response')

                elif self.current_command == QUERY_COMMANDS['company name']:
                    m = re.match(rb'^Name (.+)$', line)
                    if m:
                        self.on_company_name(m.group(1).decode())
                    else:
                        logging.warning('unknown company name response')

                else:
                    raise ValueError()

                self.current_command = None

    def on_lamp_status(self, status):
        logging.debug('lamp status {}'.format(status))

        if status != self.current_lamp_status and status == True:
            logging.debug('lamp status changed on, querying')
            try:
                self.queue_on_only_queries()
            except queue.Full:
                pass

        self.current_lamp_status = status

        if self.mqtt_thread:
            self.mqtt_thread.mqtt_client.publish('beamer/plenar/lamp_state', b'\x01' if status else b'\x00', retain=True, qos=0)

    def on_lamp_hours(self, hours):
        logging.debug('lamp hours {}'.format(hours))

        if self.mqtt_thread:
            self.mqtt_thread.mqtt_client.publish('beamer/plenar/lamp_hours', str(hours).encode(), retain=True, qos=0)

    def on_source_type(self, srctype):
        logging.debug('source type {}'.format(srctype))

        if self.mqtt_thread:
            self.mqtt_thread.mqtt_client.publish('beamer/plenar/source_type', str(srctype).encode(), retain=True, qos=0)

    def on_model_name(self, name):
        logging.debug('model name {}'.format(name))

    def on_company_name(self, name):
        logging.debug('company name {}'.format(name))

    def send_command(self):
        try:
            cmd = self.command_queue.get(block=False)

        except queue.Empty:
            return

        self.current_command = cmd
        self._ser.write((cmd + '\r').encode())

        self.on_command_sent(cmd)

    def queue_on_only_queries(self):
        self.command_queue.put(QUERY_COMMANDS['lamp hours'])
        self.command_queue.put(QUERY_COMMANDS['source type'])

    def queue_lamp_query(self):
        logging.debug('queueing lamp queries')
        self.queue_command(QUERY_COMMANDS['lamp status'])
        if self.current_lamp_status:
            self.queue_on_only_queries()

    def queue_automatic_queries(self):
        if time.time() - self.last_lamp_query > 60:
            try:
                self.queue_lamp_query()
            except queue.Full:
                pass
            return

        now = time.time()
        for i in range(len(self.deferred_commands)):
            if self.deferred_commands[i][1] <= now:
                cmd, _ = self.deferred_commands.pop(i)
                try:
                    self.queue_command(cmd)
                except queue.Full:
                    pass # shouldn't happen, but to be safe
                return

    def on_command_sent(self, cmd):
        if cmd == QUERY_COMMANDS['lamp status']:
            self.last_lamp_query = time.time()
        elif cmd in ( ALLOWED_COMMANDS['power on'], ALLOWED_COMMANDS['power off']):
            self.deferred_commands.append((QUERY_COMMANDS['lamp status'], time.time() + 5))

    def main_loop(self):

        with serial.Serial(self.serial_device, self.baudrate, timeout=.1) as ser:

            self._ser = ser
            current_buffer = b''
            last_data_received = time.time()

            while not self.should_stop:

                res = ser.read()

                if res:
                    current_buffer += res
                    last_data_received = time.time()

                    a, sep, b = current_buffer.partition(b'\r')

                    if sep:
                        current_buffer = b
                        self.on_line_received(a)

                else: # read timed out, no new data
                    if not current_buffer and self.current_command is None:
                        # line buffer empty, may queue command

                        if self.command_queue.empty():
                            self.queue_automatic_queries()

                        self.send_command()

                    elif current_buffer and time.time() - last_data_received > 10:
                        logging.warning('received incomplete line, timed out, resetting buffer ({})'.format(repr(current_buffer)))
                        current_buffer = b''


def main():
    parser = argparse.ArgumentParser(
            description='MQTT Beamer Control',
            parents=[helpers.get_default_parser()],
        )
    args = parser.parse_args()
    helpers.configure_logging(args.logging_type, args.loglevel, args.logfile)

    logging.info('starting')

    logging.info('starting beamer control script')

    serial_thread = SerialThread('/dev/ttyUSB0', 9600)
    serial_thread.start()

    mqtt_thread = MQTT_beamer_controller(serial_thread)
    mqtt_thread.start()

    while mqtt_thread.is_alive() and serial_thread.is_alive():
        time.sleep(1)

    logging.info('exiting')
    sys.exit(1)

if __name__ == '__main__':
    main()
