"""Curated starting aliases for well-known institutions: acronyms the list's
name lacks, Swahili names people actually type, spelling variants and former
names. Applied by exact (type, name), so a row that isn't in a given
database is simply reported and skipped -- never guessed at.

Used by migration alumni.0005 (so production gets them on deploy) and by
`manage.py seed_school_aliases` (re-runnable, idempotent). More aliases are
added in the Django admin on each school."""

U = 'university'

SEED = [
    (U, 'University of Dar es Salaam (UDSM)', ['Chuo Kikuu cha Dar es Salaam']),
    (U, 'University of Dodoma (UDOM)', ['Chuo Kikuu cha Dodoma']),
    (U, 'Sokoine University of Agriculture (SUA)',
     ['Chuo Kikuu cha Kilimo cha Sokoine', 'Chuo Kikuu cha Kilimo Sokoine']),
    (U, 'Muhimbili University of Health and Allied Sciences (MUHAS)',
     ['Chuo Kikuu cha Afya na Sayansi Shirikishi Muhimbili']),
    (U, 'Open University of Tanzania (OUT)', ['Chuo Kikuu Huria cha Tanzania']),
    (U, 'Ardhi University (ARU)',
     ['Chuo Kikuu cha Ardhi', 'UCLAS', 'University College of Lands and Architectural Studies']),
    (U, 'Mzumbe University (MU)', ['Chuo Kikuu Mzumbe']),
    (U, 'State University of Zanzibar (SUZA)', ['Chuo Kikuu cha Taifa cha Zanzibar']),
    (U, 'Nelson Mandela African Institution of Science and Technology (NM-AIST)', ['NMAIST']),
    (U, 'Moshi Cooperative University (MoCU)', ['Moshi Co-operative University', 'MUCCoBS']),
    (U, 'Mbeya University of Science and Technology (MUST)',
     ['MIST', 'Mbeya Institute of Science and Technology']),
    (U, 'St. Augustine University of Tanzania (SAUT)', ['Saint Augustine University of Tanzania']),
    (U, "St. John's University of Tanzania (SJUT)",
     ['St Johns University of Tanzania', 'Saint Johns University of Tanzania']),
    (U, 'Institute of Finance Management - Dar Es Salaam', ['IFM']),
    (U, 'Institute of Finance Management - Dodoma Campus', ['IFM']),
    (U, 'Institute of Finance Management - Mwanza Campus', ['IFM']),
    (U, 'Dar Es Salaam Institute of Technology', ['DIT']),
    (U, 'Dar Es Salaam Institute of Technology - Myunga Campus', ['DIT']),
    (U, 'College of Business Education - Mwanza', ['CBE']),
    (U, 'Arusha Technical College - Arusha', ['ATC']),
]


def seed(School, SchoolAlias):
    """Returns (aliases_created, [names not found]). Safe to re-run."""
    created, missing = 0, []
    for school_type, name, aliases in SEED:
        schools = list(School.objects.filter(school_type=school_type, name=name))
        if not schools:
            missing.append(name)
            continue
        for school in schools:
            existing = {a.lower() for a in SchoolAlias.objects.filter(school=school).values_list('alias', flat=True)}
            for alias in aliases:
                if alias.lower() in existing or alias.lower() == school.name.lower():
                    continue
                SchoolAlias.objects.create(school=school, alias=alias)
                existing.add(alias.lower())
                created += 1
    return created, missing
