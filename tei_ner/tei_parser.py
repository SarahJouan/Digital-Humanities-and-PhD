"""Lecture et écriture des fichiers XML-TEI.

Principes retenus (voir docs/CONVENTIONS.md) :

* le fichier source n'est jamais modifié : il est conservé tel quel en base
  et toute écriture produit un NOUVEAU document ;
* le texte brut servant de référence aux offsets est construit par un parcours
  en ordre documentaire de l'élément <text> ; chaque fragment conserve un lien
  vers le nœud lxml dont il provient (table de correspondance), ce qui permet
  de réinjecter des balises exactement au bon endroit ;
* les espaces consécutifs sont réduits à une espace simple et les éléments
  de bloc sont séparés par un saut de ligne : ces caractères « virtuels »
  n'appartiennent à aucun nœud et sont signalés comme tels.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable

from lxml import etree

from models import BALISES_TEI, DETECTION_TEI, normaliser

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI_NS, "xml": XML_NS}

# Éléments provoquant une séparation visuelle dans le texte brut.
ELEMENTS_BLOC = {
    "p", "div", "div1", "div2", "div3", "head", "lg", "l", "ab", "item",
    "list", "sp", "speaker", "stage", "quote", "cit", "note", "table",
    "row", "cell", "body", "front", "back", "text", "opener", "closer",
    "dateline", "salute", "signed", "titlePage", "docTitle", "epigraph",
    "figure", "fw", "label", "argument", "castList", "castItem",
}

# Éléments dont le contenu textuel n'appartient pas au texte édité.
ELEMENTS_EXCLUS = {"teiHeader", "facsimile", "standOff"}


class ErreurTEI(Exception):
    """Fichier TEI illisible ou non conforme aux attentes de l'application."""


def _local(tag: Any) -> str:
    """Nom local d'une balise lxml (sans namespace)."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


# --------------------------------------------------------------------------
# Table de correspondance texte brut <-> nœuds XML
# --------------------------------------------------------------------------
@dataclass
class Segment:
    """Fragment contigu du texte brut provenant d'un même nœud XML.

    La correspondance est affine à l'intérieur d'un segment :
    position_dans_le_noeud = decalage_noeud + (position_globale - debut)
    """

    debut: int
    fin: int
    noeud: Any  # élément lxml, ou None pour un caractère virtuel
    partie: str  # 'text', 'tail' ou 'virtuel'
    decalage_noeud: int = 0

    @property
    def virtuel(self) -> bool:
        return self.noeud is None


@dataclass
class DocumentTEI:
    """Résultat de l'analyse d'un fichier XML-TEI."""

    arbre: Any
    texte: str
    segments: list[Segment]
    metadonnees: dict[str, Any]
    tei_id: str | None
    titre: str
    annotations_existantes: list[dict[str, Any]]
    xml_source: str

    @property
    def empreinte(self) -> str:
        return hashlib.sha256(self.xml_source.encode("utf-8")).hexdigest()


class _ConstructeurTexte:
    """Construit le texte brut et la table de correspondance."""

    def __init__(self) -> None:
        self.morceaux: list[str] = []
        self.segments: list[Segment] = []
        self.position = 0

    # -- caractères virtuels ------------------------------------------------
    def separateur(self, chaine: str = "\n") -> None:
        if not self.morceaux:
            return
        courant = "".join(self.morceaux[-2:])
        if courant.endswith(chaine) or (chaine == "\n" and courant.endswith("\n")):
            return
        self.morceaux.append(chaine)
        self.segments.append(
            Segment(self.position, self.position + len(chaine), None, "virtuel")
        )
        self.position += len(chaine)

    # -- texte issu d'un nœud ----------------------------------------------
    def ajouter(self, brut: str | None, noeud: Any, partie: str) -> None:
        """Ajoute le contenu d'un nœud en réduisant les espaces multiples.

        Le découpage en segments se fait à chaque réduction d'espaces, de
        manière à conserver une correspondance affine dans chaque segment.
        """
        if not brut:
            return
        i = 0
        n = len(brut)
        while i < n:
            if brut[i].isspace():
                j = i
                while j < n and brut[j].isspace():
                    j += 1
                # Une réduction d'espaces n'est émise que si elle sépare du texte.
                if self.morceaux and not "".join(self.morceaux[-1:]).endswith(("\n", " ")):
                    self.morceaux.append(" ")
                    self.segments.append(
                        Segment(self.position, self.position + 1, noeud, partie, i)
                    )
                    self.position += 1
                i = j
                continue
            j = i
            while j < n and not brut[j].isspace():
                j += 1
            fragment = brut[i:j]
            self.morceaux.append(fragment)
            self.segments.append(
                Segment(
                    self.position, self.position + len(fragment), noeud, partie, i
                )
            )
            self.position += len(fragment)
            i = j

    def resultat(self) -> tuple[str, list[Segment]]:
        texte = "".join(self.morceaux)
        # Nettoyage final : suppression des espaces de tête/fin sans toucher
        # aux segments (on se contente de ne pas les produire côté constructeur).
        return texte, self.segments


def _parcourir(
    element: Any,
    constructeur: _ConstructeurTexte,
    collecte: list[dict[str, Any]],
) -> None:
    """Parcours récursif en ordre documentaire."""
    nom = _local(element.tag)
    if nom in ELEMENTS_EXCLUS:
        return
    bloc = nom in ELEMENTS_BLOC
    if bloc:
        constructeur.separateur("\n")

    debut_element = constructeur.position
    constructeur.ajouter(element.text, element, "text")
    for enfant in element:
        if isinstance(enfant.tag, str):  # ignore les commentaires / PI
            _parcourir(enfant, constructeur, collecte)
        if enfant.tail:
            constructeur.ajouter(enfant.tail, enfant, "tail")
    fin_element = constructeur.position

    # Détection des entités déjà encodées dans la source.
    type_attr = element.get("type")
    label = DETECTION_TEI.get((nom, type_attr)) or DETECTION_TEI.get((nom, None))
    if label and fin_element > debut_element:
        collecte.append(
            {
                "label": label,
                "debut": debut_element,
                "fin": fin_element,
                "balise": nom,
                "ref": element.get("ref") or element.get("key") or element.get("corresp"),
                "xml_id": element.get(f"{{{XML_NS}}}id"),
            }
        )
    if bloc:
        constructeur.separateur("\n")


def _extraire_metadonnees(racine: Any) -> dict[str, Any]:
    """Récupère les principales informations du teiHeader."""

    def premier(chemin: str) -> str:
        noeuds = racine.xpath(chemin, namespaces=NS)
        for noeud in noeuds:
            valeur = " ".join(
                (noeud.itertext() if hasattr(noeud, "itertext") else [str(noeud)])
            )
            valeur = re.sub(r"\s+", " ", valeur).strip()
            if valeur:
                return valeur
        return ""

    meta: dict[str, Any] = {
        "titre": premier(".//tei:titleStmt/tei:title"),
        "auteur": premier(".//tei:titleStmt/tei:author"),
        "editeur": premier(".//tei:publicationStmt/tei:publisher"),
        "date": premier(".//tei:publicationStmt/tei:date")
        or premier(".//tei:sourceDesc//tei:date"),
        "source": premier(".//tei:sourceDesc//tei:title"),
        "langue": premier(".//tei:profileDesc//tei:language"),
        "identifiant": premier(".//tei:publicationStmt/tei:idno"),
    }
    # teiHeader intégral sérialisé, pour ne rien perdre.
    entetes = racine.xpath("//tei:teiHeader", namespaces=NS)
    if entetes:
        meta["teiHeader_xml"] = etree.tostring(
            entetes[0], encoding="unicode", pretty_print=True
        )
    return {cle: valeur for cle, valeur in meta.items() if valeur}


def analyser(contenu: bytes | str, nom_fichier: str = "") -> DocumentTEI:
    """Analyse un fichier XML-TEI et renvoie texte, offsets et métadonnées.

    Lève ErreurTEI si le fichier n'est pas un XML bien formé ou n'est pas du TEI.
    """
    if isinstance(contenu, str):
        brut = contenu.encode("utf-8")
    else:
        brut = contenu

    # Analyse sans résolution d'entités externes ni réseau (sécurité).
    parseur = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        recover=False,
    )
    try:
        arbre = etree.fromstring(brut, parser=parseur)
    except etree.XMLSyntaxError as exc:
        raise ErreurTEI(f"XML mal formé : {exc}") from exc

    if _local(arbre.tag) != "TEI":
        # On tolère un fragment dont la racine contient un <TEI>.
        candidats = arbre.xpath("//tei:TEI", namespaces=NS) or arbre.xpath("//TEI")
        if candidats:
            arbre = candidats[0]
        else:
            raise ErreurTEI(
                "L'élément racine n'est pas <TEI> : le fichier ne semble pas "
                "être un document TEI P5."
            )

    corps = arbre.xpath(".//tei:text", namespaces=NS)
    if not corps:
        corps = [c for c in arbre if _local(c.tag) == "text"]
    if not corps:
        raise ErreurTEI("Aucun élément <text> trouvé : document sans texte éditorial.")

    constructeur = _ConstructeurTexte()
    collecte: list[dict[str, Any]] = []
    _parcourir(corps[0], constructeur, collecte)
    texte, segments = constructeur.resultat()

    # Normalisation Unicode : NFC ne modifie pas la longueur pour les
    # caractères usuels du français ; on vérifie malgré tout.
    texte_nfc = normaliser(texte)
    if len(texte_nfc) == len(texte):
        texte = texte_nfc

    metadonnees = _extraire_metadonnees(arbre)
    tei_id = arbre.get(f"{{{XML_NS}}}id")
    titre = metadonnees.get("titre") or nom_fichier or "Document sans titre"

    # Retrait des mentions vides ou purement blanches.
    annotations = []
    for item in collecte:
        surface = texte[item["debut"]:item["fin"]].strip()
        if not surface:
            continue
        debut = item["debut"] + (len(texte[item["debut"]:item["fin"]])
                                 - len(texte[item["debut"]:item["fin"]].lstrip()))
        fin = debut + len(surface)
        item = dict(item, debut=debut, fin=fin, surface=surface)
        annotations.append(item)

    return DocumentTEI(
        arbre=arbre,
        texte=texte,
        segments=segments,
        metadonnees=metadonnees,
        tei_id=tei_id,
        titre=titre,
        annotations_existantes=annotations,
        xml_source=brut.decode("utf-8", errors="replace"),
    )


def segments_pour(
    segments: list[Segment], debut: int, fin: int
) -> list[Segment]:
    """Segments recouvrant l'intervalle [debut, fin[."""
    return [s for s in segments if s.debut < fin and s.fin > debut]


# --------------------------------------------------------------------------
# Export : réinjection en ligne
# --------------------------------------------------------------------------
@dataclass
class ResultatExport:
    xml: str
    inserees: int
    reportees: list[dict[str, Any]]


def _position_noeud(segment: Segment, position_globale: int) -> int:
    return segment.decalage_noeud + (position_globale - segment.debut)


def _localiser(
    segments: list[Segment], debut: int, fin: int
) -> tuple[Any, str, int, int] | None:
    """Convertit un intervalle global en (nœud, partie, début, fin) locaux.

    Renvoie None si l'intervalle traverse plusieurs nœuds ou contient
    des caractères virtuels : l'annotation devra alors être exportée en
    standOff uniquement.
    """
    couvrants = segments_pour(segments, debut, fin)
    if not couvrants:
        return None
    reels = [s for s in couvrants if not s.virtuel]
    if len(reels) != len(couvrants) or not reels:
        return None
    premier = reels[0]
    dernier = reels[-1]
    if any(s.noeud is not premier.noeud or s.partie != premier.partie for s in reels):
        return None
    return (
        premier.noeud,
        premier.partie,
        _position_noeud(premier, debut),
        _position_noeud(dernier, min(fin, dernier.fin)),
    )


def exporter_tei(
    document_tei: DocumentTEI,
    annotations: Iterable[dict[str, Any]],
    entites: dict[str, dict[str, Any]] | None = None,
    mode: str = "mixte",
    note_encodage: bool = True,
) -> ResultatExport:
    """Produit un nouveau document TEI enrichi des annotations.

    mode :
      * 'inline'   : balises insérées dans le texte uniquement ;
      * 'standoff' : bloc <standOff> uniquement, le texte reste intact ;
      * 'mixte'    : balises en ligne quand c'est possible, standOff sinon
                     (et liste des entités dans <standOff> dans tous les cas).
    """
    entites = entites or {}
    # On travaille sur une copie profonde : la source n'est jamais modifiée.
    racine = etree.fromstring(etree.tostring(document_tei.arbre))
    # La copie a son propre arbre : il faut recalculer les segments dessus.
    corps = racine.xpath(".//tei:text", namespaces=NS)
    constructeur = _ConstructeurTexte()
    _parcourir(corps[0], constructeur, [])
    _, segments = constructeur.resultat()

    annotations = sorted(annotations, key=lambda a: (a["debut"], -a["fin"]))
    reportees: list[dict[str, Any]] = []
    a_inserer: list[tuple[Any, str, int, int, dict[str, Any]]] = []

    enrichies = 0
    if mode in ("inline", "mixte"):
        fin_precedente = -1
        for ann in annotations:
            if ann["debut"] < fin_precedente:
                reportees.append({**ann, "motif": "chevauchement avec l'annotation précédente"})
                continue
            cible = _localiser(segments, ann["debut"], ann["fin"])
            if cible is None:
                reportees.append(
                    {**ann, "motif": "la mention traverse plusieurs éléments XML"}
                )
                continue
            noeud, partie, a, b = cible
            # Si une balise TEI couvre déjà exactement la mention, on l'enrichit
            # au lieu d'en imbriquer une seconde.
            reutilisable = _balise_reutilisable(noeud, partie, a, b, ann)
            if reutilisable is not None:
                if reutilisable:
                    _enrichir_balise(noeud, ann)
                    enrichies += 1
                else:
                    reportees.append(
                        {
                            **ann,
                            "motif": (
                                "balise éditoriale préexistante conservée "
                                "(attribut @ref déjà renseigné)"
                            ),
                        }
                    )
                fin_precedente = ann["fin"]
                continue
            a_inserer.append((noeud, partie, a, b, ann))
            fin_precedente = ann["fin"]
    else:
        reportees = [{**a, "motif": "export en standOff demandé"} for a in annotations]

    # Regroupement par (nœud, partie) puis insertion en ordre décroissant.
    groupes: dict[tuple[int, str], list[tuple[int, int, dict[str, Any]]]] = {}
    noeuds: dict[int, Any] = {}
    for noeud, partie, a, b, ann in a_inserer:
        cle = (id(noeud), partie)
        noeuds[id(noeud)] = noeud
        groupes.setdefault(cle, []).append((a, b, ann))

    inserees = 0
    for (cle_noeud, partie), items in groupes.items():
        noeud = noeuds[cle_noeud]
        items.sort(key=lambda t: t[0], reverse=True)
        if partie == "text":
            reste = noeud.text or ""
            for a, b, ann in items:
                element = _creer_balise(ann, entites)
                element.text = reste[a:b]
                element.tail = reste[b:]
                noeud.insert(0, element)
                reste = reste[:a]
                inserees += 1
            noeud.text = reste
        else:
            parent = noeud.getparent()
            if parent is None:  # pragma: no cover - un tail implique un parent
                continue
            index = list(parent).index(noeud)
            reste = noeud.tail or ""
            for a, b, ann in items:
                element = _creer_balise(ann, entites)
                element.text = reste[a:b]
                element.tail = reste[b:]
                parent.insert(index + 1, element)
                reste = reste[:a]
                inserees += 1
            noeud.tail = reste

    inserees += enrichies

    # Bloc standOff : référentiel + annotations non insérées.
    annotations_standoff = reportees if mode != "standoff" else list(annotations)
    _ajouter_standoff(racine, annotations_standoff, entites, mode)

    if note_encodage:
        _ajouter_note_encodage(racine, mode)

    xml = etree.tostring(
        etree.ElementTree(racine),
        encoding="unicode",
        xml_declaration=False,
        pretty_print=False,
    )
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml
    return ResultatExport(xml=xml, inserees=inserees, reportees=reportees)


def _balise_reutilisable(
    noeud: Any, partie: str, a: int, b: int, ann: dict[str, Any]
) -> bool | None:
    """La mention coïncide-t-elle avec une balise TEI déjà présente ?

    Renvoie True si la balise peut recevoir l'identifiant du référentiel,
    False si elle porte déjà un @ref éditorial (qui ne doit pas être écrasé),
    et None si la mention ne coïncide pas avec une balise existante.
    """
    if partie != "text" or len(noeud):
        return None
    texte = noeud.text or ""
    if a != 0 or b != len(texte):
        return None
    nom_attendu = BALISES_TEI.get(ann.get("label", "OTHER"), ("rs", {}))[0]
    if _local(noeud.tag) != nom_attendu:
        return None
    return not noeud.get("ref")


def _enrichir_balise(noeud: Any, ann: dict[str, Any]) -> None:
    """Ajoute l'identifiant du référentiel à une balise TEI préexistante."""
    _, attributs = BALISES_TEI.get(ann.get("label", "OTHER"), ("rs", {}))
    for cle, valeur in attributs.items():
        if not noeud.get(cle):
            noeud.set(cle, valeur)
    entity_id = ann.get("entity_id")
    if entity_id:
        noeud.set("ref", f"#{entity_id}")
    if ann.get("statut") in ("ambigue", "non_resolue") and not noeud.get("cert"):
        noeud.set("cert", "low")


def _creer_balise(ann: dict[str, Any], entites: dict[str, dict[str, Any]]) -> Any:
    nom, attributs = BALISES_TEI.get(ann.get("label", "OTHER"), ("rs", {"type": "other"}))
    element = etree.Element(f"{{{TEI_NS}}}{nom}")
    for cle, valeur in attributs.items():
        element.set(cle, valeur)
    entity_id = ann.get("entity_id")
    if entity_id:
        element.set("ref", f"#{entity_id}")
    else:
        element.set("cert", "low")
    if ann.get("statut") in ("ambigue", "non_resolue"):
        element.set("cert", "low")
    return element


def _balise_liste(entity_type: str) -> tuple[str, str]:
    return {
        "PERSON": ("listPerson", "person"),
        "PLACE": ("listPlace", "place"),
        "ORG": ("listOrg", "org"),
    }.get(entity_type, ("list", "item"))


def _ajouter_standoff(
    racine: Any,
    annotations: Iterable[dict[str, Any]],
    entites: dict[str, dict[str, Any]],
    mode: str,
) -> None:
    standoff = etree.Element(f"{{{TEI_NS}}}standOff")

    # 1. Référentiel des entités citées.
    par_type: dict[str, list[dict[str, Any]]] = {}
    for fiche in entites.values():
        par_type.setdefault(fiche["entity_type"], []).append(fiche)
    for entity_type, fiches in sorted(par_type.items()):
        nom_liste, nom_item = _balise_liste(entity_type)
        liste = etree.SubElement(standoff, f"{{{TEI_NS}}}{nom_liste}")
        if nom_liste == "list":
            liste.set("type", entity_type)
        for fiche in sorted(fiches, key=lambda f: f["entity_id"]):
            item = etree.SubElement(liste, f"{{{TEI_NS}}}{nom_item}")
            item.set(f"{{{XML_NS}}}id", fiche["entity_id"])
            item.set("type", entity_type)
            if fiche.get("validation_status"):
                item.set("subtype", fiche["validation_status"])
            nom_balise = {
                "PERSON": "persName",
                "PLACE": "placeName",
                "ORG": "orgName",
            }.get(entity_type, "name")
            principal = etree.SubElement(item, f"{{{TEI_NS}}}{nom_balise}")
            principal.set("type", "canonical")
            principal.text = fiche.get("canonical_name", "")
            for variante in fiche.get("variants", []):
                if variante == fiche.get("canonical_name"):
                    continue
                noeud = etree.SubElement(item, f"{{{TEI_NS}}}{nom_balise}")
                noeud.set("type", "variant")
                noeud.text = variante
            if fiche.get("description"):
                note = etree.SubElement(item, f"{{{TEI_NS}}}note")
                note.set("type", "description")
                note.text = fiche["description"]
            for source in fiche.get("sources", []):
                bibl = etree.SubElement(item, f"{{{TEI_NS}}}bibl")
                bibl.text = source

    # 2. Annotations déportées.
    annotations = list(annotations)
    if annotations:
        liste_ann = etree.SubElement(standoff, f"{{{TEI_NS}}}listAnnotation")
        liste_ann.set("type", "named-entities")
        for ann in annotations:
            span = etree.SubElement(liste_ann, f"{{{TEI_NS}}}span")
            span.set("type", ann.get("label", "OTHER"))
            # Schéma de pointeur documenté : char=<debut>,<fin>
            span.set("target", f"#char={ann['debut']},{ann['fin']}")
            span.set("from", f"#char={ann['debut']}")
            span.set("to", f"#char={ann['fin']}")
            if ann.get("entity_id"):
                span.set("ana", f"#{ann['entity_id']}")
            if ann.get("statut"):
                span.set("subtype", ann["statut"])
            if ann.get("motif"):
                span.set("resp", "application")
            span.text = ann.get("surface", "")

    if len(standoff):
        # <standOff> se place après <teiHeader>.
        entetes = racine.xpath("./tei:teiHeader", namespaces=NS)
        if entetes:
            entetes[0].addnext(standoff)
        else:  # pragma: no cover - un TEI valide possède un teiHeader
            racine.insert(0, standoff)


def _ajouter_note_encodage(racine: Any, mode: str) -> None:
    """Documente les choix d'encodage dans <encodingDesc>."""
    entetes = racine.xpath("./tei:teiHeader", namespaces=NS)
    if not entetes:
        return
    entete = entetes[0]
    encodage = entete.xpath("./tei:encodingDesc", namespaces=NS)
    if encodage:
        cible = encodage[0]
    else:
        cible = etree.Element(f"{{{TEI_NS}}}encodingDesc")
        profils = entete.xpath("./tei:fileDesc", namespaces=NS)
        if profils:
            profils[0].addnext(cible)
        else:
            entete.append(cible)

    for existant in cible.xpath(
        "./tei:appInfo/tei:application[@ident='annotation-tei-ner']", namespaces=NS
    ):
        existant.getparent().remove(existant)

    app_info = cible.xpath("./tei:appInfo", namespaces=NS)
    app = app_info[0] if app_info else etree.SubElement(cible, f"{{{TEI_NS}}}appInfo")
    application = etree.SubElement(app, f"{{{TEI_NS}}}application")
    application.set("ident", "annotation-tei-ner")
    application.set("version", "1.0")
    label = etree.SubElement(application, f"{{{TEI_NS}}}label")
    label.text = "Application d'annotation et de gestion des entités nommées"
    desc = etree.SubElement(application, f"{{{TEI_NS}}}desc")
    desc.text = (
        "Les entités nommées sont référencées par l'attribut @ref pointant vers "
        "un identifiant du référentiel déclaré dans <standOff>. Les annotations "
        "qui ne peuvent pas être insérées en ligne (chevauchement ou mention "
        "traversant plusieurs éléments) sont déportées dans "
        "<standOff><listAnnotation> sous forme de <span> dont @target utilise le "
        "schéma de pointeur « char=début,fin ». Les positions sont des indices de "
        "points de code Unicode (normalisation NFC) dans le texte brut obtenu par "
        "parcours en ordre documentaire de <text>, avec réduction des espaces "
        f"consécutifs. Mode d'export utilisé : {mode}."
    )


def valider_xml(xml: str) -> tuple[bool, str]:
    """Vérifie qu'une chaîne est un XML bien formé."""
    try:
        etree.fromstring(xml.encode("utf-8"))
        return True, "XML bien formé."
    except etree.XMLSyntaxError as exc:
        return False, str(exc)
