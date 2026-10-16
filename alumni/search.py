"""School search shared by the browser autocomplete (config.views.school_search)
and the mobile API (alumni.views.SchoolSearchView).

The master school list stores bare names ("Arusha", "Njiro Hill"), but people
type the official form ("Arusha Secondary School"). A plain substring match on
the whole query therefore finds nothing, so the query is split into words,
filler words are dropped for school-level types, every remaining word must
appear in the name (any order), and results are ranked best-first."""
import re

from django.db.models import Q
from django.db.models.functions import Length

from .models import School

DEFAULT_LIMIT = 20
_CANDIDATE_CAP = 300

# Words people add to a school's name that the master list doesn't store.
# Only dropped for primary/secondary/high_school -- "school", "college" and
# "institute" are real parts of university and college names.
_FILLER = {
    'secondary', 'primary', 'school', 'schools', 'high', 'sec', 'pri', 'sch',
    'ss', 'ps', 'level', 'olevel', 'alevel',
}
_FILLER_TYPES = {'primary', 'secondary', 'high_school'}

_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text):
    return _WORD_RE.findall((text or '').lower())


def query_tokens(query, school_type):
    """The words a school name must contain for this query. Falls back to
    every word typed when the query is only filler ("primary school"), so
    partial typing like "Prim" -> "Primary" never blanks the results."""
    typed = _words(query)
    if school_type in _FILLER_TYPES:
        return [t for t in typed if t not in _FILLER] or typed
    return typed


def _rank(name, tokens):
    words = _words(name)
    if words == tokens:
        return 0                                    # exactly what was typed
    if all(t in words for t in tokens):
        return 1                                    # every typed word is a whole word
    if all(any(w.startswith(t) for w in words) for t in tokens):
        return 2 if words and words[0].startswith(tokens[0]) else 3
    return 4                                        # only matches inside a word


def search_schools(query, school_type=None, limit=DEFAULT_LIMIT):
    """`school_type=None` searches every type (the mobile API allows that)."""
    tokens = query_tokens(query, school_type)
    if not tokens:
        return []
    qs = School.objects.filter(is_active=True)
    if school_type:
        qs = qs.filter(school_type=school_type)
    # A school matches when every word is in its own name, or every word is
    # in one of its aliases (one Q so both words must hit the same alias).
    name_q, alias_q = Q(), Q()
    for token in tokens:
        name_q &= Q(name__icontains=token)
        alias_q &= Q(aliases__alias__icontains=token)
    candidates = list(
        qs.filter(name_q | alias_q).distinct()
        .annotate(name_len=Length('name')).order_by('name_len', 'name')
        .prefetch_related('aliases')[:_CANDIDATE_CAP]
    )

    def best_rank(school):
        return min([_rank(school.name, tokens)] + [_rank(a.alias, tokens) for a in school.aliases.all()])

    candidates.sort(key=lambda s: (best_rank(s), len(s.name), s.name))
    return candidates[:limit]
