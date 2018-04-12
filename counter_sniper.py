#!/usr/bin/python3
# -*- coding: utf-8 -*-

import asyncio
import configargparse
import logging.handlers
import os
import re
import sqlite3
import sys
from collections import namedtuple, OrderedDict
from CounterSniper.Hammer import Hammer
from CounterSniper.Monitor import Spy
from CounterSniper.utils import get_path, LoggerWriter

filehandler = logging.handlers.TimedRotatingFileHandler(
    'counter_sniper.log',
    when='midnight',
    backupCount=2,
    encoding='utf-8'
)
consolehandler = logging.StreamHandler()
logging.basicConfig(
    format=(
        '%(asctime)s [%(processName)15.15s][%(name)10.10s][%(levelname)8.8s] '
        '%(message)s'
    ),
    level=logging.INFO,
    handlers=[filehandler, consolehandler]
)

log = logging.getLogger('Server')
sys.stdout = LoggerWriter(log.info)
sys.stderr = LoggerWriter(log.warning)

entries = []


def start_server():
    logging.getLogger("discord").setLevel(logging.WARNING)
    con = sqlite3.connect('counter_sniper.db')
    cur = con.cursor()
    cur.execute(
        'CREATE TABLE IF NOT EXISTS guilds(guild_id TEXT, guild TEXT, '
        'UNIQUE(guild_id) ON CONFLICT IGNORE)'
    )
    parse_settings(con, cur)


def parse_settings(con, cur):
    loop = asyncio.get_event_loop()
    Entry = namedtuple('Entry', 'client event')
    config_files = [
        os.path.join(os.path.dirname(__file__), 'config/config.ini')
    ]
    if '-cf' in sys.argv or '--config' in sys.argv:
        config_files = []
    parser = configargparse.ArgParser(default_config_files=config_files)
    parser.add_argument(
        '-cf', '--config',
        help='Configuration file'
    )
    parser.add_argument(
        '-st', '--spy_token',
        type=str,
        help='Token for your spy account',
        required=True
    )
    parser.add_argument(
        '-ht', '--hammer_token',
        type=str,
        help='Token for your hammer bot (optional)'
    )
    parser.add_argument(
        '-sid', '--my_server_ids',
        type=str,
        action='append',
        default=[],
        help='List of your server IDs',
        required=True
    )
    parser.add_argument(
        '-whurl', '--webhook_url',
        type=str,
        help='Webhook url',
        required=True
    )
    parser.add_argument(
        '-ar', '--admin_roles',
        type=str.lower,
        action='append',
        default=[],
        help='Admin role(s)'
    )
    parser.add_argument(
        '-iid', '--ignore_ids',
        type=str,
        action='append',
        default=[],
        help='List of IDs for users you want the bot to ignore'
    )
    parser.add_argument(
        '-mu', '--monitor_users',
        action='store_false',
        default=True,
        help=(
            "Set to False if you don't want to be alerted if a user joins " 
            "a blacklisted server. default: True"
        )
    )
    parser.add_argument(
        '-mm', '--monitor_messages',
        action='store_false',
        default=True,
        help=(
            "Set to False if you don't want to be alerted of messages " 
            "containing coords from your geofences. default: True"
        )
    )
    parser.add_argument(
        '-mum', '--monitor_user_messages',
        action='store_true',
        default=False,
        help=(
            "Set to True if you only want to be alerted of messages " 
            "containing coords in your geofences posted only by your users." 
            "default: False"
        )
    )
    parser.add_argument(
        '-il', '--invite_listener',
        action='store_false',
        default=True,
        help=(
            "Set to False if you do not want to listen for invites for new "
            "sniping servers. Invite listening requires a hammer token. "
            "default: True"
        )
    )
    parser.add_argument(
        '-msg', '--message_users',
        action='store_true',
        default=False,
        help=(
            "Set to True to send a message to users when they have joined a "
            "blacklisted server. Requires a hammer token. default: False"
        )
    )
    parser.add_argument(
        '-punish', '--punishment',
        type=str.lower,
        default=None,
        choices=[None, 'ban', 'kick'],
        help=(
            "Choose a punishment for joining a blacklisted server.  Options "
            "are 'ban' or 'kick'. Requires a hammer token. default: None"
        )
    )
    parser.add_argument(
        '-timer', '--timer',
        type=int,
        default=900,
        help=(
            "Amount of time before punishment happens in seconds. default: 900"
        )
    )
    parser.add_argument(
        '-gf', '--geofences',
        type=str,
        action='append',
        default='../geofence.txt',
        help='File containing geofences. default: geofence.txt'
    )
    args = parser.parse_args()
    if args.monitor_messages or args.monitor_user_messages:
        geofences = load_geofence_file(get_path(args.geofences))
    else:
        geofences = None
    queue = asyncio.Queue()
    if args.monitor_users:
        cur.execute('DROP TABLE IF EXISTS snipers')
        cur.execute(
            'CREATE TABLE snipers(member_id TEXT, member TEXT, guild_id TEXT, '
            'guild TEXT, UNIQUE(member_id, guild_id) ON CONFLICT IGNORE)'
        )
        cur.execute(
            'CREATE TABLE IF NOT EXISTS cache(member_id TEXT, member TEXT, '
            'guild_id TEXT, guild TEXT, timer TIMESTAMP, '
            'UNIQUE(member_id, guild_id) ON CONFLICT IGNORE)'
        )
    con.commit()
    con.close()
    if (args.invite_listener or
            args.message_users or
            args.punishment is not None):
        h = Hammer(
            my_server_ids=args.my_server_ids,
            message_users=args.message_users,
            monitor_users=args.monitor_users,
            punishment=args.punishment,
            webhook_url=args.webhook_url,
            queue=queue
        )
        log.info('Starting the Hammer bot')
        entries.append(Entry(client=h, event=asyncio.Event()))
        loop.run_until_complete(h.login(args.hammer_token))
        loop.create_task(h.connect())
        loop.create_task(h.webhook())
    s = Spy(
        my_server_ids=args.my_server_ids,
        webhook_url=args.webhook_url,
        ignore_ids=args.ignore_ids,
        admin_roles=args.admin_roles,
        monitor_users=args.monitor_users,
        monitor_messages=args.monitor_messages,
        monitor_user_messages=args.monitor_user_messages,
        invite_listener=args.invite_listener,
        punishment=args.punishment,
        timer=args.timer,
        geofences=geofences,
        queue=queue
    )
    log.info('Starting the Spy bot')
    entries.append(Entry(client=s, event=asyncio.Event()))
    loop.run_until_complete(s.login(args.spy_token, bot=False))
    loop.create_task(s.connect())
    try:
        loop.run_until_complete(check_close(entries))
    except KeyboardInterrupt:
        loop.close()
    except Exception:
        raise Exception


def load_geofence_file(file_path):
    try:
        geofences = OrderedDict()
        name_pattern = re.compile("(?<=\[)([^]]+)(?=\])")
        coor_patter = re.compile(
            "[-+]?[0-9]*\.?[0-9]*" + "[ \t]*,[ \t]*" + "[-+]?[0-9]*\.?[0-9]*")
        with open(file_path, 'r') as f:
            lines = f.read().splitlines()
        name = "geofence"
        points = []
        for line in lines:
            line = line.strip()
            match_name = name_pattern.search(line)
            if match_name:
                if len(points) > 0:
                    geofences[name] = Geofence(name, points)
                    log.info("Geofence {} added.".format(name))
                    points = []
                name = match_name.group(0)
            elif coor_patter.match(line):
                lat, lng = map(float, line.split(","))
                points.append([lat, lng])
            else:
                log.info((
                    "Geofence was unable to parse this line: {}"
                ).format(line))
                log.info("All lines should be either '[name]' or 'lat,lng'.")
                sys.exit(1)
        geofences[name] = Geofence(name, points)
        log.info("Geofence {} added!".format(name))
        return geofences
    except IOError:
        log.info((
            "IOError: Please make sure a file with read/write permissions "
            "exist at {}"
        ).format(file_path))
    except Exception as e:
        log.info((
            "Encountered error while loading Geofence: {}: {}"
        ).format(type(e).__name__, e))
    sys.exit(1)


class Geofence(object):

    def __init__(self, name, points):
        self.__name = name
        self.__points = points
        self.__min_x = points[0][0]
        self.__max_x = points[0][0]
        self.__min_y = points[0][1]
        self.__max_y = points[0][1]
        for p in points:
            self.__min_x = min(p[0], self.__min_x)
            self.__max_x = max(p[0], self.__max_x)
            self.__min_y = min(p[1], self.__min_y)
            self.__max_y = max(p[1], self.__max_y)

    def contains(self, x, y):
        if (self.__max_x < x or
            x < self.__min_x or
            self.__max_y < y or
                y < self.__min_y):
            return False
        inside = False
        p1x, p1y = self.__points[0]
        n = len(self.__points)
        for i in range(1, n + 1):
            p2x, p2y = self.__points[i % n]
            if min(p1y, p2y) < y <= max(p1y, p2y) and x <= max(p1x, p2x):
                if p1y != p2y:
                    xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if x <= xinters:
                        inside = not inside
                else:
                    inside = not inside
            p1x, p1y = p2x, p2y
        return inside

    def get_name(self):
        return self.__name


async def check_close(entry_list):
    futures = [entry.event.wait() for entry in entry_list]
    await asyncio.wait(futures)


###############################################################################


if __name__ == '__main__':
    log.info('CounterSniper is getting ready')
    start_server()
