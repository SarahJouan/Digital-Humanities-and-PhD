# Conventions d'encodage et de positionnement

## 1. Texte de référence

Toutes les annotations portent sur un **texte brut** dérivé du fichier XML-TEI,
construit de la façon suivante :

1. parcours en **ordre documentaire** de l'élément `<text>` ;
   les éléments `teiHeader`, `facsimile` et `standOff` sont exclus ;
2. toute suite d'espaces, tabulations et retours à la ligne est **réduite à une
   espace simple** ;
3. un **saut de ligne** est inséré entre les éléments de bloc
   (`p`, `div`, `head`, `lg`, `l`, `item`, `note`, `sp`, `table`, `row`, `cell`…).

Ce texte est celui qui est affiché dans l'application, stocké dans la base et
exporté dans le JSONL. Il est reproductible : deux analyses du même fichier
donnent exactement le même texte.

## 2. Positions de caractères

* unité : **point de code Unicode** (indice de chaîne Python), jamais l'octet,
  jamais l'unité UTF-16, jamais le « grapheme cluster » ;
* normalisation : **NFC** ;
* intervalle **semi-ouvert** `[début, fin[`, donc `fin − début` est le nombre de
  caractères de la mention ;
* la chaîne enregistrée dans le champ `surface` doit être rigoureusement égale à
  `texte[début:fin]`. Le contrôle « Validité des positions de caractères » de la
  page *Validation* vérifie cette égalité pour chaque mention.

## 3. Table de correspondance texte ↔ XML

Chaque fragment du texte brut conserve un lien vers le nœud `lxml` dont il
provient (`element.text` ou `element.tail`) et son décalage dans ce nœud. La
correspondance est affine à l'intérieur de chaque fragment, ce qui permet de
convertir une position du texte brut en position dans la source XML, et donc
d'insérer une balise exactement au bon endroit lors de l'export — sans jamais
modifier le fichier d'origine, qui est conservé intact en base de données.

Les sauts de ligne insérés entre blocs sont des caractères **virtuels** : ils
n'appartiennent à aucun nœud. Une mention qui en contiendrait un ne peut pas
être balisée en ligne et part en `standOff` (voir § 5).

## 4. Balises TEI utilisées à l'export

| Type d'entité        | Balise produite                        |
|----------------------|----------------------------------------|
| `PERSON`             | `<persName ref="#ID">`                 |
| `PLACE`              | `<placeName ref="#ID">`                |
| `ORG`                | `<orgName ref="#ID">`                  |
| `WORK`               | `<title ref="#ID">`                    |
| `EVENT`              | `<rs type="event" ref="#ID">`          |
| `OTHER` / types ajoutés | `<rs type="…" ref="#ID">`           |

À l'import, la détection des entités déjà encodées accepte en outre
`geogName`, `name[@type]`, `rs[@type]`, `person`, `place` et `org`.

Les fiches du référentiel sont déclarées dans `<standOff>` sous forme de
`<listPerson>/<person>`, `<listPlace>/<place>`, `<listOrg>/<org>` ou
`<list type="…">/<item>`, chacune portant un `@xml:id` égal à l'identifiant du
référentiel. Les renvois `@ref="#ID"` sont donc **résolubles à l'intérieur du
fichier exporté**.

### Balises préexistantes

* Si une balise TEI de la source couvre **exactement** la mention et porte le
  nom attendu, elle est **enrichie** (ajout de `@ref`) plutôt que dédoublée.
* Si cette balise porte déjà un `@ref` éditorial, il **n'est jamais écrasé** :
  l'annotation de l'application est alors déportée en `standOff`, et le motif
  est signalé dans le rapport d'export.

## 5. Annotations déportées (`standOff`)

Une mention est déportée lorsqu'elle :

* chevauche une autre mention déjà insérée,
* traverse plusieurs éléments XML,
* viserait une balise éditoriale déjà pourvue d'un `@ref`,
* ou lorsque le mode d'export « annotations déportées » est choisi (le texte
  source reste alors rigoureusement intact).

Forme produite :

```xml
<standOff>
  <listAnnotation type="named-entities">
    <span type="PLACE" target="#char=125,130" from="#char=125" to="#char=130"
          ana="#PLACE_0001" subtype="validee">Paris</span>
  </listAnnotation>
</standOff>
```

Le schéma de pointeur `char=début,fin` renvoie aux positions définies au § 2.

## 6. Documentation dans le fichier exporté

Les choix ci-dessus sont consignés dans le fichier produit, sous
`<teiHeader><encodingDesc><appInfo><application ident="annotation-tei-ner">`.

## 7. Format JSONL

```json
{"id": "doc1-0",
 "text": "M. Delacroix se rendit à Paris.",
 "entities": [{"start": 0, "end": 12, "label": "PERSON",
               "entity_id": "PERSON_0001", "text": "M. Delacroix",
               "annotation_id": 1, "statut": "validee"}],
 "meta": {"document_id": 1, "nom_fichier": "lettre.xml", "titre": "…",
          "offset_dans_document": 0, "granularite": "paragraphe"}}
```

* `start` / `end` suivent la convention du § 2, **relatives au champ `text`** de
  l'enregistrement (le décalage absolu dans le document figure dans
  `meta.offset_dans_document`).
* `entity_id` et `annotation_id` assurent la traçabilité vers le référentiel et
  vers la base.
* Le contrôle intégré à la page *Export* vérifie, pour chaque enregistrement,
  que `text[start:end] == entities[i].text`.
