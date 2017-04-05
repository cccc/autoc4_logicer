import argparse
import logging
from systemd.journal import JournalHandler


def get_default_parser():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--logging-type', default='stdout', choices=['stdout', 'file', 'journald'])
    parser.add_argument('--logfile', default='/var/log/mqtt-mpd-transport.log', help='Only used for logging-type=file')
    parser.add_argument('--loglevel', default='debug', help='Standard python logging levels error,warning,info,debug')
    return parser


def configure_logging(logging_type, loglevel, logfile=None):
    # assuming loglevel is bound to the string value obtained from the
    # command line argument. Convert to upper case to allow the user to
    # specify --log=DEBUG or --log=debug

    numeric_level = getattr(logging, loglevel.upper(), None)

    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % loglevel)

    if logging_type == 'stdout':
        logging.basicConfig(
                format='%(asctime)s [%(levelname)s]: %(message)s',
                level=numeric_level
            )
    elif logging_type == 'file':
        assert logfile is not None
        logging.basicConfig(
                filename=logfile,
                format='%(asctime)s [%(levelname)s]: %(message)s',
                level=numeric_level
            )
    elif logging_type == 'journald':
        logging.basicConfig(
                handlers=[JournalHandler()],
                format='%(message)s',
                level=numeric_level
            )
    else:
        assert False
