"""данные личной оценки полезности готового разбора"""

from pydantic import BaseModel, ConfigDict, StrictBool


class UsefulnessRating(BaseModel):
    model_config = ConfigDict(extra="forbid")
    useful: StrictBool
