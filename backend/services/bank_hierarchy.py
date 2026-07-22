"""Conservative bank-to-group relationships used to explain reporting scope.

Only relationships backed by an official group/issuer source are marked as
``reports_with_parent``.  Network membership alone is useful context, but is
not treated as proof that an entity has no standalone prudential disclosure.
"""

from __future__ import annotations

import unicodedata


def _key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).strip())
    return normalized.encode("ascii", "ignore").decode("ascii").casefold()


_RELATIONSHIPS: dict[str, dict[str, str | bool]] = {
    "natixis": {
        "parent_group": "Groupe BPCE",
        "relationship": "subsidiary",
        "reports_with_parent": True,
        "source": "Natixis legal information: BPCE owns 100% of Natixis.",
        "source_url": "https://natixis.groupebpce.com/legal-information/",
    },
    "bnp paribas personal finance": {
        "parent_group": "BNP Paribas",
        "relationship": "subsidiary",
        "reports_with_parent": True,
        "source": "BNP Paribas describes Personal Finance as its specialist personal-finance business.",
        "source_url": "https://group.bnpparibas/en/press-release/bnp-paribas-sets-personal-finance-business-consolidating-specialist-personal-finance-operations",
    },
    "credit foncier de france": {
        "parent_group": "Groupe BPCE",
        "relationship": "BPCE subsidiary",
        "reports_with_parent": True,
        "source": "Groupe BPCE identifies Crédit Foncier among its subsidiaries.",
        "source_url": "https://natixis.groupebpce.com/wp-content/uploads/2022/08/natixis_en_bref_2021_july_en.pdf",
    },
    "bred - banque populaire": {
        "parent_group": "Groupe BPCE",
        "relationship": "Banque Populaire network member",
        "reports_with_parent": True,
        "source": "Groupe BPCE lists BRED Banque Populaire in its entity directory.",
        "source_url": "https://www.groupebpce.com/en/directory/",
    },
    "banque populaire auvergne rhon": {
        "parent_group": "Groupe BPCE",
        "relationship": "Banque Populaire network member",
        "reports_with_parent": True,
        "source": "Banques Populaires are one of Groupe BPCE's cooperative networks.",
        "source_url": "https://www.groupebpce.com/en/the-group/organization/",
    },
    "banque populaire alsace lorrai": {
        "parent_group": "Groupe BPCE",
        "relationship": "Banque Populaire network member",
        "reports_with_parent": True,
        "source": "Banques Populaires are one of Groupe BPCE's cooperative networks.",
        "source_url": "https://www.groupebpce.com/en/the-group/organization/",
    },
    "banque populaire grand ouest": {
        "parent_group": "Groupe BPCE",
        "relationship": "Banque Populaire network member",
        "reports_with_parent": True,
        "source": "Banques Populaires are one of Groupe BPCE's cooperative networks.",
        "source_url": "https://www.groupebpce.com/en/the-group/organization/",
    },
    "banque populaire rives de pari": {
        "parent_group": "Groupe BPCE",
        "relationship": "Banque Populaire network member",
        "reports_with_parent": True,
        "source": "Banques Populaires are one of Groupe BPCE's cooperative networks.",
        "source_url": "https://www.groupebpce.com/en/the-group/organization/",
    },
    "caisse d epargne cepac": {
        "parent_group": "Groupe BPCE",
        "relationship": "Caisse d'Epargne network member",
        "reports_with_parent": True,
        "source": "Caisses d'Epargne are one of Groupe BPCE's cooperative networks.",
        "source_url": "https://www.groupebpce.com/en/the-group/organization/",
    },
    "cic": {
        "parent_group": "Crédit Mutuel",
        "relationship": "Crédit Mutuel Alliance Fédérale subsidiary",
        "reports_with_parent": True,
        "source": "CIC reports under Crédit Mutuel Alliance Fédérale consolidated disclosures.",
        "source_url": "https://www.creditmutuel.fr",
    },
    "caisse federale de credit mutuel": {
        "parent_group": "Confédération Nationale du Crédit Mutuel",
        "relationship": "Crédit Mutuel network member",
        "reports_with_parent": True,
        "source": "Reports consolidated under Confédération Nationale du Crédit Mutuel.",
        "source_url": "https://www.creditmutuel.fr",
    },
}


def get_bank_relationship(bank_name: str) -> dict[str, str | bool] | None:
    """Return an official-source relationship record for a known reporting entity."""
    normalized_name = _key(bank_name)
    relationship = _RELATIONSHIPS.get(normalized_name)
    if relationship is None and normalized_name.startswith("caisse d epargne"):
        relationship = {
            "parent_group": "Groupe BPCE",
            "relationship": "Caisse d'Epargne network member",
            "reports_with_parent": True,
            "source": "Caisses d'Epargne are one of Groupe BPCE's cooperative networks.",
            "source_url": "https://www.groupebpce.com/en/the-group/organization/",
        }
    if relationship is None and normalized_name.startswith("banque populaire"):
        relationship = {
            "parent_group": "Groupe BPCE",
            "relationship": "Banque Populaire network member",
            "reports_with_parent": True,
            "source": "Banques Populaires are one of Groupe BPCE's cooperative networks.",
            "source_url": "https://www.groupebpce.com/en/the-group/organization/",
        }
    if relationship is None and ("credit agricole" in normalized_name or normalized_name.startswith("caisse regionale")):
        relationship = {
            "parent_group": "Crédit Agricole",
            "relationship": "Crédit Agricole network member",
            "reports_with_parent": True,
            "source": "Caisses Régionales report under Crédit Agricole consolidated disclosures.",
            "source_url": "https://www.credit-agricole.com",
        }
    return dict(relationship) if relationship else None
