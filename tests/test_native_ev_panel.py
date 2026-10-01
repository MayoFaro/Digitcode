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
    assert '1 incomplètes' in panel.status.text() and 'Repérage incomplet' in panel.status.text()
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
