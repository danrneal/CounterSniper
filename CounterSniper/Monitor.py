import discord
import logging
import re
import sqlite3
from datetime import datetime, timedelta
from CounterSniper.utils import send_webhook, try_sending

log = logging.getLogger('Spy')

guilds = {}
users = []


class Spy(discord.Client):

    def __init__(self, my_server_ids, webhook_url, ignore_ids, admin_roles,
                 monitor_users, monitor_messages, monitor_user_messages,
                 invite_listener, punishment, timer, geofences, queue):
        super(Spy, self).__init__()
        self.__my_server_ids = my_server_ids
        self.__webhook_url = webhook_url
        self.__ignore_ids = ignore_ids
        self.__admin_roles = admin_roles
        self.__monitor_users = monitor_users
        self.__monitor_messages = monitor_messages
        self.__monitor_user_messages = monitor_user_messages
        self.__invite_listener = invite_listener
        self.__punishment = punishment
        if self.__punishment == 'ban':
            self.__punish_str = 'banned'
        else:
            self.__punish_str = 'kicked'
        self.__timer = timer
        self.__geofences = geofences
        self.__queue = queue

    async def on_ready(self):
        log.info('----------------------------------')
        log.info('Connected! Ready to counter-snipe.')
        log.info('User: {}'.format(self.user))
        log.info('ID: {}'.format(self.user.id))
        log.info('----------------------------------')
        if str(self.user.id) not in self.__ignore_ids:
            self.__ignore_ids.append(str(self.user.id))
        con = sqlite3.connect('counter_sniper.db')
        cur = con.cursor()
        for guild in self.guilds:
            guilds[str(guild.id)] = str(guild)
            if ((self.__monitor_users or self.__monitor_user_messages) and
                    str(guild.id) in self.__my_server_ids):
                for role in guild.roles:
                    if role.name.lower() in self.__admin_roles:
                        self.__admin_roles.remove(role.name.lower())
                        self.__admin_roles.append(role)
                for member in guild.members:
                    if str(member.id) not in users:
                        users.append(str(member.id))
            elif self.__monitor_users:
                log.info(guild)
                for member in guild.members:
                    if str(member.id) not in self.__ignore_ids:
                        cur.execute(
                            'INSERT INTO snipers '
                            '(member_id, member, guild_id, guild) '
                            'VALUES (?, ?, ?, ?)',
                            (
                                str(member.id), str(member),
                                str(member.guild.id), str(member.guild)
                            )
                        )
        old_guilds = []
        cur.execute(
            'SELECT * '
            'FROM guilds'
        )
        for guild_info in cur.fetchall():
            if guild_info[0] not in guilds:
                self.remove_guild(cur, guild_info[1], guild_info[0])
            else:
                old_guilds.append(guild_info[0])
                if guild_info[1] != guilds[guild_info[0]]:
                    guild = self.get_guild(int(guild_info[0]))
                    self.update_guild(cur, guild)
        for guild in self.guilds:
            if str(guild.id) not in old_guilds:
                self.add_guild(cur, guild)
        con.commit()
        if self.__monitor_users:
            queries = [users[x:x+999] for x in range(0, len(users), 999)]
            snipers = []
            for query in queries:
                cur.execute(
                    'SELECT member_id, guild_id '
                    'FROM snipers '
                    'WHERE member_id IN ({})'.format(
                        ', '.join('?'*len(query))),
                    tuple(query)
                )
                snipers += cur.fetchall()
            removed = []
            cache = {}
            cur.execute(
                'SELECT member_id, guild_id, member, guild '
                'FROM cache'
            )
            for member_info in cur.fetchall():
                if member_info[0] in removed:
                    pass
                elif member_info[0] not in users:
                    self.remove_member(cur, member_info[2], member_info[0])
                    removed.append(member_info[0])
                elif member_info[:2] not in snipers:
                    member = discord.utils.get(
                        self.get_all_members(),
                        id=int(member_info[0])
                    )
                    await self.remove_sniper(
                        cur, member, member_info[3], member_info[1]
                    )
                else:
                    if member_info[0] not in cache:
                        cache[member_info[0]] = [member_info[1]]
                    else:
                        cache[member_info[0]].append(member_info[1])
                    member = discord.utils.get(
                        self.get_all_members(),
                        id=int(member_info[0])
                    )
                    if member_info[2] != str(member):
                        self.update_member(cur, member)
            added = []
            for member_info in snipers:
                if member_info[0] in added:
                    pass
                elif member_info[0] not in cache:
                    member = discord.utils.get(
                        self.get_all_members(),
                        guild__id=int(member_info[1]),
                        id=int(member_info[0])
                    )
                    await self.add_member(cur, member)
                    added.append(member_info[0])
                elif member_info[1] not in cache[member_info[0]]:
                    member = discord.utils.get(
                        self.get_all_members(),
                        guild__id=int(member_info[1]),
                        id=int(member_info[0])
                    )
                    await self.add_sniper(cur, member)
            con.commit()
        con.close()
        payload = {'event': 'start'}
        await self.__queue.put(payload)
        log.info('----------- Spy bot finished setting up')

    def update_guild(self, cur, guild):
        cur.execute(
            'UPDATE guilds '
            'SET guild = ? '
            'WHERE guild_id = ?',
            (str(guild), str(guild.id))
        )
        if self.__monitor_users:
            cur.execute(
                'UPDATE cache '
                'SET guild = ? '
                'WHERE guild_id = ?',
                (str(guild), str(guild.id))
            )

    async def on_guild_update(self, before, after):
        if str(before) != str(after):
            guilds[str(after.id)] = str(after)
            con = sqlite3.connect('counter_sniper.db')
            cur = con.cursor()
            self.update_guild(cur, after)
            if self.__monitor_users:
                cur.execute(
                    'UPDATE snipers '
                    'SET guild = ? '
                    'WHERE guild_id = ?',
                    (str(after), str(after.id))
                )
            con.commit()
            con.close()

    def add_guild(self, cur, guild):
        cur.execute(
            'INSERT INTO guilds (guild_id, guild) '
            'VALUES (?, ?)',
            (str(guild.id), str(guild))
        )
        webhook = {
            'url': self.__webhook_url,
            'payload': {
                'embeds': [{
                    'title': (
                            u"\u2705" + ' CounterSniper added to a server'
                    ),
                    'description': '\n**Server**\n{}\n\n{}'.format(
                        guild,
                        datetime.time(datetime.now().replace(microsecond=0))
                    ),
                    'color': int('0x71cd40', 16),
                    'thumbnail': {'url': guild.icon_url}
                }]
            }
        }
        try_sending("Discord", send_webhook, webhook)
        log.info('CounterSniper was added to {}.'.format(guild))

    async def on_guild_join(self, guild):
        guilds[str(guild.id)] = str(guild)
        con = sqlite3.connect('counter_sniper.db')
        cur = con.cursor()
        self.add_guild(cur, guild)
        if ((self.__monitor_users or self.__monitor_user_messages) and
                str(guild.id) in self.__my_server_ids):
            for member in guild.members:
                if str(member.id) not in users:
                    users.append(str(member.id))
                    cur.execute(
                        'SELECT member_id '
                        'FROM snipers '
                        'WHERE member_id = ?',
                        (str(member.id))
                    )
                    is_sniper = cur.fetchone()
                    if is_sniper is not None:
                        await self.add_member(cur, member)
        elif self.__monitor_users:
            for member in guild.members:
                if str(member.id) not in self.__ignore_ids:
                    cur.execute(
                        'INSERT INTO snipers '
                        '(member_id, member, guild_id, guild) '
                        'VALUES (?, ?, ?, ?)',
                        (
                            str(member.id), str(member),
                            str(member.guild.id), str(member.guild)
                        )
                    )
                    con.commit()
                    if str(member.id) in users:
                        await self.add_sniper(cur, member)
        con.commit()
        con.close()

    def remove_guild(self, cur, guild, guild_id, guild_icon_url=None):
        cur.execute(
            'DELETE FROM guilds '
            'WHERE guild_id = ?',
            (str(guild_id),)
        )
        webhook = {
            'url': self.__webhook_url,
            'payload': {
                'embeds': [{
                    'title': (
                        u"\u274C" + ' CounterSniper removed from a server'
                    ),
                    'description': '\n**Server**\n{}\n\n{}'.format(
                        guild,
                        datetime.time(datetime.now().replace(microsecond=0))
                    ),
                    'color': int('0xee281f', 16),
                    'thumbnail': {'url': guild_icon_url}
                }]
            }
        }
        if guild_icon_url is None:
            webhook['payload']['embeds'][0].pop('thumbnail')
        try_sending("Discord", send_webhook, webhook)
        log.info('CounterSniper was removed from {}.'.format(guild))

    async def on_guild_remove(self, guild):
        guilds.pop(str(guild.id))
        con = sqlite3.connect('counter_sniper.db')
        cur = con.cursor()
        self.remove_guild(cur, guild, guild.id, guild.icon_url)
        if ((self.__monitor_users or self.__monitor_user_messages) and
                str(guild.id) in self.__my_server_ids):
            for member in guild.members:
                users.remove(str(member.id))
            for guild_id in self.__my_server_ids:
                my_guild = self.get_guild(int(guild_id))
                if my_guild is None:
                    continue
                for member in my_guild.members:
                    if str(member.id) not in users:
                        users.append(str(member.id))
            for member in guild.members:
                if str(member.id) not in users:
                    self.remove_member(
                        cur, member, member.id, member.avatar_url
                    )
        elif self.__monitor_users:
            cur.execute(
                'DELETE FROM snipers '
                'WHERE guild_id = ?',
                (str(guild.id),)
            )
            con.commit()
            for member in guild.members:
                if (str(member.id) in users and
                        str(member.id) not in self.__ignore_ids):
                    await self.remove_sniper(
                        cur, member, member.guild, member.guild.id
                    )
        con.commit()
        con.close()

    def update_member(self, cur, member):
        cur.execute(
            'UPDATE cache '
            'SET member = ? '
            'WHERE member_id = ?',
            (str(member), str(member.id))
        )

    async def on_member_update(self, before, after):
        if self.__monitor_users and str(before) != str(after):
            con = sqlite3.connect('counter_sniper.db')
            cur = con.cursor()
            self.update_member(cur, after)
            cur.execute(
                'UPDATE snipers '
                'SET member = ? '
                'WHERE member_id = ?',
                (str(after), str(after.id))
            )
            con.commit()
            con.close()

    async def add_member(self, cur, member):
        cur.execute(
            'SELECT guild_id '
            'FROM snipers '
            'WHERE member_id = ?',
            (str(member.id),)
        )
        sniper_guilds = cur.fetchall()
        if len(sniper_guilds) > 0:
            descript = '{} | {}\n{}\n\n**Servers**\n```\n'.format(
                member, member.id, member.mention)
            if member.joined_at < datetime.utcnow() - timedelta(minutes=5):
                seconds = max(86400, self.__timer)
                timer = (
                    datetime.utcnow().replace(microsecond=0) +
                    timedelta(seconds=seconds)
                )
            else:
                seconds = self.__timer
                timer = (
                    datetime.utcnow().replace(microsecond=0) +
                    timedelta(seconds=self.__timer)
                )
            if seconds > 5400:
                time_str = '{} hours'.format(seconds / 3600)
            else:
                time_str = '{} minutes'.format(seconds / 60)
            for guild_info in sniper_guilds:
                descript += '{}\n'.format(guilds[guild_info[0]])
                cur.execute(
                    'INSERT INTO cache '
                    '(member_id, member, guild_id, guild, timer) '
                    'VALUES (?, ?, ?, ?, ?)',
                    (
                        str(member.id), str(member), guild_info[0],
                        guilds[guild_info[0]], timer
                    )
                )
                payload = {
                    'timer': timer,
                    'member_id': member.id,
                    'content': (
                        "Whoops!  It looks like you have joined a blacklisted "
                        "server!  You will need to leave `{}` in the next "
                        "`{}` to avoid being `{}`.  Sorry for the "
                        "inconvenience!  Please refer to the server rules or "
                        "contact an administrator for more information."
                    ).format(
                        guilds[guild_info[0]], time_str, self.__punish_str
                    ),
                    'event': 'msg'
                }
                await self.__queue.put(payload)
            descript += '```\n{}'.format(
                datetime.time(datetime.now().replace(microsecond=0)))
            webhook = {
                'url': self.__webhook_url,
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
            log.info('{} is in a blacklisted server.'.format(member))

    async def add_sniper(self, cur, member):
        if member.joined_at < datetime.utcnow() - timedelta(minutes=5):
            seconds = max(86400, self.__timer)
            timer = (
                datetime.utcnow().replace(microsecond=0) +
                timedelta(seconds=seconds)
            )
        else:
            seconds = self.__timer
            timer = (
                datetime.utcnow().replace(microsecond=0) +
                timedelta(seconds=self.__timer)
            )
        if seconds > 5400:
            time_str = '{} hours'.format(seconds / 3600)
        else:
            time_str = '{} minutes'.format(seconds / 60)
        cur.execute(
            'INSERT INTO cache '
            '(member_id, member, guild_id, guild, timer) '
            'VALUES (?, ?, ?, ?, ?)',
            (
                str(member.id), str(member), str(member.guild.id),
                guilds[str(member.guild.id)], timer
            )
        )
        payload = {
            'timer': timer,
            'member_id': member.id,
            'content': (
                "Whoops!  It looks like you have joined a blacklisted "
                "server!  You will need to leave `{}` in the next "
                "`{}` to avoid being `{}`.  Sorry for the "
                "inconvenience!  Please refer to the server rules or "
                "contact an administrator for more information."
            ).format(
                guilds[str(member.guild.id)], time_str, self.__punish_str
            ),
            'event': 'msg'
        }
        await self.__queue.put(payload)
        cur.execute(
            'SELECT guild_id '
            'FROM snipers '
            'WHERE member_id = ?',
            (str(member.id),)
        )
        sniper_guilds = cur.fetchall()
        descript = '{} | {}\n{}\n\n**Server Joined**\n{}\n'.format(
            member, member.id, member.mention, member.guild)
        if len(sniper_guilds) > 1:
            descript += '\n**All Servers**\n```\n'
            for guild_info in sniper_guilds:
                descript += '{}\n'.format(guilds[guild_info[0]])
            descript += '```'
        descript += '\n{}'.format(
            datetime.time(datetime.now().replace(microsecond=0)))
        webhook = {
            'url': self.__webhook_url,
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
        log.info('{} joined {}.'.format(member, member.guild))

    async def on_member_join(self, member):
        if ((self.__monitor_users or self.__monitor_user_messages) and
                str(member.guild.id) in self.__my_server_ids):
            if str(member.id) not in users:
                users.append(str(member.id))
            if self.__monitor_users:
                con = sqlite3.connect('counter_sniper.db')
                cur = con.cursor()
                await self.add_member(cur, member)
                con.commit()
                con.close()
        elif self.__monitor_users and str(member.id) not in self.__ignore_ids:
            con = sqlite3.connect('counter_sniper.db')
            cur = con.cursor()
            cur.execute(
                'INSERT INTO snipers '
                '(member_id, member, guild_id, guild) '
                'VALUES (?, ?, ?, ?)',
                (
                    str(member.id), str(member), str(member.guild.id),
                    str(member.guild)
                )
            )
            con.commit()
            if str(member.id) in users:
                await self.add_sniper(cur, member)
            con.commit()
            con.close()

    def remove_member(self, cur, member, member_id, member_avatar_url=None):
        cur.execute(
            'DELETE FROM cache '
            'WHERE member_id = ?',
            (str(member_id),)
        )
        webhook = {
            'url': self.__webhook_url,
            'payload': {
                'embeds': [{
                    'title': u"\u274C" + ' User left the building',
                    'description': '{}\n\n**Id**\n{}\n\n{}'.format(
                        member, member_id,
                        datetime.time(datetime.now().replace(microsecond=0))
                    ),
                    'color': int('0xee281f', 16),
                    'thumbnail': {'url': member_avatar_url}
                }]
            }
        }
        if member_avatar_url is None:
            webhook['payload']['embeds'][0].pop('thumbnail')
        try_sending("Discord", send_webhook, webhook)
        log.info('{} has left the building.'.format(member))

    async def remove_sniper(self, cur, member, guild, guild_id):
        cur.execute(
            'DELETE FROM cache '
            'WHERE member_id = ? AND guild_id = ?',
            (str(member.id), str(guild_id))
        )
        cur.execute(
            'SELECT guild_id '
            'FROM snipers '
            'WHERE member_id = ?',
            (str(member.id),)
        )
        sniper_guilds = cur.fetchall()
        descript = '{} | {}\n{}\n\n**Server left**\n{}\n'.format(
            member, member.id, member.mention, guild)
        if len(sniper_guilds) > 0:
            descript += '\n**All Servers**\n```\n'
            for guild_info in sniper_guilds:
                descript += '{}\n'.format(guilds[guild_info[0]])
            descript += '```'
        else:
            payload = {
                'member_id': member.id,
                'content': (
                    "It appears you have left all blacklisted servers, you "
                    "are all set!  Thank you for your understanding!"
                ),
                'event': 'msg'
            }
            await self.__queue.put(payload)
        descript += '\n{}'.format(
            datetime.time(datetime.now().replace(microsecond=0)))
        webhook = {
            'url': self.__webhook_url,
            'payload': {
                'embeds': [{
                    'title': (
                            u"\u2705" + ' User left Blacklisted Server'
                    ),
                    'description': descript,
                    'color': int('0x71cd40', 16),
                    'thumbnail': {'url': member.avatar_url}
                }]
            }
        }
        try_sending("Discord", send_webhook, webhook)
        log.info('{} left {}.'.format(member, guild))

    async def on_member_remove(self, member):
        if ((self.__monitor_users or self.__monitor_user_messages) and
                str(member.guild.id) in self.__my_server_ids):
            users.remove(str(member.id))
            for guild_id in self.__my_server_ids:
                my_guild = self.get_guild(int(guild_id))
                if my_guild is None:
                    continue
                for member in my_guild.members:
                    if str(member.id) not in users:
                        users.append(str(member.id))
            if self.__monitor_users:
                con = sqlite3.connect('counter_sniper.db')
                cur = con.cursor()
                cur.execute(
                    'SELECT member_id '
                    'FROM cache '
                    'WHERE member_id = ?',
                    (str(member.id),)
                )
                in_cache = cur.fetchone()
                if in_cache is not None:
                    self.remove_member(
                        cur, member, member.id, member.avatar_url
                    )
                    con.commit()
                con.close()
        elif self.__monitor_users and str(member.id) not in self.__ignore_ids:
            con = sqlite3.connect('counter_sniper.db')
            cur = con.cursor()
            cur.execute(
                'DELETE FROM snipers '
                'WHERE member_id = ? AND guild_id = ?',
                (str(member.id), str(member.guild.id))
            )
            con.commit()
            if str(member.id) in users:
                await self.remove_sniper(
                    cur, member, member.guild, member.guild.id
                )
            con.commit()
            con.close()

    async def on_message(self, message):
        if (message.guild is not None and
                str(message.guild.id) not in self.__my_server_ids):
            if (self.__monitor_messages or
                    (self.__monitor_user_messages and
                     str(message.author.id) in users)):
                coor_patter = re.compile(
                    "[-+]?[0-9]*\.?[0-9]*" + "[ \t]*,[ \t]*" +
                    "[-+]?[0-9]*\.?[0-9]*"
                )
                msg = message.content.replace(', ', ',').replace('- ', '-')
                match = re.search(coor_patter, msg)
                alert = False
                if match:
                    coords = match.group(0)
                    try:
                        lat, lng = map(float, coords.split(","))
                        for name, gf in self.__geofences.items():
                            if gf.contains(lat, lng):
                                alert = True
                    except ValueError:
                        pass
                if alert:
                    if str(message.author.id) in users:
                        descript = message.author.mention
                    else:
                        descript = '{} | {}'.format(
                            message.author, message.author.id)
                    descript += ((
                        '\n\n**Server**\n{}\n\n**Message**\n```\n{}\n```\n{}'
                    ).format(
                        message.guild, message.content,
                        datetime.time(datetime.now().replace(microsecond=0))
                    ))
                    webhook = {
                        'url': self.__webhook_url,
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
                    log.info('{} posted coords in Blacklisted Server.'.format(
                        message.author))
            if self.__invite_listener:
                invite_patter = re.compile(
                    "(?:https?://)?(?:www\.)?discord\.gg/\S+")
                match = re.search(invite_patter, message.content)
                if match:
                    payload = {
                        'invite': match.group(0),
                        'guilds': guilds,
                        'posted': str(message.guild),
                        'event': 'invite'
                    }
                    await self.__queue.put(payload)
        elif (self.__monitor_users and
                len(self.__admin_roles) > 0 and
                message.guild is not None and
                str(message.guild.id) in self.__my_server_ids and
                message.content.lower().startswith('!check ') and
                not set(self.__admin_roles).isdisjoint(message.author.roles)):
            if len(message.mentions) == 1:
                member = message.mentions[0]
                member_id = member.id
            else:
                try:
                    member_id = int(message.content.lower().split()[1])
                    member = discord.utils.get(
                        self.get_all_members(),
                        id=member_id
                    )
                except (ValueError, IndexError):
                    webhook = {
                        'url': self.__webhook_url,
                        'payload': {
                            'embeds': [{
                                'description': (
                                    '{} Not a valid user id.'
                                ).format(message.author.mention),
                                'color': int('0xee281f', 16),
                            }]
                        }
                    }
                    try_sending("Discord", send_webhook, webhook)
                    log.info('{} sent an invalid user id.'.format(
                        message.author))
                    return
            con = sqlite3.connect('counter_sniper.db')
            cur = con.cursor()
            cur.execute(
                'SELECT guild_id, guild '
                'FROM snipers '
                'WHERE member_id = ?',
                (str(member_id),)
            )
            sniper_guilds = cur.fetchall()
            con.close()
            if member is None and len(sniper_guilds) == 0:
                webhook = {
                    'url': self.__webhook_url,
                    'payload': {
                        'embeds': [{
                            'description': (
                                '{} Cannot find user with id `{}`.'
                            ).format(message.author.mention, member_id),
                            'color': int('0xee281f', 16),
                        }]
                    }
                }
                try_sending("Discord", send_webhook, webhook)
                log.info('Cannot find user id {}.'.format(member_id))
            elif len(sniper_guilds) > 0:
                descript = '{} | {}'.format(member, member_id)
                member_avatar_url = None
                if member is not None:
                    descript += '\n{}'.format(member.mention)
                    member_avatar_url = member.avatar_url
                descript += '\n\n**Servers**\n```\n'
                for guild_info in sniper_guilds:
                    descript += '{}\n'.format(guild_info[1])
                descript += '```\n{}'.format(
                    datetime.time(datetime.now().replace(microsecond=0)))
                webhook = {
                    'url': self.__webhook_url,
                    'payload': {
                        'embeds': [{
                            'title': (
                                u"\U0001F3F4" +
                                ' User is in Blacklisted Server'
                            ),
                            'description': descript,
                            'color': int('0xee281f', 16),
                            'thumbnail': {'url': member_avatar_url}
                        }]
                    }
                }
                if member_avatar_url is None:
                    webhook['payload']['embeds'][0].pop('thumbnail')
                try_sending("Discord", send_webhook, webhook)
                log.info('{} is in a blacklisted server.'.format(member))
            else:
                webhook = {
                    'url': self.__webhook_url,
                    'payload': {
                        'embeds': [{
                            'title': (
                                u"\u2705" +
                                ' User is in no Blacklisted Servers'
                            ),
                            'description': '{}\n{}\n\n**Id**\n{}\n\n{}'.format(
                                member, member.mention, member.id,
                                datetime.time(datetime.now().replace(
                                    microsecond=0))
                            ),
                            'color': int('0x71cd40', 16),
                            'thumbnail': {'url': member.avatar_url}
                        }]
                    }
                }
                try_sending("Discord", send_webhook, webhook)
                log.info('{} is not in a blacklisted server.'.format(member))
