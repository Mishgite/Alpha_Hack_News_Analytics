"""импортируем все таблицы, чтобы SQLAlchemy мог разрешить связи между ними"""

from app.infrastructure.database.models.analytics import (
    AIAnalysis,
    AlfaReport,
    AlfaReportChunk,
    AnalysisJob,
    AnalysisQuestion,
    LLMUsage,
)
from app.infrastructure.database.models.feed import (
    FeedSnapshot,
    FeedSnapshotItem,
    InteractionEvent,
)
from app.infrastructure.database.models.market import Stock, StockSnapshot
from app.infrastructure.database.models.news import (
    News,
    NewsAttribution,
    NewsEvent,
    NewsSource,
    NewsTag,
    ReactionTotal,
    SourceRun,
    TagFeedback,
    UserReaction,
)
from app.infrastructure.database.models.profiles import (
    Company,
    CompanyContextSnapshot,
    CompanyFeature,
    CompanyLink,
    CompanyTag,
    Tag,
    TagAlias,
    User,
    UserSession,
    UserTag,
    UserTagOverride,
    UserTagPreference,
)

__all__ = [
    "AIAnalysis",
    "AlfaReport",
    "AlfaReportChunk",
    "AnalysisJob",
    "AnalysisQuestion",
    "Company",
    "CompanyContextSnapshot",
    "CompanyFeature",
    "CompanyLink",
    "CompanyTag",
    "FeedSnapshot",
    "FeedSnapshotItem",
    "InteractionEvent",
    "LLMUsage",
    "News",
    "NewsAttribution",
    "NewsEvent",
    "NewsSource",
    "NewsTag",
    "ReactionTotal",
    "SourceRun",
    "Stock",
    "StockSnapshot",
    "Tag",
    "TagAlias",
    "TagFeedback",
    "User",
    "UserReaction",
    "UserSession",
    "UserTag",
    "UserTagOverride",
    "UserTagPreference",
]

from .runtime import ProcessingState  # noqa: F401
from .quality import AnalysisFeedback  # noqa: F401
