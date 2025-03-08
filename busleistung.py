#!/usr/bin/python3

"""
A MQTT <-> MPD bridge.

Runs an idling thread waiting for events for every configured MPD server and
another thread subscribed to the MQTT server, listening for commands.
"""

import argparse
import collections
import json
import logging
import queue
import re
import sys
import threading
import time

from pyfis import aegmis

import busleistungserbringer
import helpers



class MQTT_Thread(helpers.MQTT_Client):

    subscribe_topics = [
            ('busleiste/change_module', 0),
            ('busleiste/modules/+/+', 0),
        ]

    def __init__(self, display_manager, clientId='busleiste', keepalive=60, heartbeat=True, *args, **kwargs):
        super().__init__(clientId, *args, keepalive=keepalive, heartbeat=heartbeat, daemon=True, **kwargs)

        self.display_manager = display_manager

    def on_connect(self, client, userdata, flags, rc):
        super().on_connect(client, userdata, flags, rc)

        data = {
                mod.name: (mod.name, mod.display_name) for mod in self.display_manager.modules.values()
            }

        self.mqtt_client.publish('busleiste/modules', json.dumps(data), retain=True)

        self.display_manager.on_mqtt_connect()

    def on_message(self, client, userdata, msg):
        if msg.topic == 'busleiste/change_module':
            if msg.payload == b'quit':
                sys.exit(1)
            self.display_manager.change_module(msg.payload.decode())

        self.display_manager.on_mqtt_message(msg)


class DisplayManager(threading.Thread):

    active_module = None
    modules = {}

    queued_module = None
    queued_interrupts: collections.deque

    mqtt_thread = None

    def __init__(self):
        super().__init__(daemon=True)

        self.queued_interrupts = collections.deque() # thread-safe

        self.disp=aegmis.MIS1TextDisplay("/dev/ttyAMA0", baudrate=19200)

        for cls in busleistungserbringer.enabled_modules:
            o = cls(self.disp)
            self.modules[cls.__name__] = o

        self.change_module('InternalStatus')


    def run(self):

        try:
            self.main_loop()

        except:
            logging.exception('Display Thread exception, exiting.')

    def main_loop(self):
        self.disp.reset()
        time.sleep(2) # need to sleep after reset

        self.disp.simple_text(1, 0, 0, "Booting...")
        self.disp.set_page(1)

        while True:
            interrupt_run = False

            while len(self.queued_interrupts) != 0:
                im = self.queued_interrupts.popleft()
                logging.info(f"Running Interrupt Module: {im.name}")
                if self.mqtt_thread:
                    self.mqtt_thread.mqtt_client.publish('busleiste/active_interrupt', im.name, retain=True)
                interrupt_run = True
                im.do_init()
                im.run_iteration()

            if interrupt_run:
                if self.mqtt_thread:
                    self.mqtt_thread.mqtt_client.publish('busleiste/active_interrupt', b'', retain=True)


            if self.queued_module:
                logging.info(f"Changing Module: {self.queued_module.name}")
                self.active_module = self.queued_module
                self.queued_module = None
                if self.mqtt_thread:
                    self.mqtt_thread.mqtt_client.publish('busleiste/active_module', self.active_module.name, retain=True)
                self.active_module.do_init()

            elif interrupt_run:
                if self.active_module is not None:
                    logging.info(f"Re-init Module: {self.active_module.name}")
                    self.active_module.do_init()


            if self.active_module is not None:
                self.active_module.run_iteration()
            else:
                time.sleep(1)

    def queue_interrupt(self, module_name):
        mod = self.modules.get(module_name, None)

        if mod is None:
            logging.warning(f"Could not queue interrupt, module not found: {module_name}")
            return

        if not mod.enabled:
            logging.warning(f"Not queuing interrupt, module disabled: {module_name}")
            return

        if self.active_module is not None and self.active_module.name == module_name:
            logging.info(f"Module interrupt already the active module, ignoring: {module_name}")
            return

        if any(module_name == mod.name for mod in self.queued_interrupts):
            logging.info(f"Module interrupt already queued: {module_name}")
            return

        logging.info(f"Module interrupt queued: {module_name}")
        self.queued_interrupts.append(mod)

    def change_module(self, module_name):
        mod = self.modules.get(module_name, None)

        if mod is None:
            logging.warning(f"Could not queue module change, module not found: {module_name}")
            return

        logging.info(f"Module Queued: {module_name}")
        self.queued_module = mod

    def on_mqtt_connect(self):
        for module in self.modules.values():
            module.on_mqtt_connect(self.mqtt_thread.mqtt_client, self)

    def on_mqtt_message(self, msg):
        if match := re.match('busleiste/modules/([^/]+)/enabled', msg.topic):
            module_name = match.group(1)
            module = self.modules.get(module_name, None)

            if module is not None:
                module.enabled = (msg.payload == b'\x01')

        for module in self.modules.values():
            module.on_mqtt_message(msg, self)



def main():
    parser = argparse.ArgumentParser(
            description='Busleisten Kontrollatöör',
            parents=[helpers.get_default_parser()],
        )
    args = parser.parse_args()
    helpers.configure_logging(args.logging_type, args.loglevel, args.logfile)

    logging.info('starting')

    logging.info('starting display manager')
    dm = DisplayManager()
    dm.start()

    logging.info('starting mqtt client')
    mqtt_thread = MQTT_Thread(dm, mqtt_host='172.23.23.110', heartbeat=True, heartbeat_blank=True)
    dm.mqtt_thread = mqtt_thread
    mqtt_thread.start()

    # time.sleep(10)
    # dm.change_module('OpenChaos')
    # time.sleep(10)
    # return

    while mqtt_thread.is_alive() and dm.is_alive():
        time.sleep(1)

    logging.info('exiting')
    sys.exit(1)


if __name__ == '__main__':
    main()
