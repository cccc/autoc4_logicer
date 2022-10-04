# LEGACY

import time
from bs4 import BeautifulSoup
import urllib.request
from subprocess import Popen

#Popen(['/usr/bin/python2.7', '/home/autoc4/logicer/irc_topicer.py', status])

#foobar = []

def scrape():
    #global foobar
    #r = urllib.request.urlopen('https://bbb.daten.reisen/b/XXX-XXX-XXX')
    req = urllib.request.Request('https://bbb.daten.reisen/b/XXX-XXX-XXX', headers={
            'Accept-Language': 'en-US,en;q=0.5',
        })
    r = urllib.request.urlopen(req)
    s = r.read()
    #foobar.append(s)
    b = BeautifulSoup(s, 'html.parser')
    t = b.find('button').get_text()
    return 'Teilnehmen' in t or 'Join' in t

def set_new_state(newstate):
    Popen(['/usr/bin/python2.7', '/home/autoc4/logicer/irc_bbb_topicer.py', newstate])

def main():
    counter = 0
    last_state = None
    while True:
        try:
            print('scraping')
            newstate = 'open' if scrape() else 'closed'
            print('current state is: {}'.format(newstate))
            if last_state != newstate or counter == 0:
                print('state change, starting irc bot')
                set_new_state(newstate)
            last_state = newstate
            counter += 1
            counter = counter % (60 * 24)
            print('sleeping')
        except:
            print('exception')
        time.sleep(60)

if __name__ == '__main__':
    main()
