"""Least-privilege, read-only access to the component-visible Farm X core data."""
from functools import lru_cache
import math

from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine

from backend.app.core.config import get_settings
from components.member1_didt.schemas.counterfactual import CowReference, CowState


class AnimalNotFound(LookupError):
    """The approved shared data has no usable current cow-day for the reference."""


class FarmXDataUnavailable(RuntimeError):
    """The approved data source could not be accessed or is incomplete."""


@lru_cache(maxsize=1)
def component_engine() -> Engine:
    """Create a read-only connection using only the configured farmx_c13 role."""
    settings = get_settings()
    if not settings.app_db_c13_user or not settings.app_db_c13_password:
        raise FarmXDataUnavailable("The component database role is not configured.")
    url = URL.create(
        "postgresql+psycopg",
        username=settings.app_db_c13_user,
        password=settings.app_db_c13_password,
        host=settings.app_db_host,
        port=settings.app_db_port,
        database=settings.app_db_name,
    )
    return create_engine(
        url, pool_pre_ping=True,
        connect_args={"options": "-c default_transaction_read_only=on"},
    )


CURRENT_STATE_SQL = text("""
    select d.animal_key as animal_ref, d.milk_date as observed_date,
           a.breed, (d.milk_date - a.birth_date) as age_days,
           d.lactation_no, d.dim as days_in_milk, cd.days_pregnant,
           d.yield_litres as milk_yield_l_day,
           case when d.milkings >= 0 then d.milkings end as milkings_per_day,
           case when d.dm_consumed >= 0 then d.dm_consumed end as dry_matter_intake,
           case when d.conc_consumed >= 0 then d.conc_consumed end as concentrate_intake,
           case when d.avg_bcs between 1 and 5 then d.avg_bcs end as bcs,
           case when d.avg_weight > 0 then d.avg_weight end as body_weight,
           d.avg_rectal_temp as rectal_temperature,
           w.thi_mean,
           a.n_calvings,
           (select count(*) from core.clinical_event ce
             where ce.animal_key=d.animal_key and ce.event_date between d.milk_date - 30 and d.milk_date
               and coalesce(ce.is_bad_date,false)=false) as recent_clinical_event_count,
           (select count(*) from core.treatment_history th
             where th.animal_key=d.animal_key and th.treatment_start_date between d.milk_date - 30 and d.milk_date
               and coalesce(th.is_bad_date,false)=false) as recent_treatment_count
    from core.daily_milk d
    join core.animal a on a.animal_key=d.animal_key
    left join core.weather_day w on w.date=d.milk_date
    left join lateral (
        select cow_day.days_pregnant from core.cow_day
        where cow_day.animal_key=d.animal_key and cow_day.milk_date=d.milk_date
        order by cow_day.is_reliable desc nulls last limit 1
    ) cd on true
    where d.animal_key=:animal_ref
      and coalesce(a.is_placeholder,false)=false
      and coalesce(d.is_unlinked_animal,false)=false
      and coalesce(d.is_placeholder,false)=false
      and coalesce(d.is_spike,false)=false
      and coalesce(d.is_missing_yield,false)=false
      and coalesce(d.is_bad_date,false)=false
      and d.yield_litres is not null and d.yield_litres >= 0 and d.dim is not null and d.dim >= 0
      and (d.lactation_no is null or d.lactation_no >= 0)
    order by d.milk_date desc limit 1
""")


AVAILABLE_ANIMALS_SQL = text("""
    select distinct on (d.animal_key)
           d.animal_key as animal_ref, d.milk_date as observed_date
    from core.daily_milk d
    join core.animal a on a.animal_key=d.animal_key
    where coalesce(a.is_placeholder,false)=false
      and coalesce(d.is_unlinked_animal,false)=false
      and coalesce(d.is_placeholder,false)=false
      and coalesce(d.is_spike,false)=false
      and coalesce(d.is_missing_yield,false)=false
      and coalesce(d.is_bad_date,false)=false
      and d.yield_litres is not null and d.yield_litres >= 0
      and d.dim is not null and d.dim >= 0
      and (d.lactation_no is null or d.lactation_no >= 0)
    order by d.animal_key, d.milk_date desc
    limit :limit
""")


TRAINING_SQL = """
with usable as (
    select d.milk_date,
           d.yield_litres as yield_today_l_day,
           lead(d.milk_date) over (partition by d.animal_key order by d.milk_date) as target_date,
           lead(d.yield_litres) over (partition by d.animal_key order by d.milk_date) as target_yield_l_day,
           d.dim as days_in_milk, d.lactation_no,
           case when d.milkings >= 0 then d.milkings end as milkings_per_day,
           case when d.dm_consumed >= 0 then d.dm_consumed end as dry_matter_intake,
           case when d.conc_consumed >= 0 then d.conc_consumed end as concentrate_intake,
           case when d.avg_bcs between 1 and 5 then d.avg_bcs end as bcs,
           case when d.avg_weight > 0 then d.avg_weight end as body_weight,
           d.avg_rectal_temp as rectal_temperature,
           w.thi_mean, a.breed
    from core.daily_milk d
    join core.animal a on a.animal_key=d.animal_key
    left join core.weather_day w on w.date=d.milk_date
    where coalesce(a.is_placeholder,false)=false
      and coalesce(d.is_unlinked_animal,false)=false
      and coalesce(d.is_placeholder,false)=false
      and coalesce(d.is_spike,false)=false
      and coalesce(d.is_missing_yield,false)=false
      and coalesce(d.is_bad_date,false)=false
      and d.yield_litres is not null and d.yield_litres >= 0 and d.dim is not null and d.dim >= 0
      and (d.lactation_no is null or d.lactation_no >= 0)
)
select milk_date, target_yield_l_day, yield_today_l_day, days_in_milk,
       lactation_no, milkings_per_day, dry_matter_intake, concentrate_intake,
       bcs, body_weight, rectal_temperature, thi_mean, breed
from usable
where target_date = milk_date + 1 and target_yield_l_day is not null
order by milk_date
"""


class FarmXRepository:
    """Read actual current state and historical prediction rows; never writes."""
    def __init__(self, engine: Engine | None = None):
        self.engine = engine or component_engine()

    def get_current_state(self, animal_ref: str) -> CowState:
        try:
            with self.engine.connect() as connection:
                row = connection.execute(CURRENT_STATE_SQL, {"animal_ref": animal_ref}).mappings().first()
        except Exception as exc:
            raise FarmXDataUnavailable("Approved Farm X data could not be read.") from exc
        if row is None:
            raise AnimalNotFound("No usable published cow-day was found for this animal reference.")
        record = dict(row)
        record["observed_date"] = record["observed_date"].isoformat()
        limitations = []
        for key, predicate, explanation in (
            ("bcs", lambda value: 1 <= value <= 5, "BCS value is outside the supported 1–5 scale and was withheld."),
            ("body_weight", lambda value: value > 0, "Non-positive body weight was withheld as invalid."),
            ("age_days", lambda value: value >= 0, "Negative age derived from source dates was withheld as invalid."),
            ("days_in_milk", lambda value: value >= 0, "Negative days in milk was withheld as invalid."),
            ("lactation_no", lambda value: value >= 0, "Negative lactation number was withheld as invalid."),
            ("days_pregnant", lambda value: value >= 0, "Negative pregnancy duration was withheld as invalid."),
            ("milkings_per_day", lambda value: value >= 0, "Negative milking count was withheld as invalid."),
            ("n_calvings", lambda value: value >= 0, "Negative calving count was withheld as invalid."),
            ("dry_matter_intake", lambda value: value >= 0, "Negative dry matter intake was withheld as invalid."),
            ("concentrate_intake", lambda value: value >= 0, "Negative concentrate intake was withheld as invalid."),
        ):
            value = record.get(key)
            if value is not None and not predicate(value):
                record[key] = None
                limitations.append(explanation)
        for key in ("milk_yield_l_day", "dry_matter_intake", "concentrate_intake", "rectal_temperature", "thi_mean"):
            value = record.get(key)
            if value is not None and isinstance(value, (float, int)) and not math.isfinite(value):
                record[key] = None
                limitations.append(f"Non-finite {key} value was withheld as invalid.")
        for key, label in (
            ("dry_matter_intake", "Dry matter intake is missing/invalid or its source unit is undocumented."),
            ("concentrate_intake", "Concentrate intake is missing/invalid or its source unit is undocumented."),
            ("bcs", "Body-condition score is unavailable for the latest valid day."),
            ("body_weight", "Body weight is unavailable for the latest valid day."),
            ("thi_mean", "Daily THI is unavailable for the latest valid day."),
        ):
            if record.get(key) is None:
                limitations.append(label)
        record["data_limitations"] = limitations
        try:
            return CowState.model_validate(record)
        except Exception as exc:
            raise FarmXDataUnavailable("Published cow state did not match the component data contract.") from exc

    def list_available_animals(self, limit: int = 10000) -> list[CowReference]:
        """List a bounded set of approved references with usable yield history."""
        if not 1 <= limit <= 10000:
            raise ValueError("Animal reference list limit must be from 1 to 10000.")
        try:
            with self.engine.connect() as connection:
                rows = connection.execute(AVAILABLE_ANIMALS_SQL, {"limit": limit}).mappings().all()
        except Exception as exc:
            raise FarmXDataUnavailable("Approved Farm X animal references could not be read.") from exc
        try:
            return [CowReference(animal_ref=row["animal_ref"], observed_date=row["observed_date"].isoformat())
                    for row in rows]
        except Exception as exc:
            raise FarmXDataUnavailable("Approved animal references did not match the component data contract.") from exc
