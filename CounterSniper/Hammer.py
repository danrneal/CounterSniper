import asyncio
import discord
import logging
import sqlite3
from datetime import datetime
from CounterSniper.utils import send_webhook, try_sending

log = logging.getLogger('Hammer')


class Hammer(discord.Client):

    def __init__(self, punishment, webhook_url, queue):
        super(Hammer, self).__init__()
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
                    (member_info[0] -
                     datetime.utcnow().replace(microsecond=0)).total_seconds()
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
                                'description': str(invite),
                                'fields': [
                                    {
                                        'name': 'Server',
                                        'value': invite.guild.name,
                                        'inline': True
                                    },
                                    {
                                        'name': 'Posted In',
                                        'value': payload['posted'],
                                        'inline': True
                                    }
                                ],
                                'footer': {
                                    'text': str(datetime.now().strftime(
                                        "%m/%d/%Y at %I:%M %p"))
                                },
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
                        (
                            payload['timer'] -
                            datetime.utcnow().replace(microsecond=0)
                        ).total_seconds()
                    ))
                member = discord.utils.get(
                    self.get_all_members(),
                    id=payload['member_id']
                )
                try:
                    await member.send(payload['content'])
                    log.info("Sent {} msg to {}".format(
                        payload['msg'], member))
                except discord.Forbidden:
                    log.info('Unable to send {} message to {}'.format(
                        payload['msg'], member))
            elif payload['event']:
                await self.punish_user()

    async def on_ready(self):
        log.info("----------- Hammer Bot is connected.")
