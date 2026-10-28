# Sage → Pennylane, avec analytique

Application Streamlit en français pour convertir un export **Écritures / Trésorerie Sage PNM** en CSV d’import Pennylane. Elle rattache les lignes analytiques A à la ligne comptable qui les précède, agrège les régularisations d’une même section et calcule les poids par famille. Les lignes exportées d’une même ligne comptable ont le même identifiant : mapper impérativement ce champ pour éviter de multiplier les montants.

## Démarrer sur Windows

1. Extraire entièrement ce ZIP dans un dossier.
2. Installer Python 3.11 ou supérieur si nécessaire.
3. Double-cliquer sur `lancer_windows.bat`. La première exécution installe les dépendances ; une connexion Internet est nécessaire.
4. L’application s’ouvre dans le navigateur. Charger votre PNM depuis la barre latérale.

En terminal, depuis ce dossier :

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address=localhost
```

Le fichier `exemple_fictif.pnm` permet de tester sans données réelles.

Pour Streamlit Community Cloud : placer les fichiers source dans un dépôt et sélectionner `app.py` comme fichier principal. N’ajoutez pas les PNM clients ni les ZIP d’import au dépôt. Le traitement s’effectue sur le serveur qui héberge Streamlit ; une installation locale garde les fichiers sur votre poste. Le code ne transmet rien à Pennylane et ne journalise pas les écritures.

## Utilisation

- En-tête du PNM fourni : **1 ligne**. Décodage automatique UTF-8 / Windows-1252 ; CP850 et ISO-8859-1 disponibles.
- Vérifier les journaux proposés : les codes numériques de Sage doivent être remplacés par les codes alphabétiques du dossier Pennylane. Les noms suggérés ne sont pas une lecture de votre plan de journaux.
- Vérifier les comptes auxiliaires : le code tiers est conservé dans le numéro de compte cible, avec préfixe du collectif si nécessaire. Les correspondances sont éditables.
- Nommer les familles et catégories. Le PNM contient des codes de section, pas leur intitulé descriptif : les codes sont proposés comme noms, à remplacer par les noms exacts existants si nécessaire.
- Corriger les écarts analytiques directement dans le tableau, ou sélectionner un traitement **pour chaque écart**. Le choix par défaut bloque l’export.
- Choisir éventuellement le regroupement mensuel des pièces déséquilibrées. Sans ce choix, elles bloquent l’export. Pour préserver les dates de chaque ligne, corriger la source dans Sage puis réexporter.
- Télécharger le ZIP d’import et le paramétrage réutilisable.

### Traitements des écarts

**Correction manuelle** : saisir le montant signé exact de chaque ventilation (crédit négatif), sans modifier le montant comptable.

**Reliquat** : conserve les ventilations et ajoute une catégorie `NON AFFECTÉ — REPRISE` pour la part manquante. Refusé en cas de surventilation.

**Recalcul proportionnel** : répartit le montant comptable selon les proportions des ventilations présentes. Il change les montants analytiques, même s’il conserve leurs proportions. Il ne faut pas l’utiliser pour masquer une erreur de section ou une ventilation dupliquée : corriger alors les montants.

Une ventilation nette de sens contraire reste bloquée. Les ajustements négatifs d’une même section sont agrégés avant ce contrôle.

**Regroupement mensuel** : seules les pièces déséquilibrées sont réunies, par journal et mois, à la date de fin de mois. Leurs références et libellés d’import changent. Les pièces déjà équilibrées conservent leur date. Chaque ligne d’origine reste identifiable dans la piste de contrôle. Aucun compte d’écart ni aucune contrepartie artificielle n’est créé.

## Importer dans Pennylane

Dans **Saisie > Imports > Importer un fichier > Écritures**, charger uniquement `01_IMPORT_PENNYLANE.csv`.

- Séparateur `;`, encodage UTF-8, dates `JJ/MM/AAAA`, **1 ligne d’en-tête**.
- Mapper Date, Code journal, Numéro de pièce, Numéro de compte, Libellé, Débit, Crédit et Date d’échéance.
- Mapper impérativement **Identifiant de ligne**, **Famille de catégories**, **Catégorie** et **Poids de la catégorie**.
- Ne pas importer les CSV de contrôle.
- Le code analytique optionnel n’est pas transmis. Vérifier les noms si des familles/catégories existent déjà.
- L’import avec analytique remplace une reprise par FEC : ne pas importer les deux. Cette opération ne complète pas les écritures déjà importées ; elle en crée de nouvelles.
- Après import, comparer la balance et le grand livre analytique, et vérifier des pièces multi-sections.

Les lignes CSV portent le montant complet répété pour chaque catégorie avec un poids ; leur somme brute n’est donc pas une balance. Dédupliquer par Identifiant de ligne pour contrôler les débits et crédits.

Le libellé exporté est commun à la pièce (premier libellé rencontré pour une pièce équilibrée). Les libellés de chaque ligne d’origine sont conservés dans `02_PISTE_CONTROLE.csv`.

## Vérification sur le fichier fourni

Fichier SAS LAUNAY TRANSPORT 2026 ANALYTIQUE :

| Contrôle | Résultat |
|---|---:|
| Lignes comptables, simulations comprises | 37 850 |
| Lignes analytiques A | 3 677 |
| Sections / plans | 187 / 1 |
| Lignes de simulation S | 72 |
| Lignes comptables hors simulations | 37 778 |
| Ventilations en écart | 13 |
| Pièces déséquilibrées sur journal + date + référence | 423 |
| Débit = crédit, simulations comprises | 44 706 550,94 € |
| Débit = crédit, simulations exclues | 44 421 870,28 € |

Les simulations sont **exclues par défaut**. Une option permet de les inclure ; elles seront alors importées comme des écritures ordinaires dans Pennylane. Les journaux mensuels sont équilibrés sur le fichier fourni.

Validation technique : tests unitaires, chargement Streamlit sans fichier et avec le fichier fourni, puis essai de conversion avec choix proportionnels et regroupement mensuel uniquement pour tester le parcours. Cet essai a produit 38 106 lignes CSV pour 37 778 lignes comptables distinctes, avec égalité des débits/crédits et poids de chaque famille totalisant 1. **Ces choix de test ne sont pas préappliqués dans l’application.** Aucun import réel dans Pennylane n’a été effectué.

## Fichiers remis par l’application

- `01_IMPORT_PENNYLANE.csv` : seul fichier à importer.
- `02_PISTE_CONTROLE.csv` : correspondance des lignes, dates, références, libellés et comptes d’origine.
- `03_VENTILATIONS_CONTROLE.csv` : montants analytiques d’origine et corrigés, traitement choisi.
- `04_RAPPORT.json` : empreinte du PNM, totaux, exclusions, écarts et paramétrage.
- `05_PARAMETRAGE.json` : correspondances et traitements à recharger. En-tête, encodage et inclusion des simulations restent à choisir dans la barre latérale.
- `LIRE_AVANT_IMPORT.txt` : consignes d’import.

## Périmètre

PNM à largeur fixe de 105, 112, 138, 141, 164 ou 199 caractères. Le profil 199 caractères du fichier fourni a été testé sur données réelles ; les autres variantes suivent la structure Sage mais n’ont pas été testées sur des exports réels. Les dates à deux chiffres utilisent la convention Python : 00–68 = 2000–2068 ; 69–99 = 1969–1999.

EUR uniquement. Les échéances E, devises et extensions de section non prises en charge sont bloquées avec numéro de ligne. Le convertisseur ne reprend ni lettrage ni justificatifs, ni transactions bancaires du module de gestion. Les lignes comptables nulles, sans analytique, sont omises et comptées dans le rapport. Conserver le PNM original pour les champs non repris (modes de règlement, zones réservées).

Tests : `python -m unittest -v`.

## Références consultées le 28/10/2026

- [Structure officielle Sage PNM](https://fr-kb.sage.com/portal/app/portlets/results/viewdocument.jsp?solutionid=220407073650230)
- [Pennylane : importer des écritures](https://help.pennylane.com/fr/articles/18793-importer-des-ecritures)
- [Pennylane : plusieurs catégories analytiques](https://help.pennylane.com/fr/articles/74963-importer-des-ecritures-comptables-avec-plusieurs-categories-analytiques)
