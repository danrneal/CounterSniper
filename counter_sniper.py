#!/usr/bin/python3
# -*- coding: utf-8 -*-

import configargparse
import asyncio
import discord
import requests
import time
import os
import sys
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
        type=int,
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
        '-iid', '--ignore_ids',
        type=int,
        action='append',
        default=[],
        help='List of IDs for users you want the bot to ignore'
    )

    args = parser.parse_args()

    return args


def send_webhook(url, payload):
    resp = requests.post(url, json=payload, timeout=5)
    if resp.ok is True:
        time.sleep(2)
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
            time.sleep(3)
    print("Could not send notification... Giving up.")


client = discord.Client()
args = get_args()
users = []
snipers = {}


@client.event
async def on_ready():
    await client.change_presence(status=discord.Status.invisible)
    if client.user.id not in args.ignore_ids:
        args.ignore_ids.append(client.user.id)
    print((
        'Connected! Ready to counter-snipe.\n' +
        'Username: {}\n' +
        'ID: {}\n' +
        '--Guild List--'
    ).format(client.user.name, client.user.id))
    for guild in client.guilds:
        if guild.id in args.my_server_ids:
            for member in guild.members:
                users.append(member.id)
        else:
            for member in guild.members:
                if member.id not in args.ignore_ids:
                    if member.id not in snipers:
                        snipers[member.id] = [guild]
                    else:
                        snipers[member.id].append(guild)
        print(guild.name)
    print(
        '---------------\n' +
        'Current list of users in blacklisted servers:'
    )
    bastards = set(snipers).intersection(set(users))
    for member_id in bastards:
        member = discord.utils.get(client.get_all_members(), id=member_id)
        descript = (
            str(member) + ' | ' + str(member.id) +
            '\n\n**Servers**\n```'
        )
        for server in snipers[member.id]:
            descript += server.name + '\n'
        descript += '```\n' + str(datetime.time(datetime.now().replace(
            microsecond=0)))
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
        print('{} `{}`'.format(member.display_name, member.id))
    print(
        '---------------\n'
        'Monitoring new joins'
    )


@client.event
async def on_member_join(member):
    if member.guild.id in args.my_server_ids:
        users.append(member.id)
        if member.id in snipers:
            descript = (
                str(member) + ' | ' + str(member.id) +
                '\n\n**Servers**\n```'
            )
            for server in snipers[member.id]:
                descript += server.name + '\n'
            descript += '```\n' + str(datetime.time(datetime.now().replace(
                microsecond=0)))
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
            print('{} is in a blacklisted server.'.format(member.display_name))
    elif member.id not in args.ignore_ids:
        if member.id not in snipers:
            snipers[member.id] = [member.guild]
        else:
            snipers[member.id].append(member.guild)
        if member.id in users:
            descript = (
                str(member) + ' | ' + str(member.id) +
                '\n\n**Server**\n' + member.guild.name + '\n'
            )
            if len(snipers[member.id]) > 1:
                descript += '\n**Servers**\n```'
                for server in snipers[member.id]:
                    if server.name != member.guild.name:
                        descript += server.name + '\n'
                descript += '```'
            descript += '\n' + str(datetime.time(datetime.now().replace(
                microsecond=0)))
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
            print('{} joined {}.'.format(
                member.display_name, member.guild.name))


@client.event
async def on_member_remove(member):
    if member.guild.id in args.my_server_ids:
        users.remove(member.id)
        if member.id in snipers:
            webhook = {
                'url': args.webhook_url,
                'payload': {
                    'embeds': [{
                        'title': u"\U0001F3F4" + ' User left the building',
                        'description': (
                            str(member) +
                            '\n\n**Id**\n' + str(member.id) +
                            '\n\n' + str(datetime.time(datetime.now().replace(
                                microsecond=0)))
                        ),
                        'color': int('0xee281f', 16),
                        'thumbnail': {'url': member.avatar_url}
                    }]
                }
            }
            try_sending("Discord", send_webhook, webhook)
            print('{} has left the building.'.format(member.display_name))
    elif member.id not in args.ignore_ids:
        if len(snipers[member.id]) <= 1:
            snipers.pop(member.id)
        else:
            snipers[member.id].remove(member.guild)
        if member.id in users:
            descript = (
                str(member) + ' | ' + str(member.id) +
                '\n\n**Server**\n' + member.guild.name + '\n'
            )
            if member.id in snipers:
                descript += '\n**Servers**\n```'
                for server in snipers[member.id]:
                    descript += server.name + '\n'
                descript += '```'
            descript += '\n' + str(datetime.time(datetime.now().replace(
                microsecond=0)))
            webhook = {
                'url': args.webhook_url,
                'payload': {
                    'embeds': [{
                        'title': (
                            u"\U0001F3F4" + ' User left Blacklisted Server'
                        ),
                        'description': descript,
                        'color': int('0x71cd40', 16),
                        'thumbnail': {'url': member.avatar_url}
                    }]
                }
            }
            try_sending("Discord", send_webhook, webhook)
            print('{} left {}.'.format(member.display_name, member.guild.name))


def counter_sniper():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(client.login(args.bot_token, bot=False))
    loop.run_until_complete(client.connect())

###############################################################################


if __name__ == '__main__':
    counter_sniper()
