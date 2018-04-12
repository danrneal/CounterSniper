import asyncio
import discord
import logging
import sqlite3
from datetime import datetime
from CounterSniper.utils import send_webhook, try_sending

log = logging.getLogger('Hammer')


class Hammer(discord.Client):

    def __init__(self, my_server_ids, message_users, monitor_users,
                 admin_roles, punishment, webhook_url, queue):
        super(Hammer, self).__init__()
        self.__my_server_ids = my_server_ids
        self.__message_users = message_users
        self.__monitor_users = monitor_users
        self.__admin_roles = admin_roles
        self.__punishment = punishment
        self.__webhook_url = webhook_url
        self.__queue = queue
        self.__next_punishment = None

    async def punish_user(self):
        self.__next_punishment = None
        con = sqlite3.connect(
            'counter_sniper.db',
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        cur = con.cursor()
        cur.execute(
            'SELECT timer, member_id '
            'FROM cache '
            'ORDER BY timer'
        )
        for member_info in cur.fetchall():
            if member_info[0] < datetime.utcnow():
                member = discord.utils.get(
                    self.get_all_members(),
                    id=int(member_info[1])
                )
                while member is not None:
                    if self.__punishment == 'ban':
                        try:
                            await member.ban()
                            log.info("Banned {}".format(member))
                        except discord.Forbidden:
                            log.error('Could not ban member {}'.format(member))
                            break
                    else:
                        try:
                            await member.kick()
                            log.info("Kicked {}".format(member))
                        except discord.Forbidden:
                            log.error('Could not kick member {}'.format(
                                member))
                            break
                    member = discord.utils.get(
                        self.get_all_members(),
                        id=int(member_info[1])
                    )
            else:
                self.__next_punishment = member_info[0]
                log.info("Next punish check in {} seconds".format(
                    (member_info[0] - datetime.utcnow()).total_seconds()
                ))
                break
        con.close()
        log.info("Finished punish check")

    async def webhook(self):
        while True:
            if self.__queue.empty():
                if (self.__next_punishment is not None and
                        self.__next_punishment < datetime.utcnow()):
                    await self.punish_user()
                await asyncio.sleep(1)
                continue
            payload = await self.__queue.get()
            if payload['event'] == 'invite':
                invite = await self.get_invite(payload['invite'])
                if (not invite.revoked and
                        str(invite.guild.id) not in payload['guilds']):
                    webhook = {
                        'url': self.__webhook_url,
                        'payload': {
                            'embeds': [{
                                'title': (
                                    u"\U0001F3F4" + ' Invite Posted in '
                                    'Blacklisted Server'
                                ),
                                'description': (
                                    '{}\n\n**Server**\n{}'
                                    '\n\n**Posted In**\n{}\n\n{}'.format(
                                        invite, invite.guild.name,
                                        payload['posted'],
                                        datetime.time(datetime.now().replace(
                                            microsecond=0))
                                    )
                                ),
                                'color': int('0xee281f', 16)
                            }]
                        }
                    }
                    try_sending("Discord", send_webhook, webhook)
                    log.info('Sent new invite {} for {}'.format(
                        invite, invite.guild.name))
            elif payload['event'] == 'msg':
                if (payload.get('timer') is not None and
                    (self.__next_punishment is None or
                     payload.get('timer') < self.__next_punishment)):
                    self.__next_punishment = payload['timer']
                    log.info("Next punish check in {} seconds".format(
                        (payload['timer'] - datetime.utcnow()).total_seconds()
                    ))
                member = discord.utils.get(
                    self.get_all_members(),
                    id=payload['member_id']
                )
                await member.send(payload['content'])
                log.info("Sent msg to {}".format(member))
            elif payload['event']:
                await self.punish_user()

    async def on_ready(self):
        for guild in self.guilds:
            if self.__monitor_users and str(guild.id) in self.__my_server_ids:
                for role in guild.roles:
                    if role.name.lower() in self.__admin_roles:
                        self.__admin_roles.remove(role.name.lower())
                        self.__admin_roles.append(role)
        log.info("----------- Hammer Bot is connected.")

    async def on_message(self, message):
        if (self.__monitor_users and
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
                    em = discord.Embed(
                        description='{} Not a valid user id.'.format(
                            message.author.mention),
                        color=int('0xee281f', 16)
                    )
                    await message.channel.send(embed=em)
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
                em = discord.Embed(
                    description=(
                        '{} Cannot find user with id `{}`.'
                    ).format(message.author.mention, member_id),
                    color=int('0xee281f', 16)
                )
                await message.channel.send(embed=em)
                log.info('Cannot find user id {}.'.format(member_id))
            elif len(sniper_guilds) > 0:
                descript = '{} | {}'.format(member, member_id)
                if member is not None:
                    descript += '\n{}'.format(member.mention)
                descript += '\n\n**Servers**\n```\n'
                for guild_info in sniper_guilds:
                    descript += '{}\n'.format(guild_info[1])
                descript += '```\n{}'.format(
                    datetime.time(datetime.now().replace(microsecond=0)))
                em = discord.Embed(
                    title=u"\U0001F3F4" + ' User is in Blacklisted Server',
                    description=descript,
                    color=int('0xee281f', 16),
                )
                if member is not None:
                    em.set_thumbnail(url=member.avatar_url)
                await message.channel.send(embed=em)
                log.info('{} is in a blacklisted server.'.format(member))
            else:
                em = discord.Embed(
                    title=u"\u2705" + ' User is in no Blacklisted Servers',
                    description='{}\n{}\n\n**Id**\n{}\n\n{}'.format(
                        member, member.mention, member.id,
                        datetime.time(datetime.now().replace(microsecond=0))
                    ),
                    color=int('0x71cd40', 16)
                )
                em.set_thumbnail(url=member.avatar_url)
                await message.channel.send(embed=em)
                log.info('{} is not in a blacklisted server.'.format(member))
