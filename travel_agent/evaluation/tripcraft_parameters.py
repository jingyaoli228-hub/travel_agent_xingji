"""Published TripCraft parameters plus explicitly labelled engineering policy."""

MEAL_PARAMETERS = {
    3: {"breakfast": (9.63, .90, 1.08, .24, .21), "lunch": (14.30, 1.11, 1.03, .36, .10), "dinner": (20.75, 1.19, 1.25, .43, -.20)},
    5: {"breakfast": (9.80, 1.08, 1.08, 1.43, .63), "lunch": (14.46, 1.10, 1.07, .35, .04), "dinner": (20.67, 1.32, 1.37, .91, -.18)},
    7: {"breakfast": (9.84, .85, 1.34, .23, .03), "lunch": (14.44, .99, 1.07, .26, .30), "dinner": (20.42, 1.15, 1.66, 1.15, -.07)},
}

ATTRACTION_PARAMETERS = {
    3: {"laidback_lambda": 1.10, "adventurous_lambda": 2.01, "sigma": 1.11, "n_max": 5, "n_min": 0, "k": .28},
    5: {"laidback_lambda": 1.26, "adventurous_lambda": 1.61, "sigma": 1.07, "n_max": 4, "n_min": 0, "k": .28},
    7: {"laidback_lambda": 1.11, "adventurous_lambda": 1.82, "sigma": .90, "n_max": 4, "n_min": 0, "k": .28},
}

SPATIAL_D0_METERS = 5000.0
SPATIAL_LAMBDA = .0002

# Engineering thresholds, independently calibrated/configurable; no aggregate score.
METRIC_THRESHOLDS = {"temporal_meal": .35, "temporal_attraction": .02, "spatial": .35, "persona": -.10}


def nearest_duration_bucket(days: int) -> tuple[int, bool]:
    bucket = min((3, 5, 7), key=lambda candidate: (abs(candidate - days), candidate))
    return bucket, days not in (3, 5, 7)
