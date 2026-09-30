# Liste noire avant la fin de partie

Branche : `feat/pre-endgame-blacklist`.

## Comportement livré pour essai dans l'application native

Au-delà de 20 candidats publics, une analyse en arrière-plan repère les
questions informatives dont au moins une réponse possible laisse au plus
20 candidats. Pour chaque petite branche, elle calcule la probabilité de
victoire dans la phase **ma question vient d'être répondue** : proposer ou
terminer le tour, avec les tentatives, exclusions privées et échecs adverses
courants. C'est une comparaison de mes prochaines questions, même si
l'adversaire doit encore jouer ; l'interface l'indique explicitement.

Une seule branche entièrement évaluée sous 40 % suffit à exclure la question.
Les autres branches de cette question ne sont plus planifiées. Le résultat
indique la réponse dangereuse, le nombre de candidats et sa probabilité de
victoire. La question disparaît des recommandations rapides, des alternatives
et des coups à solution unique. Les questions ne sont pas bloquées à la saisie.

Trois états distincts :

- **Liste noire** : une issue calculée sous 40 %.
- **Filtre validé** : toutes les issues possibles ont une valeur calculée
  supérieure ou égale à 40 %. EV moyenne et minimum sont affichés.
- **Incomplète** : au moins une issue inconnue, sans danger encore prouvé.
  Aucune EV globale n'est inventée. Le nombre et les noms des questions
  incomplètes sont indiqués dans le texte de statut et son infobulle.

Le meilleur résultat parmi les questions entièrement validées devient la
recommandation EV. Les autres questions peuvent rester dans le classement
rapide : une analyse incomplète n'est jamais présentée comme validée.

## Budget et méthode

- Budget global par analyse : 55 secondes ; l'API borne toute demande à 60.
- La préparation des branches est comprise dans le budget.
- Premier passage par taille croissante, tranches de 0,25 seconde par branche.
- Les branches équivalentes sont mutualisées. Les mémoires de calcul sont
  conservées après une interruption de tranche.
- Après le passage rapide, priorité à l'achèvement des questions dont toutes
  les issues sont à 20 candidats ou moins, pour obtenir au moins une EV
  complète plutôt que disperser tout le budget.
- Sur un pool modeste, une seule énumération construit les partitions et un
  moteur partagé. Au-delà de 500 candidats, chaque réponse est énumérée
  jusqu'à 21 candidats seulement : 500 est une optimisation, pas un seuil
  d'éligibilité.
- Une nouvelle saisie annule le calcul ; un numéro de génération empêche
  l'affichage des anciens résultats. Les résultats progressifs sont copiés.

Les branches à plus de 20 candidats ne font pas l'objet d'une recherche EV
approximative dans cette première version. Les probabilités conservent les
hypothèses et limites du modèle `endgame_tempo`, notamment sur l'information
privée adverse. Le seuil de risque n'est pas une garantie contre tout
adversaire réel. Les limites temporelles sont coopératives, contrôlées dans
l'énumération et la recherche, et ne bloquent pas l'interface Qt.

Cette branche intègre l'interface native ; l'interface web et le CLI ne
présentent pas encore ce filtre.

## Reproduction de la partie du 30 septembre

Position après A=2, avant U/X : K=4 ; C=4, D=4, G=1, A=2 ; T<W, T>U.
60 candidats publics, deux tentatives chacun, aucune exclusion.

```bash
.venv/bin/python -m tests.bench_pre_endgame --seconds 55
```

Mesure locale du 30 septembre, sans autre suite de tests en concurrence :

| Résultat | Temps depuis le début |
|---|---:|
| U/V exclue : U>V, 3 candidats, P=33,3 % | 0,007 s |
| Ligne Q exclue : Q=1, 4 candidats, P=25 % | 0,016 s |
| U/X exclue : U>X, 6 candidats, P=33,3 % | 0,041 s |
| Quatre questions de segments équivalentes exclues | 0,041 s |
| H entièrement validée : EV=48,33 %, minimum=44,79 % | 37,404 s |

Ces temps sont des mesures de cette position sur cette machine, pas une
promesse de couverture complète de toutes les questions dans 55 secondes.
Le benchmark imprime les changements d'état puis le résultat final JSON.

Pour essayer l'interface, relancer l'application sur cette branche :

```bash
.venv/bin/python -m digitcode.native
```

Saisir la position ci-dessus pour reproduire le résultat à N=60. Lancer cette
commande sans arrêter une instance existante ouvre une fenêtre indépendante.

## Validation

- Suite complète : 347 tests réussis (451 s), avec trois avertissements Qt
  de dépréciation dans un test existant.
- Deux vérifications supplémentaires réussies : pondération d'une exclusion
  privée et déclenchement/annulation du calcul par la fenêtre.
- Tests de la nouvelle interface rejoués après l'ajustement d'affichage :
  5 réussis. Contrôle visuel hors écran à 380 pixels de large.
- Couverture du nouveau filtre : régression réelle U/X, U/V et Q ; seuil
  strict de 40 % ; arrêt des branches sœurs ; mutualisation ; branches
  inconnues ; délais ; annulation ; retrait des recommandations ; résultats
  périmés ; conservation des indices d'entrée.

## Présentation des alertes

Le bloc d'anticipation est placé en bas du volet Chiffres, qui défile
verticalement. Le compteur de solutions est conservé uniquement dans
l'en-tête commun au lieu d'être répété dans ce volet. Les boutons des
lettres sont répartis sur deux rangées pour éviter le défilement horizontal.

Un bandeau rouge commun aux trois volets apparaît dès qu'une issue calculée
est strictement sous 50 %, y compris entre 40 et 50 %. Cette alerte ne change
pas le seuil de la liste noire, qui reste à 40 %. Elle indique la probabilité
minimale observée et se réinitialise avec la position. Les résultats périmés
ne peuvent pas la réactiver. Le conseil du premier volet suit aussi le
filtrage des questions, y compris après sélection d'une lettre.

Les issues connues entre 40 % inclus et 50 % exclus sont affichées dans une
liste « Questions à risque », même si l'EV globale de la question reste
incomplète. Chaque ligne précise la question, la réponse, le nombre de
candidats et la probabilité. Une question déjà exclue figure uniquement dans
la liste noire avec son issue sous 40 %. Les listes vides sont masquées.
