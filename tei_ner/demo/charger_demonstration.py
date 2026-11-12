"""Charge le jeu de démonstration dans la base de l'application.

Usage (depuis la racine du projet) :

    python demo/charger_demonstration.py            # base de travail
    python demo/charger_demonstration.py --base /tmp/essai.db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import pandas as pd  # noqa: E402

import corpus  # noqa: E402
import database  # noqa: E402
import excel_import  # noqa: E402
import validation  # noqa: E402

DOSSIER = Path(__file__).resolve().parent


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--base", default=None, help="chemin de la base SQLite")
    arguments = analyseur.parse_args()

    cx = database.ouvrir(arguments.base)
    print(f"Base : {database.chemin_base(arguments.base)}")

    print("\n1. Import des fichiers XML-TEI")
    for fichier in sorted(DOSSIER.glob("*.xml")):  # les exemples d'export sont dans exemples/
        compte_rendu = corpus.importer_fichier(
            cx, fichier.read_bytes(), fichier.name, reprendre_annotations_tei=True
        )
        print(f"   {fichier.name:35s} {compte_rendu['statut']:9s} {compte_rendu['message']}")

    tableur = DOSSIER / "anciennes-donnees.xlsx"
    if tableur.exists():
        feuilles = excel_import.lire_tableur(tableur.read_bytes(), tableur.name)

        print("\n2. Reprise du référentiel depuis le tableur")
        cadre = feuilles["Entités"]
        correspondances = excel_import.deviner_correspondances(cadre.columns, "referentiel")
        print(f"   colonnes reconnues : {correspondances}")
        lignes = excel_import.preparer_referentiel(
            cx, cadre, correspondances, colonnes_metadonnees=["Dates"]
        )
        rapport = excel_import.appliquer_referentiel(cx, lignes, tableur.name)
        print(f"   {rapport}")

        print("\n3. Reprise des mentions depuis le tableur")
        cadre = feuilles["Mentions"]
        correspondances = excel_import.deviner_correspondances(cadre.columns, "annotations")
        print(f"   colonnes reconnues : {correspondances}")
        lignes = excel_import.preparer_annotations(
            cx, cadre, correspondances, creer_entites_manquantes=False,
            toutes_occurrences=True,
        )
        for resultat in lignes:
            if resultat["messages"]:
                print(f"   ligne {resultat['ligne']} : {' '.join(resultat['messages'])}")
        rapport = excel_import.appliquer_annotations(cx, lignes, tableur.name)
        print(f"   {rapport}")

    print("\n4. Contrôles qualité")
    alertes = validation.executer_controles(cx)
    print(f"   {validation.resume(alertes)}")
    for alerte in alertes[:8]:
        print(f"   [{alerte.niveau}] {alerte.message}")

    print("\n5. Statistiques")
    for cle, valeur in database.statistiques(cx).items():
        print(f"   {cle:28s} {valeur}")

    print("\nJeu de démonstration chargé. Lancez : streamlit run app.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
