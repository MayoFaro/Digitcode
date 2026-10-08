from PySide6.QtWidgets import QGroupBox
from digitcode.native.panels.ev_panel import EVPanel


def question(label, values, weights):
    return dict(label=label, status='validated', ev=sum(v*w for v,w in zip(values,weights))/sum(weights),
                worst=min(values), branches=[dict(answer=str(i), n=w, n_mine=w, p_win=v)
                                           for i,(v,w) in enumerate(zip(values,weights))])


def test_ranking_threshold_details_and_reset(qapp):
    panel = EVPanel(QGroupBox())
    robust = question('Robuste', [.56, .60], [1, 1])
    risky = question('Risquée', [.30, .90], [1, 3])
    risky['status'] = 'blacklisted'
    threshold = question('Seuil', [.55, .80], [1, 1])
    incomplete = dict(label='Inconnue', ev=None, worst=None, status='incomplete')
    panel.set_pre_endgame_result(dict(questions=[robust, risky, threshold, incomplete],
                                     finished=True, discovery_complete=False))
    assert panel.table.rowCount() == 3
    assert panel.table.item(0, 0).text() == 'Risquée (exclue)'
    assert 'Robuste' in panel.favorable.text() and 'Seuil' not in panel.favorable.text()
    assert '1 sans moyenne définitive' in panel.status.text() and 'Repérage incomplet' in panel.status.text()
    panel.table.selectRow(0)
    assert '30.0%' in panel.details.text() and '25.0%' in panel.details.text()
    panel.sort_order.setCurrentIndex(1)
    assert panel.table.item(0, 0).text() == 'Robuste ★'
    panel.clear()
    assert panel.table.rowCount() == 0 and 'Aucune question certifiée' in panel.favorable.text()


def test_endgame_ranking_and_non_question_phases(qapp):
    panel = EVPanel(QGroupBox())
    panel.set_endgame_result(dict(complete=True, ranked_questions=[
        dict(label='H', p_win=.65, worst=.6, branches=[dict(answer='2', n=2, prob=1., value=.65)])]))
    assert panel.table.item(0, 1).text() == '65.0%'
    panel.table.selectRow(0)
    assert '100.0%' in panel.details.text()
    panel.set_endgame_result(dict(complete=True, ranked_questions=[], p_win=.4))
    assert panel.table.rowCount() == 0 and '40.0%' in panel.status.text()
    panel.set_endgame_result(dict(complete=False))
    assert 'incomplet' in panel.status.text()


def test_best_ev_sorting_and_selection_survive_progress(qapp):
    panel = EVPanel(QGroupBox())
    robust = question('Robuste', [.56, .60], [1, 1])
    risky = question('Risquée', [.30, .90], [1, 3])
    result = dict(questions=[robust, risky], finished=False, discovery_complete=True)
    panel.set_pre_endgame_result(result)
    assert panel.table.columnCount() == 4
    assert panel.table.item(0, 3).text() == '90.0%'
    panel.table.selectRow(1)
    assert panel.details.text().startswith('Robuste')
    panel.sort_order.setCurrentIndex(2)
    assert panel.table.item(0, 0).text() == 'Risquée (à risque)'
    assert panel.details.text().startswith('Robuste')
    panel.set_pre_endgame_result(result)
    assert panel.details.text().startswith('Robuste')


def test_partial_branches_display_calculated_extremes_without_inventing_average(qapp):
    panel = EVPanel(QGroupBox())
    partial = dict(label='Partielle', ev=None, worst=None, best=None, status='incomplete',
                   branches=[dict(answer='oui', n=4, n_mine=4, p_win=.4),
                             dict(answer='non', n=16, n_mine=16, p_win=None)])
    panel.set_pre_endgame_result(dict(questions=[partial], finished=False, discovery_complete=True))
    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 1).text() == '…'
    assert panel.table.item(0, 3).text() == '40.0% *'
    panel.table.selectRow(0)
    assert 'non calculée' in panel.details.text()
    partial['branches'][1]['p_win'] = .8
    partial.update(ev=.72, worst=.4, best=.8, status='validated')
    panel.set_pre_endgame_result(dict(questions=[partial], finished=True, discovery_complete=True))
    assert panel.table.item(0, 1).text() == '72.0%'
    assert panel.table.item(0, 3).text() == '80.0%'
    assert 'non calculée' not in panel.details.text()
