"""начальные интересы должностей для демонстрационного ранжирования"""

from app.schemas.services import ProfilePolicy


def default_policy():
    """задаёт явные стартовые веса, отключённые пользователем темы всё равно получают ноль"""
    return ProfilePolicy(
        version="roles-v1",
        role_weights={
            "ceo": {"biz_investment": 1.2, "biz_logistic": 1.1},
            "cfo": {"biz_credit": 1.3, "biz_rates": 1.3, "biz_budget": 1.2},
            "accountant": {"biz_tax": 1.3, "biz_vat": 1.3, "biz_account": 1.3},
            "treasury": {"biz_fx": 1.3, "biz_rates": 1.3, "biz_bank": 1.2},
        },
    )
