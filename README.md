# prediag-enviro

Outillage du pré-diagnostic environnemental bibliographique, pour l'équipe
développement PV d'UNITe.

L'outil comporte deux volets. **Seul le volet 1 est implémenté.**

| Volet | Objet | État |
|---|---|---|
| **1 · Veille** | garder à jour les classeurs B-Statuts de référence | fonctionnel |
| **2 · Prédiag** | pré-remplir un prédiag à partir d'une emprise projet | à venir |

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

## Volet 1 — la veille

### Installation

```bash
pip install -r requirements.txt
```

Déposer les six classeurs dans `classeurs/`. Les noms sont reconnus par motif
(`*oiseaux*.xlsx`, `*mammif*.xlsx`, `*amphib*.xlsx`, `*insectes*.xlsx`,
`*macroh*.xlsx`, `*araign*.xlsx`).

### Usage

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

## Organisation

```
config/sources.yml        référentiels épinglés (URL, version)
classeurs/                les six classeurs B-Statuts          (hors dépôt)
referentiels/             archives INPN + index en cache       (hors dépôt)
memoire/arbitrages.json   décisions rendues, alias appris      (hors dépôt)
sorties/                  rapports produits                    (hors dépôt)

src/prediag_enviro/
    referentiels.py   téléchargement avec reprise, épinglage des versions
    taxref.py         index TaxRef, moteur d'appariement
    bdc.py            index BDC-Statuts
    classeurs.py      lecture des classeurs (dispositions hétérogènes)
    vocabulaire.py    correspondance des codes entre les deux sources
    veille.py         production des constats
    memoire.py        arbitrages et alias persistés
    rapport.py        sortie Excel
```

`classeurs.py` mérite un mot : les six fichiers n'ont pas la même disposition
(`CD_NOM` en colonne 4, 5 ou 6 selon le groupe) et les en-têtes fusionnés ne
disent pas à quelle période chaque colonne correspond. La solution ne vient pas
d'une heuristique : **l'onglet « Saisie étude » est un dictionnaire de colonnes**
que la responsable environnement tient elle-même à jour (ligne 5 l'index, ligne 6
le territoire, ligne 7 le champ). On le lit plutôt que de deviner, avec repli sur
les en-têtes et leurs plages fusionnées quand il est absent.

---

## Limites connues

- **La détection des nouvelles listes rouges régionales n'est pas
  implémentée.** Le tableau de bord de l'UICN France et l'arborescence
  `inpn.mnhn.fr/docs/LR_FCE/` permettraient de savoir ce qui est paru et
  quand ; la chaîne n'a pas été éprouvée.
- **Les listes rouges européennes de BDC sont sans édition déclarée.** Les
  écarts constatés sur `LRE` ressemblent à des différences d'édition plutôt
  qu'à des erreurs, mais rien dans les données ne permet de trancher.
- **L'écriture dans les classeurs n'est pas implémentée**, délibérément. Le jour
  où elle le sera, elle passera par le pilotage d'Excel (et non par une
  réécriture du fichier), travaillera sur copie horodatée, n'appliquera que les
  lignes marquées `accepté` et ne supprimera jamais de ligne.
