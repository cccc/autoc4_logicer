import json
import logging
import time


def sanitize_string(s):
    return s.encode('cp437', errors='ignore').decode('cp437')

enabled_modules = []

def register_module(mod):
    enabled_modules.append(mod)
    return mod

class BaseModule():

    name = None
    display_name = None
    subscribe_topics = []
    enabled = False

    def __init__(self, disp):
        self.disp = disp
        self.name = self.__class__.__name__

    def on_mqtt_connect(self, mqtt_client, display_manager):
        """
        Called from the MQTT thread

        Generally modules should not change the DisplayManager's state except through `queue_interrupt`
        """

        if self.subscribe_topics:
            mqtt_client.subscribe(self.subscribe_topics)

    def on_mqtt_message(self, msg, display_manager):
        """
        Called from the MQTT thread

        Generally modules should not change the DisplayManager's state except through `queue_interrupt`
        """

        pass

    def do_init(self):
        pass

    def run_iteration(self):
        pass


@register_module
class InternalStatus(BaseModule):

    display_name = 'Internal Status / Debug Info'

    def do_init(self):
        # self.disp.set_page(0)
        self.disp.set_page(1)

        self.disp.simple_text(1, 0, 0, 'Status:')
        self.disp.simple_text(1, 1, 0, '  Waiting for MQTT')
        self.disp.simple_text(1, 2, 0, '')
        self.disp.simple_text(1, 3, 0, '')

        # self.disp.set_page(1)

    def run_iteration(self):
        time.sleep(.1)

@register_module
class OpenChaos(BaseModule):

    display_name = 'OpenChaos Welcome Screen'

    def do_init(self):
        # self.disp.set_page(0)
        self.disp.set_page(1)

        self.disp.simple_text(1, 0, 0, "╔═══╗              ")
        self.disp.simple_text(1, 1, 0, "║         ║ ╔══╗  ╔═══ ║|, ║")
        self.disp.simple_text(1, 2, 0, "║         ║ ╠══╝  ╠═══ ║'|,║")
        self.disp.simple_text(1, 3, 0, "╚═══╝ ║           ╚═══ ║ |,║")

        self.disp.simple_text(2, 0, 0, "╔═══╗                         im C4 :3")
        self.disp.simple_text(2, 1, 0, "║             ║   ║ ╔═╗ ╔═╗ ╔═╗ ")
        self.disp.simple_text(2, 2, 0, "║             ╠═╣ ╠═╣ ║   ║ ╚═╗")
        self.disp.simple_text(2, 3, 0, "╚═══╝ ║   ║ ║   ║ ╚═╝ ╚═╝")

    def run_iteration(self):
        self.disp.set_page(1)
        time.sleep(3)
        self.disp.set_page(2)
        time.sleep(3)

@register_module
class Music(BaseModule):

    display_name = 'Currently Playing Music'

    subscribe_topics = [
            ('mpd/wohnzimmer/+/json', 0),
        ]

    last_state = None
    last_song = {}
    first_iteration = False
    display_dirty = False

    def write_data(self):
        display_state = {
                'play': 'Playing',
                'stop': 'Stopped',
                'pause': 'Paused',
            }.get(self.last_state, self.last_state)
        artist = self.last_song.get('artist', '')
        album = self.last_song.get('album', '')
        title = self.last_song.get('title', '')
        if not (artist or album or title):
            title = self.last_song.get('file', '')

        self.disp.simple_text(1, 0, 0, sanitize_string(f'MPD Wohnzimmer:   {display_state}'))
        self.disp.simple_text(1, 1, 0, sanitize_string(title))
        self.disp.simple_text(1, 2, 0, sanitize_string(album))
        self.disp.simple_text(1, 3, 0, sanitize_string(artist))
        self.display_dirty = False
        self.first_iteration = True

    def do_init(self):
        # self.disp.set_page(0)
        self.disp.set_page(1)
        self.write_data()
        # self.disp.set_page(1)

    def run_iteration(self):
        if self.display_dirty:
            self.write_data()

        if self.first_iteration:
            self.first_iteration = False
            time.sleep(5)

        else:
            time.sleep(.1)

    def on_mqtt_message(self, msg, display_manager):
        if msg.topic == 'mpd/wohnzimmer/state/json':
            try:
                new_state = json.loads(msg.payload.decode())['state']
            except:
                logging.exception('Error while processing message for {self.name} module')
                return

            if new_state != self.last_state:
                self.last_state = new_state
                self.display_dirty = True
                if not msg.retain:
                    display_manager.queue_interrupt(self.name)

        if msg.topic == 'mpd/wohnzimmer/song/json':
            try:
                new_song = json.loads(msg.payload.decode())
            except:
                logging.exception('Error while processing message for {self.name} module')
                return

            if new_song != self.last_song:
                self.last_song = new_song
                self.display_dirty = True
                if not msg.retain:
                    display_manager.queue_interrupt(self.name)

@register_module
class Text(BaseModule):

    display_name = 'Custom Text Messages'

    default_text_data = [
            "Hier könnte ihr Text stehen",
            "Hier auch",
            "hui, so viele Zeilen",
            "... wow",
        ]
    text_data = default_text_data

    first_iteration = False
    display_dirty = False

    def write_data(self):
        self.disp.simple_text(1, 0, 0, sanitize_string(self.text_data[0]))
        self.disp.simple_text(1, 1, 0, sanitize_string(self.text_data[1]))
        self.disp.simple_text(1, 2, 0, sanitize_string(self.text_data[2]))
        self.disp.simple_text(1, 3, 0, sanitize_string(self.text_data[3]))
        self.display_dirty = False
        self.first_iteration = True

    def do_init(self):
        # self.disp.set_page(0)
        self.disp.set_page(1)
        self.write_data()
        # self.disp.set_page(1)

    def run_iteration(self):
        if self.display_dirty:
            self.write_data()

        if self.first_iteration:
            self.first_iteration = False
            time.sleep(5)

        else:
            time.sleep(.1)

    def on_mqtt_message(self, msg, display_manager):
        if msg.topic != 'busleiste/modules/Text/settings':
            return

        if not msg.payload:
            # reset text data on empty message
            self.text_data = self.default_text_data

        else:
            try:
                data = json.loads(msg.payload.decode())
                new_data = [
                        str(data[0]),
                        str(data[1]),
                        str(data[2]),
                        str(data[3]),
                    ]

            except:
                logging.exception('Error while processing message for {self.name} module')
                return
            self.text_data = new_data

        self.display_dirty = True
        if not msg.retain:
            display_manager.queue_interrupt(self.name)
