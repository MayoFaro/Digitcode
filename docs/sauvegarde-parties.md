# Sauvegarde des parties

Le bouton **Réinitialiser** archive automatiquement la partie avant de l'effacer,
dans l'interface native comme dans l'interface web. Une partie vierge ne crée
aucun fichier. Si la sauvegarde échoue, la réinitialisation est annulée et la
partie reste disponible.

Chaque archive est un fichier JSON distinct, daté en UTC, dans
`~/.local/share/digitcode/parties/`. Le chemin suit `XDG_DATA_HOME` si cette
variable est définie ; `DIGITCODE_ARCHIVE_DIR` permet de choisir directement un
autre dossier. Dans l'interface native, le chemin de la dernière archive est
affiché après la réinitialisation.

Le format version 1 conserve les indices, l'historique encore présent après les
annulations, les tentatives enregistrées, les codes exclus et le suivi des tours.
Il ne déduit ni les codes essayés par l'adversaire ni un résultat final non saisi.

Cette sauvegarde se déclenche uniquement à la réinitialisation, pas à la fermeture
de l'application. Les archives peuvent être consultées comme fichiers JSON ;
l'application ne propose pas encore de commande pour recharger une partie.
