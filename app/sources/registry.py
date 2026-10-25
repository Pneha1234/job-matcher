"""Every source plugin, by name."""

from app.sources.ats import ATS_SOURCES
from app.sources.base import Source
from app.sources.crawl import CRAWL_SOURCES
from app.sources.feeds import FEED_SOURCES
from app.sources.jobspy_source import JOBSPY_SOURCES

SOURCES: dict[str, Source] = {
    cls.name: cls() for cls in [*JOBSPY_SOURCES, *ATS_SOURCES, *FEED_SOURCES, *CRAWL_SOURCES]
}


def get(name: str) -> Source:
    if name not in SOURCES:
        raise KeyError(name)
    return SOURCES[name]
