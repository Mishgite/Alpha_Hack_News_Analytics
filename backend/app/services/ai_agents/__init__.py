"""JSON-compatible AI tagging services."""
from .bad_news import add_bad_news, load_bad_news
from .news_tagger import NewsTagger
from .profile_tagger import ProfileTagger

__all__ = ['NewsTagger', 'ProfileTagger', 'add_bad_news', 'load_bad_news']
