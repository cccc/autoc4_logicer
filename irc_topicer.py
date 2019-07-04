#!/usr/bin/env python

"""
Connects to freenode and sets the topic of the c4 irc channel.

Usage:
    python irc_topicer.py {open|closed}
"""

from twisted.words.protocols import irc
from twisted.internet.protocol import Factory
from twisted.internet import ssl, reactor
from twisted.internet.endpoints import TCP4ClientEndpoint
from twisted.internet.endpoints import SSL4ClientEndpoint
from datetime import datetime
import re
import sys
import time

import config

class Bot(irc.IRCClient):
    def __init__(self, factory):
        self.nickname = factory.bot_nickname
        self.status = factory.status
        self.identified = False

    def signedOn(self):
        self.setNick(self.nickname)
        self.msg("NickServ", "identify c4status {}".format(config.irc_password))
        print("Bot online with nickname: %s" % (self.nickname,)) #DEBUG

    def noticed(self, sender, recipient, msg):
        if re.search(r'You are now identified', msg):
            print("Logged in.")
            self.identifed = True
            #self.sendLine("TOPIC #cccc")
            self.join("#cccc")

    def irc_RPL_TOPIC(self, prefix, params):
        self.updateTopic(params[2])

    def updateTopic(self, oldtopic):
        print("Old Topic: %s" % oldtopic)
        topic = re.sub(' \| Club ist offen', '', oldtopic)
        if self.status == "open":
            topic += " | Club ist offen"
        if topic == oldtopic:
            print("not updating topic")
        else:
            print("updating topic to: %s" % topic)
            self.msg("ChanServ", "topic #cccc %s" % topic)
        reactor.callLater(2, self.gtfo)

    def gtfo(self):
        self.quit()
        reactor.stop()

class BotFactory(Factory):
    def __init__(self, nickname, status):
        self.bot_nickname = nickname
        self.status = status
        
    def buildProtocol(self, addr):
        return Bot(self)

if __name__ == "__main__":
    if sys.argv[1] == "open":
        status = "open"
    elif sys.argv[1] == "closed":
        status = "closed"
    else:
        print("Alter, l2syntax!")
        sys.exit(0) 
    endpoint = SSL4ClientEndpoint(reactor, "chat.freenode.net", 6697, ssl.CertificateOptions())
    d = endpoint.connect(BotFactory("c4status", status))
    reactor.run()
