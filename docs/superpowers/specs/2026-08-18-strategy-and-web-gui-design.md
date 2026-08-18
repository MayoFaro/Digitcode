# Digitcode — moteur stratégique de course & interface web

Date: 2026-08-18
Statut: validé en brainstorming, prêt pour plan d'implémentation

## Contexte

`digitcode` est un assistant CLI (`cli.py` + `solver.py` + `mapping.py`) pour un
jeu de déduction à 6 chiffres affichés en 7-segments (positions `T,U,V/W,X,Y`),
joué à deux contre un adversaire sur un plateau partagé (grille `A-I` × `J-S`
donnant des indices : sommes de ligne/colonne, parité, comparaisons entre
positions adjacentes, état on/off d'un segment précis).

Deux changements sont adressés par cette spec :

1. **Changement de règle du jeu** : à son tour, un joueur peut poser une
   question *et/ou* proposer une solution (au lieu du choix exclusif
   précédent). Chaque joueur dispose d'un **budget de 2 tentatives** de
   solution sur toute la partie. Le moteur stratégique actuel (zugzwang
   binaire) ne modélise pas cette dynamique de course et doit être remplacé.
2. **Absence d'interface graphique** : le CLI (regex, `input()`) est trop lent
   à l'usage en partie réelle. On construit une interface web locale calquée
   sur le plateau réel du jeu, pour la saisie des indices et l'affichage des
   recommandations.

**Hors scope de cette spec** (pistes retenues mais non traitées ici, à
spécifier séparément plus tard) :
- interception du flux réseau du jeu pour éviter la ressaisie manuelle des
  questions/réponses ;
- extraction automatique des indices déjà posés à partir d'une capture
  d'écran du plateau réel (vision).

## Règles du jeu confirmées (pour le modèle)

- Tours **strictement alternés** entre les deux joueurs.
- À son tour, le joueur peut poser une question (parmi ligne/colonne/parité/
  comparaison/segment) *et/ou* proposer une solution — dans cet ordre
  logique (une question posée puis répondue avant toute tentative, puisque
  attendre l'information ne coûte rien).
- Un joueur ne peut jamais proposer de solution pendant le tour de l'autre.
- Chaque joueur a un budget de **2 tentatives** de solution pour toute la
  partie. Une tentative ratée ne coûte que 1 point de budget — elle ne
  consomme pas le droit de poser une question ce tour-ci ni les suivants
  ("bonus gratuit").
- Une tentative ratée ne donne **aucun feedback partiel** (juste faux/vrai),
  et le code tenté n'est **jamais révélé à l'adversaire**.
- Le fait qu'une tentative ait eu lieu et ait échoué **est annoncé** (visible
  des deux joueurs), donc le nombre d'essais restants de l'adversaire est
  une information publique et exacte.
- La première proposition correcte met fin à la partie immédiatement
  (victoire).

## Point 1 — Moteur stratégique récursif (`digitcode/strategy.py`, nouveau module)

### État de la fonction de valeur

`f(clue, a_me, a_opp, mes_exclusions, au_tour_de)` — probabilité que "moi"
(le joueur assisté) gagne la partie, sous jeu optimal des deux côtés :

- `clue` : état partagé des indices, comme aujourd'hui (détermine les
  domaines via `DigitcodeSolver.propagate`).
- `a_me`, `a_opp` ∈ {0,1,2} : essais restants de chaque joueur — **exacts**
  des deux côtés (les échecs sont annoncés publiquement).
- `mes_exclusions` : ensemble des candidats que *moi* j'ai personnellement
  déjà tentés et éliminés (privé, taille ≤ 2). Sert uniquement à ne jamais
  reproposer un code que je sais déjà faux, même si le plateau partagé ne
  l'exclut pas formellement.
- `au_tour_de` ∈ {moi, adversaire}.

**Hypothèse simplificatrice assumée** : les exclusions privées de
l'adversaire ne sont jamais modélisées (invisibles par construction). Sa
probabilité de succès à chaque tentative reste conservativement
`1 / N_partagé` (N = nombre de solutions consistantes avec `clue`), même
après un éventuel échec précédent de sa part. C'est une approximation
légèrement prudente (elle peut sous-estimer ses vraies chances s'il se
souvient de ses propres essais), documentée comme telle plutôt que
modélisée exactement — la dissymétrie d'information rend une modélisation
exacte de son côté impossible de toute façon.

### Récursion

À un nœud "moi" : je choisis, parmi les questions légales (types déjà
existants : ligne, colonne, parité, comparaison, segment — cf.
`enumerate_all_questions`), celle qui **maximise** `f`. Pour chaque question,
pour chaque réponse possible pondérée par sa probabilité (`n_réponse/N`,
logique déjà présente dans `_ev_immediate_for_question`), je choisis ensuite
le meilleur de : deviner maintenant (si `a_me > 0`) vs. ne pas deviner et
laisser passer le tour.

À un nœud "adversaire" : structure symétrique, mais il choisit la question
qui **minimise** ma valeur (somme nulle).

**Terminal** : `N = 1` correspond à une victoire quasi assurée au prochain
essai disponible. Cas dégénéré documenté (non traité spécialement) :
`a_me = 0` alors que `N = 1` — improbable avec un budget de 2, laissé comme
état où je ne peux que continuer à jouer sans pouvoir conclure.

**Mémoïsation** : clé = (signature figée de `clue` — tuples/frozensets des
totaux/parités/comparaisons/états de segment — , `a_me`, `a_opp`,
`frozenset(mes_exclusions)`, `au_tour_de`). La taille du domaine est déjà
démontrée tractable par l'énumération DFS existante (`enumerate_solutions`) ;
la mémoïsation évite les recalculs sur états déjà visités dans l'arbre.

### API exposée par `strategy.py`

Une fonction principale, appelée par le CLI et par le backend web :

```python
def evaluate_race_strategy(
    solver: DigitcodeSolver,
    clue: Clue,
    a_me: int,
    a_opp: int,
    my_excluded: frozenset[tuple],
) -> dict:
    """Retourne :
    - 'p_win': probabilité de victoire sous jeu optimal depuis cet état
    - 'best_question': la question recommandée (label + qtype)
    - 'guess_now': bool, si deviner immédiatement bat l'attente
    - 'ranked_alternatives': liste des autres questions classées par p_win
    """
```

Remplace l'usage de `evaluate_forcing_questions` dans `cli.py` et dans le
futur backend web (les fonctions `enumerate_global_questions`,
`enumerate_all_questions` de `solver.py` restent utilisées en interne comme
briques de base, inchangées).

## Point 2 — Interface web (`digitcode/web/`, nouveau module)

### Backend

Petite application (Flask ou FastAPI) qui garde l'état courant (`Clue`, et
les compteurs `a_me`/`a_opp`/`mes_exclusions`) en mémoire pour une session de
jeu locale unique (pas de multi-session, pas d'authentification — usage
personnel local).

Endpoints :
- `GET /state` : domaines courants, solutions candidates (`enumerate_solutions`,
  limite existante conservée), sortie de `evaluate_race_strategy`.
- `POST /clue` : applique une modification structurée (équivalent JSON de
  ce que `parse_one` fait aujourd'hui via regex : somme ligne/colonne,
  parité, comparaison, segment on/off, y compris suppression).
- `POST /guess-failed` : enregistre un essai raté — `{"who": "me"|"opponent"}`
  — décrémente `a_me`/`a_opp` en conséquence ; si `who == "me"`, ajoute aussi
  le candidat tenté à `mes_exclusions` (le candidat est choisi par le joueur
  dans la liste des solutions courantes affichées, pas généré par le
  serveur).
- `POST /undo`, `POST /reset` : mêmes sémantiques que le CLI actuel.

Erreurs : une contradiction (domaine vide, `propagate()` lève déjà
`ValueError`) est interceptée et renvoyée comme réponse d'erreur explicite,
affichée en bandeau côté frontend — même logique défensive que le
`try/except` déjà présent dans `cli.py`.

### Frontend

Page unique HTML/JS vanilla (pas de framework/build lourd, cohérent avec le
minimalisme actuel du projet), layout validé pendant le brainstorming
(compagnon visuel) :

- **Colonne gauche (saisie compacte)** : les 6 positions `T,U,V,W,X,Y` sous
  forme de cases compactes affichant l'ensemble courant de candidats (ex.
  `{0,2,7}`), cliquables pour ouvrir un mini-éditeur (parité, segment
  on/off) ; liste compacte des sommes ligne/colonne posées ; liste des
  comparaisons ; historique/trace des déductions (repliable, reprend
  `solver.trace`).
- **Colonne droite (recommandation, dominante visuellement)** : nombre de
  solutions possibles ; meilleure question recommandée avec sa
  probabilité de victoire (`p_win` de `evaluate_race_strategy`) ; verdict
  "deviner maintenant ?" ; liste des alternatives classées ; compteurs
  d'essais restants (moi / adversaire) avec un bouton pour signaler un
  échec adverse (`POST /guess-failed {"who": "opponent"}`).

### Tests

Le projet n'a aujourd'hui aucune infrastructure de test. Étant donné la
complexité du nouveau moteur récursif (point 1), on introduit des tests
unitaires ciblés (`pytest`) sur `strategy.py` : quelques scénarios de fin de
partie construits à la main (N=1, N=2 avec 2/1/0 essais restants de chaque
côté, N=3) avec valeur de `p_win` attendue calculable manuellement. Le reste
(CLI existant, backend web, frontend) reste couvert manuellement, comme
aujourd'hui pour le CLI.

## Notes de portée

- `mapping.py` et le cœur de `solver.py` (propagation de contraintes,
  énumération) restent inchangés — le nouveau moteur et la GUI sont des
  couches additionnelles qui les réutilisent.
- Le projet n'a pas de dépôt git à ce jour ; à décider séparément si on en
  initialise un avant de committer cette spec.
