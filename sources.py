"""Source registry for the State Capacity Tracker.

Three source types (SPEC.md §4):
- STATENEWSROOM_FEEDS — the spine. States Newsroom owned outlets, one per
  state, at https://<domain>/feed/localFeed. All verified live.
- NEWSPAPER_FEEDS — breadth. Up to ~3 complementary outlets per state with
  verified public RSS (nonprofit statehouse outlets, capital dailies, metro
  dailies, business journals). Covers the 11 states States Newsroom misses.
  This is a living list — entries were RSS-verified on 2026-06-09; prune dead
  feeds and add new outlets as found.
- NATIONAL_FEEDS — trade press. No state tag; the classifier infers the state
  from the article. StateScoop is dense digital-pillar coverage.
"""

STATENEWSROOM_FEEDS = {
    "AK": "alaskabeacon.com",
    "AL": "alabamareflector.com",
    "AR": "arkansasadvocate.com",
    "AZ": "azmirror.com",
    "CO": "coloradonewsline.com",
    "FL": "floridaphoenix.com",
    "GA": "georgiarecorder.com",
    "IA": "iowacapitaldispatch.com",
    "ID": "idahocapitalsun.com",
    "IN": "indianacapitalchronicle.com",
    "KS": "kansasreflector.com",
    "KY": "kentuckylantern.com",
    "LA": "lailluminator.com",
    "MD": "marylandmatters.org",
    "ME": "mainemorningstar.com",
    "MI": "michiganadvance.com",
    "MN": "minnesotareformer.com",
    "MO": "missouriindependent.com",
    "MT": "dailymontanan.com",
    "NC": "ncnewsline.com",
    "ND": "northdakotamonitor.com",
    "NE": "nebraskaexaminer.com",
    "NH": "newhampshirebulletin.com",
    "NJ": "newjerseymonitor.com",
    "NM": "sourcenm.com",
    "NV": "nevadacurrent.com",
    "OH": "ohiocapitaljournal.com",
    "OK": "oklahomavoice.com",
    "OR": "oregoncapitalchronicle.com",
    "PA": "penncapital-star.com",
    "RI": "rhodeislandcurrent.com",
    "SC": "scdailygazette.com",
    "SD": "southdakotasearchlight.com",
    "TN": "tennesseelookout.com",
    "UT": "utahnewsdispatch.com",
    "VA": "virginiamercury.com",
    "WA": "washingtonstatestandard.com",
    "WI": "wisconsinexaminer.com",
    "WV": "westvirginiawatch.com",
}

# state -> [{"name": outlet name, "feed_url": verified RSS URL}]
# Populated from the 2026-06-09 RSS verification sweep; see module docstring.
NEWSPAPER_FEEDS = {
    "AK": [
        {"name": "Anchorage Daily News", "feed_url": "https://www.adn.com/arc/outboundfeeds/rss/?outputType=xml"},
        {"name": "Juneau Empire", "feed_url": "https://www.juneauempire.com/feed/"},
    ],
    "AL": [
        {"name": "Alabama Daily News", "feed_url": "https://aldailynews.com/feed/"},
        {"name": "Alabama Political Reporter", "feed_url": "https://www.alreporter.com/feed/"},
        {"name": "AL.com", "feed_url": "https://www.al.com/arc/outboundfeeds/rss/?outputType=xml"},
    ],
    "AR": [
        {"name": "Arkansas Times", "feed_url": "https://arktimes.com/feed"},
        {"name": "Talk Business & Politics", "feed_url": "https://talkbusiness.net/feed/"},
    ],
    "AZ": [
        {"name": "Arizona Capitol Times", "feed_url": "https://azcapitoltimes.com/feed/"},
        {"name": "KJZZ", "feed_url": "https://www.kjzz.org/politics.rss"},
    ],
    "CA": [
        {"name": "CalMatters", "feed_url": "https://calmatters.org/feed/"},
        {"name": "Capitol Weekly", "feed_url": "https://capitolweekly.net/feed/"},
        {"name": "LA Times Politics", "feed_url": "https://www.latimes.com/politics/rss2.0.xml"},
    ],
    "CO": [
        {"name": "The Colorado Sun", "feed_url": "https://coloradosun.com/feed/"},
        {"name": "Colorado Politics", "feed_url": "https://www.coloradopolitics.com/feed/"},
    ],
    "CT": [
        {"name": "CT Mirror", "feed_url": "https://ctmirror.org/feed/"},
        {"name": "CT News Junkie", "feed_url": "https://ctnewsjunkie.com/feed/"},
    ],
    "DE": [
        {"name": "Spotlight Delaware", "feed_url": "https://spotlightdelaware.org/feed/"},
        {"name": "Delaware Public Media", "feed_url": "https://www.delawarepublic.org/politics-government.rss"},
        {"name": "WHYY Delaware", "feed_url": "https://whyy.org/feed/"},
    ],
    "FL": [
        {"name": "Florida Politics", "feed_url": "https://floridapolitics.com/feed/"},
        {"name": "Tampa Bay Times", "feed_url": "https://www.tampabay.com/arc/outboundfeeds/rss/?outputType=xml"},
        {"name": "WUSF", "feed_url": "https://www.wusf.org/politics-issues.rss"},
    ],
    "GA": [
        {"name": "Capitol Beat News Service", "feed_url": "https://capitol-beat.org/feed/"},
        {"name": "Georgia Public Broadcasting", "feed_url": "https://www.gpb.org/rss"},
        {"name": "Atlanta Civic Circle", "feed_url": "https://atlantaciviccircle.org/feed/"},
    ],
    "HI": [
        {"name": "Honolulu Civil Beat", "feed_url": "https://www.civilbeat.org/feed/"},
        {"name": "Hawaii Public Radio", "feed_url": "https://www.hawaiipublicradio.org/local-news.rss"},
        {"name": "Star-Advertiser", "feed_url": "https://www.staradvertiser.com/feed/"},
    ],
    "IA": [
        {"name": "Radio Iowa", "feed_url": "https://www.radioiowa.com/feed/"},
        {"name": "Iowa Public Radio", "feed_url": "https://www.iowapublicradio.org/ipr-news.rss"},
        {"name": "Bleeding Heartland", "feed_url": "https://www.bleedingheartland.com/feed/"},
    ],
    "ID": [
        {"name": "Idaho Education News", "feed_url": "https://www.idahoednews.org/feed/"},
        {"name": "Boise State Public Radio", "feed_url": "https://www.boisestatepublicradio.org/news.rss"},
    ],
    "IL": [
        {"name": "Capitol News Illinois", "feed_url": "https://capitolnewsillinois.com/feed/"},
        {"name": "NPR Illinois", "feed_url": "https://www.nprillinois.org/illinois.rss"},
        {"name": "Chicago Sun-Times", "feed_url": "https://chicago.suntimes.com/feed"},
    ],
    "IN": [
        {"name": "Indiana Public Media", "feed_url": "https://indianapublicmedia.org/index.rss"},
    ],
    "KS": [
        {"name": "KCUR", "feed_url": "https://www.kcur.org/politics-elections-and-government.rss"},
        {"name": "KSNT", "feed_url": "https://www.ksnt.com/feed/"},
        {"name": "Sunflower State Journal", "feed_url": "https://sunflowerstatejournal.com/feed/"},
    ],
    "KY": [
        {"name": "Kentucky Public Radio", "feed_url": "https://www.lpm.org/news.rss"},
        {"name": "Link NKY", "feed_url": "https://linknky.com/feed/"},
    ],
    "LA": [
        {"name": "Louisiana Radio Network", "feed_url": "https://louisianaradionetwork.com/feed/"},
        {"name": "WWNO", "feed_url": "https://www.wwno.org/politics.rss"},
    ],
    "MA": [
        {"name": "CommonWealth Beacon", "feed_url": "https://commonwealthbeacon.org/feed/"},
        {"name": "GBH News", "feed_url": "https://www.wgbh.org/news/politics.rss"},
        {"name": "MassLive", "feed_url": "https://www.masslive.com/arc/outboundfeeds/rss/?outputType=xml"},
    ],
    "MD": [
        {"name": "Baltimore Banner", "feed_url": "https://www.thebaltimorebanner.com/arc/outboundfeeds/rss/?outputType=xml"},
        {"name": "WYPR", "feed_url": "https://www.wypr.org/index.rss"},
        {"name": "Maryland Reporter", "feed_url": "https://marylandreporter.com/feed/"},
    ],
    "ME": [
        {"name": "Portland Press Herald", "feed_url": "https://www.pressherald.com/feed/"},
        {"name": "Bangor Daily News", "feed_url": "https://www.bangordailynews.com/feed/"},
        {"name": "Maine Public", "feed_url": "https://www.mainepublic.org/politics.rss"},
    ],
    "MI": [
        {"name": "Bridge Michigan", "feed_url": "https://www.bridgemi.com/rss.xml"},
        {"name": "Michigan Public", "feed_url": "https://www.michiganpublic.org/politics-government.rss"},
        {"name": "MLive", "feed_url": "https://www.mlive.com/arc/outboundfeeds/rss/?outputType=xml"},
    ],
    "MN": [
        {"name": "MinnPost", "feed_url": "https://www.minnpost.com/feed/"},
        {"name": "Star Tribune", "feed_url": "https://www.startribune.com/rss/"},
    ],
    "MO": [
        {"name": "St. Louis Public Radio", "feed_url": "https://www.stlpr.org/government-politics-issues.rss"},
        {"name": "Missourinet", "feed_url": "https://www.missourinet.com/feed/"},
        {"name": "St. Louis Post-Dispatch", "feed_url": "https://www.stltoday.com/search/?f=rss"},
    ],
    "MS": [
        {"name": "Mississippi Today", "feed_url": "https://mississippitoday.org/feed/"},
        {"name": "Magnolia Tribune", "feed_url": "https://magnoliatribune.com/feed/"},
        {"name": "Mississippi Free Press", "feed_url": "https://www.mississippifreepress.org/feed/"},
    ],
    "MT": [
        {"name": "Montana Free Press", "feed_url": "https://montanafreepress.org/feed/"},
        {"name": "Montana Public Radio", "feed_url": "https://www.mtpr.org/montana-news.rss"},
    ],
    "NC": [
        {"name": "The Assembly", "feed_url": "https://www.theassemblync.com/feed/"},
        {"name": "WUNC", "feed_url": "https://www.wunc.org/politics.rss"},
        {"name": "WRAL", "feed_url": "https://www.wral.com/news/rss/142/"},
    ],
    "ND": [
        {"name": "InForum", "feed_url": "https://www.inforum.com/index.rss"},
        {"name": "Prairie Public", "feed_url": "https://news.prairiepublic.org/local-news.rss"},
        {"name": "KFYR", "feed_url": "https://www.kfyrtv.com/arc/outboundfeeds/rss/?outputType=xml"},
    ],
    "NE": [
        {"name": "Flatwater Free Press", "feed_url": "https://flatwaterfreepress.org/feed/"},
        {"name": "KETV", "feed_url": "https://www.ketv.com/topstories-rss"},
    ],
    "NH": [
        {"name": "NHPR", "feed_url": "https://www.nhpr.org/nh-news.rss"},
        {"name": "InDepthNH", "feed_url": "https://indepthnh.org/feed/"},
        {"name": "NH Journal", "feed_url": "https://nhjournal.com/feed/"},
    ],
    "NJ": [
        {"name": "NJ Spotlight News", "feed_url": "https://www.njspotlightnews.org/feed/"},
        {"name": "New Jersey Globe", "feed_url": "https://newjerseyglobe.com/feed/"},
        {"name": "NJ.com", "feed_url": "https://www.nj.com/arc/outboundfeeds/rss/?outputType=xml"},
    ],
    "NM": [
        {"name": "NM Political Report", "feed_url": "https://nmpoliticalreport.com/feed/"},
        {"name": "KUNM", "feed_url": "https://www.kunm.org/local-news.rss"},
    ],
    "NV": [
        {"name": "The Nevada Independent", "feed_url": "https://thenevadaindependent.com/feed"},
        {"name": "Las Vegas Review-Journal", "feed_url": "https://www.reviewjournal.com/feed/"},
    ],
    "NY": [
        {"name": "New York Focus", "feed_url": "https://nysfocus.com/feed"},
        {"name": "City & State NY", "feed_url": "https://www.cityandstateny.com/rss/all/"},
        {"name": "Gothamist", "feed_url": "https://gothamist.com/feed"},
    ],
    "OH": [
        {"name": "Statehouse News Bureau", "feed_url": "https://www.statenews.org/government-politics.rss"},
        {"name": "Signal Ohio", "feed_url": "https://signalohio.org/feed/"},
        {"name": "Signal Cleveland", "feed_url": "https://signalcleveland.org/feed/"},
    ],
    "OK": [
        {"name": "The Journal Record", "feed_url": "https://journalrecord.com/feed/"},
        {"name": "NonDoc", "feed_url": "https://nondoc.com/feed/"},
        {"name": "Oklahoma Watch", "feed_url": "https://oklahomawatch.org/feed/"},
    ],
    "OR": [
        {"name": "OPB", "feed_url": "https://www.opb.org/arc/outboundfeeds/rss/?outputType=xml"},
        {"name": "Willamette Week", "feed_url": "https://www.wweek.com/arc/outboundfeeds/rss/?outputType=xml"},
        {"name": "The Oregonian", "feed_url": "https://www.oregonlive.com/arc/outboundfeeds/rss/?outputType=xml"},
    ],
    "PA": [
        {"name": "WHYY", "feed_url": "https://whyy.org/categories/politics-policy/feed/"},
        {"name": "PennLive", "feed_url": "https://www.pennlive.com/arc/outboundfeeds/rss/?outputType=xml"},
        {"name": "WESA", "feed_url": "https://www.wesa.fm/politics-government.rss"},
    ],
    "RI": [
        {"name": "The Public's Radio", "feed_url": "https://thepublicsradio.org/feed/"},
        {"name": "Providence Business News", "feed_url": "https://pbn.com/feed/"},
        {"name": "WPRI", "feed_url": "https://www.wpri.com/feed/"},
    ],
    "SC": [
        {"name": "FITSNews", "feed_url": "https://www.fitsnews.com/feed/"},
        {"name": "SC Public Radio", "feed_url": "https://www.southcarolinapublicradio.org/sc-news.rss"},
    ],
    "SD": [
        {"name": "KELOLAND", "feed_url": "https://www.keloland.com/feed/"},
        {"name": "Mitchell Republic", "feed_url": "https://www.mitchellrepublic.com/index.rss"},
        {"name": "Dakota News Now", "feed_url": "https://www.dakotanewsnow.com/arc/outboundfeeds/rss/?outputType=xml"},
    ],
    "TN": [
        {"name": "Nashville Banner", "feed_url": "https://nashvillebanner.com/feed/"},
        {"name": "WPLN", "feed_url": "https://wpln.org/feed/"},
    ],
    "TX": [
        {"name": "Texas Tribune", "feed_url": "https://www.texastribune.org/feeds/main/"},
        {"name": "Texas Observer", "feed_url": "https://www.texasobserver.org/feed/"},
        {"name": "Texas Standard", "feed_url": "https://www.texasstandard.org/feed/"},
    ],
    "UT": [
        {"name": "KUER", "feed_url": "https://www.kuer.org/politics-government.rss"},
        {"name": "The Salt Lake Tribune", "feed_url": "https://www.sltrib.com/arc/outboundfeeds/rss/?outputType=xml"},
        {"name": "Utah Policy", "feed_url": "https://utahpolicy.com/feed/"},
    ],
    "VA": [
        {"name": "Cardinal News", "feed_url": "https://cardinalnews.org/feed/"},
        {"name": "Virginia Business", "feed_url": "https://virginiabusiness.com/feed/"},
        {"name": "VPM", "feed_url": "https://www.vpm.org/news.rss"},
    ],
    "VT": [
        {"name": "VTDigger", "feed_url": "https://vtdigger.org/feed/"},
        {"name": "Seven Days", "feed_url": "https://www.sevendaysvt.com/vermont/Rss.xml"},
    ],
    "WA": [
        {"name": "Washington Observer", "feed_url": "https://washingtonobserver.substack.com/feed"},
        {"name": "Cascade PBS", "feed_url": "https://crosscut.com/rss"},
    ],
    "WI": [
        {"name": "Wisconsin Watch", "feed_url": "https://wisconsinwatch.org/feed/"},
        {"name": "Urban Milwaukee", "feed_url": "https://urbanmilwaukee.com/feed/"},
        {"name": "WPR", "feed_url": "https://www.wpr.org/feed"},
    ],
    "WV": [
        {"name": "Mountain State Spotlight", "feed_url": "https://mountainstatespotlight.org/feed/"},
        {"name": "WV MetroNews", "feed_url": "https://wvmetronews.com/feed/"},
        {"name": "Charleston Gazette-Mail", "feed_url": "https://www.wvgazettemail.com/search/?f=rss&c=news/politics"},
    ],
    "WY": [
        {"name": "WyoFile", "feed_url": "https://wyofile.com/feed/"},
        {"name": "Wyoming Public Media", "feed_url": "https://www.wyomingpublicmedia.org/rss.xml"},
        {"name": "Oil City News", "feed_url": "https://oilcity.news/feed/"},
    ],
}

NATIONAL_FEEDS = [
    {"name": "StateScoop", "feed_url": "https://statescoop.com/feed/"},
]


def all_feeds():
    """Yield (state_or_None, outlet_name, feed_url, source_type)."""
    for state, domain in STATENEWSROOM_FEEDS.items():
        yield state, domain, f"https://{domain}/feed/localFeed", "statenewsroom"
    for state, outlets in NEWSPAPER_FEEDS.items():
        for o in outlets:
            yield state, o["name"], o["feed_url"], "newspaper"
    for o in NATIONAL_FEEDS:
        yield None, o["name"], o["feed_url"], "trade-press"


if __name__ == "__main__":
    # `python sources.py --json > web/app/methodology/sources.json`
    # regenerates the snapshot the web Sources & Methodology page renders.
    import json
    import sys

    if "--json" in sys.argv:
        json.dump(
            {
                "verified": "2026-06-09",
                "statenewsroom": STATENEWSROOM_FEEDS,
                "newspapers": NEWSPAPER_FEEDS,
                "national": NATIONAL_FEEDS,
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
    else:
        print(f"{sum(1 for _ in all_feeds())} feeds; use --json for the registry")
