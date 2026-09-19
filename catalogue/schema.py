"""Catalogue JSON schema and validation.

Single source of truth for the data contract between provisioning
(``catalogue/build_catalogue.py``) and the bot (``bot/shared``). The bot image
vendors this file at build time; keep it dependency-free (stdlib only).

Validation is hand-rolled (no jsonschema dep in the root environment): it
checks required fields, basic types, and — critically — that no private
column ever leaks into the export.
"""

from typing import Any, Dict, List

# Column names that must never appear anywhere in the catalogue.
FORBIDDEN_KEYS = frozenset(
    {
        "author_emails",
        "primary_email",
        "organiser_emails",
        "registered_emails",
        "review1",
        "review2",
        "review3",
        "review4",
        "meta_review",
    }
)

# (field, type) pairs required on every item of each list.
ITEM_REQUIRED = [
    ("id", str),
    ("title", str),
    ("abstract", str),
    ("authors", list),
    ("affiliations", list),
    ("keywords", list),
    ("miniconf_url", str),
    ("slack_channel_name", str),
    ("slack_channel_id", str),
]

PAPER_REQUIRED = ITEM_REQUIRED + [
    ("day", int),
    ("session", int),
    ("position", int),
    ("session_id", str),
    ("summary_of_updates_post_review", str),
    ("special_track", bool),
    ("award_nominee", bool),
    ("is_tismir", bool),
]

SESSION_REQUIRED = [
    ("id", str),
    ("title", str),
    ("type", str),
    ("day", int),
    ("start_utc", str),
    ("end_utc", str),
    ("location", str),
    ("slack_channel_id", str),
    ("paper_ids", list),
]

LOGISTICS_REQUIRED = [("id", str), ("title", str), ("body", str)]

TOP_LEVEL_REQUIRED = [
    ("version", str),
    ("conference", dict),
    ("embedding_model", str),
    ("papers", list),
    ("lbds", list),
    ("music", list),
    ("industry", list),
    ("sessions", list),
    ("logistics", list),
]


def _check_fields(obj, required, where, errors):
    for field, ftype in required:
        if field not in obj:
            errors.append("{}: missing field '{}'".format(where, field))
        elif not isinstance(obj[field], ftype):
            errors.append(
                "{}: field '{}' should be {}, got {}".format(
                    where, field, ftype.__name__, type(obj[field]).__name__
                )
            )


def _walk_forbidden(obj, where, errors):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in FORBIDDEN_KEYS:
                errors.append("{}: forbidden private key '{}'".format(where, key))
            _walk_forbidden(value, "{}.{}".format(where, key), errors)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _walk_forbidden(value, "{}[{}]".format(where, i), errors)


def validate_catalogue(cat: Dict[str, Any]) -> List[str]:
    """Return a list of validation errors (empty list == valid)."""
    errors: List[str] = []
    _check_fields(cat, TOP_LEVEL_REQUIRED, "catalogue", errors)

    conf = cat.get("conference", {})
    if isinstance(conf, dict):
        for field in ("name", "timezone", "site_base_url"):
            if not conf.get(field):
                errors.append("conference: missing or empty '{}'".format(field))

    for paper in cat.get("papers", []):
        _check_fields(
            paper, PAPER_REQUIRED, "papers[{}]".format(paper.get("id")), errors
        )
    for kind in ("lbds", "music", "industry"):
        for item in cat.get(kind, []):
            _check_fields(
                item, ITEM_REQUIRED, "{}[{}]".format(kind, item.get("id")), errors
            )
    for sess in cat.get("sessions", []):
        _check_fields(
            sess, SESSION_REQUIRED, "sessions[{}]".format(sess.get("id")), errors
        )
    for log in cat.get("logistics", []):
        _check_fields(
            log, LOGISTICS_REQUIRED, "logistics[{}]".format(log.get("id")), errors
        )

    # Duplicate ids within each list
    for kind in ("papers", "lbds", "music", "industry", "sessions", "logistics"):
        ids = [item.get("id") for item in cat.get(kind, [])]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            errors.append("{}: duplicate ids {}".format(kind, sorted(dupes)))

    # sessions.paper_ids must reference existing papers
    paper_ids = {p.get("id") for p in cat.get("papers", [])}
    for sess in cat.get("sessions", []):
        unknown = [i for i in sess.get("paper_ids", []) if i not in paper_ids]
        if unknown:
            errors.append(
                "sessions[{}]: unknown paper_ids {}".format(sess.get("id"), unknown)
            )

    _walk_forbidden(cat, "catalogue", errors)
    return errors
