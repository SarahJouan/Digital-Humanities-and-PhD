# Procédure de sauvegarde et de restauration

Toutes les données de travail (documents, référentiel, annotations, journal)
sont dans un seul fichier SQLite : `data/corpus.db`.

## Sauvegarder

### Depuis l'application

*Paramètres → Sauvegarde et restauration → « Sauvegarder maintenant »*.
Le fichier est déposé dans `backups/` sous la forme
`corpus-AAAAMMJJ-HHMMSS[-étiquette].db` et peut être téléchargé depuis la page.

Une sauvegarde est créée **automatiquement** avant :

* l'application de corrections en lot (page *Validation*) ;
* tout import de tableur (page *Import tableur*) ;
* la réinitialisation des données de travail (page *Paramètres*).

### En ligne de commande

```bash
python -c "import database; print(database.sauvegarder(database.ouvrir(), etiquette='manuelle'))"
```

La sauvegarde utilise l'API `sqlite3.Connection.backup`, qui produit une copie
cohérente même si l'application est en cours d'utilisation. Une simple copie du
fichier avec `cp` est déconseillée tant que l'application tourne (journal WAL).

## Restaurer

1. **Fermez l'application** (`Ctrl+C` dans le terminal) — ou, depuis l'interface,
   utilisez *Paramètres → Restaurer*, qui ferme la connexion avant d'agir.
2. Choisissez la sauvegarde à restaurer.
3. Confirmez. L'état courant est d'abord copié sous
   `data/corpus-avant-restauration-AAAAMMJJ-HHMMSS.db`, de sorte qu'une
   restauration peut elle-même être annulée.
4. Relancez `streamlit run app.py`.

### En ligne de commande

```bash
python -c "import database; database.restaurer('backups/corpus-20260301-101500.db')"
```

La fonction refuse tout fichier qui n'est pas une base SQLite lisible.

## Que sauvegarder en plus ?

* Le dossier `exports/` si vous y avez déposé des livrables.
* Vos fichiers XML-TEI d'origine : l'application ne les modifie jamais, mais
  elle n'en est pas le dépôt principal.

## Rythme conseillé

Une sauvegarde étiquetée en fin de séance de travail, conservée hors de la
machine de travail (disque externe, espace de sauvegarde institutionnel).
