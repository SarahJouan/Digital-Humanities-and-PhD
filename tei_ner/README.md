# Annotation et gestion des entités nommées dans un corpus XML-TEI

Application web **locale** permettant de gérer, annoter, enrichir et valider un
corpus de textes XML-TEI, afin de constituer un référentiel fiable d'entités
nommées et un jeu de données d'entraînement pour la reconnaissance d'entités.

Tout fonctionne sur votre ordinateur : aucun serveur externe, aucune API
payante, aucune connexion Internet requise. **Aucun texte du corpus n'est
transmis à un service tiers.**

---

## 1. Installation

### Pré-requis

* Python 3.11 ou supérieur (`python3 --version`).

### Installation automatique

**macOS / Linux**

```bash
cd annotation-tei-ner
./lancer.sh
```

**Windows**

```bat
cd annotation-tei-ner
lancer.bat
```

Au premier appel, le script crée un environnement virtuel `.venv`, installe les
dépendances puis démarre l'application. Les fois suivantes, il démarre
directement.

### Installation manuelle

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

L'application s'ouvre dans votre navigateur à l'adresse `http://localhost:8501`.
Pour l'arrêter : `Ctrl+C` dans le terminal.

---

## 2. Démarrage rapide avec le jeu de démonstration

```bash
python demo/charger_demonstration.py
streamlit run app.py
```

Le script importe deux lettres et chroniques TEI (dont un fichier volontairement
mal formé, pour montrer le signalement des erreurs), reprend un ancien tableur
Excel, puis affiche le résultat des contrôles qualité.

Pour essayer sans toucher à votre base de travail :

```bash
python demo/charger_demonstration.py --base /tmp/essai.db
```

Contenu du dossier `demo/` :

| Fichier | Rôle |
|---|---|
| `lettre-delacroix-1832.xml`, `chronique-salon-1824.xml` | corpus TEI de démonstration |
| `fichier-invalide.xml` | fichier mal formé, refusé à l'import |
| `anciennes-donnees.xlsx` | ancien dépouillement (feuilles « Entités » et « Mentions ») |
| `exemples/referentiel-demonstration.json` | exemple de référentiel exporté |
| `exemples/exemple-export-*.xml` | exemple de corpus réexporté en TEI enrichi |
| `exemples/exemple-corpus-validees.jsonl` | exemple de jeu d'entraînement |

---

## 3. Les pages de l'application

### Tableau de bord

Nombre de documents, d'entités et de mentions ; répartition des statuts
(validées, à vérifier, ambiguës, non résolues) ; répartition par type ; entités
les plus citées ; entités à variantes multiples ; mentions identifiées de façon
ambiguë ; avancement document par document ; journal des dernières opérations.

### Corpus

* Import d'un ou plusieurs fichiers XML-TEI.
* Reprise facultative des entités **déjà encodées** dans le XML (`persName`,
  `placeName`, `orgName`, `title`, `rs`, `geogName`, `name[@type]`) : elles
  entrent dans la base avec le statut « non résolue » et devront être reliées à
  une fiche.
* Signalement explicite des fichiers mal formés ou non TEI, qui restent
  visibles dans la liste avec leur message d'erreur.
* Détection des doublons par empreinte SHA-256 du fichier.
* Consultation du texte intégral avec surlignage des mentions, pagination,
  navigation entre documents, affichage des métadonnées et du `teiHeader`.
* **Le fichier d'origine n'est jamais modifié** : il est copié intégralement en
  base et peut être retéléchargé à l'identique.

### Annotation

Trois façons complémentaires de travailler :

1. **Sélection par bornes de mots** — vous choisissez un passage, puis le
   premier et le dernier mot de la mention ; le programme calcule les positions
   de caractères. Les entités du référentiel ressemblant à la mention sont
   proposées automatiquement.
2. **Recherche d'une chaîne** — toutes les occurrences sont listées avec leur
   contexte ; vous les annotez d'un seul geste, en totalité ou partiellement.
3. **Liste des mentions** — filtrage par statut, type et texte ; modification,
   suppression, et opérations groupées (changer le statut, relier à une entité,
   supprimer).

Un quatrième onglet permet de **créer une fiche d'entité sans quitter la page**,
avec signalement immédiat des doublons possibles.

Types initiaux : `PERSON`, `PLACE`, `ORG`, `WORK`, `EVENT`, `OTHER`.
Statuts d'une mention : validée, à vérifier, ambiguë, non résolue.

> **Limite technique et solution retenue.** Streamlit ne donne pas accès à la
> sélection faite à la souris dans la page : il n'existe pas d'événement
> « texte sélectionné » exploitable côté Python sans développer un composant
> JavaScript personnalisé, qui sortirait du cadre technique demandé (et
> imposerait une chaîne de compilation Node.js). Les deux mécanismes ci-dessus
> sont donc proposés à la place. Ils sont pleinement fonctionnels, et surtout
> **plus sûrs** : les positions de caractères sont toujours calculées par le
> programme à partir du texte réel, jamais saisies à la main, ce qui élimine
> une source classique d'erreurs d'offsets.

### Référentiel des entités

Fiche complète : identifiant unique et stable, type, nom canonique, variantes
orthographiques et historiques, description, métadonnées propres au type,
sources documentaires, statut de validation, dates de création et de
modification.

* Recherche par nom, variante, identifiant, description et type.
* Consultation de **toutes les occurrences** d'une entité, avec contexte.
* Aperçu de la fiche au format JSON.
* **Détection des doublons** (dénominations identiques après normalisation ou
  très proches) : ils sont **signalés**, jamais fusionnés automatiquement. La
  fusion reste une action manuelle, confirmée, dont le sens est choisi par vous.
* La suppression d'une fiche ne supprime pas les mentions : elles redeviennent
  « non résolues ».

Exemple de fiche exportée :

```json
{
  "entity_id": "PERSON_0001",
  "entity_type": "PERSON",
  "canonical_name": "Eugène Delacroix",
  "variants": ["Delacroix", "Eugène Delacroix", "M. Delacroix"],
  "description": "Peintre français",
  "metadata": {"naissance": "1798", "deces": "1863"},
  "sources": ["Correspondance générale"],
  "validation_status": "validated",
  "created_at": "2026-03-01 10:15:00",
  "updated_at": "2026-03-02 09:40:00"
}
```

### Validation

Neuf contrôles, exécutables séparément :

| Contrôle | Ce qu'il vérifie |
|---|---|
| Unicité et forme des identifiants | forme `TYPE_0000`, cohérence avec le type, collisions de casse |
| Existence des entités référencées | toute mention renvoie à une fiche existante |
| Cohérence des types | le type de la mention égale celui de la fiche |
| Validité des positions | `0 ≤ début < fin ≤ longueur` et `texte[début:fin] == surface` |
| Chevauchements | mentions qui se recouvrent dans un même document |
| Mentions ambiguës | surfaces identiques reliées à plusieurs entités |
| Champs obligatoires | nom canonique, type connu, statut connu |
| Mentions non résolues | mentions sans entité |
| Doublons d'entités | fiches potentiellement redondantes |

Chaque anomalie est classée (erreur / avertissement / information) et, quand
c'est possible, assortie d'une **correction proposée**. Rien n'est appliqué sans
que vous ayez sélectionné les cas puis coché une confirmation ; une sauvegarde
de la base est créée juste avant.

### Import tableur

Reprise des données déjà collectées dans un fichier **Excel ou CSV**.

Déroulé : téléversement → choix de la feuille → association des colonnes
(proposée automatiquement d'après les intitulés) → **simulation** → application.

* **Référentiel** : création ou complément des fiches. En cas de fiche déjà
  existante, vous choisissez : compléter (variantes et sources ajoutées),
  ne rien changer, ou créer une seconde fiche signalée comme doublon. Les
  colonnes non utilisées peuvent être conservées comme métadonnées.
* **Mentions** : rattachement à un document du corpus par nom de fichier, titre
  ou identifiant. Si le tableur fournit des positions de caractères, elles sont
  utilisées après vérification ; sinon la mention est **recherchée dans le
  texte**. Une mention déjà présente et non résolue (par exemple détectée dans
  le XML) est **complétée** plutôt que dupliquée. Les fiches manquantes peuvent
  être créées à la volée.
* Les types et statuts sont reconnus en français comme en anglais
  (« personne », « lieu », « institution », « œuvre », « validé », « à
  vérifier »…), les variantes peuvent être séparées par `;`, `|` ou un retour à
  la ligne.
* La simulation **n'écrit rien** : elle affiche ligne par ligne l'action prévue
  et les observations (mention absente du texte, document introuvable,
  rapprochement avec une fiche existante…).
* Un historique des imports est conservé.

### Export

Trois livrables, séparables entre **données validées** et **non validées** :

1. **Référentiel JSON** — fiches complètes, nombre d'occurrences et liste des
   documents où chaque entité apparaît.
2. **Corpus XML-TEI enrichi** — trois modes : balises en ligne, annotations
   déportées (`standOff`, texte intact), ou mixte. Chaque fichier produit est
   vérifié comme **XML bien formé** avant téléchargement, et un rapport indique
   les mentions insérées en ligne, celles déportées et pourquoi.
3. **Jeu d'entraînement JSONL** — un enregistrement par paragraphe (recommandé)
   ou par document, avec vérification automatique de la cohérence des offsets.

L'**archive ZIP** réunit le tout, plus un manifeste (date, portée, convention
d'offsets) et une copie conforme des fichiers d'origine.

### Paramètres

Ajout de types d'entités personnalisés, sauvegarde et restauration, taille et
version de la base, réinitialisation des données de travail, et rappel complet
des conventions d'encodage.

---

## 4. Conventions d'offsets et d'encodage TEI

Résumé : les positions sont des **indices de points de code Unicode** dans le
texte brut normalisé **NFC**, en intervalles **semi-ouverts** `[début, fin[`.

Le détail complet — construction du texte de référence, table de correspondance
avec les nœuds XML, balises produites, traitement des balises préexistantes,
forme du `standOff`, format JSONL — est dans **[`docs/CONVENTIONS.md`](docs/CONVENTIONS.md)**.

---

## 5. Sauvegarde et restauration

Procédure complète dans **[`docs/SAUVEGARDE.md`](docs/SAUVEGARDE.md)**.

En bref : *Paramètres → Sauvegarde et restauration*. Les sauvegardes sont des
copies cohérentes (API `sqlite3.backup`) déposées dans `backups/`. Une
sauvegarde est créée automatiquement avant toute opération de masse. La
restauration conserve une copie de l'état remplacé.

---

## 6. Arborescence du projet

```
annotation-tei-ner/
├── app.py                  Point d'entrée Streamlit, navigation
├── models.py               Structures de données, types, statuts, conventions
├── database.py             Accès SQLite, schéma, sauvegarde et restauration
├── corpus.py               Import des fichiers TEI, consultation, surlignage
├── tei_parser.py           Analyse TEI, table d'offsets, réécriture TEI
├── annotation.py           Logique d'annotation, jetons, occurrences
├── entity_manager.py       Référentiel, identifiants, doublons, fusion
├── excel_import.py         Reprise des anciennes données (Excel, CSV)
├── validation.py           Contrôles qualité et corrections proposées
├── export.py               Exports JSON, TEI, JSONL et archive ZIP
├── ui/
│   ├── commun.py                  Composants partagés
│   ├── tableau_de_bord_page.py
│   ├── corpus_page.py
│   ├── annotation_page.py
│   ├── referentiel_page.py
│   ├── validation_page.py
│   ├── import_tableur_page.py
│   ├── export_page.py
│   └── parametres_page.py
├── tests/                  Tests automatisés (pytest)
├── demo/                   Corpus, tableur et exports de démonstration
├── docs/
│   ├── CONVENTIONS.md      Offsets et encodage TEI
│   └── SAUVEGARDE.md       Sauvegarde et restauration
├── data/                   Base SQLite (créée au premier lancement)
├── backups/                Sauvegardes (créé à la demande)
├── exports/                Exports écrits sur disque (créé à la demande)
├── requirements.txt
├── lancer.sh / lancer.bat
└── README.md
```

### Schéma de la base

| Table | Contenu |
|---|---|
| `documents` | fichier, titre, `xml:id`, empreinte, texte brut, métadonnées, XML source, statut |
| `entites` | fiche d'autorité (identifiant, type, nom canonique, description, métadonnées, statut, dates) |
| `variantes` | variantes orthographiques, une par ligne, liées à une fiche |
| `sources` | sources documentaires d'une fiche |
| `annotations` | mention : document, entité, type, début, fin, surface, statut, origine, note |
| `imports` | historique des imports de tableurs |
| `journal` | journal des opérations |
| `meta` | version du schéma, compteurs d'identifiants, types personnalisés |

Clés étrangères activées ; suppression en cascade des annotations d'un document
supprimé ; mise à `NULL` de l'entité d'une annotation dont la fiche est
supprimée.

---

## 7. Tests

```bash
python -m pytest            # depuis la racine du projet
python -m pytest -v         # détail test par test
python -m pytest tests/test_tei_parser.py
```

89 tests couvrent : analyse TEI et offsets, détection des entités encodées,
refus des fichiers mal formés, réécriture TEI (en ligne, `standOff`, mixte),
non-altération de la source, import du corpus, référentiel (identifiants,
recherche, doublons, fusion), annotations (positions, lots, occurrences),
contrôles qualité et corrections, exports JSON/TEI/JSONL/ZIP, import de tableur
(correspondance des colonnes, simulation, conflits), base de données
(sauvegarde, restauration, résistance à l'injection SQL).

---

## 8. Sécurité et confidentialité

* Requêtes SQL **paramétrées** partout ; les rares noms de table interpolés sont
  validés contre une liste fermée.
* Analyse XML **sans résolution d'entités externes**, sans accès réseau et sans
  chargement de DTD (protection contre les attaques par entités XML).
* Fichiers importés validés avant tout enregistrement.
* Aucun appel réseau sortant : l'application fonctionne hors ligne.
* Les fichiers d'origine ne sont jamais réécrits ; toute production de XML
  enrichi crée un **nouveau** fichier.
* Confirmation explicite avant toute opération destructrice, et sauvegarde
  automatique avant les opérations de masse.

---

## 9. Limites connues

* **Sélection à la souris impossible dans Streamlit** : voir l'encadré de la
  section *Annotation*. Deux mécanismes de sélection équivalents sont fournis.
* **Validation TEI par schéma** : les fichiers produits sont vérifiés comme XML
  bien formé et conformes aux conventions décrites, mais l'application
  n'embarque pas de validateur RELAX NG. Pour une validation contre le schéma
  TEI P5, passez les fichiers exportés à un outil dédié (`jing`, `xmllint
  --relaxng tei_all.rng`, ou l'éditeur Oxygen).
* **Mentions discontinues** non prises en charge : une mention est un intervalle
  continu de caractères.
* **Chevauchements** autorisés en base (ils sont parfois légitimes) mais
  signalés par les contrôles ; à l'export en ligne, seule la première mention
  d'un groupe qui se chevauche est balisée, les autres partent en `standOff`.
* **Volumétrie** : l'application est conçue pour des corpus de recherche
  (quelques centaines de documents). Au-delà, l'affichage paginé reste fluide
  mais le calcul des doublons, quadratique, peut ralentir : augmentez alors le
  seuil de similarité.
* **Annulation** : il n'y a pas d'historique « annuler/refaire » pas à pas ; le
  filet de sécurité est la sauvegarde de la base, automatique avant toute
  opération de masse.
