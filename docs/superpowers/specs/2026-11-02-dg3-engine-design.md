# DG3 — le moteur de fin de partie tempo des deux côtés du tour

## Constat

DG1 (`selfplay.DG1Policy`) et DG2 (`dg2.DG2Policy`) perdent tous les deux
contre un même défaut : avant de poser sa question, aucun des deux
n'utilise le moteur le plus fort déjà présent dans le dépôt.

- DG1 utilise `strategy.evaluate_race_strategy` avant la question (exact
  seulement jusqu'à N <= 5, recherche en faisceau jusqu'à N <= 12, heuristique
  1-coup au-delà) et ne passe au moteur `endgame_tempo.TempoEndgameSolver`
  (exact jusqu'à N <= 20, conscient du tempo et de l'exclusion adverse) qu'une
  fois sa question répondue. C'est documenté, pas caché, dans le docstring de
  `DG1Policy`.
- `strategy._exact_value` simule la réponse de l'adversaire avec un
  `frozenset()` neuf à chaque fois (voir le commentaire associé) : même
  à N <= 5, DG1 ne modélise jamais que l'adversaire a pu déjà manquer un essai
  et donc exclure ce code de son propre tirage suivant. Seul
  `endgame.opp_hit_probability` (repris par `endgame_tempo`) fait ce calcul.
- DG2 réinvente un troisième modèle, plus faible que les deux : recherche
  exacte seulement jusqu'à N <= 12 (`exact_n_max`), sans aucune notion
  d'exclusion adverse (`_opp_guess_value` utilise un taux de réussite plat
  `1/n`), et une heuristique de question large qui ignore les questions
  déjà déterminées. Les benchmarks existants (`benchmarks/dg1-dg2-*.json`)
  montrent un taux de victoire proche de 50 % contre DG1 — pas l'amélioration
  visée par sa propre conception (`2026-11-02-dg2-engine-design.md`).

## Approche DG3

DG3 ne construit aucun nouveau modèle de jeu. Il pose une question étroite :
le moteur le plus fort déjà publié peut-il décider des deux moments du tour,
pas seulement de celui où DG1 l'utilise déjà ?

- Tant que le pool public tient dans `ENDGAME_N_MAX` (20, mesuré et déjà
  réglé pour `endgame_tempo.py`), DG3 appelle
  `endgame_tempo.evaluate_endgame` avant ET après sa question
  (`PHASE_MY_TURN` et `PHASE_MY_POST_QUESTION`), avec un budget de temps de
  10 s (voir mesures ci-dessous).
- Au-delà de cette taille, ou si le moteur dépasse son budget, DG3 délègue
  intégralement au modèle de DG1 (`selfplay.race_strategy_action`, extrait
  tel quel de `DG1Policy.choose`). Sur un plateau large, DG3 et DG1 jouent
  donc exactement le même coup : pas de régression possible à cet endroit,
  seulement un gain potentiel une fois que la partie — toute partie — se
  resserre sous le seuil exact.

Un détail nouveau : à `PHASE_MY_TURN`, le moteur peut recommander de poser
une question « nulle » (réponse déjà déterminée par le pool courant), un
coup de tempo délibéré documenté dans `endgame_tempo.py`. Ce coup n'existe
pas dans l'ancien modèle de DG1, qui ne considère jamais une question à une
seule issue. `dg3._null_question_action` construit directement l'action à
partir de l'entrée structurée déjà calculée par le moteur
(`endgame_tempo.question_entry`), plutôt que de chercher le libellé dans
`solver.enumerate_all_questions` : ce dernier élimine silencieusement les
questions de segment déjà déterminées (`solver.py`), le cas de question
nulle le plus fréquent sur un plateau moyen.

## Budget de temps

Mesuré directement sur cette machine (script jetable, 2026-11-02) avec
`TempoEndgameSolver.analyze`, 6 plateaux aléatoires par palier :

| N cible | pire cas mesuré |
|---|---:|
| <= 14 | 0.67 s |
| <= 17 | 2.78 s |
| <= 19 | 8.03 s |
| <= 20 | 2.30 s |

Le moteur plus simple `endgame.EndgameSolver` (sans la couche tempo) est
plus lent dans le pire cas (14.81 s à N = 20, `tests/bench_endgame.py perf`) :
l'optimisation `stability_threshold` de la couche tempo réduit le coût
plutôt que l'alourdir. 10 s laisse une marge confortable sur les mesures
ci-dessus sans rendre une décision isolée sans limite : un dépassement
dégrade vers le modèle de DG1, jamais vers un plantage ou une attente
non bornée.

Les deux moteurs tournent avec un budget bien plus généreux que celui déjà
accordé à DG1 après sa question dans le tournoi existant
(`dg1_time_budget_s=0.25`, choisi pour la vitesse du benchmark, pas comme
contrainte de production — l'application native accepte déjà jusqu'à 30 s
pour la même analyse, voir `ENDGAME_TIME_BUDGET_S`). Le gain mesuré de DG3
inclut donc à la fois un modèle plus fort avant la question et un budget de
calcul plus réaliste après — les deux sont documentés, aucun n'est caché.

## Validation

- `tests/test_dg3.py` : DG3 suit exactement la recommandation du moteur
  tempo sur un petit plateau (comparaison directe avec
  `evaluate_endgame`), retombe bit-à-bit sur le coup de DG1 sur un plateau
  large, ne révèle jamais les essais ratés privés, et le coup nul round-trip
  correctement à travers `solver._apply_answer_to_clue` pour chacun des cinq
  types de question.
- Tournoi : `python -m digitcode.tournament --checkpoint <path> --games N`
  avec `DG3Policy` à la place de `DG2Policy`, même protocole de secrets et de
  seeds que les benchmarks DG1-DG2 existants, pour une comparaison
  directement reproductible.
- Résultat mesuré sur 300 parties (`benchmarks/dg1-dg3-300.json`) : 172/300
  (57,3 %), p ≈ 0,013 (test binomial exact contre l'hypothèse 50/50).

## Pistes explorées après le premier résultat (2026-11-02)

Deux leviers identifiés pour la zone « plateau large » (> 20 candidats,
celle où la plupart des tours se jouent) : repousser le seuil de calcul
exact, et rendre la détection de piège de l'heuristique large plus
rigoureuse. Un troisième levier (nombre d'essais restants, non pris en
compte par l'heuristique large) a été écarté sur confirmation utilisateur :
jamais observé comme pertinent en plus de 1000 parties humaines.

### Repousser `ENDGAME_N_MAX` au-delà de 20 — abandonné

Mesuré directement (`TempoEndgameSolver.analyze`, plateaux aléatoires à
cible 22/24/26/28/30) : le tout premier plateau testé à N=22 dépasse un
budget de 120 s sans conclure (`EndgameBudgetExceeded`). L'estimation
optimiste historique du docstring d'`endgame_tempo.py` ("N=24 en 1-3s,
N=28 en ~31s") ne tient pas sur le pire cas réel une fois la variance
prise en compte, en particulier sur un plateau où presque aucune question
n'a encore été posée (grande réserve de questions nulles). Conclusion :
20 est proche du plafond pratique de cet algorithme sans un investissement
d'ingénierie bien plus lourd (parallélisation, meilleur élagage, portage
dans un langage plus bas niveau) -- hors de portée d'une amélioration
ciblée. Ce levier n'a pas été retenu.

### Détection de piège rigoureuse pour l'heuristique large — essayé, abandonné

`strategy._apply_lookahead_penalty` (le seul garde-fou existant pour les
plateaux larges) ne regarde qu'un indicateur binaire -- "l'adversaire a-t-il
au moins une question sans risque" -- sur les 4 meilleures questions par
score d'entropie seul, sans jamais regarder qui profite réellement d'une
branche. Une version (`dg3._wide_board_action`, retirée depuis) remplaçait
cet indicateur par une vraie probabilité de victoire par branche : quand
une branche d'une question large retombe sous `endgame_n_max`, évaluation
exacte avec le même moteur tempo que DG3 utilise déjà après sa question
(`PHASE_MY_POST_QUESTION`) ; sinon, rappel à 1 niveau du modèle de DG1
lui-même (`evaluate_race_strategy`) sur cette branche -- les deux sur une
échelle `p_win` directement comparable.

**Résultat mesuré, négatif** : un tournoi de 300 parties avec cette version
donne 56,0 % (168/300, p≈0,043) -- statistiquement indiscernable du 57,3 %
obtenu sans elle. La cause, diagnostiquée directement (pas juste supposée) :
une seule branche peut légitimement coûter plusieurs secondes à résoudre
exactement (mesuré jusqu'à 8s à N=19 dans le tableau ci-dessus), donc
n'importe quel budget de temps total raisonnable pour un tournoi (5 à 8s)
suffit rarement à évaluer plus d'un seul candidat sur les 4 du faisceau --
mesuré directement : aussi peu que 1 candidat sur 4 obtient une vraie
évaluation avant épuisement du budget, que ce budget soit partagé entre
candidats ou réparti équitablement entre eux. Sans un deuxième candidat
évalué, il n'y a rien à comparer : le mécanisme ne fait, la plupart du
temps, que retomber plus lentement sur le choix de DG1 lui-même.

Ce n'est pas que l'idée soit fausse -- c'est que le coût réel d'une
évaluation exacte par branche est incompatible avec un budget de décision
raisonnable à l'échelle d'un tournoi (le même obstacle, en plus petit, que
celui qui a fait abandonner l'extension de `ENDGAME_N_MAX` ci-dessus).
Retenter ce levier n'a de sens qu'avec soit un budget de temps par décision
bien plus généreux (au prix d'un tournoi bien plus lent), soit un moteur
nettement plus rapide pour la recherche par branche.
