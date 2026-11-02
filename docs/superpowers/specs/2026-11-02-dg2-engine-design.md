# DG2 — moteur de course à information privée

## But

DG2 ne cherche pas à réduire le nombre de codes pour lui-même. Il choisit
l'action qui maximise sa probabilité de gagner avant l'adversaire.

Une proposition est évaluée contre l'action de ne pas proposer, jamais avec
un seuil arbitraire de candidats ou de probabilité immédiate.

## Contrat de jeu

L'arbitre possède le code secret. Les deux moteurs ne reçoivent que :

- les questions et réponses publiques ;
- les deux budgets d'essais, publics ;
- leurs propres propositions ratées, privées.

Un second essai raté est terminal : le joueur adverse gagne. Une proposition
ratée n'est jamais incluse dans le journal public.

## Valeur

Pour une position publique `S`, le pool privé du joueur `M`, et une
proposition `g`, la valeur est :

```
V(proposer g) = P(g est le secret) + P(g est faux) × V(après échec)
```

Après une question, DG2 compare cette valeur à `V(passer le tour)` pour chaque
réponse possible. Au début du tour, il compare une proposition directe à la
valeur espérée de chaque question, suivie de cette même décision.

Les ex-aequo ne sont pas départagés par l'ordre d'énumération : le moteur
reçoit un générateur pseudo-aléatoire injecté, reproductible par seed. Cela
évite qu'un duel de moteurs identiques annule artificiellement la composante
probabiliste des propositions.

## Première portée

La première implémentation est un solveur exact de fin de partie : toutes les
questions non posées sont converties en partitions de l'univers fini des
candidats et l'état est représenté par des bitmasks. Le calcul garde les
questions déjà consommées et l'exclusion privée du joueur.

La modélisation complète des croyances sur l'exclusion privée adverse est une
seconde couche explicite : elle devra représenter une distribution de mondes
possibles, et non donner au moteur l'essai caché de l'adversaire. Aucune API
DG2 ne devra accepter cet essai privé comme observation.

## Intégration

`selfplay.play_match(secret, policy_zero, policy_one)` est l'unique point de
branchement pour un match. Il construit une `Observation` indépendante pour
chaque tour ; elle contient seulement les échecs du joueur qui reçoit
l'observation. DG2 expose `DG2Policy.choose(observation)` et peut donc être
opposé à DG1 sans adaptateur qui aurait accès au secret.

`play_dg2_selfplay` est un contrôle de fumée. Le tournoi futur doit créer une
instance DG2 par joueur avec deux seeds indépendantes, puis jouer chaque
secret deux fois en inversant `starter`. Les seeds et les journaux publics
sont des artefacts obligatoires du rapport.
