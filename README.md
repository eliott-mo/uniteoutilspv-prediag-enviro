# prediag-enviro

Outillage du pré-diagnostic environnemental bibliographique, pour l'équipe
développement PV d'UNITe.

Deux onglets, dans l'ordre où on s'en sert.

| Onglet | Objet |
|---|---|
| **A · Mise à jour des tables** | ce qui a bougé dans les référentiels depuis la dernière révision des classeurs B-Statuts |
| **B · Prédiag** | emprise projet, communes, zonages, cartes, espèces, prédiagnostic Word |

```bash
streamlit run app.py
```

La ligne de commande reste disponible pour l'onglet A : `python run_veille.py`.

---

## Le principe

Le référentiel métier, ce sont les **classeurs B-Statuts** maintenus par la
responsable environnement : six classeurs (oiseaux, mammifères,
amphibiens-reptiles, insectes, macrohétérocères, araignées), une ligne par
taxon, indexés sur `CD_NOM`, couvrant toutes les régions et toutes les périodes.

Cet outil ne les remplace pas et **ne les modifie jamais**. Il les lit, les
confronte aux référentiels nationaux de l'INPN, et produit une liste de
constats à arbitrer.

> L'outil propose, l'experte arbitre.

Quatre raisons de ne pas écrire dans les classeurs, par ordre croissant
d'importance :

1. Ils sont pilotés par formules, avec en-têtes fusionnés et mises en forme
   conditionnelles ; une réécriture automatique les dégraderait.
2. BDC-Statuts ne dit pas de quelle **édition** viennent ses statuts : face à un
   écart, il n'existe pas de bonne réponse calculable.
3. La curation contient des choix délibérés — lignes « population du Quercy »,
   annotations « ssp. brookei, non reconnu TAXREF 14 » — qu'une synchronisation
   effacerait comme absents du référentiel.
4. C'est elle qui signe les études.

---

## Onglet A — la veille

### Installation

```bash
pip install -r requirements.txt
```

Déposer les six classeurs dans `classeurs/`. Les noms sont reconnus par motif
(`*oiseaux*.xlsx`, `*mammif*.xlsx`, `*amphib*.xlsx`, `*insectes*.xlsx`,
`*macroh*.xlsx`, `*araign*.xlsx`).

### Usage

L'interface fait tout cela ; la ligne de commande sert au lot et à la relecture.

```bash
python run_veille.py                               # tout
python run_veille.py --groupes oiseaux insectes    # cibler des groupes
python run_veille.py --territoires Normandie       # cibler un territoire
python run_veille.py --maj-referentiels            # rafraîchir TaxRef / BDC
python run_veille.py --relire sorties/veille.xlsx  # enregistrer les arbitrages
```

Au premier lancement, les référentiels INPN sont téléchargés (90 Mo) puis
indexés. Les lancements suivants repartent du cache.

### Ce qui sort

Un classeur Excel dans `sorties/`, un onglet par famille de constats :

| Famille | Ce qu'elle contient |
|---|---|
| ① À corriger dans ton fichier | une ligne porte la taxonomie d'une autre espèce, ou une coquille |
| ② Taxonomie à rafraîchir | `CD_NOM` devenu synonyme ou supprimé dans TaxRef |
| ③ Statuts qui ont bougé | un statut diffère de BDC-Statuts |

Chaque ligne porte la valeur actuelle, la valeur proposée, la source, un lien de
vérification en un clic, et une colonne **Décision** laissée vide
(`accepté` / `refusé` / `à revoir`) avec une liste déroulante.

### La boucle d'arbitrage

```
python run_veille.py              →  rapport Excel
   ↓  elle renseigne la colonne Décision
python run_veille.py --relire …   →  arbitrages mémorisés
   ↓
python run_veille.py              →  seulement ce qui est nouveau
```

Le « refusé » compte autant que l'« accepté » : il est retenu, et le constat ne
revient que si la source a rebougé depuis. Sans cette mémoire, chaque passage
reproposerait les mêmes centaines de lignes et l'outil finirait par ne plus être
ouvert.

---

## Onglet B — le prédiag

Six étapes, chacune avec son point de contrôle.

1. **Périmètre du projet** — ZIP de shapefile, KML ou GeoJSON. Le contrôle
   d'entrée s'affiche avant tout calcul : entités, projection lue dans le
   `.prj`, surface, emprise. La surface est celle de l'union et non la somme
   des entités — sur l'emprise de Périgny, les cinq polygones se recouvrent et
   sommer annoncerait 108,43 ha au lieu de 54,51. Le recouvrement est signalé.
2. **Communes concernées** — intersection géométrique, avec la **part de
   surface** de chacune, parce que c'est ce qui fonde la décision. Décochables,
   et une commune s'ajoute par son code INSEE. Périgny en concerne trois :
   65 / 30 / 4,9 %.
3. **Aires d'étude** — immédiate et rapprochée, pré-remplies d'après le guide
   du ministère (2016), modifiables.
4. **Sources d'espèces** — on dépose ce qu'on a trouvé : exports Excel ou CSV,
   PDF, captures d'écran. Trois étiquettes par fichier (commune, groupe,
   source), devinées du nom de fichier et corrigeables.
5. **Liste recoupée** — appariement sur TaxRef, dédoublonnage par `cd_ref`,
   date la plus récente retenue, conflits signalés. Les **non résolus** se
   corrigent à la main, et l'outil retient l'association pour les études
   suivantes.
6. **Prédiagnostic Word** — le document complet, dans la forme du
   prédiagnostic interne de l'équipe.

### Le document produit

La structure reprend celle du prédiagnostic interne, et non celle de l'étude
d'impact externe : c'est le document court qu'un chef de projet génère et que
la responsable environnement complète.

```
Page de garde                            site, surface, aires, date d'édition
Sommaire · Sommaire des tableaux · Sommaire des cartes
Zone d'étude : analyse générale          surface, communes, aires, carte 1
Patrimoine naturel                       dénombrement, tableaux, cartes 2 à 4
Zones humides
Espèces recensées sur la commune         un tableau par groupe
Conclusion                               note de risque de 0 à 10 par groupe
Sources
```

### Le modèle Word

Le document ne part pas d'une page blanche. `modele/prediag_modele.docx` est
tiré du prédiagnostic de référence de l'équipe, vidé de son contenu : il
apporte l'**en-tête au logo**, le **pied de page paginé**, les marges et les
styles maison — « Titre partie », « Style1 », « Titre colonne », « Corps de
texte - Unite », « Table Grid ». La première version les recréait à
l'approchant, ce qui donnait un document qui ne ressemblait à rien de ce que
l'équipe produit.

Deux pièges ont été rencontrés en le fabriquant, qui valent d'être notés pour
la prochaine mise à jour du modèle :

* la `sectPr` de fin de corps est celle de la **dernière** section du document
  source — une carte, donc en paysage. Un modèle naïf sortait toutes ses pages
  couchées ;
* seule la **première** section porte les références vers l'en-tête et le pied
  de page. Garder la dernière donnait un modèle où `header1.xml` et
  `footer1.xml` existaient dans le paquet sans que rien ne les appelle : ni
  logo, ni pagination.

Le modèle est aussi purgé des propriétés du document d'origine (auteur,
révisions) : il part d'un livrable réel, et cette vérification est faite à
chaque reconstruction.

Un modèle déposé dans l'interface prend le pas sur celui-ci.

### La mise en forme des tableaux

Elle est **relevée** dans le document de référence, pas choisie. Deux
observations ont tout déterminé :

* les tableaux n'ont **pas de traits** — leurs bordures sont blanches, et
  c'est l'ombrage des cellules qui les structure. Reproduire « Table Grid » et
  ses filets noirs donnait des tableaux que personne de l'équipe n'aurait
  reconnus ;
* l'ombrage des cellules de statut **code la catégorie de liste rouge**. Le
  couple valeur/couleur a été extrait de ses 243 cellules colorées plutôt que
  deviné : LC vert, NT jaune pâle, VU jaune, EN orange, CR rouge, NA gris,
  DD gris clair. `RE`, `EX` et `CR*` n'y figuraient pas et prennent le rouge
  de `CR` — extrapolation assumée, et signalée dans le code.

S'y ajoutent l'en-tête vert répété en haut de chaque page (un tableau
d'avifaune fait couramment quarante lignes), la première colonne gardée en
vert parce que c'est elle qui identifie la ligne, et des marges de cellule
serrées à 70 dxa — les tableaux d'espèces ont jusqu'à dix colonnes.

### Les zonages sans source nationale fiable

Les espaces naturels sensibles n'en ont pas. La question posée à la
responsable environnement a tranché la conception :

> « départementaux, régionaux, ça dépend, il faut fouiller à chaque fois pour
> dénicher les infos les plus à jour. J'ai même une couche nationale censée se
> mettre à jour au fur et à mesure mais comme je sais qu'elle n'est pas
> toujours à jour, et bah je fouille »

L'INPN diffuse bien une couche ENS, mais il la décrit comme « en
construction » et prévient qu'elle « ne peut être considérée comme exhaustive
ni utilisée comme donnée de référence ». La brancher en silence remplacerait
un doute éclairé par une fausse certitude : le document afficherait un chiffre
sourcé, et un chef de projet le croirait.

`sources_locales.py` fait donc trois choses.

**Il dit ce qu'il ne sait pas.** Quand aucune source n'est enregistrée pour le
département, le prédiagnostic l'écrit sous le tableau : l'absence de ligne ne
vaut pas absence de zonage. Quand une source est enregistrée et qu'elle se
sait incomplète, son avertissement voyage avec elle jusqu'au document.

**Il accepte ce qu'on dépose.** Une couche — ZIP de shapefile, GeoJSON,
GeoPackage, KML — est croisée avec l'emprise et mise en forme comme les
zonages nationaux, carte comprise. Une source sans couche, quand on n'a
consulté qu'un visualiseur, est seulement citée en bibliographie.

**Il garde ce qui a été trouvé.** Le registre retient, par département, la
source, son lien et sa date de consultation. Le projet suivant dans le même
département n'a plus à refouiller. C'est le mécanisme du dictionnaire d'alias,
pour la même raison : une recherche faite une fois profite à toute l'équipe —
un fichier par contributeur, fusionnés à la lecture, parce que deux personnes
qui écrivent le même fichier sur un dossier synchronisé en perdent une.

### Le bandeau gris du pied de page

Il est **ancré au paragraphe** qui porte les dessins, soit le deuxième des
quatre que comptait le pied. Les deux derniers ne contenaient rien : ni texte,
ni champ, ni dessin, mais chacun une hauteur de ligne. Ils repoussaient le
bandeau d'environ un centimètre au-dessus du bord de page, d'où une bande
blanche en bas de chaque page. Le constructeur du modèle retire les
paragraphes de fin réellement vides — et seulement ceux-là : celui qui porte
les dessins n'a pas de texte non plus.

### Sommaires et numérotation

Les numéros de tableaux et de cartes sont posés dans des champs `SEQ`, avec
leur valeur déjà calculée. Deux conséquences : Word peut les recalculer si
quelqu'un insère un tableau au milieu, et les **sommaires des tableaux et des
cartes** se construisent tout seuls — sans champ `SEQ`, Word ne saurait pas
distinguer un tableau d'une carte. Le document demande la mise à jour des
champs à l'ouverture ; à défaut, Ctrl+A puis F9.

Chaque carte occupe une **page en paysage**, comme dans le prédiagnostic de
référence. Les poser en portrait obligeait à les réduire à 16 cm de large,
soit la moitié de leur définition utile, et les toponymes du fond de plan
devenaient illisibles.

Ce que l'outil écrit lui-même : les dénombrements (« dans l'aire d'étude
rapprochée, on recense 5 ZNIEFF de type I et 1 ZNIEFF de type II »), les
distances, l'appartenance aux aires d'étude, les statuts de chaque espèce lus
dans BDC-Statuts, les cartes, la numérotation des tableaux et des figures.

Ce qu'il laisse : tout jugement. Chaque trou est écrit en couleur et **formule
sa consigne** — « indiquer lesquelles de ces espèces peuvent effectivement se
trouver sur la ZIP au regard de leur écologie » — pour que le document se
parcoure une fois et qu'on sache quoi faire. La frontière ne passe pas où on la
met d'instinct : « 18 ZNIEFF sont présentes » est du comptage et revient à
l'outil ; « les interactions avec la ZIP sont peu probables » est un jugement
et revient à l'experte.

Les tableaux de zonages portent une **ligne fusionnée par type**, comme le
document de référence : « ZNIEFF de type I » occupe une ligne à lui seul et ses
entrées suivent dessous, plutôt qu'une colonne « Type » qui répète la même
valeur onze fois.

Les tableaux d'espèces ont les colonnes de leur groupe, reprises du document de
référence : protection régionale et directive Habitats pour la flore ; annexe I
de la directive Oiseaux et trois colonnes de liste rouge nationale — nicheurs,
hivernants, de passage — pour l'avifaune ; annexe II et liste rouge pour les
autres groupes. Le groupe se déduit du taxon (`GROUP3_INPN`) et ne se demande
pas : un export de faune mêle les groupes.

### Ce que l'onglet B ne fait pas

Il ne va pas chercher les occurrences. Le choix des sources est un jugement
d'experte — quelle source fait autorité pour tel groupe dans telle région —
qu'on n'a aucune chance de coder. L'outil recoupe ce qu'on lui donne.

Il ne rédige pas l'interprétation : les interactions probables entre un zonage
et la ZIP, le raisonnement sur les corridors, les exceptions. C'est ce qui fait
la valeur du document.

---

## Sources

Référentiels **téléchargés et figés**, jamais appelés en direct pendant une
étude. Trois raisons : la Licence Ouverte impose de citer la source *et sa
date* ; deux prédiags faits à six mois d'écart doivent être comparables ; le
site de l'INPN est en reconstruction et les appels directs tombent.

| Référentiel | Version | Apport |
|---|---|---|
| **TaxRef** | 18 | taxonomie, synonymies, 49 476 noms vernaculaires français |
| **BDC-Statuts** | 18 | LRE, LRN, LRR, LRM, ZDET, PN, PR, DH, DO, PNA |

Source : Muséum national d'Histoire naturelle / PatriNat (OFB-MNHN-CNRS-IRD) —
<https://inpn.mnhn.fr/referentiels-donnees>

**Licence Ouverte / Open Licence (Etalab)** : réutilisation libre, y compris
commerciale, sous réserve de citer la source et sa date de mise à jour. Chaque
rapport produit porte cette mention.

> L'API de l'UICN a été écartée : elle interdit explicitement l'usage
> commercial et renvoie les usages professionnels vers un abonnement payant.
> BDC-Statuts couvre les mêmes statuts, sans cette restriction.

---

## Ce qui se compare, et ce qui ne se compare pas

Les deux sources ne codent pas les statuts de la même façon. Comparer sans
traduire produit des centaines de faux écarts — mesuré : **1 050 des 1 383
premiers constats n'étaient que des différences d'écriture.**

**Comparé** — listes rouges (`LRE`, `LRN`, `LRR`, `LRM`), ZNIEFF déterminantes
(`ZDET`, booléen), directive Habitats (`DH`).

**Non comparé**, et annoncé comme tel dans le rapport :

- `PN`, `PR` — BDC désigne l'arrêté (`NO3`, `RV93`), le classeur l'article
  (« Art. 3 ») : deux nomenclatures sans pont automatique.
- `DO` — BDC code l'annexe (`CDO1`), le classeur le code espèce (`A092`).
- `PD`, `PNA` — non traités à ce stade.

Par ailleurs **BDC ne distingue pas les périodes** (nicheurs, hivernants, de
passage). Une colonne périodisée n'est confrontée que lorsqu'une seule de ses
périodes est renseignée, l'appariement étant alors sans ambiguïté. C'est ce qui
limite la couverture du classeur oiseaux.

---

## Appariement des noms

`prediag_enviro.taxref.Index.apparier()` résout un nom — vernaculaire ou
scientifique — vers un `cd_ref`. Il servira au volet 2 pour recouper les
sources d'occurrences.

Taux mesurés sur 360 espèces tirées des classeurs :

| Entrée | Taux |
|---|---|
| nom scientifique | **98,6 %** |
| nom commun + scientifique | **95,8 %** |
| nom commun seul | 85,3 % |
| capture d'écran (OCR simulé) | 81,4 % |

Deux règles font l'essentiel de la fiabilité :

- **filtre par groupe** — sans lui, « Grande Tortue » s'apparie à
  *Scutellaria galericulata*, une plante. Il ne gagne qu'un point de taux brut
  mais convertit des faux silencieux en « non résolu » explicites.
- **préférence de rang** — « Effraie des clochers » renvoie *Tyto alba* et deux
  sous-espèces ; on garde l'espèce.

---

## Où vont les fichiers

Le départage n'est pas affaire de goût : OneDrive synchronise ce qu'il voit.

**Dans le dossier de l'application** — ce qui se partage et change rarement :

```
app.py                    l'interface, deux onglets
_LANCER Prediag.bat       le lanceur Windows
run_veille.py             la veille en ligne de commande
config/sources.yml        référentiels épinglés (URL, version)
classeurs/                les six classeurs B-Statuts, maître unique
extraits/                 zonages par département, ~650 Mo pour la France
```

**Sur la machine** (`%LOCALAPPDATA%\prediag-enviro`) — ce qui est lourd, dérivé
ou écrit pendant l'exécution :

```
venv/                     l'environnement Python (~300 Mo)
referentiels/             archives INPN + index (jusqu'à 1 Go)
memoire/arbitrages.json   décisions rendues, alias appris
sorties/                  rapports et documents produits
```

Les archives nationales ne servent qu'à **construire** les extraits : seul le
poste qui tient les référentiels à jour les porte. Un chef de projet n'a que
les quelques mégaoctets de son département.

`PREDIAG_ENVIRO_DONNEES` déplace le dossier local, par exemple vers un disque
plus grand. L'outil avertit s'il se retrouve sous OneDrive — un gigaoctet
synchronisé pour chaque personne, et des copies de conflit sur les fichiers
écrits en cours d'exécution.

```

src/prediag_enviro/
    referentiels.py   téléchargement avec reprise, épinglage des versions
    taxref.py         index TaxRef, moteur d'appariement
    bdc.py            index BDC-Statuts
    classeurs.py      lecture des classeurs (dispositions hétérogènes)
    vocabulaire.py    correspondance des codes entre les deux sources
    veille.py         production des constats
    memoire.py        arbitrages et alias persistés
    rapport.py        sortie Excel
    communes.py       emprise projet, communes et parts de surface
    recoupement.py    sources d'espèces déposées → liste unique
    zonages.py        croisement avec les zonages du patrimoine naturel
    extraits.py       extraits départementaux, construits une fois
    cartes.py         planches A4 paysage, fond Plan IGN
    statuts_especes.py colonnes de statuts par groupe, résolues sur BDC
    sortie_word.py    construction du document (compteurs, tableaux, styles)
    rapport_prediag.py assemblage du prédiagnostic

    modele/prediag_modele.docx   en-tête, pied de page, styles maison
    service.py        orchestration partagée interface / ligne de commande
```

`classeurs.py` mérite un mot : les six fichiers n'ont pas la même disposition
(`CD_NOM` en colonne 4, 5 ou 6 selon le groupe) et les en-têtes fusionnés ne
disent pas à quelle période chaque colonne correspond. La solution ne vient pas
d'une heuristique : **l'onglet « Saisie étude » est un dictionnaire de colonnes**
que la responsable environnement tient elle-même à jour (ligne 5 l'index, ligne 6
le territoire, ligne 7 le champ). On le lit plutôt que de deviner, avec repli sur
les en-têtes et leurs plages fusionnées quand il est absent.

---

## Déploiement

`packages.txt` déclare les dépendances système pour Streamlit Community Cloud :
`tesseract-ocr` et `tesseract-ocr-fra`, ce dernier parce que sans le paquet de
langue les accents sortent faux et l'appariement TaxRef échoue sur des noms
pourtant corrects.

**Ce fichier n'admet aucun commentaire.** Streamlit Cloud le passe tel quel à
`apt-get` via `xargs` : une ligne commençant par `#` est traitée comme un nom de
paquet, et une apostrophe française casse `xargs` avant même l'installation
(`unmatched single quote`). Un commentaire d'une ligne a suffi à faire échouer
un déploiement entier. `requirements.txt`, lui, accepte les commentaires — c'est
pip qui le lit.

**Réserve sur l'hébergement.** Les référentiels pèsent 550 Mo au total et
l'extraction du GeoPackage des espaces protégés en demande 148 de plus. C'est
hors de portée du plan gratuit de Streamlit Cloud. L'outil est conçu pour
tourner **en local**, où les archives se téléchargent une fois et se réutilisent.
Un déploiement n'aurait de sens qu'en limitant le périmètre aux référentiels
d'espèces, ou en pré-construisant des référentiels réduits aux régions
réellement couvertes.

## Limites connues

- **La détection des nouvelles listes rouges régionales n'est pas
  implémentée.** Le tableau de bord de l'UICN France et l'arborescence
  `inpn.mnhn.fr/docs/LR_FCE/` permettraient de savoir ce qui est paru et
  quand ; la chaîne n'a pas été éprouvée.
- **Les listes rouges européennes de BDC sont sans édition déclarée.** Les
  écarts constatés sur `LRE` ressemblent à des différences d'édition plutôt
  qu'à des erreurs, mais rien dans les données ne permet de trancher.
- **La couverture européenne de BDC est partielle.** `LRE` ne porte que
  421 entrées pour les oiseaux, 29 pour les reptiles et 16 pour les
  amphibiens : la colonne « Liste rouge Europe » reste souvent vide, et une
  case vide y signifie « non renseigné dans BDC », non « non évalué ». BDC
  porte parfois une évaluation **mondiale** là où il n'a pas d'évaluation
  européenne ; elle n'est pas recopiée dans la colonne Europe.
- **Les zones humides ne sont pas alimentées.** Les couches de sols et de
  milieux humides ne sont pas nationales et relèvent de sources régionales. La
  rubrique sort avec une consigne qui nomme les sources à consulter.
- **La casse des noms de zonages est une aide de présentation.** Les noms que
  le référentiel porte tout en capitales sont remis en casse de lecture, avec
  une liste de particules et de noms communs de géographie. Un nom commun
  absent de cette liste prend une capitale de trop : coquille visible et
  corrigeable, préférée à la décapitalisation des noms propres que produisait
  le passage en bas de casse.
- **L'écriture dans les classeurs n'est pas implémentée**, délibérément. Le jour
  où elle le sera, elle passera par le pilotage d'Excel (et non par une
  réécriture du fichier), travaillera sur copie horodatée, n'appliquera que les
  lignes marquées `accepté` et ne supprimera jamais de ligne.
