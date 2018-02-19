#!/usr/bin/python3
# -*- coding: utf-8 -*-

import configargparse
import asyncio
import discord
import requests
import time
import os
import re
import sys
import json
from collections import OrderedDict
from datetime import datetime


def get_path(path):
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(__file__), path)
    return path


def get_args():
    if '-cf' not in sys.argv and '--config' not in sys.argv:
        config_files = [get_path('./config/config.ini')]
    parser = configargparse.ArgParser(default_config_files=config_files)
    parser.add_argument(
        '-cf', '--config',
        is_config_file=True,
        help='Configuration file'
    )
    parser.add_argument(
        '-token', '--bot_token',
        type=str,
        help='Token for your account',
        required=True
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
        '-ar', '--admin_role',
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
            "Set to False if you don't want to be alerted if a user joins " +
            "a blacklisted server. default: True"
        )
    )
    parser.add_argument(
        '-mm', '--monitor_messages',
        action='store_false',
        default=True,
        help=(
            "Set to False if you don't want to be alerted of messages " +
            "containing coords from your geofences. default: True"
        )
    )
    parser.add_argument(
        '-mum', '--monitor_user_message',
        action='store_true',
        default=False,
        help=(
            "Set to True if you only want to be alerted of messages " +
            "containing coords in your geofences posted only by your users." +
            "default: False"
        )
    )
    parser.add_argument(
        '-gf', '--geofences',
        type=str,
        action='append',
        default='geofence.txt',
        help='File containing geofences. default: geofence.txt'
    )

    args = parser.parse_args()

    return args


def send_webhook(url, payload):
    resp = requests.post(url, json=payload, timeout=5)
    if resp.ok is True:
        time.sleep(0.25)
    else:
        print("Discord response was {}".format(resp.content))
        raise requests.exceptions.RequestException(
            "Response received {}, webhook not accepted.".format(
                resp.status_code))


def try_sending(name, send_alert, args, max_attempts=3):
    for i in range(max_attempts):
        try:
            send_alert(**args)
            return
        except Exception as e:
            print((
                "Encountered error while sending notification ({}: {})"
            ).format(type(e).__name__, e))
            print((
                "{} is having connection issues. {} attempt of {}."
            ).format(name, i+1, max_attempts))
            time.sleep(5)
    print("Could not send notification... Giving up.")


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
                    print("Geofence {} added.".format(name))
                    points = []
                name = match_name.group(0)
            elif coor_patter.match(line):
                lat, lng = map(float, line.split(","))
                points.append([lat, lng])
            else:
                print((
                    "Geofence was unable to parse this line: {}"
                ).format(line))
                print("All lines should be either '[name]' or 'lat,lng'.")
                sys.exit(1)
        geofences[name] = Geofence(name, points)
        print("Geofence {} added!".format(name))
        return geofences
    except IOError as e:
        print((
            "IOError: Please make sure a file with read/write permissions " +
            "exist at {}"
        ).format(file_path))
    except Exception as e:
        print((
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
                if p1x == p2x or x <= xinters:
                    inside = not inside
            p1x, p1y = p2x, p2y
        return inside

    def get_name(self):
        return self.__name


client = discord.Client()
args = get_args()
if args.monitor_messages or args.monitor_user_messages:
    geofences = load_geofence_file(get_path(args.geofences))
if args.monitor_users:
    try:
        with open('cache.json') as f:
            cache = json.load(f)
    except Exception:
        cache = {}
users = []
snipers = {}
guilds = {}


@client.event
async def on_ready():
    if str(client.user.id) not in args.ignore_ids:
        args.ignore_ids.append(str(client.user.id))
    print((
        '----------------------------------\n'
        'Connected! Ready to counter-snipe.\n'
        'Username: {}\n'
        'ID: {}\n'
        '------------Guild List------------'
    ).format(client.user.name, client.user.id))
    for guild in client.guilds:
        if ((args.monitor_users or args.monitor_user_messages) and
                str(guild.id) in args.my_server_ids):
            guilds[str(guild.id)] = guild.name
            for member in guild.members:
                if str(member.id) not in users:
                    users.append(str(member.id))
        elif args.monitor_users:
            guilds[str(guild.id)] = guild.name
            for member in guild.members:
                if str(member.id) not in args.ignore_ids:
                    if str(member.id) not in snipers:
                        snipers[str(member.id)] = [str(guild.id)]
                    elif str(guild.id) not in snipers[str(member.id)]:
                        snipers[str(member.id)].append(str(guild.id))
        print(guild.name)
    if args.monitor_users:
        print(
            '---------------------------------------------\n'
            'Current list of users in blacklisted servers:\n'
            '---------------------------------------------'
        )
        bastards = set(snipers).intersection(set(users))
        for member_id in bastards:
            member = discord.utils.get(
                client.get_all_members(),
                id=int(member_id)
            )
            print('{} `{}`'.format(member.display_name, member.id))
            if (member_id not in cache or
                    cache[member_id] != snipers[member_id]):
                descript = '{}\n\n**Servers**\n```'.format(member.mention)
                for guild_id in snipers[member_id]:
                    descript += '{}\n'.format(guilds[guild_id])
                descript += '```\n{}'.format(
                    datetime.time(datetime.now().replace(microsecond=0)))
                webhook = {
                    'url': args.webhook_url,
                    'payload': {
                        'embeds': [{
                            'title': (
                                u"\U0001F3F4" + ' User is in Blacklisted ' +
                                'Server'
                            ),
                            'description': descript,
                            'color': int('0xee281f', 16),
                            'thumbnail': {'url': member.avatar_url}
                        }]
                    }
                }
                try_sending("Discord", send_webhook, webhook)
                cache[member_id] = snipers[member_id]
                with open('cache.json', 'w+') as f:
                    json.dump(cache, f, indent=4)
        for member_id in cache:
            if member_id not in users:
                member = discord.utils.get(
                    client.get_all_members(),
                    id=int(member_id)
                )
                if member is not None:
                    descript = '{}\n\n**Id**\n{}'.format(member, member.id)
                    thumbnail = {'url': member.avatar_url}
                else:
                    descript = '**Id**\n{}'.format(member_id)
                    thumbnail = None
                descript += '\n\n{}'.format(
                    datetime.time(datetime.now().replace(microsecond=0)))
                webhook = {
                    'url': args.webhook_url,
                    'payload': {
                        'embeds': [{
                            'title': u"\uE333" + ' User left the building',
                            'description': descript,
                            'color': int('0xee281f', 16),
                            'thumbnail': thumbnail
                        }]
                    }
                }
                try_sending("Discord", send_webhook, webhook)
                cache.pop(member_id)
                with open('cache.json', 'w+') as f:
                    json.dump(cache, f, indent=4)
                print('{} has left the building.'.format(member.display_name))
            elif member_id not in snipers:
                webhook = {
                    'url': args.webhook_url,
                    'payload': {
                        'embeds': [{
                            'title': (
                                u"\u2705" +
                                ' User is in no Blacklisted Servers'
                            ),
                            'description': '{}\n\n{}'.format(
                                member.mention,
                                datetime.time(datetime.now().replace(
                                    microsecond=0))
                            ),
                            'color': int('0x71cd40', 16),
                            'thumbnail': {'url': member.avatar_url}
                        }]
                    }
                }
                try_sending("Discord", send_webhook, webhook)
                cache.pop(member_id)
                with open('cache.json', 'w+') as f:
                    json.dump(cache, f, indent=4)
                print('{} is not in a blacklisted server.'.format(
                    member.display_name))
    print(
        '--------------------------\n'
        'Monitoring sniping servers\n'
        '--------------------------'
    )


@client.event
async def on_member_join(member):
    if ((args.monitor_users or args.monitor_user_messages) and
            str(member.guild.id) in args.my_server_ids):
        if str(member.id) not in users:
            users.append(str(member.id))
        if args.monitor_users and str(member.id) in snipers:
            descript = '{}\n\n**Servers**\n```'.format(member.mention)
            for guild_id in snipers[str(member.id)]:
                descript += '{}\n'.format(guilds[guild_id])
            descript += '```\n{}'.format(
                datetime.time(datetime.now().replace(microsecond=0)))
            webhook = {
                'url': args.webhook_url,
                'payload': {
                    'embeds': [{
                        'title': (
                            u"\U0001F3F4" + ' User is in Blacklisted Server'
                        ),
                        'description': descript,
                        'color': int('0xee281f', 16),
                        'thumbnail': {'url': member.avatar_url}
                    }]
                }
            }
            try_sending("Discord", send_webhook, webhook)
            cache[str(member.id)] = snipers[str(member.id)]
            with open('cache.json', 'w+') as f:
                json.dump(cache, f, indent=4)
            print('{} is in a blacklisted server.'.format(member.display_name))
    elif args.monitor_users and str(member.id) not in args.ignore_ids:
        if str(member.id) not in snipers:
            snipers[str(member.id)] = [str(member.guild.id)]
        elif str(member.guild.id) not in snipers[str(member.id)]:
            snipers[str(member.id)].append(str(member.guild.id))
        if str(member.id) in users:
            descript = '{}\n\n**Server Joined**\n{}\n'.format(
                member.mention, member.guild.name)
            if len(snipers[str(member.id)]) > 1:
                descript += '\n**All Servers**\n```'
                for guild_id in snipers[str(member.id)]:
                    descript += '{}\n'.format(guilds[guild_id])
                descript += '```'
            descript += '\n{}'.format(
                datetime.time(datetime.now().replace(microsecond=0)))
            webhook = {
                'url': args.webhook_url,
                'payload': {
                    'embeds': [{
                        'title': (
                            u"\U0001F3F4" + ' User joined Blacklisted Server'
                        ),
                        'description': descript,
                        'color': int('0xee281f', 16),
                        'thumbnail': {'url': member.avatar_url}
                    }]
                }
            }
            try_sending("Discord", send_webhook, webhook)
            cache[str(member.id)] = snipers[str(member.id)]
            with open('cache.json', 'w+') as f:
                json.dump(cache, f, indent=4)
            print('{} joined {}.'.format(
                member.display_name, member.guild.name))


@client.event
async def on_member_remove(member):
    if ((args.monitor_users or args.monitor_user_messages) and
            str(member.guild.id) in args.my_server_ids):
        if str(member.id) in users:
            users.remove(str(member.id))
        if args.monitor_users and str(member.id) in snipers:
            webhook = {
                'url': args.webhook_url,
                'payload': {
                    'embeds': [{
                        'title': u"\uE333" + ' User left the building',
                        'description': '{}\n\n**Id**\n{}\n\n{}'.format(
                            member, member.id,
                            datetime.time(datetime.now().replace(
                                microsecond=0))
                        ),
                        'color': int('0xee281f', 16),
                        'thumbnail': {'url': member.avatar_url}
                    }]
                }
            }
            try_sending("Discord", send_webhook, webhook)
            cache.pop(str(member.id))
            with open('cache.json', 'w+') as f:
                json.dump(cache, f, indent=4)
            print('{} has left the building.'.format(member.display_name))
    elif args.monitor_users and str(member.id) not in args.ignore_ids:
        if str(member.id) in snipers and len(snipers[str(member.id)]) <= 1:
            snipers.pop(str(member.id))
        elif (str(member.id) in snipers and
              str(member.guild.id) in snipers[str(member.id)]):
            snipers[str(member.id)].remove(str(member.guild.id))
        if str(member.id) in users:
            descript = '{}\n\n**Server left**\n{}\n'.format(
                member.mention, member.guild.name)
            if str(member.id) in snipers:
                descript += '\n**All Servers**\n```'
                for guild_id in snipers[str(member.id)]:
                    descript += '{}\n'.format(guilds[guild_id])
                descript += '```'
            descript += '\n{}'.format(
                datetime.time(datetime.now().replace(microsecond=0)))
            webhook = {
                'url': args.webhook_url,
                'payload': {
                    'embeds': [{
                        'title': (
                            u"\u274C" + ' User left Blacklisted Server'
                        ),
                        'description': descript,
                        'color': int('0x71cd40', 16),
                        'thumbnail': {'url': member.avatar_url}
                    }]
                }
            }
            try_sending("Discord", send_webhook, webhook)
            if str(member.id) in snipers:
                cache[str(member.id)] = snipers[str(member.id)]
            else:
                cache.pop(str(member.id))
            with open('cache.json', 'w+') as f:
                json.dump(cache, f, indent=4)
            print('{} left {}.'.format(member.display_name, member.guild.name))


@client.event
async def on_message(message):
    if ((args.monitor_messages or
         (args.monitor_user_messages and
          str(message.author.id) in users)) and
        message.channel.guild is not None and
            str(message.guild.id) not in args.my_server_ids):
        alert = False
        msg = message.content.replace(', ', ',').split()
        for word in msg:
            coor_patter = re.compile(
                "[-+]?[0-9]*\.?[0-9]*" + "[ \t]*,[ \t]*" +
                "[-+]?[0-9]*\.?[0-9]*"
            )
            if coor_patter.match(word):
                coords = coor_patter.match(word).group().strip('.').strip(',')
                if ',' in coords:
                    try:
                        lat, lng = map(float, coords.split(","))
                        for name, gf in geofences.items():
                            if gf.contains(lat, lng):
                                alert = True
                    except ValueError:
                        print('!!!!!!!!!!!!!!!!!!!!!!!!!!')
                        print(msg)
                        print(word)
                        print(coords)
                        print('!!!!!!!!!!!!!!!!!!!!!!!!!!')
        if alert is True:
            if str(message.author.id) in users:
                descript = message.author.mention
            else:
                descript = '{} | {}'.format(message.author, message.author.id)
            descript += '\n\n**Server**\n{}\n\n**Message**\n```{}```'.format(
                message.guild.name, message.content)
            webhook = {
                'url': args.webhook_url,
                'payload': {
                    'embeds': [{
                        'title': (
                            u"\U0001F3F4" +
                            ' User posted coords in Blacklisted Server'
                        ),
                        'description': descript,
                        'color': int('0xee281f', 16),
                        'thumbnail': {'url': message.author.avatar_url}
                    }]
                }
            }
            try_sending("Discord", send_webhook, webhook)
            print('{} posted coords in Blacklisted Server.'.format(
                message.author.display_name))
    elif (args.monitor_users and
          len(args.admin_role) > 0 and
          str(message.guild.id) in args.my_server_ids and
          message.content.lower().startswith('!check ')):
        for role in message.author.roles:
            if role.name.lower() in args.admin_role:
                try:
                    msg = int(message.content.lower().split()[1])
                except Exception as e:
                    webhook = {
                        'url': args.webhook_url,
                        'payload': {
                            'embeds': [{
                                'description': (
                                    '{} Not a valid user id.'
                                ).format(message.author.mention),
                                'color': int('0xee281f', 16)
                            }]
                        }
                    }
                    try_sending("Discord", send_webhook, webhook)
                    print('{} sent an invalid user id.'.format(
                        message.author.display_name))
                    break
                member = discord.utils.get(
                    client.get_all_members(),
                    id=msg
                )
                if member is None:
                    webhook = {
                        'url': args.webhook_url,
                        'payload': {
                            'embeds': [{
                                'description': (
                                    '{} Cannot find user with id `{}`.'
                                ).format(message.author.mention, msg),
                                'color': int('0xee281f', 16)
                            }]
                        }
                    }
                    try_sending("Discord", send_webhook, webhook)
                    print('Cannot find user id {}.'.format(msg))
                elif msg in snipers:
                    if str(member.id) in users:
                        descript = '{}\n\n**Servers**\n```'.format(
                            member.mention)
                    else:
                        descript = '{} | {}\n\n**Servers**\n```'.format(
                            member, member.id)
                    for guild_id in snipers[str(member.id)]:
                        descript += '{}\n'.format(guilds[guild_id])
                    descript += '```\n{}'.format(
                        datetime.time(datetime.now().replace(microsecond=0)))
                    webhook = {
                        'url': args.webhook_url,
                        'payload': {
                            'embeds': [{
                                'title': (
                                    u"\U0001F3F4" +
                                    ' User is in Blacklisted Server'
                                ),
                                'description': descript,
                                'color': int('0xee281f', 16),
                                'thumbnail': {'url': member.avatar_url}
                            }]
                        }
                    }
                    try_sending("Discord", send_webhook, webhook)
                    print('{} is in a blacklisted server.'.format(
                        member.display_name))
                else:
                    if str(member.id) in users:
                        descript = member.mention
                    else:
                        descript = '{}\n\n**Id**\n{}'.format(member, member.id)
                    descript += '\n\n{}'.format(
                        datetime.time(datetime.now().replace(microsecond=0)))
                    webhook = {
                        'url': args.webhook_url,
                        'payload': {
                            'embeds': [{
                                'title': (
                                    u"\u2705" +
                                    ' User is in no Blacklisted Servers'
                                ),
                                'description': descript,
                                'color': int('0x71cd40', 16),
                                'thumbnail': {'url': member.avatar_url}
                            }]
                        }
                    }
                    try_sending("Discord", send_webhook, webhook)
                    print('{} is not in a blacklisted server.'.format(
                        member.display_name))


def counter_sniper():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(client.login(args.bot_token, bot=False))
    loop.run_until_complete(client.connect())

###############################################################################


if __name__ == '__main__':
    counter_sniper()
