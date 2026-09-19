from pydantic import BaseModel, ConfigDict, Field


class SearchConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seuil_confiance_min: float
    top_k_llm: int
    anonymisation_par_defaut: bool


class SearchConfigUpdate(BaseModel):
    seuil_confiance_min: float | None = Field(default=None, ge=0.0, le=1.0)
    top_k_llm: int | None = Field(default=None, ge=3, le=15)
    anonymisation_par_defaut: bool | None = None


class NotificationTypePreference(BaseModel):
    email: bool = True
    in_app: bool = True


class NotificationPreferencesRead(BaseModel):
    cv_echec: NotificationTypePreference
    gdpr_terminee: NotificationTypePreference
    invitation_envoyee: NotificationTypePreference


class NotificationPreferencesUpdate(BaseModel):
    cv_echec: NotificationTypePreference | None = None
    gdpr_terminee: NotificationTypePreference | None = None
    invitation_envoyee: NotificationTypePreference | None = None
