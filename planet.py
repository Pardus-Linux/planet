#!/usr/bin/env python
"""The Planet RSS Aggregator.

Requires Python 2.2.
"""

__version__ = "0.2"
__authors__ = [ "Scott James Remnant <scott@netsplit.com>",
                "Jeff Waugh <jdub@perkypants.org>" ]
__credits__ = "Originally based on spycyroll."
__license__ = "Python"


import sys
import time
import os
import locale

try:
    import logging
except:
    import compat_logging
    logging = compat_logging

import planetlib

from ConfigParser import ConfigParser
from htmltmpl import TemplateManager, TemplateProcessor


# Defaults for [Planet] config sections
CONFIG_FILE = 'config.ini'
PLANET_NAME = 'Unconfigured Planet'
PLANET_LINK = 'Unconfigured Planet'
OWNER_NAME = 'Anonymous Coward'
OWNER_EMAIL = ''
TEMPLATE_FILES = " ".join(('examples/planet.html.tmpl',
                           'examples/planet.rss10.tmpl',
                           'examples/planet.rss20.tmpl'))
OUTPUT_DIR = 'output'
ITEMS_PER_PAGE = 60
DAYS_PER_PAGE = 0
DATE_FORMAT = '%B %d, %Y %I:%M %p'
LOG_LEVEL = 'WARNING'


def config_get(config, section, option, default=None, raw=0, vars=None):
    """Get a value from the configuration, with a default."""
    if config.has_option(section, option):
        return config.get(section, option, raw=raw, vars=None)
    else:
        return default

def tcfg_get(config, template, option, default=None, raw=0, vars=None):
    """Get a template value from the configuration, with a default."""
    if config.has_option(template, option):
        return config.get(template, option, raw=raw, vars=None)
    elif config.has_option("Planet", option):
        return config.get("Planet", option, raw=raw, vars=None)
    else:
        return default


if __name__ == "__main__":
    config_file = CONFIG_FILE
    offline = 0

    for arg in sys.argv[1:]:
        if arg == '-h' or arg == '--help':
            print "Usage: planet [options] [CONFIGFILE]"
            print
            print "Options:"
            print " -o, --offline       Update the Planet from the cache only"
            print " -h, --help          Display this help message and exit"
            print
            sys.exit(0)
        elif arg == '-o' or arg == '--offline':
            offline = 1
        elif arg.startswith("-"):
            print >>sys.stderr, "Unknown option:", arg
            sys.exit(1)
        else:
            config_file = arg

    config = ConfigParser()
    config.read(config_file)
    if not config.has_section('Planet'):
        print >>sys.stderr, "Configuration missing [Planet] section."
        sys.exit(1)

    # Read the global configuration values
    planet_name = config_get(config, 'Planet', 'name', PLANET_NAME)
    planet_link = config_get(config, 'Planet', 'link', PLANET_LINK)
    owner_name = config_get(config, 'Planet', 'owner_name', OWNER_NAME)
    owner_email = config_get(config, 'Planet', 'owner_email', OWNER_EMAIL)
    if config.has_option('Planet', 'cache_directory'):
        planetlib.cache_directory = config.get('Planet', 'cache_directory')
    log_level = config_get(config, 'Planet', 'log_level', LOG_LEVEL)
    template_files = config_get(config, 'Planet', 'template_files',
                                TEMPLATE_FILES).split(" ")

    # Activate the settings
    logging.getLogger().setLevel(logging.getLevelName(log_level))
    planetlib.user_agent = " ".join((planet_name, planet_link,
                                     planetlib.user_agent))

    # The other configuration blocks are channels to subscribe to
    channels = {}
    planet = planetlib.Planet()
    for feed in config.sections():
        if feed == 'Planet' or feed in template_files: continue

        # Build a configuration dict the slow, 2.2-compatible way
	channel_options = {}
	options = config.options(feed)
	for option in options:
            channel_options[option] = config.get(feed, option)

        # Create the Channel and subscribe to it
        try:
            logging.info("Subscribing <" + feed + ">")
            channel = planetlib.Channel(feed, channel_options)
            planet.subscribe(channel)
        except:
            logging.error("Subscription failure <" + feed + ">",
                          exc_info=1)
            continue

        try:
            if not offline:
                channel.update()
        except:
            logging.error("Update from <" + channel.uri + "> failed", exc_info=1)

        # Prepare the template information now
        info = {}
        info["uri"] = channel.uri
        info["title"] = channel.title
        info["description"] = channel.description
        info["link"] = channel.link
        for k, v in channel.props.items():
            info[k] = v
        if "name" not in info:
            info["name"] = channel.title

        channels[channel] = info

    # Sort the channels list by name
    channel_list = channels.values()
    locale.setlocale(locale.LC_ALL,"tr_TR.UTF-8")
    channel_list.sort(key=lambda x: locale.strxfrm(x.name))
    locale.setlocale(locale.LC_ALL,"C")    


    # Go-go-gadget-template
    for template_file in template_files:
        output_dir = tcfg_get(config, template_file, 'output_dir', OUTPUT_DIR)
        date_format = tcfg_get(config, template_file, 'date_format',
                               DATE_FORMAT, raw=1)
        items_per_page = int(tcfg_get(config, template_file, 'items_per_page',
                                      ITEMS_PER_PAGE))
        days_per_page = int(tcfg_get(config, template_file, 'days_per_page',
                                     DAYS_PER_PAGE))

        # We treat each template individually
        base = os.path.basename(template_file)
        logging.info("Processing " + base)
        output_file = os.path.join(output_dir, os.path.splitext(base)[0])

        # Work out the URI to this output file
        uri = planet_link
        if not uri.endswith("/"): uri += "/"
        uri += os.path.basename(output_file)

        # Prepare the template information for the items
        items = []
        prev_date = None
        prev_channel = None
        date_today_raw = time.time()

        # Prepare information for this template
        for newsitem in planet.items()[:items_per_page]:
            format_date = newsitem.channel.format_date

            info = {}
            info["id"] = newsitem.id
            info["date"] = format_date(newsitem.date, date_format)
            info["date_iso"] = format_date(newsitem.date, 'iso')
            info["date_822"] = format_date(newsitem.date, 'rfc822')
            info["title"] = newsitem.title
            info["summary"] = newsitem.summary
            info["content"] = newsitem.content
            info["link"] = newsitem.link
            info["creator"] = newsitem.creator

            chaninfo = channels[newsitem.channel]
            for k, v in chaninfo.items():
                info["channel_" + k] = v

            date_raw = newsitem.channel.utctime(newsitem.date)
            date = time.gmtime(date_raw)

            if prev_date != date[:3]:
                days_passed = time.gmtime(date_today_raw - date_raw).tm_yday
                if days_per_page and days_passed >= days_per_page:
                    break

                info["new_date"] = time.strftime("%B %d, %Y", date)
                prev_date = date[:3]
            else:
                info["new_date"] = ""

            if prev_channel != info["channel_uri"] or info["new_date"] != "":
                info["new_channel"] = info["channel_uri"]
                prev_channel = info["channel_uri"]
            else:
                info["new_channel"] = ""

            items.append(info)

        # Process the template
        template = TemplateManager().prepare(template_file)
        tp = TemplateProcessor(html_escape=0)
        tp.set("name", planet_name)
        tp.set("link", planet_link)
        tp.set("owner_name", owner_name)
        tp.set("owner_email", owner_email)
        tp.set("uri", uri)
        tp.set("date", time.strftime(date_format, time.gmtime()))
        tp.set("date_iso", time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()))
        tp.set("date_822", time.strftime("%a, %d %b %Y %H:%M:%S +0000",
                                         time.gmtime()))
        tp.set("Items", items)
        tp.set("Channels", channel_list)
        try:
            logging.info("Writing " + output_file)
            output = open(output_file, "w")
            output.write(tp.process(template))
            output.close()
        except:
            logging.error("Couldn't save " + output_file, exc_info=1)
