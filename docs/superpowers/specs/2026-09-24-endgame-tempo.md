# Fin de partie : questions nulles et correction du tour

Branche : `feat/endgame-null-questions`. Le moteur livré dans `endgame.py`
reste intact. Le moteur de cette branche est `endgame_tempo.py`, utilisé par
`GameState.build_endgame_from` et le calcul natif en arrière-plan.

## Périmètre

- Activation à 1–20 candidats publics ; aucune diminution du seuil.
- Budget de recherche de 30 secondes, préparation des partitions comprise.
- Deux propositions de code par joueur ; deuxième échec = défaite.
- Réponses publiques, codes tentés privés. Poser une question ne consomme pas
  une tentative. Après une question, son auteur peut proposer ou terminer le
  tour. Sans question, il doit proposer : aucun passage gratuit.
- Chaque question peut être jouée une seule fois, par l'un ou l'autre joueur.
  Une réponse déjà déductible n'empêche pas de poser une question non jouée.
- Catalogue conforme aux questions existantes : 10 lignes, 9 colonnes,
  6 parités, 7 comparaisons adjacentes, 42 segments. Une comparaison inversée
  est la même question. Les questions explicitement saisies sont consommées ;
  une réponse simplement déduite ne consomme pas la question correspondante.

## Modèle adverse : limite conservée et explicite

Cette livraison corrige les coups légaux et les phases du tour. Elle ne résout
pas encore le jeu à information imparfaite contre une politique optimale.
Comme le moteur actuel, elle optimise nos propositions, minimise notre EV
pour les choix adverses, mais utilise une proposition adverse uniforme et
la taille du pool au moment de son premier échec pour ses probabilités.
L'adversaire choisit encore comme s'il connaissait notre exclusion privée ;
sa propre exclusion n'influence pas son choix de question. Ces approximations
ne constituent pas une garantie pessimiste. L'interface affiche une estimation.
Aucune tentative adverse n'est demandée ni supposée observée.

L'optimisation symétrique des politiques avec informations privées reste un
chantier distinct. Il faudra revalider les regroupements de questions si
l'identité des actions devient un signal utilisé pour réviser les croyances.

## Quatre phases, correction ponctuelle et annulation

Le menu est visible seulement en endgame. Il fixe un nouvel état courant,
puis les actions enregistrées font avancer automatiquement le suivi :

| État courant | Prochain indice enregistré | Tentative ratée de l'auteur du tour | Terminer sans proposer |
|---|---|---|---|
| Moi, avant question | Moi, question posée | Adversaire, avant question | Interdit |
| Moi, question posée | Adversaire, question posée | Adversaire, avant question | Adversaire, avant question |
| Adversaire, avant question | Adversaire, question posée | Moi, avant question | Interdit |
| Adversaire, question posée | Moi, question posée | Moi, avant question | Moi, avant question |

Un indice saisi après une question déjà posée signifie que l'ancien auteur
n'a pas proposé et que la question suivante a été jouée. Le bouton de fin de
tour permet également d'enregistrer cette transition avant le prochain indice.
La sélection « moi, question posée » ne termine jamais le tour : le calcul
compare exclusivement proposer maintenant et terminer sans proposer.

Les questions nulles disposent d'une liste et d'un bouton d'enregistrement.
Après une question déjà posée, le libellé indique à quel joueur appartient
la question suivante. L'enregistrement vérifie à nouveau la disponibilité et
le caractère nul sur l'état courant, puis enregistre la réponse réelle comme
un indice. Impossible de rejouer une entrée périmée.

En endgame, les snapshots d'undo restaurent indices, phase, tentatives,
exclusions, échecs adverses et corrections du menu. Modifier ou ressaisir une
réponse existante n'avance pas le tour. Hors endgame, l'undo historique des
indices est conservé. Le décompte historique `turn_phase` reste disponible ;
l'endgame utilise `endgame_turn_phase` et ses quatre états.

## Réserve commune et déduplication exacte sous ce modèle

Soit le catalogue des questions non jouées à l'entrée du calcul. Chaque
question est une partition des candidats de cet univers. Pour un pool public
S, C(S) est le nombre de questions du catalogue devenues constantes sur S.

Après u questions jouées depuis la racine, toutes ces questions sont
constantes sur S : les réponses publiques ont restreint S à leur classe.
Il reste donc exactement **K = C(S) − u** questions nulles. Les identités des
questions consommées n'ont pas à être mémorisées : elles ne pourront jamais
redevenir informatives dans un descendant.

Une question informative menant à S' produit :

    K' = K + C(S') − C(S) − 1

La différence ajoutée est toujours positive ou nulle. Une question nulle
produit K' = K − 1. Les autres questions partageant la même partition sont
bien conservées dans C : mutualiser leur valeur ne supprime pas leurs coups.

Toutes les questions nulles disponibles sont équivalentes pour ce modèle.
Un représentant suffit dans la recherche ; à la racine tous les libellés et
les réponses restent disponibles pour l'utilisateur. Une question nulle est
suivie du choix proposer/terminer, tout comme une question informative.

## Compression de la réserve par un seuil de périodicité

Une réduction à la seule parité pour toute réserve serait injustifiée. On
calcule d'abord un seuil structurel T(S,a,b), indépendant des exclusions et
de la taille historique du pool adverse, au-delà duquel V(K+2)=V(K).

Preuve par induction sur les réductions de S et des tentatives :

- Les états terminaux et S singleton ont T=0.
- Fixons un état non terminal. Une fois toutes les valeurs des actions qui
  quittent cet état périodiques, écrivons A(K) le maximum de nos propositions
  directes, questions informatives et propositions après question nulle.
  B(K) est le minimum adverse correspondant. La seule action restante est
  la question nulle sans proposition :

      V_moi(K) = max(A(K), V_adv(K−1))
      V_adv(K) = min(B(K), V_moi(K−1))

- En composant deux tours, on obtient, pour une parité fixée, une application
  x -> max(A, min(B, x)), ou symétriquement min(B, max(A, x)). Chacune est
  idempotente, y compris lorsque A > B. Un passage par cette application
  suffit donc à stabiliser les valeurs de cette parité.
- Les propositions après question nulle consultent une réserve K−1 :
  le seuil de leurs continuations est majoré par
  1 + max(T(S,a−1,b), T(S,a,b−1)).
- Une réponse informative consulte K+delta, avec
  delta=C(S')−C(S)−1. Son seuil est majoré par T(S',a,b)−delta.
  Le choix de proposer après cette réponse ne requiert pas un seuil plus
  grand, car les seuils sont croissants avec les tentatives.

Un seuil suffisant est donc :

    T(S,a,b) = 1 + max(
        1,
        1 + max(T(S,a−1,b), T(S,a,b−1)),
        max_sur_les_réponses(T(S',a,b) − delta)
    )

La dernière unité assure que les deux tours de la composition utilisent
les coefficients déjà périodiques. Pour K > T+1, le calcul remplace K par
T + ((K−T) modulo 2). Le nombre réel reste affiché et enregistré ; seule la
représentation interne est réduite. Les propositions directes sont également
mémoïsées avec le seuil de leur état d'échec.

Cette propriété dépend des hypothèses du modèle actuel et doit être réétablie
si les actions révèlent des informations privées dans un futur modèle.

## Autres optimisations

- Réponses calculées directement sur les codes complets avec la même table
  de segments que le solveur ; validation contre ses contraintes.
- Partitions équivalentes évaluées une fois par pool, avec multiplicité
  conservée pour les questions nulles.
- Arrêts sur valeurs terminales certaines ; dernier essai évalué directement.
- Élagage par bornes [0,1] des branches probabilistes : une option incapable
  de battre la meilleure valeur déjà calculée n'est pas développée davantage.
  Les valeurs mémorisées des états restent complètes ; aucun beam heuristique.
- Mémoïsation des meilleures propositions et des partitions restreintes.

## Présentation

Le bloc endgame précède les comparaisons rapides. Avant question, il conserve
proposition directe, meilleure question informative, meilleure question nulle
et le plan selon les réponses. Après question : uniquement proposer/terminer.
Au tour adverse après question, il compare nos chances selon ses deux actions
légales. Les comparaisons rapides restent affichées, avec leur hypothèse
« nouvelle question » clairement indiquée lorsqu'elle ne s'applique plus au
tour courant. Un défilement garde tous les éléments accessibles dans la
fenêtre étroite existante.

Le texte de parité est conditionnel : si chacun ne fait que consommer des
questions nulles, il indique qui devra agir sans cette option en premier.
Il ne prétend jamais forcer une question informative : proposer reste légal.

## Validation et mesures

- Oracle indépendant avec ensemble explicite des questions disponibles :
  états synthétiques, doublons, questions nulles, deux joueurs, configurations
  de tentatives et échecs privés. Aucune comparaison ancien/nouveau moteur.
- Comparaison compression activée/désactivée sur de grandes réserves, deux
  parités et différentes tentatives.
- Sémantique de chaque réponse vérifiée contre le solveur existant.
- Tests des quatre corrections de phase, échecs, fin de tour, répétitions,
  contradiction, undo et reset ; tests Qt des contrôles et des conseils.
- Budget et annulation testés ; contrôle visuel hors écran à 380 pixels.

Mesures de développement sur cette machine : la position reproductible
`random_board(20002, 20)` contient exactement 20 candidats, 56 questions
restantes et 21 nulles. L'analyse complète termine en environ 27,25 secondes
après optimisation (préparation comprise), contre une expiration à 30 secondes
avant optimisation. La position `random_board(20001, 20)` contient 19 candidats
et a terminé en environ 11 secondes à une étape précédente.

Ces mesures ne sont pas une garantie pour toutes les grilles ou machines.
En cas d'expiration le résultat est explicitement incomplet, aucune EV exacte
n'est inventée, et les comparaisons rapides sont identifiées comme telles.
Commande reproductible : `python3 -m tests.bench_tempo`.

Validation de la livraison : suite complète **318 tests réussis** (trois
avertissements Qt préexistants). Après les derniers ajustements, **58 tests
ciblés réussis**, puis **9 tests ciblés réussis**, dont un nouveau cas limite
vérifiant qu'une exclusion privée n'active pas l'endgame au-dessus du seuil
public. `git diff --check` ne signale aucun problème. `endgame.py`,
`strategy.py` et `solver.py` sont inchangés.

## Correction UI du 25 septembre — partie E4 ... G1

Le résumé compare désormais des actions explicites : proposition sans
question, meilleure question informative suivie d'une proposition, question
nulle sans proposition. Toutes les valeurs désignent la victoire finale.
Les probabilités de réponses, de réussite immédiate et les moyennes pondérées
sont dans « Détails des probabilités », avec les anciennes comparaisons.
Le conseil conserve la politique du moteur, y compris lorsqu'une politique
adaptative (question puis attendre selon la réponse) domine les trois options
fixes ; cette exception est alors nommée explicitement.

Le moteur expose les valeurs proposer/attendre déjà calculées pour chaque
réponse. Aucun changement des récurrences, du choix optimal ou des hypothèses
adverses. Sur la position rapportée, à mon tour avant question : proposition
directe 58,3 %, L puis proposition 62,5 %, question nulle sans proposition
33,3 %. Les 58,3 % auparavant affichés pour une question nulle correspondaient
à la politique question nulle **puis proposition**.

Une phase automatiquement mémorisée suit maintenant les changements de
« L'adversaire débute ». Une correction explicite du tour reste prioritaire,
ainsi qu'une fin de tour explicitement enregistrée ; cette priorité figure
dans l'infobulle. L'undo restaure aussi l'origine automatique/explicite de la
phase. Après G1, avec l'adversaire premier joueur, la phase est « adversaire,
question déjà posée », puis « moi, avant question » s'il termine sans proposer.

Validation de cette correction : 140 tests distincts couverts par les suites
ciblées (moteur inchangé, tours, reproduction G1 et interface native), tous
réussis. Vérification visuelle à 380 pixels, contrôles de diff sans erreur.
