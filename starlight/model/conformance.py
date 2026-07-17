"""
starlight.model.conformance

RDF 1.2 / SPARQL 1.2 VERSION-directive conformance checking.

Per RDF 1.2 Concepts sec 2.1 ("Version Labels") and SPARQL 1.2 Query sec 4.3,
three version labels are defined:

    "1.2"        full RDF 1.2 conformance - triple terms and dirLangString allowed
    "1.2-basic"  RDF 1.2 syntax, but excludes triple terms and dirLangString
    "1.1"        legacy RDF 1.1 compatibility mode (discouraged in a VERSION
                 directive, since it would needlessly break RDF 1.1 parsers)

The directive is explicitly only a hint: the spec states a parser "is not
required to reject features that are outside the announced version (but
could signal them with a warning)", and the SPARQL spec similarly says
"processors may treat unrecognized labels as an error or as a warning" -
neither mandates specific behavior. Starlight signals via a warning, never a
hard error, to stay consistent with its permissive-by-default posture: a
stale-but-harmless VERSION line should never turn otherwise-valid data or a
otherwise-valid query into a hard failure.
"""

import warnings

VALID_VERSION_LABELS = frozenset({'1.2', '1.2-basic', '1.1'})


class RDF12ConformanceWarning(UserWarning):
    """A declared VERSION label doesn't match the RDF 1.2 features actually used."""


def check_version_conformance(declared_version, *, uses_triple_term: bool,
                               uses_dirlangstring: bool, context: str) -> None:
    """Warn if declared_version is unrecognized, or is "1.2-basic" while a
    triple term and/or dirLangString is actually present.

    declared_version -- the VERSION directive's label, or None if no
                         directive was present (in which case this is a no-op)
    context           -- short label identifying what was checked, for the
                          warning message, e.g. "Turtle document" or
                          "SPARQL query"
    """
    if declared_version is None:
        return

    if declared_version not in VALID_VERSION_LABELS:
        warnings.warn(
            f'{context} declares unrecognized VERSION {declared_version!r} '
            f'(expected one of {sorted(VALID_VERSION_LABELS)})',
            RDF12ConformanceWarning, stacklevel=3,
        )
        return

    if declared_version == '1.2-basic':
        used = [name for name, present in (
            ('a triple term', uses_triple_term),
            ('a directional language-tagged literal (dirLangString)', uses_dirlangstring),
        ) if present]
        if used:
            warnings.warn(
                f'{context} declares VERSION "1.2-basic" but uses {" and ".join(used)}, '
                'which "1.2-basic" conformance excludes (RDF 1.2 Concepts sec 2.1)',
                RDF12ConformanceWarning, stacklevel=3,
            )
