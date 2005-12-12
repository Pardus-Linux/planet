#!/usr/bin/env python
"""Planet RSS Aggregator Library.

You may modify the following variables;

    user_agent: User-Agent sent to remote sites
    cache_directory: Where to put cached feeds

Requires Python 2.2 and Mark Pilgrim's feedparser.py.
"""

__version__ = "0.2"
__authors__ = [ "Scott James Remnant <scott@netsplit.com>",
                "Jeff Waugh <jdub@perkypants.org>" ]
__credits__ = "Originally based on spycyroll."
__license__ = "Python"


import os
import re
import time

import feedparser
import StringIO

try:
    import logging
except:
    import compat_logging
    logging = compat_logging

try:
    import gzip
except:
    gzip = None


# We might as well advertise ourself when we're off galavanting
user_agent = " ".join(("Planet/" + __version__,
                       "http://www.planetplanet.org/",
                       feedparser.USER_AGENT))

# Where to put cached rss feeds
cache_directory = 'cache'

# Things we don't want to see in our cache filenames
cache_invalid_stuff = re.compile(r'\W+')
cache_multiple_dots = re.compile(r'\.+')


def cache_filename(url):
    """Returns a cache filename for a URL.

    Sanitises the URL given, replacing unwelcome characters with periods,
    then prepends the configured cache directory.
    """
    filename = url
    filename = filename.replace("http://", "")
    filename = filename.replace("www.", "")
    filename = cache_invalid_stuff.sub('.', filename)
    filename = cache_multiple_dots.sub('.', filename)

    return os.path.join(cache_directory, filename)


class Channel:
    """A collection of news items.

    Channel represents a feed of news from a website, or some other
    source.

    A channel is created with a URI where we can obtain the feed
    and an optional dictionary of additional properties you wish
    to set (probably from a config file).

    Special properties:
        offset: The number of hours out the channel's times tend to be.

    Useful members:
        uri: Where the feed can be downloaded from
        etag, modified: Used to determine whether the feed has changed

        title: Title for the feed, often the author's name
        description: A description of the content of the feed
        link: Link associated with the feed, generally the HTML version

        items: List of current NewsItems
        props: Dictionary of properties
    """
    def __init__(self, uri, props=None):
        self.uri = uri
        self.etag = None
        self.modified = None

        self.title = None
        self.description = None
        self.link = None

        self.items = []

        if props:
            self.props = props
        else:
            self.props = {}
        if self.props.has_key('offset'):
            self.offset = float(self.props['offset'])
        else:
            self.offset = None

        self.cache_read()

    def update(self, uri=None):
        """Update the channel.

        Read feed data from channel's URI (or an alternate one) and
        parse it using feedparser.  This, where possible, caches the
        data and tries not to request it again if it hasn't changed.

        Most of this is actually what feedparser.parse() does, but as
        we need the unparsed data (to cache), we have to do a bit of the
        work ourselves.

        The real work is done in _update().
        """
        if uri is None:
            save_uri = 1
            uri = self.uri
            logging.info("Updating feed <" + self.uri + ">")
        else:
            save_uri = 0
            logging.info("Updating feed <" + self.uri + "> from <" + uri + ">")

        # Open the resource and read the data
        f = feedparser.open_resource(uri, agent=user_agent,
                                     etag=self.etag, modified=self.modified)
        data = self._read_data(f)

        # Check for some obvious things
        if hasattr(f, 'status'):
            if f.status == 304:
                logging.info("Feed has not changed")
                return
            if f.status >= 400:
                logging.error("Update failed for <%s> (Error: %d)"
                              % (uri, f.status))
                return

        # Update etag and modified
        new_etag = feedparser.get_etag(f)
        if new_etag:
            self.etag = new_etag
            logging.debug("E-Tag: " + self.etag)
        new_modified = feedparser.get_modified(f)
        if new_modified:
            self.modified = new_modified
            logging.debug("Modified: " + self.format_date(self.modified))

        # Update URI in case of redirect
        if hasattr(f, 'url') and save_uri:
            self.uri = f.url
            logging.debug("URI: <" + self.uri + ">")
        if hasattr(f, 'headers'):
            baseuri = f.headers.get('content-location', self.uri)
        else:
            baseuri = self.uri

        # Parse the feed
        f.close()
        self._update(baseuri, data)

    def _read_data(self, f):
        """Read the data from the resource.

        Attempts to gunzip the data if the Content-Encoding header claimed
        to be gzip, but if that fails it doesn't overly worry about it.

        We then take the data and try to squeeze it into a UTF-8 string
        using Python's unicode module.  If it doesn't decode as UTF-8
        we try ISO-8559-1 before ruthlessly stripping the bad characters.
        """
        data = f.read()

        if hasattr(f, 'headers'):
            if gzip and f.headers.get('content-encoding', '') == 'gzip':
                try:
                    gzdata = gzip.GzipFile(fileobj=StringIO.StringIO(data))
                    data = gzdata.read()
                except:
                    logging.warn("Feed contained invalid gzipped data",
                                 exc_info=1)

        try:
            data = unicode(data, "utf8").encode("utf8")
            logging.debug("Encoding: UTF-8")
        except UnicodeError:
            try:
                data = unicode(data, "iso8859_1").encode("utf8")
                logging.debug("Encoding: ISO-8859-1")
            except UnicodeError:
                data = unicode(data, "ascii", "replace").encode("utf8")
                logging.warn("Feed wasn't in UTF-8 or ISO-8859-1, replaced " +
                             "all non-ASCII characters.")

        return data

    def cache_read(self):
        """Initialise the channel from the cache.

        The data is read from a file in the cache_directory and parsed.
        """
        cache_uri = cache_filename(self.uri)

        try:
            if os.path.exists(cache_uri):
                if os.path.exists(cache_uri + ",etag"):
                    c = open(cache_uri + ",etag")
                    self.etag = c.read().strip()
                    c.close()

                if os.path.exists(cache_uri + ",modified"):
                    c = open(cache_uri + ",modified")
                    self.modified = feedparser.parse_date(c.read().strip())
                    c.close()

                self.update(cache_uri)
        except:
            logging.warn("Cache read failed <" + cache_uri + ">", exc_info=1)

    def cache_write(self, data):
        """Write the unparsed feed to the cache.

        The data is written as-is to a file in the cache_directory.
        If the channel has etag or modified information, those are written
        to files alongside.
        """
        cache_uri = cache_filename(self.uri)

        try:
            c = open(cache_uri, "w")
            c.write(data)
            c.close()

            if self.etag:
                c = open(cache_uri + ",etag", "w")
                c.write(self.etag + "\n")
                c.close()
            elif os.path.exists(cache_uri + ",etag"):
                try:
                    os.remove(cache_uri + ",etag")
                except:
                    pass

            if self.modified:
                c = open(cache_uri + ",modified", "w")
                c.write(feedparser.format_http_date(self.modified) + "\n")
                c.close()
            elif os.path.exists(cache_uri + ",modified"):
                try:
                    os.remove(cache_uri + ",modified")
                except:
                    pass
        except:
            logging.warn("Cache write failed <" + cache_uri + ">", exc_info=1)

    def _update(self, baseuri, data):
        """Update the channel from a parsed feed.

        This is the real guts of update() and after all the fuss is
        actually pretty simple.  We parse the feed using feedparser
        and if we get the information, cache it.
        """
        feed = feedparser.FeedParser(baseuri)
        feed.feed(data)

        if len(feed.items) < 1:
            logging.info("Empty feed, cowardly not updating %s" % (baseuri))
            return

        new_items = []
        for item in feed.items:
            new_items.append(NewsItem(item, self))
            if new_items[-1].date[0] > time.gmtime()[0] + 1:
                logging.warning(("Obviously bogus year in feed (%d), " +
                                 "cowardly not updating")
                                % (new_items[-1].date[0],))
                return

        self.items = new_items
        self.title = feed.channel.get('title', '')
        self.description = feed.channel.get('description', '')
        self.link = feed.channel.get('link', '')

        self.cache_write(data)
        return self.items

    def utctime(self, date):
        """Return UTC time() for given date.

        Returns the equivalent of time() for the given date, but taking
        into account local timezone or any forced offset for the channel.

        This is suitable for using in a call to gmtime() only.
        """
        offset = time.timezone
        if self.offset is not None:
            # self.offset is the difference from UTC, so add timezone
            offset += self.offset * 3600 + time.timezone

        return time.mktime(date) - offset

    def format_date(self, date, fmt=None):
        """Formats a date for output.

        Outputs the UTC date, taking into account any forced offset for the
        channel.
        """
        if fmt == 'iso':
            fmt = "%Y-%m-%dT%H:%M:%S+00:00"
        elif fmt == 'rfc822':
            fmt = "%a, %d %b %Y %H:%M:%S +0000"
        elif fmt is None:
            fmt = "%B %d, %Y %I:%M %p"

#        '''Show date/time in Turkish - caglar10ur'''
#    	import locale
#    	locale.setlocale( locale.LC_ALL, "tr_TR.UTF-8")
        
    	return time.strftime(fmt, time.gmtime(self.utctime(date)))


class NewsItem:
    """A single item of news.

    NewsItem represents a single item of news from a channel.  They
    are created and owned by the Channel and accessible through
    Channel().items.

    Useful members:
        id: Unique identifier for the item (often a URI)
        date: Date item was last modified

        title: Title of the item
        summary: Summary of the content for the first page
        content: Content of the item
        link: Link associated with the item, generally the HTML version
        creator: Person who created the item

        channel: Channel this NewsItem belongs to
    """
    def __init__(self, dict, channel):
        self.channel = channel

        self.link = dict.get('link', '')
        self.id = dict.get('id', self.link)

        self.title = dict.get('title', '')
        self.summary = dict.get('summary', '')
        if 'content' in dict and len(dict['content']):
            self.content = dict['content'][0]['value']
        elif 'description' in dict:
            self.content = dict['description']
        else:
            self.content = ''

        self.date = dict.get('modified_parsed')
        if self.date is None or self.date[3:6] == (0, 0, 0):
            self.date = self._cached_time()

        self.creator = dict.get('creator', '');

    def _cached_time(self):
        """Retrieve or save a cached time for this entry.

        Sometimes entries lack any date or time information, and
        sometimes they just lack time information.  The trouble is
        we need both to be able to put them in the right place in the
        output.

        This is the solution (for both).  When you find no date, or
        one that ends up at exactly midnight (as-if!) we grovel around
        inside a cache file to see whether we've recorded anything for
        it so far.  If we have, we use that, otherwise we'll use the
        current UTC time and save that (along with the rest) into the
        cache file for use next time.

        Truly midnight dates will sneak a bit forward, but that's not
        a great loss.
        """
        time_cache_uri = cache_filename(self.channel.uri) + ",times"
        time_cache = {}

        if os.path.exists(time_cache_uri):
            try:
                c = open(time_cache_uri)
                for line in c.readlines():
                    id, timestr = line.strip().split(" = ")
                    time_cache[id] = feedparser.parse_date(timestr)
                c.close()

                if time_cache.has_key(self.id):
                    return time_cache[self.id]
            except:
                logging.warn("Time cache read failed <" + time_cache_uri + ">",
                             exc_info = 1)

        time_cache[self.id] = time.gmtime()
        fmt_time = self.channel.format_date(time_cache[self.id], 'iso')

        # Make sure we don't move the entry *too far*
        if self.date is not None:
            orig_time = self.channel.utctime(self.date)
            this_time = self.channel.utctime(time_cache[self.id])
            if abs(this_time - orig_time) > 86400:
                return self.date

        try:
            c = open(time_cache_uri, "a")
            c.write("%s = %s\n" % (self.id, fmt_time))
            c.close()
        except:
            logging.warn("Time cache write failed <" + time_cache_uri + ">",
                         exc_info=1)

        return time_cache[self.id]


class Planet:
    """A collection of channels.

    Planet represents an aggregated set of channels, easing their
    management and allowing you to directly retreive the items in
    descending date order.

    Once a planet is created you subscribe new Channels to it.  You
    can then obtain a list of subscribed channels through the
    channels() member function and a list of items through the items()
    function (bypassing the Channel level).

    What you do with a Planet is up to you.
    """
    def __init__(self):
        self._channels = []
        self._items = None

    def subscribe(self, channel):
        """Subscribe the Planet to a Channel."""
        self._channels.append(channel)
        self._items = None

    def unsubscribe(self, channel):
        """Unsubscribe the Planet from a Channel."""
        self._channels.remove(channel)
        self._items = None

    def channels(self):
        """Retrieve the currently subscribed channels.

        Returns a list of all the Channels this planet is subscribed to.
        """
        return list(self._channels)

    def items(self):
        """Retrieve the items in date order.

        Returns all items in descending date order (most recent first).
        """
        if self._items is not None:
            return self._items

        self._items = []
        for channel in self._channels:
            for item in channel.items:
                if item.date is not None:
                    self._items.append(item)

        self._items.sort(lambda x,y: cmp(y.channel.utctime(y.date),
                                         x.channel.utctime(x.date)))
        return list(self._items)
