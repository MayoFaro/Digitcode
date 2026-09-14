# App native (fenêtre indépendante, hors navigateur)

Date : 2026-09-14
Branche : `app-native`

## Contexte et objectif

L'interface actuelle est une page web (`web/app.py` + `web/static/`) servie par
Flask et affichée dans un navigateur. L'objectif de cette branche est de
proposer une interface **native**, dans une fenêtre indépendante forcée en
affichage par-dessus les autres fenêtres, avec exactement le même
comportement de résolution que le solveur actuel. Le web existant n'est pas
remplacé : les deux interfaces coexistent.

Pour limiter la largeur de la fenêtre, l'interface est éclatée en 3 volets
qui reprennent chacun un des trois blocs de la disposition web actuelle :

- **Volet 1 — Saisie chiffres** : Chiffres (domaines), Sommes ligne, Sommes
  colonne. Correspond au bloc `col-sums` de `web/static/index.html`.
- **Volet 2 — Saisie comparaisons** : Comparaisons, Parité & segments.
  Correspond au bloc `col-digits`.
- **Volet 3 — Conseils/solutions** : solutions possibles, recommandation
  (P(gagner), meilleure question, alternatives), essais (moi/adversaire),
  historique, undo/reset. Correspond au bloc `col-advice`.

Un seul volet est visible à la fois. Le nombre de solutions restantes,
aujourd'hui affiché uniquement dans le volet 3 côté web, est affiché dans
les 3 volets.

## Décisions validées

1. **Une seule fenêtre OS**, taille fixe et étroite (largeur indicative
   ~360-420px, à ajuster à l'usage), dont le contenu interne change — pas
   trois fenêtres top-level distinctes. Le changement de volet doit être
   quasi instantané : pas de recalcul, pas d'appel réseau, juste un
   changement d'affichage en mémoire.
2. **Toolkit GUI : PySide6 (ou PyQt6)**. Recommandation d'implémentation :
   PySide6, licence LGPL plus permissive que PyQt6 (GPL/commercial) pour un
   outil redistribuable.
3. **Sélecteur de volet : trois boutons façon onglets**, toujours visibles
   en haut de chaque volet, celui du volet actif mis en évidence.
4. **Logique métier extraite dans un module indépendant de Flask**
   (`game_state.py`), réutilisé par le web (adaptateur inchangé côté
   comportement) et par l'app native — une seule source de vérité, pas de
   divergence future entre les deux interfaces.
5. **Pas de packaging/installeur** pour cette branche. Point d'entrée
   `python -m digitcode.native`. Le web continue de fonctionner en
   parallèle, sans changement de comportement.

## Architecture

```
digitcode/
  game_state.py      <- NOUVEAU : logique pure, sans Flask ni Qt
  web/
    app.py            <- MODIFIÉ : mince adaptateur HTTP autour de GameState
    static/            <- inchangé
  native/
    __init__.py
    __main__.py        <- point d'entrée `python -m digitcode.native`
    main_window.py      <- QMainWindow, QStackedWidget, barre d'onglets
    panels/
      chiffres_panel.py
      comparaisons_panel.py
      solutions_panel.py
    widgets/
      chip_button.py      <- chip à cycle de clic (remplace les chips HTML)
      segment_digit.py     <- widget 7-segments dessiné (remplace buildDigitSvg)
  solver.py, strategy.py, mapping.py, cli.py   <- inchangés
```

### `game_state.py`

Classe `GameState`, extraite de la fermeture `state` +
`current_state_payload()` actuelles de `web/app.py`, sans rien de Flask
dedans (pas de `jsonify`/`request`) :

- État : `clue`, `history`, `a_me`, `a_opp`, `my_excluded` (mêmes champs
  qu'aujourd'hui).
- Méthodes : `apply_clue(type, **fields)`, `guess_failed(who, candidate=None)`,
  `undo()`, `reset()`, `payload()` — cette dernière reprend telle quelle la
  logique actuelle de `current_state_payload()` (domaines affichés, solutions,
  race strategy, sommes atteignables, etc.).
- `apply_clue` peut lever `ValueError` sur une contrainte contradictoire,
  exactement comme aujourd'hui (le history n'est modifié qu'après validation
  réussie, même garde qu'actuellement).

`web/app.py` devient un adaptateur : chaque route Flask construit son
payload en appelant les méthodes de `GameState`, sans dupliquer de logique.
Comportement HTTP inchangé — `tests/test_web.py` doit continuer à passer
sans modification.

### App native

Une seule instance de `GameState` vit dans le process Qt. `MainWindow`
(`QMainWindow`) :

- `Qt.WindowStaysOnTopHint` pour rester au-dessus des autres fenêtres.
  Fonctionne sous X11 ; certains gestionnaires de fenêtres tiling peuvent
  l'ignorer — à vérifier à l'usage, pas de contournement spécifique prévu.
- Largeur fixe étroite, hauteur adaptée au volet affiché.
- Une bannière d'erreur en haut, au-dessus des onglets (visible quel que
  soit le volet actif) — reprend le rôle de `#error-banner`.
- Une ligne "Solutions restantes : N" sous la barre d'onglets, présente
  sur les 3 volets, alimentée par le même payload.
- `QStackedWidget` central portant les 3 `QWidget` de volet
  (`ChiffresPanel`, `ComparaisonsPanel`, `SolutionsPanel`). Changer de
  volet = `setCurrentIndex(i)`, aucun recalcul déclenché.

Chaque saisie utilisateur appelle directement `GameState.apply_clue(...)`
(ou `guess_failed`/`undo`/`reset`), récupère le payload retourné, et met à
jour l'affichage des 3 volets (compteur de solutions) + le contenu du volet
actif. Pas de round-trip réseau : la réactivité perçue au changement de
volet est indépendante du temps de calcul du solveur (qui, lui, garde son
budget ~1.5s pour `evaluate_race_strategy`, configurable côté natif comme
il l'est déjà côté web).

### Widgets de saisie

Reproduction fidèle du comportement actuel (`web/static/app.js`) :

- **Chips à cycle de clic** (chiffres, parité, sommes) → `QPushButton`
  custom conservant un état interne et cyclant au clic, stylé par
  stylesheet Qt plutôt que par classes CSS.
- **Sélecteur 7-segments par position** → widget custom (`QPainter`,
  trapèzes), avec hit-testing par segment au clic, même cycle
  vrai/faux/indéterminé que l'actuel `buildDigitSvg` (`web/static/app.js`).
- **Comparaisons** → grille de boutons/combos, équivalent fonctionnel de
  `cmp-grid`.

## Gestion des erreurs

`GameState.apply_clue` peut lever `ValueError` (contrainte contradictoire).
L'app native l'attrape au point d'appel et affiche le message dans la
bannière d'erreur, sans modifier l'état affiché (même garde que côté web :
l'historique n'est pas poussé si la validation échoue).

## Tests

`game_state.py` est testable indépendamment de Flask et de Qt : tests
unitaires purs sur `GameState`, dont une partie peut être partagée avec
`tests/test_web.py` (qui doit continuer à passer sans changement de
comportement observable). Les widgets Qt ne sont pas couverts par une
suite automatisée — vérification manuelle en lançant l'app, comme c'est
déjà le cas pour le web via `run.sh`.

## Hors périmètre

- Packaging/installeur (exécutable autonome, etc.).
- Support multi-plateforme garanti (le always-on-top Qt est testé sous
  Linux/X11 ; le comportement sous d'autres OS/gestionnaires de fenêtres
  n'est pas vérifié dans cette branche).
- Remplacement ou dépréciation de l'interface web.
