# Interface native

L'application ouvre deux fenêtres distinctes, chacune toujours au-dessus des
applications ordinaires, sans priorité particulière entre elles :

- **Saisie** : onglets Chiffres et Comparaisons.
- **Analyse** : onglets Solutions et EV.

Les fenêtres peuvent être déplacées et redimensionnées séparément (la largeur
de Saisie reste fixe). Ctrl + molette règle l'opacité de la fenêtre survolée.
Fermer l'une des fenêtres ferme l'application et arrête les calculs associés.

La saisie valide les indices et affiche immédiatement les nouvelles valeurs et
les sommes accessibles. Les calculs de solutions et l'analyse EV utilisent des
processus séparés de l'interface. Chaque modification annule les anciens calculs
et lance une analyse de la nouvelle position ; les résultats de l'ancienne
position ne peuvent pas remplacer les nouveaux.

L'analyse EV native n'a pas de limite globale de durée. Elle publie ses résultats
à mesure qu'ils sont disponibles, puis s'arrête lorsque les calculs admissibles
sont terminés. Le classement rapide des conseils reste une estimation distincte.
Le domaine du moteur exact reste limité aux positions et branches de 20 candidats
publics ou moins ; enlever la limite de durée ne transforme pas les autres
branches en probabilités connues.

L'onglet EV présente la moyenne pondérée, la pire réponse et la meilleure réponse.
Une moyenne inconnue apparaît comme « … ». Les extrêmes accompagnés de « * » sont
provisoires : ils portent sur les seules réponses déjà calculées. Le détail de la
question conserve sa sélection pendant les mises à jour progressives.
