import discord
import datetime
import re
from redbot.core import commands, Config
from datetime import timezone, timedelta


#time_coversion should take one of two kinds of strings
#the first string should look something like 45m or 1hr5m and it'll send the message after the specified amount of time has passed
#the second kind of string should like like a date with time attached 05/11/2020 2:00 PM, and it'll send it on that date at that time 

# 45m
# 1hr 5m 3s

def named_group(name, group):
    return r"(?P<{}>{})".format(name, group)

def optional(term):
    return r"({})?".format(term)

HOURS_PATTERN = named_group("hours", r"\d+") + r"(h|hr|hour)s?"
MINUTES_PATTERN = named_group("minutes", r"\d+") + r"(m|min|minute)s?"
SECONDS_PATTERN = named_group("seconds", r"\d+") + r"(s|sec|second)s?"
WHITESPACE_PATTERN = r"\s*"

HOURS_MINUTES_SECONDS_REGEX = re.compile(
    "^"                         +
    HOURS_PATTERN               +
    WHITESPACE_PATTERN          +
    optional(MINUTES_PATTERN)   +
    WHITESPACE_PATTERN          +
    optional(SECONDS_PATTERN)   +
    "$"
)

MINUTES_SECONDS_REGEX = re.compile(
    "^"                         +
    MINUTES_PATTERN             +
    WHITESPACE_PATTERN          +
    optional(SECONDS_PATTERN)   +
    "$"
)

SECONDS_REGEX = re.compile(
    "^"                         +
    SECONDS_PATTERN             +
    "$"
)

# 05/11/2020 2:00pm
# 05/11/2020 2:00 PM
# 05/11/2020 14:00

DATE_PATTERN = r"{}/{}/{}".format(
    named_group("month", r"\d{1,2}"),
    named_group("day", r"\d{1,2}"),
    named_group("year", r"\d{2}|\d{4}")
)

TIME_PATTERN = named_group("time", r"\d{1,2}:\d{2}|\d{1,2}")
PERIOD_PATTERN = named_group("period", "am|pm")
TZINFO_PATTERN = named_group("tzinfo", "UTC\s*(\+|-)\s*\d{1,2}(:\d{2})?")

DATETIME_REGEX = re.compile(
    "^"                         +
    DATE_PATTERN                +
    WHITESPACE_PATTERN          +
    TIME_PATTERN                +
    WHITESPACE_PATTERN          +
    optional(PERIOD_PATTERN)    +
    WHITESPACE_PATTERN          +
    TZINFO_PATTERN              +
    "$"
)

print(
    "^"                         +
    DATE_PATTERN                +
    WHITESPACE_PATTERN          +
    TIME_PATTERN                +
    WHITESPACE_PATTERN          +
    optional(PERIOD_PATTERN)    +
    WHITESPACE_PATTERN          +
    TZINFO_PATTERN              +
    "$"
)

def time_conversion(string):
    match = HOURS_MINUTES_SECONDS_REGEX.search(string)
    if match:
        return datetime.datetime.now()

    match = MINUTES_SECONDS_REGEX.search(string)
    if match:
        return datetime.datetime.now()

    match = SECONDS_REGEX.search(string)
    if match:
        return datetime.datetime.now()
    
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

        if period == "pm":
            hour += 12

        #here we find tzinfo. tbd

        tzinfo = tzinfo.lower()
        try:
            tzhour, tzminute = tzinfo.strip("utc +").split(':')
        except ValueError:
            tzhour = tzinfo.strip("utc +")
            tzminute = 0

        return datetime.datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            int(hour),
            int(minute),
            tzinfo = timezone(timedelta(hours = int(tzhour), minutes = int(tzminute)))
        )

    raise ValueError("Invalid datetime provided.")


class PokeCog(commands.Cog):

    def __init__(self):
        self.config = Config.get_conf(self, identifier=hash('PokeCog'))
        self.config.register_guild(
            logchannel = None
        )


    @commands.group()
    async def poke(self, ctx):
        pass

    @poke.command()
    async def add(self, ctx, who: discord.User, datetime: str, message: str, channel: discord.TextChannel):
        datetime = time_conversion(datetime)
        await ctx.send("Adding!")
        await who.send(message)
        logchannel = await self.config.guild(ctx.guild).logchannel()
        if logchannel:
            await logchannel.send('Sending "{}" to "{}" on "{}"'.format(message, who, datetime))

    @poke.command()
    async def delete(self, ctx, asdf: str):
        user = ctx.bot.get_user(int(asdf))
        await ctx.send("Got a user: '{}'".format(user))

    #list should list all pokes associated with the user or server
    @poke.command()
    async def list(self, ctx):
        await ctx.send(type(ctx))

    #armageddon should delete every poke associated with the user or server
    @poke.command()
    async def armageddon(self, ctx):
        await ctx.send("Deleting all!")

    #all should send out PMs to everyone who has access to a channel
    @poke.command()
    async def all(self, ctx):
        await ctx.send("@everyone")
    
    #designate a channel on the server to log all pokes coming from the server
    @poke.command()
    async def log(self, ctx, channel: discord.TextChannel):
        await self.config.guild(ctx.guild).logchannel.set(channel)
