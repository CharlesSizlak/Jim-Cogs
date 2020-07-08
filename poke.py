import discord
import re
import hashlib
import json
import asyncio
from calendar import monthrange
from redbot.core import commands, Config
from datetime import datetime, timezone, timedelta
from typing import Union
from functools import partial


SINGLE = 0
HOURLY = 1
DAILY = 2
WEEKLY = 3
MONTHLY = 4
YEARLY = 5

USER = 0
ROLE = 1

RECURRENCES = {
    0: "Once",
    1: "Hourly",
    2: "Daily",
    3: "Weekly",
    4: "Monthly",
    5: "Yearly"
}

def named_group(name, group):
    return r"(?P<{}>{})".format(name, group)

def optional(term):
    return r"({})?".format(term)

WHITESPACE_PATTERN = r"\s*"
HOURS_PATTERN = named_group("hours", r"\d+") + WHITESPACE_PATTERN + r"(h|hr|hour)s?"
MINUTES_PATTERN = named_group("minutes", r"\d+") + WHITESPACE_PATTERN + r"(m|min|minute)s?"
#SECONDS_PATTERN = named_group("seconds", r"\d+") + WHITESPACE_PATTERN + r"(s|sec|second)s?"

HOURS_MINUTES_SECONDS_REGEX = re.compile(
    "^"                         +
    HOURS_PATTERN               +
    WHITESPACE_PATTERN          +
    optional(MINUTES_PATTERN)   +
    #WHITESPACE_PATTERN         +
    #optional(SECONDS_PATTERN)  +
    "$"
)

MINUTES_SECONDS_REGEX = re.compile(
    "^"                         +
    MINUTES_PATTERN             +
    #WHITESPACE_PATTERN         +
    #optional(SECONDS_PATTERN)  +
    "$"
)

#SECONDS_REGEX = re.compile(
#    "^"                         +
#    SECONDS_PATTERN             +
#    "$"
#)

DATE_PATTERN = r"{}/{}/{}".format(
    named_group("month", r"\d{1,2}"),
    named_group("day", r"\d{1,2}"),
    named_group("year", r"\d{2}|\d{4}")
)

TIME_PATTERN = named_group("time", r"\d{1,2}:\d{2}|\d{1,2}")
PERIOD_PATTERN = named_group("period", "am|pm")
TZINFO_PATTERN = named_group("tzinfo", "UTC\s*(\+|-)\s*\d{1,2}(:\d{2})?")

HOURS_MINUTES = re.compile(
    "^"                         +
    TIME_PATTERN                +
    "$"
)

DATETIME_REGEX = re.compile(
    "^"                         +
    DATE_PATTERN                +
    WHITESPACE_PATTERN          +
    TIME_PATTERN                +
    WHITESPACE_PATTERN          +
    optional(PERIOD_PATTERN)    +
    WHITESPACE_PATTERN          +
    optional(TZINFO_PATTERN)    +
    "$",
    re.I
)

RECURRENCE_OPTIONS = {
    SINGLE: {"single", "none", "once", "oncely", "onces", "nonely"},
    HOURLY: {"hour", "hourly", "hr", "horly", "hours"},
    DAILY: {"everyday", "daily", "day", "days"},
    WEEKLY: {"weekly", "week", "weeks"},
    MONTHLY: {"month", "monthly", "months"},
    YEARLY: {"yearly", "year", "annual", "annually", "years"}
}

class Paginator:
    def __init__(self):
        self.lines = []
        self.messages = []

    def add_line(self, text):
        self.lines.append(text + "\n")

    async def send(self, ctx):
        count = 0
        messageCount = 0
        self.messages.append("")
        for line in self.lines:
            count += len(line)
            if count <= 1992:
                self.messages[messageCount] += line
            else:
                messageCount += 1
                count = len(line)
                self.messages.append(line)
        for message in self.messages:
            await ctx.send("```\n" + message + "\n```")

def recurrence_conversion(string):
    for enum, items in RECURRENCE_OPTIONS.items():
        if string in items:
            return enum
    raise ValueError("Invalid recurrence provided")

async def time_conversion(string, cog, user):
    match = HOURS_MINUTES_SECONDS_REGEX.search(string)
    if match:
        if match.group('minutes'):
            minute = int(match.group('minutes'))
        else:
            minute = 0

        return datetime.now() + timedelta(
            hours=int(match.group('hours')),
            minutes=minute
            #,seconds=int(match.group('seconds')) 
            )

    match = MINUTES_SECONDS_REGEX.search(string)
    if match:
        return datetime.now() + timedelta(
            minutes=int(match.group('minutes'))
            #,seconds=int(match.group('seconds')) 
            )

    #match = SECONDS_REGEX.search(string)
    #if match:
        #return datetime.now()
    
    match = DATETIME_REGEX.search(string)
    if match:
        time = match.group("time")
        period = match.group("period")
        tzinfo = match.group("tzinfo")
        if period: period = period.lower()
        
        try:
            hour, minute = time.split(":")
        except ValueError:
            hour = time
            minute = 0

        hour = int(hour)
        minute = int(minute)

        if period == "pm":
            hour += 12
        
        if tzinfo != None:
            tzinfo = tzinfo.lower()
            try:
                tzhour, tzminute = tzinfo.strip("utc +").split(':')
            except ValueError:
                tzhour = tzinfo.strip("utc +")
                tzminute = 0
        else:
            tzhour, tzminute = await cog.get_user_tz(user)
        
        return datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            hour,
            minute,
            tzinfo = timezone(timedelta(hours = int(tzhour), minutes = int(tzminute)))
        )

    raise ValueError("Invalid datetime provided.")

#TODO test if year and month recurrences work
async def messenger(cog):
    data = cog.load_pokes()
    current_time = datetime.now().replace(second=0, microsecond=0)
    new_data = {}
    for guild_id, all_pokes_info in data.items():
        logchannel = await cog.get_logchannel(cog.bot.get_guild(int(guild_id)))
        added_pokes = []
        new_data[guild_id] = added_pokes
        for timestamp, message, target, channel, recurrence, user_or_role, day_in_month in all_pokes_info:
            #from the datetime timestamp reconstruct a datetime and figure out whether or not we're in the same minute, and go from there
            poke_time = datetime.fromtimestamp(timestamp)
            if poke_time == current_time:
                #go in to the guild id to find the correct guild to send a message in
                guild = cog.bot.get_guild(int(guild_id))
                #find the channel
                channel = cog.bot.get_channel(channel)
                #construct the message using the target and the message
                if user_or_role == USER:
                    target = cog.bot.get_user(target)
                else:
                    target = guild.get_role(target)
                if target is None:
                    recurrence = SINGLE
                    if logchannel:
                        await logchannel.send('Jim_Bot tried to send "{}" to a user or role that no longer exists. If this message was set to happen again, you will need to make a new poke mentioning an existing role or user'.format(message))
                if channel:
                    await channel.send("{} {}".format(target.mention, message))
                else:
                    recurrence = SINGLE
                    if logchannel:
                        await logchannel.send('Jim_Bot tried to send "{}" to "{}" in a channel that has since been deleted. If this message was set to happen again, you will need to make a new poke for an existing channel.'.format(message, target))
                #check recurrence
                if recurrence == HOURLY:
                    poke_time = poke_time + timedelta(hours=1)
                elif recurrence == DAILY:
                    poke_time = poke_time + timedelta(days=1)
                elif recurrence == WEEKLY:
                    poke_time = poke_time + timedelta(weeks=1)
                elif recurrence == MONTHLY:
                    month = poke_time.month
                    next_month = month + 1 if month < 12 else 1
                    year = poke_time.year
                    _, days_in_month = monthrange(year, next_month) 
                    if day_in_month > days_in_month:
                        new_day = days_in_month
                    else:
                        new_day = day_in_month
                    poke_time = poke_time.replace(month = next_month, day = new_day)
                elif recurrence == YEARLY:
                    if poke_time.month == 2 and day_in_month == 29:
                        _, leap_check = monthrange(year + 1, month)
                        if leap_check == 29:
                            poke_time = poke.replace(year = year + 1)
                        else:
                            poke_time = poke.replace(year = year + 1, day = 28)
                    else:
                        poke_time = poke_time.replace(year = year + 1)
                if recurrence != SINGLE:
                    timestamp = poke_time.timestamp()
                    added_pokes.append([
                        timestamp, message, target.id, channel.id, 
                        recurrence, user_or_role, day_in_month
                    ])
            else:
                added_pokes.append([
                    timestamp, message, target, channel, 
                    recurrence, user_or_role, day_in_month
                ])
    cog.save_pokes(new_data)

async def connection_handler(cog, reader, writer):
    GO_MESSAGE = b"go for pokes"
    if await reader.readexactly(len(GO_MESSAGE)) == GO_MESSAGE:
        await messenger(cog)
        
#TODO double check that all commands with pokecog work correctly across multiple servers
#TODO see if we can accept capital letters in commands from the user, instead of just lowercase
#TODO make it so you can not have a log channel anymore after setting a logchannel
#TODO what happens if a user is deleted and a message is meant to be sent to them
#TODO break the bots connection with discord to see what happens
class PokeCog(commands.Cog):
    def __init__(self):
        self.config = Config.get_conf(self, identifier=hashlib.sha512(b'PokeCog').hexdigest())
        self.config.register_guild(
            logchannel = None
        )
        self.config.register_user(
            user_tz = -4
        )
        self.server = None

    async def initialize(self):
        self.server = await asyncio.start_server(
            partial(connection_handler, self), "127.0.0.1", 2896,
            reuse_address=True, reuse_port=True
        )

    def cog_unload(self):
        if self.server is not None:
            self.server.close()

    async def get_user_tz(self, user):
        hours, minutes = await self.config.user(user).user_tz()
        return (hours, minutes)

    async def set_user_tz(self, user, hours, minutes):
        await self.config.user(user).user_tz.set((hours, minutes))

    async def get_logchannel(self, guild):
        logchannel = await self.config.guild(guild).logchannel()
        logchannel = self.bot.get_channel(logchannel)
        return logchannel
    
    def save_pokes(self, data):
        with open('/home/sizlak/jim_cogs/poke/data.json', 'w') as f:
            f.write(json.dumps(data))

    def load_pokes(self):
        try:
            with open('/home/sizlak/jim_cogs/poke/data.json') as f: 
                return json.loads(f.read())
        except json.decoder.JSONDecodeError:
            return {}
        
    def json_checker(self, serverid):
        serverid = str(serverid)
        data = self.load_pokes()
        if serverid in data:
            return
        data[serverid] = []
        save_pokes(data)

    @commands.group()
    async def poke(self, ctx):
        pass

    @poke.command()
    async def set_my_tz(self, ctx, tz_offset: str):
        tz_offset = tz_offset.lower()
        try:
            tzhour, tzminute = tz_offset.strip("utc +").split(':')
        except ValueError:
            tzhour = tz_offset.strip("utc +")
            tzminute = 0
        try:
            hours = int(tzhour)
            minutes = int(tzminute)
            await self.set_user_tz(ctx.author, hours, minutes)
            for reaction in ('\U0001F1E9', '\U0001F1F4', '\U0001F1F3', '\U0001F1EA', '\U0001F44D'):
                await ctx.message.add_reaction(reaction)
        except ValueError:
            await ctx.send("Hey that doesn't look like a viable UTC offset")

    @poke.command()
    async def delete(self, ctx, targets):
        data = self.load_pokes()
        deleted_pokes = []
        message = ""
        try:
            for target in sorted({int(t.replace(",", " ")) for t in targets.split()}, reverse=True):
                deleted_pokes.append(target)
                data[str(ctx.guild.id)].pop(target-1)
        except IndexError:
            await ctx.send("Target out of range. tldr number bigger than number of pokes that exist")
        except ValueError as e:
            await ctx.send("Try sending us numbers")
        self.save_pokes(data)
        for deleted in sorted(deleted_pokes):
            message += str(deleted)
            message += ", "
        message = message[:-2]
        await ctx.send("Pokes {} have been deleted.".format(message))
        logchannel = await self.get_logchannel(ctx.guild)
        if logchannel:
            await logchannel.send("User {} has deleted pokes {}".format(ctx.author, message))

    # TODO When there are no pokes associated with the guild it doesn't send a nice looking message
    @poke.command()
    async def list(self, ctx):
        data = self.load_pokes()
        paginator = Paginator()
        pokes = data[str(ctx.guild.id)]
        i = 0
        for timestamp, message, target, channel, recurrence, user_or_role, day_in_month in pokes:
            i += 1
            paginator.add_line(
                "{}: {} at {} we are going to message '{}' in '{}', the following\n\"{}\"".format(
                    i,
                    RECURRENCES[recurrence],
                    datetime.fromtimestamp(timestamp).astimezone().strftime(
                        "%Y-%m-%d %H:%M %z"
                    ),
                    ctx.bot.get_user(target) if user_or_role == USER else ctx.guild.get_role(target),
                    ctx.bot.get_channel(channel),
                    message
                )
            )
        await paginator.send(ctx)
        logchannel = await self.get_logchannel(ctx.guild)
        if logchannel:
            await logchannel.send("User {} has asked for a snapshot of all current pokes".format(ctx.author))
           
    @poke.command()
    async def armageddon(self, ctx):
        data = self.load_pokes()
        data[str(ctx.guild.id)] = []
        self.save_pokes(data)
        await ctx.send("Deleting all pokes!")
        await ctx.message.add_reaction('\U0001F4A5')
        logchannel = await self.get_logchannel(ctx.guild)
        if logchannel:
            await logchannel.send("User {} has deleted all pokes!".format(ctx.author))

    @poke.command()
    async def log(self, ctx, channel: discord.TextChannel):
        await self.config.guild(ctx.guild).logchannel.set(channel.id)
        logchannel = await self.get_logchannel(ctx.guild)
        if logchannel:
            await logchannel.send("This channel has been set as the log channel for pokes.")
            await ctx.send("Setting log channel!")
    

    #TODO check if the bot has access to the channel you're trying to send the message in
    @poke.command()
    async def add(self, ctx, who: Union[discord.User, discord.Role],
    poke_time: str, message: str, channel: discord.TextChannel, recurrence="single"):
        if len(message) > 1800:
            await ctx.send("That message is too large! Try to send a message with less than 1800 characters")
            return
        if isinstance(who, (discord.User, discord.ClientUser)):
            user_or_role = USER
        else:
            user_or_role = ROLE
        recurrence = recurrence.lower()
        recurrence = recurrence_conversion(recurrence)
        poke_time = await time_conversion(poke_time, self, ctx.author)
        poke_time = poke_time.replace(second=0, microsecond=0)
        self.json_checker(ctx.guild.id)
        data = self.load_pokes()
        day_in_month = poke_time.day
        data[str(ctx.guild.id)].append([
            poke_time.timestamp(), message, who.id, channel.id, 
            recurrence, user_or_role, day_in_month
        ])
        self.save_pokes(data)
        logchannel = await self.get_logchannel(ctx.guild)
        if logchannel:
            await logchannel.send('Sending "{}" to "{}" on "{}"'.format(
                message, who, 
                poke_time.astimezone().strftime("%Y-%m-%d %H:%M %z"
            )))
        for reaction in ('\U0001F1E9', '\U0001F1F4', '\U0001F1F3', '\U0001F1EA', '\U0001F44D'):
            await ctx.message.add_reaction(reaction)
