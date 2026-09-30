from digitcode.game_state import GameState
from digitcode.native.pre_endgame_worker import PreEndgameWorker
from digitcode.native.panels.solutions_panel import SolutionsPanel
from digitcode.solver import Cancelled
from tests.test_pre_endgame import n60_clue


def test_worker_progress_and_final_are_tagged_and_cancellable(qapp, monkeypatch):
    from digitcode.native import pre_endgame_worker as module
    def evaluate(*args, on_progress, **kwargs):
        on_progress({'finished': False})
        return {'finished': True}
    monkeypatch.setattr(module, 'evaluate_pre_endgame', evaluate)
    worker = PreEndgameWorker(n60_clue(), 2, 2, frozenset(), 0, 7)
    seen = []
    worker.progress.connect(lambda r, g: seen.append((r, g)))
    worker.finished_ok.connect(lambda r, g: seen.append((r, g)))
    worker.run()
    assert seen == [({'finished': False}, 7), ({'finished': True}, 7)]
    worker.cancel()
    worker.run()
    assert len(seen) == 2


def test_worker_cancellation_during_search_is_silent(qapp, monkeypatch):
    from digitcode.native import pre_endgame_worker as module
    def evaluate(*args, **kwargs):
        raise Cancelled()
    monkeypatch.setattr(module, 'evaluate_pre_endgame', evaluate)
    worker = PreEndgameWorker(n60_clue(), 2, 2, frozenset(), 0, 1)
    seen = []
    worker.finished_ok.connect(lambda *a: seen.append(a))
    worker.failed.connect(lambda *a: seen.append(a))
    worker.run()
    assert not seen


def test_blacklist_removes_question_from_all_advice_and_clears_on_refresh(qapp):
    gs = GameState()
    gs.clue = n60_clue()
    payload = gs.payload()
    label = 'Qui est plus grand, U ou X ?'
    entry = next(q for q in payload['race']['ranked_alternatives'] if q['label'] == label)
    payload['race']['best_question'] = entry
    payload['ev_plus_questions'] = [dict(entry, ev=.1, p_win=.2, p_trap=.1)]
    panel = SolutionsPanel(gs, lambda fn: fn())
    panel.refresh(payload)
    result = dict(questions=[dict(label=label, status='blacklisted', danger=dict(answer='U>X', n=6, p_win=1/3))],
                  finished=False, discovery_complete=True, elapsed_s=.1)
    panel.set_pre_endgame_result(result)
    assert panel.blacklist.count() == 1
    assert '33.3%' in panel.blacklist.item(0).text()
    assert label not in panel.best_question_label.text()
    assert all(label not in panel.alternatives_list.item(i).text() for i in range(panel.alternatives_list.count()))
    assert panel.ev_plus_list.count() == 0
    assert panel.validated_questions.count() == 0
    panel.refresh(payload)
    assert panel.pre_endgame_group.isHidden() and panel.blacklist.count() == 0


def test_stale_progress_is_ignored(qapp):
    from digitcode.native.main_window import MainWindow
    window = MainWindow()
    try:
        window._on_pre_endgame_finished({'questions': []}, window._endgame_generation - 1)
        assert window.solutions_panel.pre_endgame_group.isHidden()
    finally:
        window.close()


def test_window_schedules_pre_worker_and_cancels_it_when_state_changes(qapp, monkeypatch):
    from digitcode.native.main_window import MainWindow
    monkeypatch.setattr(PreEndgameWorker, 'start', lambda self: None)
    window = MainWindow()
    try:
        window.game_state.clue = n60_clue()
        payload = window.game_state.payload()
        window._render(payload)
        window._schedule_endgame(payload)
        worker = window._endgame_worker
        assert isinstance(worker, PreEndgameWorker)
        assert not window.solutions_panel.pre_endgame_group.isHidden()
        generation = worker.generation
        window._cancel_endgame()
        assert worker._cancel_event.is_set()
        assert window.solutions_panel.pre_endgame_group.isHidden()
        window._on_pre_endgame_finished({'questions': []}, generation)
        assert window.solutions_panel.pre_endgame_group.isHidden()
    finally:
        window.close()


def test_risk_alert_is_shared_by_tabs_and_uses_50_not_blacklist_threshold(qapp):
    from digitcode.native.main_window import MainWindow
    window = MainWindow()
    window.show()
    try:
        block = window.solutions_panel.pre_endgame_group
        assert window.panels[0].isAncestorOf(block)
        assert not window.solutions_panel.isAncestorOf(block)
        assert not hasattr(window.panels[0], 'solutions_count_label')
        result = dict(questions=[dict(label='H', status='incomplete', branches=[dict(p_win=.45)])],
                      finished=False, discovery_complete=True, elapsed_s=.1)
        window._on_pre_endgame_finished(result, window._endgame_generation)
        assert window.solutions_panel.blacklist.count() == 0
        for tab in range(3):
            window._on_tab_clicked(tab)
            assert window.risk_alert.isVisible()
            assert '45,0%' in window.risk_alert.text()
        window._show_risk_alert([.5, .8])
        assert window.risk_alert.isHidden()
        window._show_risk_alert([.49])
        window._cancel_endgame()
        assert window.risk_alert.isHidden()
        window._on_pre_endgame_finished(result, window._endgame_generation - 1)
        assert window.risk_alert.isHidden()
    finally:
        window.close()


def test_first_tab_keeps_filtered_advice_when_selecting_a_letter(qapp):
    from digitcode.native.panels.chiffres_panel import ChiffresPanel
    gs = GameState()
    gs.clue = n60_clue()
    panel = ChiffresPanel(gs, lambda fn: fn())
    payload = gs.payload()
    panel.refresh(payload)
    panel.set_pre_endgame_advice('Meilleure EV : H', '(aucun)')
    panel._select_row_letter('J')
    assert panel.best_question_label.text() == 'Meilleure EV : H'
    panel.refresh(dict(payload))
    assert panel.best_question_label.text() != 'Meilleure EV : H'
