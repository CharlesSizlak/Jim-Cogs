import discord
import re
import hashlib
import json
import asyncio
from calendar import monthrange
from redbot.core import commands, Config, checks
from redbot.cogs.permissions.converters import GuildUniqueObjectFinder, CogOrCommand, RuleType
from datetime import datetime, timezone, timedelta
from typing import Union
from functools import partial

DONE_REACTIONS = ('\U0001F1E9', '\U0001F1F4', '\U0001F1F3', '\U0001F1EA', '\U0001F44D')

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
YEARS_PATTERN = named_group("years", r"\d+") + WHITESPACE_PATTERN + r"(y|yr|year|yeer)s?"
WEEKS_PATTERN = named_group("weeks", r"\d+") + WHITESPACE_PATTERN + r"(w|wk|wek|week)s?"
DAYS_PATTERN = named_group("days", r"\d+") + WHITESPACE_PATTERN + r"(d|da|day)s?"
HOURS_PATTERN = named_group("hours", r"\d+") + WHITESPACE_PATTERN + r"(h|hr|hour)s?"
MINUTES_PATTERN = named_group("minutes", r"\d+") + WHITESPACE_PATTERN + r"(m|min|minute)s?"

OFFSET_REGEX = re.compile(
    "^"                         +
    optional(YEARS_PATTERN)     +
    WHITESPACE_PATTERN          +
    optional(WEEKS_PATTERN)     +
    WHITESPACE_PATTERN          +
    optional(DAYS_PATTERN)      +
    WHITESPACE_PATTERN          +
    optional(HOURS_PATTERN)     +
    WHITESPACE_PATTERN          +
    optional(MINUTES_PATTERN)   +
    "$"
)

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

def ListArgument(string):
    string = string.replace(",", " ")
    return string.split()

def recurrence_conversion(string):
    for enum, items in RECURRENCE_OPTIONS.items():
        if string in items:
            return enum
    raise ValueError("Invalid recurrence provided")

async def time_conversion(string, cog, user):
    match = OFFSET_REGEX.search(string)
    if match:
        minutes = 0
        if match.group('years'):
            minutes += int(match.group('years')) * 60 * 24 * 365
        if match.group('weeks'):
            minutes += int(match.group('weeks')) * 60 * 24 * 7
        if match.group('days'):
            minutes += int(match.group('days')) * 60 * 24
        if match.group('hours'):
            minutes += int(match.group('hours')) * 60
        if match.group('minutes'):
            minutes += int(match.group('minutes'))

        return datetime.now() + timedelta(
            minutes=minutes
        )

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

async def messenger(cog):
    data = cog.load_pokes()
    current_time = datetime.now().replace(second=0, microsecond=0)
    new_data = {}
    for guild_id, all_pokes_info in data.items():
        guild = cog.bot.get_guild(int(guild_id))
        if not guild:
            new_data[guild_id] = []
            continue
        added_pokes = []
        new_data[guild_id] = added_pokes
        for timestamp, message, target, channel, recurrence, user_or_role, day_in_month in all_pokes_info:
            poke_time = datetime.fromtimestamp(timestamp)
            if poke_time <= current_time:
                channel = cog.bot.get_channel(channel)
                if user_or_role == USER:
                    target = cog.bot.get_user(target)
                else:
                    target = guild.get_role(target)
                if not target:
                    recurrence = SINGLE
                    await cog.send_to_log(guild, 'Jim_Bot tried to send "{}" to a user or role that no longer exists. If this message was set to happen again, you will need to make a new poke mentioning an existing role or user'.format(message))
                    continue
                if not channel:
                    recurrence = SINGLE
                    await cog.send_to_log(guild, 'Jim_Bot tried to send "{}" to "{}" in a channel that has since been deleted. If this message was set to happen again, you will need to make a new poke for an existing channel.'.format(message, target))
                    continue
                try:
                    await channel.send("{} {}".format(target.mention, message))
                except discord.errors.Forbidden:
                    await cog.send_to_log(guild, 'Jim_Bot tried to send "{}" to "{}" in "{}" but does not have access to that channel. If this message was set to happen again, you will need to make a new poke for a channel Jim_Bot has permissions to send messages in.'.format(message, target, channel))
                    recurrence = SINGLE
                if poke_time > current_time:
                    try:
                        await channel.send("This message was originally supposed to be sent at {} but could not be sent due to an issue connecting to discord's servers at that time.".format(poke_time))
                    except discord.errors.Forbidden:
                        pass
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
                    year = poke_time.year
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

#TODO properly close the connections once they're finished
#TODO technically there's a possibility of a memory issue as we're not clearing out unused servers at this time. while it's unlikely jim is going to be added to a hundred thousand servers and removed from all of them
#TODO it is possible that it could cause issues
#TODO update jim_bot to redbot 3.4
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
        self._permissions_cog = None


    @property
    def permissions_cog(self):
        if self._permissions_cog is None:
            self._permissions_cog = self.bot.get_cog("Permissions")
        return self._permissions_cog


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
        logchannel_id = await self.config.guild(guild).logchannel()
        logchannel = self.bot.get_channel(logchannel_id)
        return logchannel
    
    async def send_to_log(self, guild, message):
        logchannel = await self.get_logchannel(guild)
        if logchannel:
            try:
                await logchannel.send(message)
            except discord.errors.Forbidden:
                pass

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
        self.save_pokes(data)
    
    async def reaction_manager(self, message, reactions_list):
        try:
            for reaction in reactions_list:
                await message.add_reaction(reaction)
        except discord.errors.Forbidden:
            await self.send_to_log(message.guild, 'Jim_Bot tried to add reactions in channel "{}" but does not have permission.'.format(message.channel))
            
    @commands.group()
    async def poke(self, ctx):
        pass

    @checks.guildowner()
    @poke.command()
    async def permissions_control(self, ctx, who: GuildUniqueObjectFinder,
            commands: ListArgument, allow_or_deny: RuleType):
        for command in commands:
            cog_or_command = await CogOrCommand.convert(ctx,"poke " + command)
            await self.permissions_cog._add_rule(
                rule=allow_or_deny,
                cog_or_cmd=cog_or_command,
                model_id=who.id,
                guild_id=ctx.guild.id
            )
            await self.send_to_log(ctx.guild, 'Changed permissions for command "{}" for "{}" to "{}"'.format(
                command, who, "Allow" if allow_or_deny else "Deny"
            ))
        await self.reaction_manager(ctx.message, DONE_REACTIONS)


    @poke.command(aliases=["Set_My_Tz", "set_my_TZ", "SET_MY_TZ", "Set_my_tz", "Set_my_TZ"])
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
            await self.reaction_manager(ctx.message, DONE_REACTIONS)
        except ValueError:
            await ctx.send("Hey that doesn't look like a viable UTC offset")

    @poke.command(aliases=["Delete", "DELETE"])
    async def delete(self, ctx, targets):
        self.json_checker(ctx.guild.id)
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
        await self.send_to_log(ctx.guild, "User {} has deleted pokes {}".format(ctx.author, message))

    @poke.command(aliases=["List", "LIST"])
    async def list(self, ctx):
        self.json_checker(ctx.guild.id)
        data = self.load_pokes()
        pokes = data[str(ctx.guild.id)]
        if pokes == []:
            await ctx.send("It doesn't look like there are any pokes for this server at this time.")
        else:
            paginator = Paginator()
            i = 0
            for timestamp, message, target, channel, recurrence, user_or_role, day_in_month in pokes:
                i += 1
                message = message.replace("`", "\u200b`\u200b")
                target = ctx.bot.get_user(target) if user_or_role == USER else ctx.guild.get_role(target)
                if not target:
                    target = "DELETED USER OR ROLE, MESSAGE WILL FAIL"
                paginator.add_line(
                    "{}: {} at {} we are going to message '{}' in '{}', the following\n\"{}\"".format(
                        i,
                        RECURRENCES[recurrence],
                        datetime.fromtimestamp(timestamp).astimezone().strftime(
                            "%Y-%m-%d %H:%M %z"
                        ),
                        target,
                        ctx.bot.get_channel(channel),
                        message
                    )
                )
            await paginator.send(ctx)
            await self.send_to_log(ctx.guild, "User {} has asked for a snapshot of all current pokes".format(ctx.author))
           
    @poke.command(aliases=["Armageddon", "ARMAGEDDON", "A R M A G E D D O N"])
    async def armageddon(self, ctx):
        data = self.load_pokes()
        data[str(ctx.guild.id)] = []
        self.save_pokes(data)
        await ctx.send("Deleting all pokes!")
        await self.reaction_manager(ctx.message, ['\U0001F4A5'])
        await self.send_to_log(ctx.guild, "User {} has deleted all pokes!".format(ctx.author))

    @poke.command(aliases=["Set_Logchannel", "SET_LOGCHANNEL", "Set_logchannel"])
    async def set_logchannel(self, ctx, channel: discord.TextChannel):
        await self.config.guild(ctx.guild).logchannel.set(channel.id)
        await self.send_to_log(ctx.guild, "This channel has been set as the log channel for pokes.")
        try:
            await ctx.send("Setting log channel!")
        except discord.errors.Forbidden:
            self.send_to_log(ctx.guild, "You set the logchannel from a channel that Jim_Bot does not have permissions in.")

    @poke.command(aliases=["Clear_Logchannel", "CLEAR_LOGCHANNEL", "Clear_logchannel"])
    async def clear_logchannel(self, ctx):
        await self.config.guild(ctx.guild).logchannel.set(None)
        try:
            await ctx.send('User {} has removed the server logchannel'.format(ctx.author))
        except discord.errors.Forbidden:
            pass

    @poke.command(aliases=["Add", "ADD"])
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
        await self.send_to_log(ctx.guild, 'Sending "{}" to "{}" on "{}"'.format(
                message, who, 
                poke_time.astimezone().strftime("%Y-%m-%d %H:%M %z"
            )))
        await self.reaction_manager(ctx.message, DONE_REACTIONS)
