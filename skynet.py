#!/usr/bin/python3

import argparse
import logging
import sys
sys.path.append('/home/autoc4/.pyenv/versions/3.4.0/lib/python3.4/site-packages/')
from paho.mqtt import client as mqtt_client
from bs4 import BeautifulSoup
from datetime import datetime
import json
import re
import threading
import time
import urllib.request

import config
import helpers

MONTH_NAME_TO_INT = {
        'Jan': 1,
        'Feb': 2,
        'Mar': 3,
        'Apr': 4,
        'May': 5,
        'Jun': 6,
        'Jul': 7,
        'Aug': 8,
        'Sep': 9,
        'Oct': 10,
        'Nov': 11,
        'Dec': 12,
    }

class IssParser():

    url = 'http://www.heavens-above.com/PassSummary.aspx?satid=25544&lat=50.9502&lng=6.9131&loc=6A&alt=51&tz=CET'
    base_url = 'http://www.heavens-above.com/'

    @staticmethod
    def get_iss_data():
        response = urllib.request.urlopen(IssParser.url)
        bs = BeautifulSoup(response, 'html.parser')

        if bs.text.find('No visible passes found within the search period') >= 0:
            return []

        table, = bs.select('table.standardTable')

        keys = [
                'Date',
                'Brightness (mag)',
                'Start Time',
                'Start Alt.',
                'Start Az.',
                'Highest Point Time',
                'Highest Point Alt.',
                'Highest Point Az.',
                'End Time',
                'End Alt.',
                'End Az.',
                'Pass type',
            ]

        rows = table.select('tr.clickableRow')
        row_dicts = []

        for row in rows:
            values = [td.getText().strip() for td in row.findAll('td')]
            row_dict = IssParser.augment_row_info(dict(zip(keys, values)))
            row_dict['url'] = IssParser.base_url + row.find('a').get('href')
            row_dict['type'] = 'iss'
            row_dicts.append(row_dict)

        return row_dicts

    ALT_RE = re.compile(r'(\d+)°')

    @staticmethod
    def augment_row_info(row_dict):

        row_dict['Start timestamp']         = int(IssParser.parse_time(row_dict, 'Start Time').timestamp())
        row_dict['Highest Point timestamp'] = int(IssParser.parse_time(row_dict, 'Highest Point Time').timestamp())
        row_dict['End timestamp']           = int(IssParser.parse_time(row_dict, 'End Time').timestamp())

        row_dict['timestamp'] = row_dict['Highest Point timestamp']

        row_dict['altitude_deg']     = int(re.match(IssParser.ALT_RE, row_dict['Highest Point Alt.']).group(1))
        row_dict['brightness_float'] = float(row_dict['Brightness (mag)'])

        return row_dict

    TIME_RE = re.compile(r'(\d\d):(\d\d):(\d\d)')
    DATE_RE = re.compile(r'(\d+) ([A-Z][a-z][a-z])')

    @staticmethod
    def parse_time(r, time_field):

        day, month = re.match(IssParser.DATE_RE, r['Date']).groups()
        hour, minute, second = re.match(IssParser.TIME_RE, r[time_field]).groups()

        dt = datetime(
                datetime.now().year,
                MONTH_NAME_TO_INT[month],
                int(day),
                int(hour),
                int(minute),
                int(second),
            )

        return dt


class IridiumParser():

    url = 'http://www.heavens-above.com/IridiumFlares.aspx?lat=50.9502&lng=6.9131&loc=6A&alt=51&tz=CET'
    base_url = 'http://www.heavens-above.com/'

    @staticmethod
    def get_iridium_data():
        response = urllib.request.urlopen(IridiumParser.url)
        bs = BeautifulSoup(response, 'html.parser')
        #data = response.read().decode()

        table, = bs.select('table.standardTable')

        thead = table.find('thead')
        tbody = table.find('tbody')

        keys = [td.getText().strip() for td in thead.find('tr').findAll('td')]

        rows = tbody.findAll('tr')
        row_dicts = []

        for row in rows:
            values = [td.getText().strip() for td in row.findAll('td')]
            row_dict = IridiumParser.augment_row_info(dict(zip(keys, values)))
            row_dict['url'] = IridiumParser.base_url + row.find('a').get('href')
            row_dict['type'] = 'iridium'
            row_dicts.append(row_dict)

        return row_dicts

    ALT_RE = re.compile(r'(\d+)°')
    AZI_RE = re.compile(r'(\d+)° \((\w+)\)')
    SAT_RE = re.compile(r'Iridium (\d+)')

    @staticmethod
    def augment_row_info(row_dict):

        dt = IridiumParser.parse_time_string(row_dict['Time'])
        row_dict['timestamp'] = int(dt.timestamp())

        row_dict['altitude_deg']     = int(re.match(IridiumParser.ALT_RE, row_dict['Altitude']).group(1))
        row_dict['azimuth_deg']      = int(re.match(IridiumParser.AZI_RE, row_dict['Azimuth']).group(1))
        row_dict['satellite_num']    = int(re.match(IridiumParser.SAT_RE, row_dict['Satellite']).group(1))
        row_dict['brightness_float'] = float(row_dict['Brightness'])

        return row_dict

    TIME_RE = re.compile(r'([A-Z][a-z][a-z]) (\d+), (\d\d):(\d\d):(\d\d)')

    @staticmethod
    def parse_time_string(s):

        month, day, hour, minute, second = re.match(IridiumParser.TIME_RE, s).groups()

        dt = datetime(
                datetime.now().year,
                MONTH_NAME_TO_INT[month],
                int(day),
                int(hour),
                int(minute),
                int(second),
            )

        return dt


class MQTT_Skynet_Thread(threading.Thread):
    """
    Publishes the current time in regular intervals.
    """

    interval = 60 * 60 * 3
    topic = 'skynet'

    def __init__(self, mqtt_thread, *args, **kwargs):
        super(MQTT_Skynet_Thread, self).__init__(*args, daemon=True, **kwargs)
        self.mqtt_thread = mqtt_thread

    def run(self):

        try:
            self.main_loop()

        except:
            logging.exception('Skynet thread exception, exiting.')

    def main_loop(self):

        while not self.mqtt_thread.connection_established:
            time.sleep(0.1)

        logging.info('skynet thread started')

        while True:
            self.poll_data()
            time.sleep(self.interval)

    def poll_data(self):

        data = IssParser.get_iss_data() + IridiumParser.get_iridium_data()
        data.sort(key=lambda x:x['timestamp'])

        self.mqtt_thread.mqtt_client.publish(self.topic, json.dumps(data), retain=True)

def to_str(i):
    i['ptime'] = datetime.fromtimestamp(i['timestamp']).strftime('%b %d, %H:%M:%S')

    if i['type'] == 'iss':
        return 'ISS   {brightness_float: 1.1f}  {altitude_deg:2}°    -   {ptime}'.format(**i)
    else:
        return 'Ir{satellite_num}  {brightness_float: 1.1f}  {altitude_deg:2}°  {azimuth_deg:3}°  {ptime}'.format(**i)


def main():
    parser = argparse.ArgumentParser(
            description='MQTT Skynet Poller',
            parents=[helpers.get_default_parser()],
        )
    args = parser.parse_args()
    helpers.configure_logging(args.logging_type, args.loglevel, args.logfile)

    logging.info('starting')

    mqtt_thread = helpers.MQTT_Client('skynet', keepalive=60, heartbeat=True, daemon=True)
    mqtt_thread.start()

    skynet_thread = MQTT_Skynet_Thread(mqtt_thread)
    skynet_thread.start()

    while mqtt_thread.is_alive() and skynet_thread.is_alive():
        time.sleep(1)

    logging.info('exiting')
    sys.stdout.flush()
    sys.stderr.flush()
    sys.exit(1)

if __name__ == "__main__":
    main()
