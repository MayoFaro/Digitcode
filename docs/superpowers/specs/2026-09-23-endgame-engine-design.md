# Moteur de fin de partie (endgame, N petit)

Date : 2026-09-23
Branche : `feat/endgame-strategy`

## Contexte et objectif

En fin de partie (peu de solutions restantes), chaque tour se joue sur une
décision fine : **proposer un code maintenant, ou poser d'abord une question
— et si oui, laquelle, puis quel code proposer selon la réponse**. C'est là
que la partie se gagne ou se perd.

Le moteur actuel (`strategy.py`, `_exact_value` / `_race_search`) modélise
déjà la course alternée (expectimax, branches pondérées par leur nombre de
solutions, choix proposer/attendre par branche). Mais en fin de partie il a
quatre défauts, établis par l'analyse et les mesures de cette branche :

1. **Trop lent pour l'exact au-delà de N=5.** Mesuré (grilles de test,
   calcul exact forcé) : N=6 → 2,8 s et 21 s selon la grille, N=8 → 23 s.
   Chaque nœud re-propage des contraintes sur un `Clue`, alors qu'à N petit
   tout l'univers tient dans une liste de N codes. D'où l'élagage (beam) dès
   N=6, et un premier niveau limité aux ~12 questions les mieux classées par
   un proxy grossier — le défaut qui a enterré « 1 contre 11 » en 24ᵉ
   position et motivé le correctif « coups à solution unique » (b68a10f).
2. **Le code proposé est supposé indifférent** (`_best_guess_value`,
   « by symmetry », tente `remaining[0]`). Faux : la probabilité de gagner
   *tout de suite* est bien 1/n pour tout code, mais **ce que laisse un
   échec** dépend du code tenté. Exemple : pool {A,B,C}, la meilleure
   question adverse coupe {A}|{B,C}. Tenter A → V = 2/3 ; tenter B →
   V = 1/2. La règle intuitive « tenter le code que les questions adverses
   isoleraient » ne tient pas en général : sur un pool à 4 avec les
   questions {A,B}|{C,D} et {A}|{B,C,D}, les valeurs des tentatives sont
   A → 0,50, B → 0,42, C et D → 0,58. Seul le calcul tranche.
3. **« Proposer sans question » n'existe qu'à la racine.** Aux nœuds
   internes, chaque joueur est forcé de poser une question informative —
   donc de donner de l'information à l'autre. Or une proposition ratée est
   **privée** (seul l'échec est annoncé) : elle réduit le pool de celui qui
   propose sans réduire celui de l'autre. Le moteur rate ce coup dès le
   deuxième niveau, et suppose un adversaire qui informe toujours
   (optimiste pour moi).
4. **L'essai raté de l'adversaire est ignoré.** Le moteur lui donne
   toujours 1/N. En réalité, s'il a raté au pool de taille m, son code raté
   x est encore peut-être dans le pool courant S, et ses chances montent
   (voir « Croyance sur l'essai raté adverse »). Exemple : raté à m=4, pool
   réduit à 2 → il gagne son prochain essai avec 2/3, pas 1/2.

Objectif : un moteur dédié, exact, qui répond à « proposer ou questionner,
quoi exactement » quand N ≤ `ENDGAME_N_MAX`, avec un budget de temps
généreux (le joueur accepte 20–30 s en fin de partie), sans dégrader le
comportement actuel du reste de la partie.

## Décisions validées

1. **Nouveau module `endgame.py`**, basé sur la liste explicite des
   candidats. Le moteur actuel reste inchangé et continue de servir pour
   N > `ENDGAME_N_MAX` et comme premier affichage rapide.
2. **Budget de temps endgame : 30 s**, calcul en arrière-plan, affichage
   progressif (le résultat rapide actuel d'abord, remplacé par le résultat
   endgame quand il arrive).
3. **Le choix du code à proposer fait partie de la décision**, à tous les
   niveaux, pour moi.
4. **« Proposer sans question » est un coup légal à tous les niveaux**, pour
   les deux joueurs.
5. **L'essai raté de l'adversaire est suivi** par une croyance exacte
   (voir plus bas), sous l'hypothèse qu'il tire son code uniformément dans
   son pool.
6. **Seuil `ENDGAME_N_MAX` fixé par mesure**, pas a priori. Cible minimale
   N ≤ 6, cible visée N ≤ 10–12 sous 30 s.

## Règles du jeu (rappel, inchangées)

Cf. spec 2026-08-18. Points qui comptent ici :

- Tours alternés ; à son tour, un joueur pose une question **et/ou**
  propose un code (question d'abord). La réponse à une question est
  **publique**.
- 2 tentatives chacun. Une tentative ratée est annoncée, **le code tenté ne
  l'est pas**.
- Un joueur à 0 tentative perd dès que l'autre en a encore (l'autre pose
  des questions jusqu'à certitude).

## Modèle

### Candidats et questions comme partitions

À l'entrée du moteur (N ≤ `ENDGAME_N_MAX`) :

1. Énumérer une fois les N solutions compatibles avec le `Clue` public
   (`enumerate_solutions`, sans exclusion — l'adversaire, lui, ne connaît
   pas mes exclusions).
2. Pour chaque question de `enumerate_all_questions` et chacune de ses
   réponses, déterminer quels candidats sont compatibles avec la réponse,
   en **vérifiant chaque candidat contre le `Clue` enfant** (logique
   existante, `_apply_answer_to_clue` + vérification d'un code complet).
   Pas de réimplémentation de la sémantique des questions.
3. Chaque question devient une fonction candidat → réponse, donc une
   partition de tout sous-ensemble de candidats. Toutes les questions sont
   concernées (sommes ligne/colonne, parité, comparaisons, segments) : la
   réponse est toujours une fonction du code.

Les candidats sont indexés 0..N-1, les ensembles représentés en bitmask.
Poser une question sur le pool S = remplacer S par la classe de la réponse.
Une question dont S tient dans une seule classe est non informative.

### Hypothèse de tirage

Le code secret est uniforme parmi les candidats compatibles. La
probabilité d'une réponse est donc |classe ∩ mon pool| / |mon pool|. (À
valider empiriquement sur des parties réelles si possible — toutes les
valeurs en dépendent.)

### État

`(S, e_me, a_me, a_opp, au_tour_de, m_fail_opp)`

- `S` : pool public (bitmask), ne fait que rétrécir.
- `e_me` : mon code raté encore pertinent, ou aucun. **Au plus un** : un
  second échec me met à 0 tentative, état terminal.
- `a_me`, `a_opp` ∈ {0,1,2}.
- `au_tour_de` ∈ {moi, adv}.
- `m_fail_opp` : taille du pool public au moment où l'adversaire a raté,
  ou aucun. Même argument : au plus un échec adverse pertinent.

Mon pool = S \ {e_me}. L'état est fini et petit (≤ 2^N sous-ensembles × une
poignée de valeurs), mémoïsation exacte et sans ambiguïté — contrairement
au memo actuel, qui repose sur la confluence de la propagation.

### Croyance sur l'essai raté adverse

L'adversaire a raté au pool S_f (|S_f| = m), en tirant uniformément dans
S_f (il n'avait pas d'exclusion avant). Sachant l'échec, son code raté x est
uniforme sur S_f \ {t} (t = solution). Son échec **ne m'apprend rien sur
t** (P(échec | t) = 1 − 1/m pour tout t).

Comme S ⊂ S_f, pour tout t ∈ S : P(x ∈ S) = (|S| − 1)/(m − 1). Seule la
taille m compte, d'où `m_fail_opp` dans l'état. Probabilité que
l'adversaire gagne en proposant (uniformément dans S \ {x}) :

    P_hit_adv(S) = 1/(m−1) + (m − |S|) / ((m−1)·|S|)

Valable pour |S| ≥ 2. Pour |S| = 1, le pool ne contient que la solution
(x ≠ t) : la réussite est certaine (1), le premier terme de la formule
étant alors un 0/0. Sans échec adverse : 1/|S|. Vérification : m=4,
|S|=2 → 2/3.

Les réponses aux questions dépendent de t seul ; la loi de x sachant t
n'est pas modifiée par les questions, la formule reste valable après
n'importe quelle suite de questions.

### Coups et valeur (probabilité que je gagne)

**Terminaux** (règle existante) : a_me=0 et a_opp>0 → 0 ; a_opp=0 et
a_me>0 → 1 ; mon pool de taille 1 à mon tour (avec a_me>0) → 1.

**À mon tour**, je maximise sur :

- **Proposer sans question** : pour chaque code g de mon pool,
  `1/|pool| + (1 − 1/|pool|) × V(S, e_me=g, a_me−1, …, adv)` ; garder le
  meilleur g.
- **Question q** (informative sur mon pool) : pour chaque réponse r, avec
  probabilité |classe_r ∩ mon pool| / |mon pool|, on passe à S_r = S ∩
  classe_r, puis max de :
  - attendre : V(S_r, …, adv) ;
  - proposer g ∈ mon pool ∩ S_r (meilleur g) : comme ci-dessus sur S_r.
- **Passer** (question non informative), si une telle question existe —
  voir « Questions ouvertes ».

**Au tour adverse**, il minimise sur les mêmes familles de coups, avec :

- une probabilité de succès `P_hit_adv(S)` (croyance ci-dessus) ;
- un code proposé **tiré uniformément dans son pool** (on ne modélise pas
  son choix de code : il ne le fait pas forcément bien, et le modéliser
  déterministe signifierait qu'un échec me révèle son code — hypothèse
  trop forte) ;
- un échec qui fixe `m_fail_opp = |S|` et décrémente a_opp.

### Approximation assumée (information privée des deux côtés)

Le vrai jeu est à information imparfaite : je connais `e_me`, lui connaît
x. La résolution exacte d'un tel jeu ne se fait pas par un simple calcul
récursif. Approximation retenue, en « croyance publique » :

- l'adversaire choisit ses coups pour minimiser **ma** valeur calculée
  avec **mon** `e_me` — comme s'il connaissait mon code raté. C'est
  pessimiste pour moi, donc prudent ; le moteur actuel fait déjà la même
  chose ;
- ses choix ne dépendent pas de son x (qu'il connaît en vrai). C'est
  légèrement optimiste pour moi, mais x n'intervient que via la
  probabilité de succès, calculée exactement.

Documenté comme limite, pas contourné en v1.

## Intégration

### `game_state.py`

- Nouvel état : `opp_fail_pool_size` (taille N du pool public au moment où
  l'adversaire a raté), renseigné dans `guess_failed(who="opponent")`,
  remis à zéro par `reset`. Si deux échecs adverses surviennent, la partie
  est terminale côté moteur, la valeur n'a plus d'importance.
- `undo` ne restaure aujourd'hui que le `Clue`, pas les tentatives ; le
  nouvel état suit la même règle (pas d'élargissement de périmètre ici).
- `build_payload_from` : inchangé (résultat rapide actuel).
- Nouvelle fonction `build_endgame_from(clue, a_me, a_opp, excluded,
  opp_fail_pool_size, should_cancel)` → dict `endgame` (ci-dessous), ou
  `None` si N > `ENDGAME_N_MAX`.

### Résultat `endgame`

- `p_win` : valeur exacte sous le modèle ;
- `decision` : `"guess_now"`, `"question"`, ou `"none"` (plus d'essai de mon côté) ;
- `guess_now` : `{"code", "p_win"}` — meilleure proposition directe ;
- `best_question` : `{"label", "p_win", "branches": [{"answer", "n",
  "prob", "action": "guess"|"wait", "code"?, "value"}]}` — pour chaque
  réponse, quoi faire ensuite et quel code proposer ;
- `ranked_questions` : toutes les questions informatives avec leur
  `p_win` (pas de troncature : le moteur les évalue toutes) ;
- `complete` : False si le budget a été dépassé (on garde alors le
  résultat rapide et on le signale).

### Native (`native/`)

- `SolveWorker` : après avoir émis le payload rapide (`finished_ok`), si
  N ≤ `ENDGAME_N_MAX`, enchaîne `build_endgame_from` et émet un nouveau
  signal `endgame_ready(dict, generation)`. Même annulation coopérative, même
  contrôle de génération.
- Panneau conseils : un bloc **« Fin de partie »** affiché dès que N ≤
  seuil : « calcul en cours… » puis le verdict (« Proposer XXX maintenant —
  p=… » ou « Poser <question> — p=… »), la comparaison des deux options,
  et pour la question recommandée le tableau par réponse (n, probabilité,
  proposer quel code / attendre, valeur).
- « Coups à solution unique » : conservé tel quel en v1 (additif) ; à
  réévaluer à l'usage, le bloc endgame le rend a priori redondant pour
  N ≤ seuil.

### Web

Hors périmètre v1 (le payload rapide est inchangé, le web continue de
marcher tel quel).

## Validation

1. **Non-régression contre le moteur exact actuel.** Avec les trois
   extensions désactivées (code proposé = premier du pool, pas de
   proposition sans question aux nœuds internes, pas de croyance
   adverse), le nouveau moteur doit reproduire **exactement** les `p_win`
   du moteur actuel en mode exact. Valeurs de référence mesurées sur les
   grilles de `tests/conftest.make_solver` :
   - `{"X": {5,6}, "Y": {1,2}}` (N=4) → 0,625, proposer maintenant ;
   - `{"Y": {6,7,8,9,0,1}}` (N=6) → 0,750 ;
   - `{"X": {5,6}, "Y": {1,2,3}}` (N=6) → 0,583 ;
   - `{"X": {5,6}, "Y": {1,2,3,4}}` (N=8) → 0,625.
2. **Cas calculés à la main**, sur des partitions construites :
   - pool {A,B,C}, question adverse {A}|{B,C} : tenter A → 2/3, B → 1/2 ;
   - X.e on/off → {A,B} | {C,D,E} : 0,40 si l'adversaire sépare {C,D,E}
     entièrement, 0,53 s'il ne peut faire que {1|2} ;
   - `P_hit_adv` : m=4, |S|=2 → 2/3.
3. **Performance** : temps par N (4 à 14) sur plusieurs grilles, pour fixer
   `ENDGAME_N_MAX` sous 30 s au pire cas mesuré.
4. **Gain réel (souhaitable)** : simulation de parties (grilles aléatoires
   à N ≤ seuil, les deux joueurs pilotés par moteurs) ancien contre nouveau
   moteur, taux de victoire. C'est la seule mesure directe de l'EV gagnée.

## Hors périmètre v1 (pistes)

- Précalcul pendant le tour adverse (pour chacune de ses questions
  possibles) → réponse instantanée à mon tour.
- Modèle d'adversaire paramétrable (« optimal » / « humain type » : par ex.
  propose dès 2 solutions sans question).
- Choix stratégique du code par l'adversaire, et l'information que son
  échec me donnerait alors.
- Résolution exacte du jeu à information imparfaite.
- Affichage web.

## Questions ouvertes

1. **Peut-on « passer » ?** Le jeu autorise-t-il une question dont la
   réponse est déjà déterminée (ou impose-t-il au moins une action
   informative) ? Si oui, « passer » est un coup légal que le moteur doit
   offrir aux deux joueurs.
2. **Tirage uniforme des codes** : a-t-on des parties enregistrées pour le
   vérifier ?

## Évolution — mesures d'implémentation (2026-09-23)

- `ENDGAME_N_MAX` = 20 ; perf (random real games, `tests/bench_endgame.py perf`) :
  worst total for target<=6: 0.03s
  worst total for target<=10: 0.07s
  worst total for target<=14: 0.27s
  worst total for target<=20: 8.21s
- Self-play exhaustif (chaque code secret × les deux ordres de jeu, 20
  plateaux N ≤ 12) : nouveau moteur contre modèle legacy (≡ strategy.py
  exact) = 0.4975 ; contrôle nouveau contre nouveau = 0.5000.
- Le moteur legacy (toutes extensions coupées) reproduit exactement les
  `p_win` de `strategy.py` en mode exact sur les grilles de référence
  (tests/test_endgame.py).
- « Passer » reste non modélisé (question ouverte 1).
